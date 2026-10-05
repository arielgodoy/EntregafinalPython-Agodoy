"""Scheduling rules for formal tasks (T030)."""

from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.utils import timezone

from tareas.models import TareaTransicion


def _as_date(value):
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            return timezone.localtime(value).date()
        return value.date()
    if isinstance(value, date):
        return value
    raise ValidationError("La fecha de referencia debe ser una fecha válida.")


def _fecha_anulacion(tarea):
    return (
        TareaTransicion.objects.filter(tarea=tarea, accion_evento="ANULAR")
        .order_by("-timestamp")
        .values_list("timestamp", flat=True)
        .first()
    )


def _fecha_referencia_efectiva(tarea, fecha_referencia):
    referencia = fecha_referencia or timezone.now()
    if not isinstance(referencia, datetime):
        referencia = datetime.combine(referencia, datetime.min.time())
        referencia = timezone.make_aware(referencia)

    if tarea.fecha_cumplimiento is not None:
        referencia = min(referencia, tarea.fecha_cumplimiento)
    if tarea.anulada:
        fecha_anulacion = _fecha_anulacion(tarea)
        if fecha_anulacion is not None:
            referencia = min(referencia, fecha_anulacion)
    return referencia


def esta_vencida(tarea, fecha_referencia=None):
    if tarea.fecha_tope is None:
        return False
    referencia = _fecha_referencia_efectiva(tarea, fecha_referencia)
    return referencia.date() > tarea.fecha_tope


def dias_atraso(tarea, fecha_referencia=None):
    if tarea.fecha_tope is None:
        return 0
    referencia = _fecha_referencia_efectiva(tarea, fecha_referencia).date()
    return max(0, (referencia - tarea.fecha_tope).days)


def reprogramar(tarea, fecha_tope_nueva, justificacion, usuario, causas):
    """Compatibility entry point; operational work always uses the resolved backend."""
    from .reprogramming_storage import ReprogramTaskCommand, reprogram_task

    result = reprogram_task(ReprogramTaskCommand(
        tarea.pk, tarea.empresa_id, usuario.pk, fecha_tope_nueva, justificacion,
        tuple(getattr(causa, "pk", causa) for causa in (causas or ())),
    ))
    tarea.fecha_tope = result.fecha_tope_nueva
    return result