from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from types import SimpleNamespace

from django.db import transaction
from django.urls import URLPattern, URLResolver, get_resolver

from access_control.models import Vista
from access_control.views import VerificarPermisoMixin
from access_control.services.view_registry import definitions_for_app


VALID_PERMISSION_NAMES = frozenset(
    {
        "ingresar",
        "crear",
        "modificar",
        "eliminar",
        "autorizar",
        "supervisor",
    }
)


@dataclass(frozen=True)
class ProtectedViewDefinition:
    vista_nombre: str
    permiso_requerido: str
    route_name: str | None
    namespace: str | None
    view_type: str
    navigable: bool


@dataclass(frozen=True)
class ViewContractIssue:
    issue: str
    route_name: str | None
    view_name: str
    vista_nombre: str | None = None


@dataclass(frozen=True)
class ViewCatalogSummary:
    created: int
    existing: int
    route_names_updated: int
    invalid_count: int
    issues: tuple[ViewContractIssue, ...]


@dataclass(frozen=True)
class CatalogItem:
    key: str | None
    nombre: str
    route_name: str | None
    vista_id: int | None = None


@dataclass(frozen=True)
class CatalogConflict:
    code: str
    key: str | None
    nombre: str | None
    route_name: str | None
    detail: str


@dataclass(frozen=True)
class CatalogResult:
    created: int
    existing: int
    updated: int
    created_rows: tuple[CatalogItem, ...]
    existing_rows: tuple[CatalogItem, ...]
    updated_rows: tuple[CatalogItem, ...]
    legacy: tuple[CatalogItem, ...]
    legacy_reports: tuple[LegacyViewReport, ...]
    conflicts: tuple[CatalogConflict, ...]
    dry_run: bool

    @property
    def route_names_updated(self):
        return self.updated

    @property
    def invalid_count(self):
        return len(self.conflicts)


@dataclass(frozen=True)
class LegacyPermissionSummary:
    count: int
    usuarios_distintos: int
    empresas_distintas: int
    flags: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class LegacyReference:
    model: str
    field: str
    count: int
    ids: tuple[int, ...]


@dataclass(frozen=True)
class LegacyViewReport:
    vista: Vista
    motivo_legacy: str
    referencias: tuple[LegacyReference, ...]
    permisos: LegacyPermissionSummary
    reemplazo_canonico_sugerido: str | None
    safe_to_delete: bool
    blockers: tuple[str, ...]


def _catalog_item(definition, vista_id=None):
    return CatalogItem(
        key=definition.key,
        nombre=definition.nombre,
        route_name=definition.route_name,
        vista_id=vista_id,
    )


def _legacy_item(vista):
    return CatalogItem(
        key=None,
        nombre=vista.nombre,
        route_name=vista.route_name,
        vista_id=vista.id,
    )


def _belongs_to_app(vista, app, definitions):
    if not definitions:
        return False
    if vista.route_name and vista.route_name.startswith(f"{app}:"):
        return True
    prefixes = {
        definition.nombre.split(" - ", 1)[0]
        for definition in definitions
        if definition.nombre
    }
    return any(
        vista.nombre == prefix or vista.nombre.startswith(f"{prefix} - ")
        for prefix in prefixes
    )


def _legacy_replacement(vista, definitions):
    for definition in definitions:
        if vista.route_name in {binding.route_name for binding in definition.routes}:
            return definition.nombre

    replacement_by_suffix = {
        "Listado": "Tareas",
        "Crear tarea": "Tareas",
        "Detalle": "Tareas",
        "Editar tarea": "Tareas",
        "Publicar tarea": "Tareas - Ciclo de vida",
        "Iniciar gestión": "Tareas - Ciclo de vida",
        "Anular tarea": "Tareas - Ciclo de vida",
        "Completar tarea": "Tareas - Ciclo de vida",
        "Aprobar cierre": "Tareas - Ciclo de vida",
        "Rechazar cierre": "Tareas - Ciclo de vida",
        "Reactivar tarea": "Tareas - Ciclo de vida",
    }
    suffix = vista.nombre.split(" - ", 1)[-1]
    replacement = replacement_by_suffix.get(suffix)
    declared_names = {definition.nombre for definition in definitions}
    return replacement if replacement in declared_names else None


def get_legacy_views_for_app(app="tareas", *, definitions=None, views=None):
    """Report historical Vista rows without changing any persistent data."""
    from django.apps import apps
    from access_control.models import AccessRequest, Permiso

    from access_control.services.view_registry_audit import APP_DEFINITION_MODULES

    module_path = APP_DEFINITION_MODULES.get(app)
    if module_path is None:
        return ()
    if definitions is None:
        import_module(module_path)
        definitions = definitions_for_app(app)
    definitions = tuple(definitions)
    if not definitions:
        return ()

    declared_names = {definition.nombre for definition in definitions}
    queryset = Vista.objects.all() if views is None else views
    legacy_views = tuple(
        vista
        for vista in queryset
        if vista.nombre not in declared_names and _belongs_to_app(vista, app, definitions)
    )
    reference_fields = []
    for model in apps.get_models():
        for field in model._meta.get_fields():
            if (
                getattr(field, "many_to_one", False)
                and getattr(field, "remote_field", None)
                and field.remote_field.model is Vista
                and model is not Permiso
            ):
                reference_fields.append((model, field.name))

    reports = []
    for vista in legacy_views:
        permission_rows = Permiso.objects.filter(vista=vista)
        flags = tuple(
            (field, permission_rows.filter(**{field: True}).count())
            for field in ("ver", "ingresar", "crear", "modificar", "eliminar", "autorizar", "supervisor")
        )
        references = []
        for model, field_name in reference_fields:
            rows = model.objects.filter(**{field_name: vista})
            if rows.exists():
                references.append(
                    LegacyReference(
                        model=model._meta.label,
                        field=field_name,
                        count=rows.count(),
                        ids=tuple(rows.values_list("pk", flat=True)),
                    )
                )

        requests = AccessRequest.objects.filter(vista_nombre=vista.nombre)
        if requests.exists():
            references.append(
                LegacyReference(
                    model=AccessRequest._meta.label,
                    field="vista_nombre",
                    count=requests.count(),
                    ids=tuple(requests.values_list("pk", flat=True)),
                )
            )

        blockers = []
        if permission_rows.exists():
            blockers.append("permisos históricos")
        if references:
            blockers.append("referencias persistentes")
        reports.append(
            LegacyViewReport(
                vista=vista,
                motivo_legacy="No corresponde a una definición declarativa activa de la app.",
                referencias=tuple(references),
                permisos=LegacyPermissionSummary(
                    count=permission_rows.count(),
                    usuarios_distintos=permission_rows.values("usuario_id").distinct().count(),
                    empresas_distintas=permission_rows.values("empresa_id").distinct().count(),
                    flags=flags,
                ),
                reemplazo_canonico_sugerido=_legacy_replacement(vista, definitions),
                safe_to_delete=not blockers,
                blockers=tuple(blockers),
            )
        )
    return tuple(reports)


def ensure_declared_views_catalog(*, app="tareas", dry_run=False, definitions=None):
    """Reconcile persistent Vista rows from explicit VICMEAS definitions only."""
    if definitions is None:
        import_module(f"{app}.vicmeas")
    definitions = tuple(
        definitions_for_app(app) if definitions is None else definitions
    )
    existing_rows = tuple(Vista.objects.order_by("id"))
    declared_names = {definition.nombre for definition in definitions}
    by_name = {}
    for vista in existing_rows:
        by_name.setdefault(vista.nombre, []).append(vista)

    created_rows = []
    existing_catalog_rows = []
    updated_rows = []
    conflicts = []
    seen_names = {}
    for definition in definitions:
        previous = seen_names.get(definition.nombre)
        if previous is not None and previous != definition:
            conflicts.append(
                CatalogConflict(
                    code="duplicate_declared_name",
                    key=definition.key,
                    nombre=definition.nombre,
                    route_name=definition.route_name,
                    detail="Más de una definición declara el mismo nombre canónico.",
                )
            )
            continue
        seen_names[definition.nombre] = definition

        matches = by_name.get(definition.nombre, [])
        route_matches = [
            vista
            for vista in existing_rows
            if definition.route_name is not None
            and vista.route_name == definition.route_name
        ]
        if len(matches) > 1 or len(route_matches) > 1:
            conflicts.append(
                CatalogConflict(
                    code="persistent_identity_conflict",
                    key=definition.key,
                    nombre=definition.nombre,
                    route_name=definition.route_name,
                    detail="Existen varias filas Vista con el mismo nombre canónico.",
                )
            )
            continue

        if matches and route_matches and matches[0].id != route_matches[0].id:
            conflicts.append(
                CatalogConflict(
                    code="route_identity_conflict",
                    key=definition.key,
                    nombre=definition.nombre,
                    route_name=definition.route_name,
                    detail=(
                        "La ruta canónica ya pertenece a otra Vista: "
                        + ", ".join(sorted({vista.nombre for vista in route_matches}))
                    ),
                )
            )
            continue

        vista = matches[0] if matches else (route_matches[0] if route_matches else None)
        if not matches:
            if vista is None:
                created_rows.append(_catalog_item(definition))
                continue

        existing_catalog_rows.append(_catalog_item(definition, vista.id))
        if vista.nombre != definition.nombre or (
            definition.route_name is not None
            and vista.route_name != definition.route_name
        ):
            updated_rows.append(_catalog_item(definition, vista.id))

    legacy = tuple(
        _legacy_item(vista)
        for vista in existing_rows
        if vista.nombre not in declared_names
        and _belongs_to_app(vista, app, definitions)
    )
    legacy_reports = get_legacy_views_for_app(
        app,
        definitions=definitions,
        views=tuple(
            vista for vista in existing_rows
            if vista.id in {item.vista_id for item in legacy}
        ),
    )

    if not dry_run and (created_rows or updated_rows):
        with transaction.atomic():
            for item in created_rows:
                Vista.objects.create(
                    nombre=item.nombre,
                    route_name=item.route_name,
                )
            for item in updated_rows:
                Vista.objects.filter(pk=item.vista_id).update(
                    nombre=item.nombre,
                    route_name=item.route_name,
                )

    return CatalogResult(
        created=len(created_rows),
        existing=len(existing_catalog_rows),
        updated=len(updated_rows),
        created_rows=tuple(created_rows),
        existing_rows=tuple(existing_catalog_rows),
        updated_rows=tuple(updated_rows),
        legacy=legacy,
        legacy_reports=legacy_reports,
        conflicts=tuple(conflicts),
        dry_run=dry_run,
    )


def _route_name(namespaces, pattern_name):
    parts = [part for part in namespaces if part]
    if pattern_name:
        parts.append(pattern_name)
    return ":".join(parts) or None


def _iter_url_patterns(patterns, namespaces=()):
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            next_namespaces = namespaces
            if pattern.namespace:
                next_namespaces = (*namespaces, pattern.namespace)
            yield from _iter_url_patterns(pattern.url_patterns, next_namespaces)
            continue
        if isinstance(pattern, URLPattern):
            yield pattern, _route_name(namespaces, pattern.name)


def _is_mixin_subclass(view_class):
    try:
        return issubclass(view_class, VerificarPermisoMixin)
    except TypeError:
        return False


def _definition_from_callback(callback, route_name):
    view_class = getattr(callback, "view_class", None)
    if view_class is not None and _is_mixin_subclass(view_class):
        return (
            getattr(view_class, "vista_nombre", None),
            getattr(view_class, "permiso_requerido", None),
            "CBV",
            view_class.__name__,
        )

    pending = [callback]
    seen = set()
    vista_nombre = permiso_requerido = None
    wrapped_callback = callback
    while pending:
        wrapped_callback = pending.pop(0)
        if id(wrapped_callback) in seen:
            continue
        seen.add(id(wrapped_callback))
        vista_nombre = getattr(wrapped_callback, "vista_nombre", None)
        permiso_requerido = getattr(wrapped_callback, "permiso_requerido", None)
        if vista_nombre is not None or permiso_requerido is not None:
            break
        next_wrapped = getattr(wrapped_callback, "__wrapped__", None)
        if next_wrapped is not None:
            pending.append(next_wrapped)
        closure = getattr(wrapped_callback, "__closure__", None) or ()
        pending.extend(
            cell.cell_contents
            for cell in closure
            if callable(cell.cell_contents) and id(cell.cell_contents) not in seen
        )
    if vista_nombre is not None or permiso_requerido is not None:
        return vista_nombre, permiso_requerido, "FBV", getattr(wrapped_callback, "__name__", repr(callback))
    return None


def audit_protected_views():
    definitions = []
    issues = []
    by_name = {}
    navigable_names = _sidebar_view_names()

    for pattern, route_name in _iter_url_patterns(get_resolver().url_patterns):
        callback_data = _definition_from_callback(pattern.callback, route_name)
        if callback_data is None:
            continue
        vista_nombre, permiso_requerido, view_type, view_name = callback_data
        if not vista_nombre or not permiso_requerido:
            issues.append(
                ViewContractIssue(
                    issue="missing_vicmeas_metadata",
                    route_name=route_name,
                    view_name=view_name,
                    vista_nombre=vista_nombre,
                )
            )
            continue
        if permiso_requerido not in VALID_PERMISSION_NAMES:
            issues.append(
                ViewContractIssue(
                    issue="invalid_permission",
                    route_name=route_name,
                    view_name=view_name,
                    vista_nombre=vista_nombre,
                )
            )
            continue

        definition = ProtectedViewDefinition(
            vista_nombre=vista_nombre,
            permiso_requerido=permiso_requerido,
            route_name=route_name,
            namespace=route_name.split(":", 1)[0] if route_name and ":" in route_name else None,
            view_type=view_type,
            navigable=vista_nombre in navigable_names,
        )
        previous = by_name.get(vista_nombre)
        if previous is None:
            by_name[vista_nombre] = definition
            definitions.append(definition)
            continue
        if previous.route_name != route_name:
            by_name[vista_nombre] = ProtectedViewDefinition(
                vista_nombre=vista_nombre,
                permiso_requerido=permiso_requerido,
                route_name=None,
                namespace=definition.namespace,
                view_type=previous.view_type,
                navigable=definition.navigable,
            )
            definitions[definitions.index(previous)] = by_name[vista_nombre]

    return tuple(definitions), tuple(issues)


def discover_protected_views():
    """Return unique protected views from active URL patterns only."""
    definitions, _ = audit_protected_views()
    return definitions


def _sidebar_view_names():
    from access_control.services.permissions import SIDEBAR_VIEW_NAMES

    return frozenset(SIDEBAR_VIEW_NAMES.values())


def ensure_protected_views_catalog(*, dry_run=False, app=None):
    """Reconcile Vista rows from all active protected Views without registries."""
    discovered = discover_protected_views()
    if app is not None:
        discovered = tuple(
            definition
            for definition in discovered
            if definition.namespace == app
        )
    definitions = tuple(
        SimpleNamespace(
            key=None,
            nombre=definition.vista_nombre,
            route_name=definition.route_name,
            routes=(),
        )
        for definition in discovered
    )
    return ensure_declared_views_catalog(
        app=app or "active_views",
        dry_run=dry_run,
        definitions=definitions,
    )
