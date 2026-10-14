"""Read-only presentation data for the personal tasks dashboard."""

from ..models import Tarea
from .kpi import OPEN_STATES, PUBLISHED_STATES


MAX_VISIBLE_ITEMS = 5


def build_personal_dashboard_presentation(dashboard_data):
    tasks = dashboard_data["tareas"]
    reference_date = dashboard_data["filters"]["reference_date"]
    tasks_by_state = []

    for state in PUBLISHED_STATES:
        state_tasks = [task for task in tasks if task.estado == state]
        tasks_by_state.append(
            {
                "estado": state,
                "total": len(state_tasks),
                "tareas": state_tasks[:MAX_VISIBLE_ITEMS],
                "has_more": len(state_tasks) > MAX_VISIBLE_ITEMS,
            }
        )

    overdue_count = sum(
        not task.anulada
        and task.estado in OPEN_STATES
        and task.fecha_tope is not None
        and task.fecha_tope < reference_date
        and task.fecha_cumplimiento is None
        for task in tasks
    )

    pending_milestones = [
        milestone
        for milestone in dashboard_data["hitos"]
        if not milestone.anulado and not milestone.completado
    ]
    pending_minitasks = dashboard_data["mini_tareas_pendientes"]

    return {
        "dashboard_kpis": [
            {
                "key": "tareas.dashboard.personal.kpi.total_tasks",
                "label": "Total de mis tareas",
                "value": len(tasks),
                "icon": "ri-task-line",
            },
            {
                "key": "tareas.dashboard.personal.kpi.active",
                "label": "Tareas activas",
                "value": sum(task.estado == Tarea.Estado.ACTIVA for task in tasks),
                "icon": "ri-play-circle-line",
            },
            {
                "key": "tareas.dashboard.personal.kpi.management",
                "label": "Tareas en gestión",
                "value": sum(task.estado == Tarea.Estado.GESTION for task in tasks),
                "icon": "ri-loader-4-line",
            },
            {
                "key": "tareas.dashboard.personal.kpi.pending_approval",
                "label": "Pendientes de aprobación de cierre",
                "value": sum(
                    task.estado == Tarea.Estado.PENDIENTE_APROBACION_CIERRE
                    for task in tasks
                ),
                "icon": "ri-time-line",
            },
            {
                "key": "tareas.dashboard.personal.kpi.closed",
                "label": "Tareas cerradas",
                "value": sum(
                    task.estado == Tarea.Estado.CERRADA for task in tasks
                ),
                "icon": "ri-checkbox-circle-line",
            },
            {
                "key": "tareas.dashboard.personal.kpi.overdue",
                "label": "Tareas vencidas",
                "value": overdue_count,
                "icon": "ri-alarm-warning-line",
            },
            {
                "key": "tareas.dashboard.personal.kpi.pending_milestones",
                "label": "Mis hitos pendientes",
                "value": len(pending_milestones),
                "icon": "ri-flag-line",
            },
            {
                "key": "tareas.dashboard.personal.kpi.pending_minitasks",
                "label": "Mis minitareas pendientes",
                "value": len(pending_minitasks),
                "icon": "ri-list-check-2",
            },
        ],
        "dashboard_state_groups": tasks_by_state,
        "dashboard_has_tasks": bool(tasks),
        "dashboard_pending_milestones": pending_milestones[
            :MAX_VISIBLE_ITEMS
        ],
        "dashboard_pending_milestones_count": len(pending_milestones),
        "dashboard_pending_milestones_has_more": (
            len(pending_milestones) > MAX_VISIBLE_ITEMS
        ),
        "dashboard_pending_minitasks": pending_minitasks[:MAX_VISIBLE_ITEMS],
        "dashboard_pending_minitasks_count": len(pending_minitasks),
        "dashboard_pending_minitasks_has_more": (
            len(pending_minitasks) > MAX_VISIBLE_ITEMS
        ),
    }
