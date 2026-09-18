"""Diagnostic consistency audit for declarative VICMEAS surfaces."""

from dataclasses import dataclass
from importlib import import_module

from django.urls import URLPattern, URLResolver, get_resolver

from access_control.views import VerificarPermisoMixin


APP_DEFINITION_MODULES = {"tareas": "tareas.vicmeas"}
DEFAULT_EXCLUDED_ROUTES = frozenset({"tareas:enlace_tarea"})


@dataclass(frozen=True)
class AuditIssue:
    code: str
    app: str
    route_name: str | None = None
    definition_key: str | None = None
    expected: str | None = None
    actual: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class ProtectedRoute:
    app: str
    route_name: str
    method: str
    vista_nombre: str | None
    permiso_requerido: str | None
    view_name: str
    callback_id: int


@dataclass(frozen=True)
class AuditResult:
    app: str
    definitions: tuple
    bindings: tuple
    protected_routes: tuple[ProtectedRoute, ...]
    issues: tuple[AuditIssue, ...]

    @property
    def issue_count(self):
        return len(self.issues)

    def by_code(self, code):
        return tuple(issue for issue in self.issues if issue.code == code)

    def for_route(self, route_name):
        return tuple(issue for issue in self.issues if issue.route_name == route_name)


def register_app_module(app, module_path):
    """Register an explicit declaration module for future audit_app calls."""
    APP_DEFINITION_MODULES[app] = module_path


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
        elif isinstance(pattern, URLPattern):
            yield pattern, _route_name(namespaces, pattern.name)


def _is_vicmeas_class(view_class):
    try:
        return issubclass(view_class, VerificarPermisoMixin)
    except TypeError:
        return False


def _metadata(value):
    return (
        getattr(value, "vista_nombre", None),
        getattr(value, "permiso_requerido", None),
    )


def _protected_routes_for_pattern(pattern, route_name, app):
    callback = pattern.callback
    view_class = getattr(callback, "view_class", None)
    if view_class is None:
        vista_nombre, permiso_requerido = _metadata(callback)
        if vista_nombre is None and permiso_requerido is None:
            return ()
        return (
            ProtectedRoute(
                app=app,
                route_name=route_name,
                method="GET",
                vista_nombre=vista_nombre,
                permiso_requerido=permiso_requerido,
                view_name=getattr(callback, "__name__", repr(callback)),
                callback_id=id(callback),
            ),
        )

    class_vista, class_permission = _metadata(view_class)
    if not _is_vicmeas_class(view_class) and class_vista is None and class_permission is None:
        return ()

    methods = []
    for method in getattr(view_class, "http_method_names", ()):
        method_handler = getattr(view_class, method, None)
        if callable(method_handler) and method not in {"options", "head", "trace"}:
            methods.append((method.upper(), method_handler))
    routes = []
    for method, handler in methods:
        method_vista, method_permission = _metadata(handler)
        routes.append(
            ProtectedRoute(
                app=app,
                route_name=route_name,
                method=method,
                vista_nombre=method_vista or class_vista,
                permiso_requerido=method_permission or class_permission,
                view_name=view_class.__name__,
                callback_id=id(callback),
            )
        )
    return tuple(routes)


def _definitions_for_app(app, definitions):
    if definitions is not None:
        return tuple(definition for definition in definitions if definition.app == app)
    module_path = APP_DEFINITION_MODULES.get(app)
    if module_path is None:
        raise ValueError(f"No hay módulo declarativo registrado para {app}.")
    module = import_module(module_path)
    return tuple(
        definition
        for definition in getattr(module, "TASKS_VIEW_DEFINITIONS", ())
        if definition.app == app
    )


def _issue_key(issue):
    return (
        issue.code,
        issue.app,
        issue.route_name,
        issue.definition_key,
        issue.expected,
        issue.actual,
    )


def _append_issue(issues, issue):
    if _issue_key(issue) not in {_issue_key(existing) for existing in issues}:
        issues.append(issue)


def _structural_issues(app, definitions, route_names):
    issues = []
    by_key = {}
    by_name = {}
    for definition in definitions:
        key = getattr(definition, "key", None)
        name = getattr(definition, "nombre", None)
        previous_key = by_key.get(key)
        if previous_key is not None and previous_key != definition:
            _append_issue(
                issues,
                AuditIssue(
                    code="duplicate_definition_key",
                    app=app,
                    definition_key=key,
                    expected="una definición",
                    actual="definiciones incompatibles",
                    detail=f"La key {key} aparece con metadatos incompatibles.",
                ),
            )
        by_key[key] = definition
        previous_name = by_name.get(name)
        if previous_name is not None and previous_name != definition:
            _append_issue(
                issues,
                AuditIssue(
                    code="duplicate_vicmeas_name_incompatible",
                    app=app,
                    definition_key=key,
                    expected=name,
                    actual="metadatos incompatibles",
                    detail=f"El nombre {name} aparece en más de una definición.",
                ),
            )
        by_name[name] = definition

        routes = tuple(getattr(definition, "routes", ()))
        if not routes:
            _append_issue(
                issues,
                AuditIssue(
                    code="definition_without_routes",
                    app=app,
                    definition_key=key,
                    expected="al menos un binding",
                    actual="0 bindings",
                ),
            )
        canonical_route = getattr(definition, "route_name", None)
        if getattr(definition, "navigable", False) and canonical_route not in route_names:
            _append_issue(
                issues,
                AuditIssue(
                    code="navigable_without_route",
                    app=app,
                    route_name=canonical_route,
                    definition_key=key,
                    expected="ruta canónica existente",
                    actual="ruta inexistente",
                ),
            )
        if getattr(definition, "access_utility", False) and (
            not key or not name
        ):
            _append_issue(
                issues,
                AuditIssue(
                    code="access_utility_without_identity",
                    app=app,
                    definition_key=key,
                    expected="key y nombre funcional",
                    actual="identidad incompleta",
                ),
            )
    return issues


def audit_app(app, *, definitions=None, resolver=None, excluded_routes=None):
    """Compare one app's declarations with its active protected URL routes."""
    excluded_routes = frozenset(
        DEFAULT_EXCLUDED_ROUTES if excluded_routes is None else excluded_routes
    )
    definitions = _definitions_for_app(app, definitions)
    resolver = resolver or get_resolver()
    patterns = tuple(_iter_url_patterns(resolver.url_patterns))
    route_names = {
        route_name
        for _, route_name in patterns
        if route_name and route_name.startswith(f"{app}:")
    }
    protected_routes = tuple(
        route
        for pattern, route_name in patterns
        if route_name
        and route_name.startswith(f"{app}:")
        and route_name not in excluded_routes
        for route in _protected_routes_for_pattern(pattern, route_name, app)
    )
    issues = _structural_issues(app, definitions, route_names)
    declaration_by_method = {}
    declaration_by_route = {}
    bindings = []
    for definition in definitions:
        for binding in tuple(getattr(definition, "routes", ())):
            for method in binding.methods:
                key = (binding.route_name, method)
                bindings.append((definition, binding, method))
                declaration_by_method.setdefault(key, []).append((definition, binding))
                declaration_by_route.setdefault(binding.route_name, []).append((definition, binding))
                if binding.route_name not in route_names and binding.route_name not in excluded_routes:
                    _append_issue(
                        issues,
                        AuditIssue(
                            code="route_not_found",
                            app=app,
                            route_name=binding.route_name,
                            definition_key=definition.key,
                            expected="ruta Django existente",
                            actual="ruta inexistente",
                        ),
                    )

    for key, entries in declaration_by_method.items():
        definition_keys = {entry[0].key for entry in entries}
        if len(definition_keys) > 1:
            _append_issue(
                issues,
                AuditIssue(
                    code="route_bound_to_multiple_definitions",
                    app=app,
                    route_name=key[0],
                    expected="una superficie por ruta y método",
                    actual=", ".join(sorted(definition_keys)),
                    detail=f"Conflicto para el método {key[1]}.",
                ),
            )

    declaration_by_actual = {}
    for route in protected_routes:
        declaration_by_actual.setdefault((route.route_name, route.method), []).append(route)
        entries = declaration_by_method.get((route.route_name, route.method), ())
        if not entries:
            if route.route_name not in declaration_by_route:
                _append_issue(
                    issues,
                    AuditIssue(
                        code="protected_route_without_definition",
                        app=app,
                        route_name=route.route_name,
                        actual=route.vista_nombre,
                        detail=f"{route.method} no tiene definición declarativa.",
                    ),
                )
            continue
        for definition, binding in entries:
            if route.vista_nombre != definition.nombre:
                _append_issue(
                    issues,
                    AuditIssue(
                        code="view_name_mismatch",
                        app=app,
                        route_name=route.route_name,
                        definition_key=definition.key,
                        expected=definition.nombre,
                        actual=route.vista_nombre,
                    ),
                )
            if route.permiso_requerido != binding.permiso_requerido:
                _append_issue(
                    issues,
                    AuditIssue(
                        code="permission_mismatch",
                        app=app,
                        route_name=route.route_name,
                        definition_key=definition.key,
                        expected=binding.permiso_requerido,
                        actual=route.permiso_requerido,
                        detail=f"Comparado para {route.method}.",
                    ),
                )

    issues = tuple(sorted(issues, key=_issue_key))
    return AuditResult(
        app=app,
        definitions=tuple(sorted(definitions, key=lambda definition: definition.key)),
        bindings=tuple(bindings),
        protected_routes=tuple(
            sorted(protected_routes, key=lambda route: (route.route_name, route.method))
        ),
        issues=issues,
    )


def audit_all_registered_apps():
    return tuple(audit_app(app) for app in sorted(APP_DEFINITION_MODULES))