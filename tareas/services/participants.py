"""Functional task participation without materializing implicit roles."""

from tareas.services.detail_storage import TaskDetailSections, resolve_detail_storage


def _effective_ids(tarea):
    detail = resolve_detail_storage().get_task_detail(
        task_id=tarea.pk,
        empresa_id=tarea.empresa_id,
        sections=TaskDetailSections(mini_tasks=True, milestones=True),
    )
    ids = set(detail.effective_user_ids)
    ids.update(participant.user_id for participant in detail.participants)
    ids.update((detail.core.creada_por_id, detail.core.responsable_id))
    return {user_id for user_id in ids if user_id is not None}


def is_effective_participant(tarea, usuario):
    """Return whether the user has an active functional role on the task."""
    if usuario is None:
        return False
    ids = getattr(tarea, "_tareas_effective_user_ids", None)
    if ids is not None:
        return usuario.pk in ids
    return usuario.pk in _effective_ids(tarea)


def effective_participant_ids(tarea):
    """Return unique effective participant ids, including active milestone owners."""
    ids = getattr(tarea, "_tareas_effective_user_ids", None)
    if ids is not None:
        return set(ids)
    return _effective_ids(tarea)
