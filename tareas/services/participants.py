"""Functional task participation without materializing implicit responsibility."""

from tareas.models import Hito, TareaParticipante


def is_effective_participant(tarea, usuario):
    """Return whether the user has an active functional role on the task."""
    if usuario is None:
        return False
    if tarea.responsable_id == usuario.pk:
        return True
    if TareaParticipante.objects.filter(
        tarea_id=tarea.pk,
        usuario_id=usuario.pk,
    ).exists():
        return True
    return Hito.objects.filter(
        tarea_id=tarea.pk,
        responsable_id=usuario.pk,
        anulado=False,
    ).exists()


def effective_participant_ids(tarea):
    """Return unique effective participant ids, including active milestone owners."""
    participant_ids = set(
        TareaParticipante.objects.filter(tarea_id=tarea.pk).values_list(
            "usuario_id", flat=True
        )
    )
    if tarea.responsable_id is not None:
        participant_ids.add(tarea.responsable_id)
    participant_ids.update(
        Hito.objects.filter(tarea_id=tarea.pk, anulado=False).values_list(
            "responsable_id", flat=True
        )
    )
    return participant_ids
