"""Declarative VICMEAS surfaces owned by the tareas application."""

from access_control.services.view_registry import (
    RouteBinding,
    VistaDefinition,
    register_app_definitions,
)


TASKS_VIEW_DEFINITIONS = (
    VistaDefinition(
        key="tareas.tasks",
        app="tareas",
        nombre="Tareas",
        route_name="tareas:listar_tareas",
        routes=(
            RouteBinding("tareas:listar_tareas", "ingresar"),
            RouteBinding("tareas:detalle_tarea", "ingresar", ("GET",)),
            RouteBinding("tareas:detalle_tarea", "modificar", ("POST",)),
            RouteBinding("tareas:crear_tarea", "crear", ("GET", "POST")),
            RouteBinding("tareas:editar_tarea", "modificar", ("GET", "POST")),
            RouteBinding("tareas:crear_enlace_tarea", "modificar", ("POST",)),
            RouteBinding("tareas:revocar_enlace_tarea", "modificar", ("POST",)),
            RouteBinding("tareas:reunion_revision_lista", "ingresar"),
            RouteBinding("tareas:reunion_revision_crear", "crear", ("GET", "POST")),
            RouteBinding("tareas:reunion_revision_detalle", "ingresar"),
            RouteBinding("tareas:reunion_revision_editar", "modificar", ("GET", "POST")),
            RouteBinding("tareas:dashboard_general", "supervisor"),
            RouteBinding("tareas:dashboard_general_empresa", "supervisor"),
            RouteBinding("tareas:dashboard_general_departamento", "supervisor"),
            RouteBinding("tareas:dashboard_general_usuario", "supervisor"),
        ),
        navigable=True,
        access_utility=True,
        group="tasks",
    ),
    VistaDefinition(
        key="tareas.lifecycle",
        app="tareas",
        nombre="Tareas - Ciclo de vida",
        route_name="tareas:publicar_tarea",
        routes=(
            RouteBinding("tareas:publicar_tarea", "modificar", ("POST",)),
            RouteBinding("tareas:gestionar_tarea", "modificar", ("POST",)),
            RouteBinding("tareas:completar_tarea", "modificar", ("POST",)),
            RouteBinding("tareas:aprobar_cierre", "modificar", ("POST",)),
            RouteBinding("tareas:rechazar_cierre", "modificar", ("POST",)),
            RouteBinding("tareas:anular_tarea", "modificar", ("POST",)),
            RouteBinding("tareas:reactivar_tarea", "modificar", ("POST",)),
            RouteBinding("tareas:similitud_tarea", "modificar"),
            RouteBinding("tareas:confirmar_similitud", "modificar", ("POST",)),
            RouteBinding("tareas:reunion_revision_accion", "modificar", ("POST",)),
        ),
        access_utility=True,
        group="tasks",
    ),
    VistaDefinition(
        key="tareas.milestones",
        app="tareas",
        nombre="Tareas - Hitos",
        route_name="tareas:hitos_tarea",
        routes=(RouteBinding("tareas:hitos_tarea", "ingresar", ("GET", "POST")),),
        access_utility=True,
        group="tasks",
    ),
    VistaDefinition(
        key="tareas.documents",
        app="tareas",
        nombre="Tareas - Documentos y evidencia",
        route_name="tareas:documentos_tarea",
        routes=(RouteBinding("tareas:documentos_tarea", "modificar", ("GET", "POST")),),
        access_utility=True,
        group="tasks",
    ),
    VistaDefinition(
        key="tareas.personal_dashboard",
        app="tareas",
        nombre="Tareas - Dashboard personal",
        route_name="tareas:mis_tareas",
        routes=(RouteBinding("tareas:mis_tareas", "ingresar"),),
        navigable=True,
        access_utility=True,
        group="tasks",
    ),
)


register_app_definitions("tareas", TASKS_VIEW_DEFINITIONS)

RECONCILIATION_RELEASES = (
    ("Tareas - Listado", "tareas:listar_tareas"),
    ("Tareas - Publicar tarea", "tareas:publicar_tarea"),
)
