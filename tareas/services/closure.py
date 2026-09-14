"""Closure rules for mini-tasks (T031)."""

from django.core.exceptions import ValidationError
from django.utils import timezone

from tareas.models import EvidenciaCierre, MiniTarea
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


def validate_closure_requirements(tarea):
    """Validate the domain rules that can block task closure."""
    errores = []
    if has_pending_mini_tasks(tarea):
        errores.append("MINI_TASKS_PENDING: No se puede cerrar una tarea con mini-tareas pendientes.")

    from tareas.services.hierarchy import has_open_operational_descendants

    if has_open_operational_descendants(tarea):
        errores.append(
            "DESCENDANTS_PENDING: No se puede cerrar una tarea con descendientes operativos pendientes."
        )

    evidencia_valida = any(
        _is_valid_closure_evidence(evidencia)
        for evidencia in EvidenciaCierre.objects.filter(tarea=tarea)
    )
    if tarea.requiere_evidencia_cierre and not evidencia_valida:
        errores.append(
            "CLOSURE_EVIDENCE_REQUIRED: Se requiere al menos una evidencia de cierre válida."
        )

    from tareas.services.quotations import (
        get_latest_quotation_round,
        has_quotation_process,
        quotation_minimum_met,
    )

    if has_quotation_process(tarea):
        ronda = get_latest_quotation_round(tarea)
        if not quotation_minimum_met(ronda):
            errores.append(
                "QUOTATION_MINIMUM_NOT_MET: La última ronda no cumple el mínimo de cotizaciones vigentes."
            )

    if errores:
        raise ValidationError(errores)


def _is_valid_closure_evidence(evidencia):
    if not evidencia.archivo and not evidencia.url:
        return False
    try:
        evidencia.full_clean()
    except ValidationError:
        return False
    return True