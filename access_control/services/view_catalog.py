from dataclasses import dataclass
from importlib import import_module

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
    conflicts: tuple[CatalogConflict, ...]
    dry_run: bool

    @property
    def route_names_updated(self):
        return self.updated

    @property
    def invalid_count(self):
        return len(self.conflicts)


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
        if len(matches) > 1:
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

        route_conflicts = [
            vista
            for vista in existing_rows
            if vista.route_name == definition.route_name
            and vista.nombre != definition.nombre
        ]
        if route_conflicts:
            conflicts.append(
                CatalogConflict(
                    code="route_identity_conflict",
                    key=definition.key,
                    nombre=definition.nombre,
                    route_name=definition.route_name,
                    detail=(
                        "La ruta canónica ya pertenece a otra Vista: "
                        + ", ".join(sorted({vista.nombre for vista in route_conflicts}))
                    ),
                )
            )
            continue

        if not matches:
            created_rows.append(_catalog_item(definition))
            continue

        vista = matches[0]
        existing_catalog_rows.append(_catalog_item(definition, vista.id))
        if vista.route_name != definition.route_name:
            updated_rows.append(_catalog_item(definition, vista.id))

    legacy = tuple(
        _legacy_item(vista)
        for vista in existing_rows
        if vista.nombre not in declared_names
        and _belongs_to_app(vista, app, definitions)
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


def ensure_protected_views_catalog(*, dry_run=False, app="tareas"):
    """Backward-compatible entry point for declarative catalog reconciliation."""
    return ensure_declared_views_catalog(app=app, dry_run=dry_run)