"""Functional task participation without materializing implicit roles."""

from tareas.models import Hito, MiniTarea, TareaParticipante


def is_effective_participant(tarea, usuario):
    """Return whether the user has an active functional role on the task."""
    if usuario is None:
        return False
    ids = getattr(tarea, "_tareas_effective_user_ids", None)
    if ids is not None:
        return usuario.pk in ids
    alias = tarea._state.db or "default"
    if tarea.creada_por_id == usuario.pk:
        return True
    if tarea.responsable_id == usuario.pk:
        return True
    if TareaParticipante.objects.using(alias).filter(
        tarea_id=tarea.pk,
        usuario_id=usuario.pk,
    ).exists():
        return True
    if MiniTarea.objects.using(alias).filter(
        tarea_id=tarea.pk,
        persona_id=usuario.pk,
    ).exists():
        return True
    return Hito.objects.using(alias).filter(
        tarea_id=tarea.pk,
        responsable_id=usuario.pk,
        anulado=False,
    ).exists()


def effective_participant_ids(tarea):
    """Return unique effective participant ids, including active milestone owners."""
    ids = getattr(tarea, "_tareas_effective_user_ids", None)
    if ids is not None:
        return set(ids)
    alias = tarea._state.db or "default"
    participant_ids = set(
        TareaParticipante.objects.using(alias).filter(tarea_id=tarea.pk).values_list(
            "usuario_id", flat=True
        )
    )
    if tarea.creada_por_id is not None:
        participant_ids.add(tarea.creada_por_id)
    if tarea.responsable_id is not None:
        participant_ids.add(tarea.responsable_id)
    participant_ids.update(
        Hito.objects.using(alias).filter(tarea_id=tarea.pk, anulado=False).values_list(
            "responsable_id", flat=True
        )
    )
    participant_ids.update(
        MiniTarea.objects.using(alias).filter(tarea_id=tarea.pk).values_list(
            "persona_id", flat=True
        )
    )
    return participant_ids
