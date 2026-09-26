"""Functional task participation without materializing implicit responsibility."""

from tareas.models import TareaParticipante


def is_effective_participant(tarea, usuario):
    """Return whether the user is responsible or explicitly linked to the task."""
    if usuario is None:
        return False
    return tarea.responsable_id == usuario.pk or TareaParticipante.objects.filter(
        tarea_id=tarea.pk,
        usuario_id=usuario.pk,
    ).exists()


def effective_participant_ids(tarea):
    """Return unique effective participant ids for a task."""
    participant_ids = set(
        TareaParticipante.objects.filter(tarea_id=tarea.pk).values_list(
            "usuario_id", flat=True
        )
    )
    if tarea.responsable_id is not None:
        participant_ids.add(tarea.responsable_id)
    return participant_ids
