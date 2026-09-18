"""Declarative VICMEAS surface registry.

This module is intentionally persistence-free. Application modules register
functional surfaces explicitly; catalog materialization is a later concern.
"""

from dataclasses import dataclass


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


class ViewRegistryError(ValueError):
    """Base error for invalid declarative VICMEAS definitions."""


class DuplicateDefinitionKeyError(ViewRegistryError):
    """Raised when a key is registered with incompatible metadata."""


class DuplicateDefinitionNameError(ViewRegistryError):
    """Raised when a VICMEAS name is assigned to incompatible surfaces."""


class DuplicateRouteBindingError(ViewRegistryError):
    """Raised when one route is assigned to incompatible surfaces."""


@dataclass(frozen=True)
class RouteBinding:
    route_name: str
    permiso_requerido: str
    methods: tuple[str, ...] = ("GET",)

    def __post_init__(self):
        route_name = self.route_name.strip()
        permission = self.permiso_requerido.strip()
        methods = tuple(method.strip().upper() for method in self.methods)
        if not route_name:
            raise ViewRegistryError("RouteBinding requiere route_name.")
        if permission not in VALID_PERMISSION_NAMES:
            raise ViewRegistryError(
                f"Permiso VICMEAS inválido para {route_name}: {permission}."
            )
        if not methods or any(not method for method in methods):
            raise ViewRegistryError(f"RouteBinding inválido para {route_name}.")
        if len(set(methods)) != len(methods):
            raise ViewRegistryError(f"Métodos duplicados para {route_name}.")
        object.__setattr__(self, "route_name", route_name)
        object.__setattr__(self, "permiso_requerido", permission)
        object.__setattr__(self, "methods", methods)


@dataclass(frozen=True)
class VistaDefinition:
    key: str
    app: str
    nombre: str
    route_name: str
    routes: tuple[RouteBinding, ...]
    navigable: bool = False
    access_utility: bool = False
    group: str | None = None

    def __post_init__(self):
        values = {
            "key": self.key,
            "app": self.app,
            "nombre": self.nombre,
            "route_name": self.route_name,
        }
        for field_name, value in values.items():
            if not isinstance(value, str) or not value.strip():
                raise ViewRegistryError(f"VistaDefinition requiere {field_name}.")
            object.__setattr__(self, field_name, value.strip())

        if self.group is not None:
            group = self.group.strip()
            if not group:
                raise ViewRegistryError("group no puede estar vacío.")
            object.__setattr__(self, "group", group)

        routes = tuple(self.routes)
        if not routes:
            raise ViewRegistryError(f"{self.key} requiere al menos un RouteBinding.")
        if any(not isinstance(route, RouteBinding) for route in routes):
            raise ViewRegistryError(f"{self.key} contiene un binding inválido.")
        if self.route_name not in {route.route_name for route in routes}:
            raise ViewRegistryError(
                f"La ruta canónica {self.route_name} no está declarada en {self.key}."
            )
        route_methods = [(route.route_name, method) for route in routes for method in route.methods]
        if len(route_methods) != len(set(route_methods)):
            raise ViewRegistryError(f"Bindings duplicados dentro de {self.key}.")
        object.__setattr__(self, "routes", routes)

    @property
    def namespace(self):
        return self.app

    @property
    def route_bindings(self):
        return self.routes


class ViewRegistry:
    """Explicit in-memory registry for application-owned VICMEAS surfaces."""

    def __init__(self):
        self._definitions_by_key = {}
        self._keys_by_name = {}
        self._keys_by_route = {}

    def register(self, definition: VistaDefinition):
        if not isinstance(definition, VistaDefinition):
            raise TypeError("Solo se pueden registrar VistaDefinition.")

        existing = self._definitions_by_key.get(definition.key)
        if existing is not None:
            if existing != definition:
                raise DuplicateDefinitionKeyError(
                    f"La key VICMEAS ya existe con otra definición: {definition.key}."
                )
            return existing

        existing_key = self._keys_by_name.get(definition.nombre)
        if existing_key is not None:
            raise DuplicateDefinitionNameError(
                f"El nombre VICMEAS ya pertenece a otra definición: {definition.nombre}."
            )

        for binding in definition.routes:
            route_key = binding.route_name
            existing_route_key = self._keys_by_route.get(route_key)
            if existing_route_key is not None and existing_route_key != definition.key:
                raise DuplicateRouteBindingError(
                    f"La ruta ya pertenece a otra superficie: {route_key}."
                )

        self._definitions_by_key[definition.key] = definition
        self._keys_by_name[definition.nombre] = definition.key
        for binding in definition.routes:
            self._keys_by_route[binding.route_name] = definition.key
        return definition

    def register_many(self, definitions):
        registered = tuple(self.register(definition) for definition in definitions)
        return registered

    def all(self):
        return tuple(
            self._definitions_by_key[key]
            for key in sorted(self._definitions_by_key)
        )

    def by_app(self, app):
        return tuple(definition for definition in self.all() if definition.app == app)

    def by_group(self, group):
        return tuple(definition for definition in self.all() if definition.group == group)

    def administrable(self):
        return tuple(definition for definition in self.all() if definition.access_utility)

    def navigable(self):
        return tuple(definition for definition in self.all() if definition.navigable)

    def get(self, key):
        try:
            return self._definitions_by_key[key]
        except KeyError as error:
            raise KeyError(f"No existe la definición VICMEAS: {key}.") from error

    def for_route(self, route_name):
        key = self._keys_by_route.get(route_name)
        if key is None:
            raise KeyError(f"No existe una definición para la ruta: {route_name}.")
        return self.get(key)

    def bindings_for_route(self, route_name, method=None):
        definition = self.for_route(route_name)
        bindings = tuple(
            binding
            for binding in definition.routes
            if binding.route_name == route_name
            and (method is None or method.upper() in binding.methods)
        )
        if not bindings:
            raise KeyError(
                f"No existe un binding para {route_name} y método {method}."
            )
        return bindings


_registry = ViewRegistry()


def get_registry():
    return _registry


def register_app_definitions(app, definitions):
    definitions = tuple(definitions)
    for definition in definitions:
        if definition.app != app:
            raise ViewRegistryError(
                f"La definición {definition.key} no pertenece a la app {app}."
            )
    return _registry.register_many(definitions)


def all_definitions():
    return _registry.all()


def definitions_for_app(app):
    return _registry.by_app(app)


def definitions_for_group(group):
    return _registry.by_group(group)


def administrable_definitions():
    return _registry.administrable()


def navigable_definitions():
    return _registry.navigable()


def definition_for_key(key):
    return _registry.get(key)


def definition_for_route(route_name):
    return _registry.for_route(route_name)


def bindings_for_route(route_name, method=None):
    return _registry.bindings_for_route(route_name, method)
