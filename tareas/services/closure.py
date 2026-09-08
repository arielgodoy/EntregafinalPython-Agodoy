"""Closure rules for mini-tasks (T031)."""

from django.core.exceptions import ValidationError
from django.utils import timezone

from tareas.models import MiniTarea
from tareas.services.assignment import _validate_user_in_task_company


def create_mini_task(*, tarea, descripcion, persona):
    descripcion = str(descripcion or "").strip()
    if not descripcion:
        raise ValidationError("La descripción de la mini-tarea es obligatoria.")
    _validate_user_in_task_company(tarea, persona)
    return MiniTarea.objects.create(
        tarea=tarea,
        descripcion=descripcion,
        persona=persona,
    )


def set_mini_task_done(mini_tarea, hecho=True):
    mini_tarea.hecho = bool(hecho)
    mini_tarea.fecha_completado = timezone.now() if mini_tarea.hecho else None
    mini_tarea.save(update_fields=["hecho", "fecha_completado"])
    return mini_tarea


def has_pending_mini_tasks(tarea):
    return tarea.mini_tareas.filter(hecho=False).exists()


def ensure_no_pending_mini_tasks(tarea):
    if has_pending_mini_tasks(tarea):
        raise ValidationError("No se puede cerrar una tarea con mini-tareas pendientes.")