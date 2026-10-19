"""Declarative VICMEAS registration for the deleted-task history surface."""

from access_control.services.view_registry import (
    RouteBinding,
    VistaDefinition,
    register_app_definitions,
)


DELETED_TASKS_HISTORY = VistaDefinition(
    key="tasks_deleted",
    app="tareas",
    nombre="Tareas - Tareas eliminadas",
    route_name="tareas:eliminadas_lista",
    routes=(
        RouteBinding("tareas:eliminadas_lista", "ingresar"),
        RouteBinding("tareas:eliminada_detalle", "ingresar"),
        RouteBinding("tareas:eliminacion_operacion_detalle", "ingresar"),
    ),
    navigable=True,
    group="tasks",
)

register_app_definitions("tareas", (DELETED_TASKS_HISTORY,))
