from dataclasses import dataclass

from django.db import transaction
from django.urls import URLPattern, URLResolver, get_resolver

from access_control.models import Vista
from access_control.views import VerificarPermisoMixin


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
        if previous.permiso_requerido != permiso_requerido:
            issues.append(
                ViewContractIssue(
                    issue="inconsistent_permission",
                    route_name=route_name,
                    view_name=view_name,
                    vista_nombre=vista_nombre,
                )
            )
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


@transaction.atomic
def ensure_protected_views_catalog():
    definitions, issues = audit_protected_views()
    created = 0
    existing = 0
    route_names_updated = 0
    for definition in definitions:
        vista = Vista.objects.filter(nombre=definition.vista_nombre).order_by("id").first()
        if vista is None:
            Vista.objects.create(
                nombre=definition.vista_nombre,
                route_name=definition.route_name,
            )
            created += 1
            continue

        existing += 1
        if definition.route_name and not vista.route_name:
            vista.route_name = definition.route_name
            vista.save(update_fields=["route_name"])
            route_names_updated += 1

    return ViewCatalogSummary(
        created=created,
        existing=existing,
        route_names_updated=route_names_updated,
        invalid_count=len(issues),
        issues=issues,
    )