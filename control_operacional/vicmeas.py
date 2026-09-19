"""Declarative VICMEAS surfaces owned by control_operacional."""

from access_control.services.view_registry import (
    RouteBinding,
    VistaDefinition,
    register_app_definitions,
)


CONTROL_OPERACIONAL_VIEW_DEFINITIONS = (
    VistaDefinition(
        key="control_operacional.dashboard",
        app="control_operacional",
        nombre="Control Operacional - Dashboard",
        route_name="control_operacional:dashboard",
        routes=(
            RouteBinding("control_operacional:dashboard", "ingresar"),
        ),
        navigable=True,
        access_utility=True,
        group="control_operacional",
    ),
    VistaDefinition(
        key="control_operacional.alertas",
        app="control_operacional",
        nombre="Control Operacional - Alertas",
        route_name="control_operacional:alertas_operacionales",
        routes=(
            RouteBinding("control_operacional:alertas_operacionales", "ingresar"),
            RouteBinding("control_operacional:ack_alerta", "ingresar", ("GET", "POST")),
        ),
        navigable=True,
        access_utility=True,
        group="control_operacional",
    ),
)


register_app_definitions("control_operacional", CONTROL_OPERACIONAL_VIEW_DEFINITIONS)
