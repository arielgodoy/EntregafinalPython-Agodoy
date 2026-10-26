"""Declarative VICMEAS registrations for task surfaces."""

from access_control.services.view_registry import (
    RouteBinding,
    VistaDefinition,
    register_app_definitions,
)
from tareas.services.authorization import MEETINGS_VISTA_NAME


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

MEETINGS = VistaDefinition(
    key="tasks_meetings",
    app="tareas",
    nombre=MEETINGS_VISTA_NAME,
    route_name="tareas:reunion_revision_lista",
    routes=(
        RouteBinding("tareas:reunion_revision_lista", "ingresar"),
        RouteBinding(
            "tareas:reunion_revision_crear",
            "crear",
            methods=("GET", "POST"),
        ),
        RouteBinding("tareas:reunion_revision_detalle", "ingresar"),
        RouteBinding(
            "tareas:reunion_revision_editar",
            "modificar",
            methods=("GET", "POST"),
        ),
        RouteBinding(
            "tareas:reunion_revision_accion",
            "modificar",
            methods=("POST",),
        ),
    ),
    navigable=True,
    group="tasks",
)

register_app_definitions("tareas", (DELETED_TASKS_HISTORY, MEETINGS))
