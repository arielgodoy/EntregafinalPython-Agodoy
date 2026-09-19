"""Declarative VICMEAS surfaces owned by proveedores."""

from access_control.services.view_registry import (
    RouteBinding,
    VistaDefinition,
    register_app_definitions,
)


PROVEEDORES_VIEW_DEFINITIONS = (
    VistaDefinition(
        key="proveedores.maestros",
        app="proveedores",
        nombre="Maestros - Proveedores",
        route_name="proveedores:listado",
        routes=(
            RouteBinding("proveedores:listado_raiz", "ingresar"),
            RouteBinding("proveedores:listado", "ingresar"),
            RouteBinding("proveedores:crear", "crear", ("GET", "POST", "PUT")),
            RouteBinding("proveedores:detalle", "ingresar"),
            RouteBinding("proveedores:editar", "modificar", ("GET", "POST", "PUT")),
            RouteBinding("proveedores:inactivar", "eliminar", ("POST",)),
            RouteBinding("proveedores:reactivar", "modificar", ("POST",)),
        ),
        navigable=True,
        access_utility=True,
        group="proveedores",
    ),
)


register_app_definitions("proveedores", PROVEEDORES_VIEW_DEFINITIONS)
