"""Contextual authorization rules owned by the tareas domain."""

from access_control.services.permissions import (
    get_valid_users_for_empresa,
    user_has_permission_for_empresa,
)


def can_manage_task(*, tarea, actor, vista_nombre="Tareas", accion="modificar"):
    """Return whether an actor may administer this concrete task."""
    if actor is None or not actor.is_active:
        return False
    if not get_valid_users_for_empresa(tarea.empresa, active_only=True).filter(
        pk=actor.pk
    ).exists():
        return False
    if not user_has_permission_for_empresa(
        user=actor,
        empresa=tarea.empresa,
        vista_nombre=vista_nombre,
        accion=accion,
    ):
        return False
    return actor.pk == tarea.creada_por_id or user_has_permission_for_empresa(
        user=actor,
        empresa=tarea.empresa,
        vista_nombre=vista_nombre,
        accion="supervisor",
    )