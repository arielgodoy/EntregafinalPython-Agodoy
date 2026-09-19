"""Declarative VICMEAS surfaces owned by evaluaciones."""

from access_control.services.view_registry import (
    RouteBinding,
    VistaDefinition,
    register_app_definitions,
)


EVALUACIONES_VIEW_DEFINITIONS = (
    VistaDefinition(
        key="evaluaciones.importar_personas",
        app="evaluaciones",
        nombre="Evaluaciones - Importar Personas",
        route_name="evaluaciones:importar_personas",
        routes=(
            RouteBinding("evaluaciones:importar_personas", "ingresar", ("GET", "POST")),
            RouteBinding("evaluaciones:importar_personas_start", "supervisor", ("POST",)),
            RouteBinding("evaluaciones:importar_personas_status", "ingresar", ("GET",)),
        ),
        navigable=True,
        access_utility=True,
        group="evaluaciones",
    ),
)


register_app_definitions("evaluaciones", EVALUACIONES_VIEW_DEFINITIONS)
