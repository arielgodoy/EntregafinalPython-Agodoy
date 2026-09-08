"""Scheduling rules for formal tasks (T030)."""

from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from access_control.services.permissions import get_valid_users_for_empresa
from tareas.models import CausaAtraso, Reprogramacion, Tarea, TareaTransicion


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


def _validate_causas(causas):
    causas = list(causas or [])
    if not causas:
        raise ValidationError("Debe indicar al menos una causa de atraso.")
    ids = {getattr(causa, "pk", causa) for causa in causas}
    if None in ids or len(ids) != len(causas):
        raise ValidationError("Las causas de atraso no son válidas.")
    valid_ids = set(CausaAtraso.objects.filter(pk__in=ids).values_list("pk", flat=True))
    if valid_ids != ids:
        raise ValidationError("Las causas de atraso no son válidas.")
    return list(ids)


def reprogramar(tarea, fecha_tope_nueva, justificacion, usuario, causas):
    """Change an existing deadline and persist its complete audit trail."""
    if tarea.pk is None or tarea.fecha_tope is None:
        raise ValidationError("Solo se puede reprogramar una tarea con fecha tope definida.")
    justificacion = str(justificacion or "").strip()
    if not justificacion:
        raise ValidationError("La justificación de reprogramación es obligatoria.")
    fecha_tope_nueva = _as_date(fecha_tope_nueva)
    causas_ids = _validate_causas(causas)
    if not get_valid_users_for_empresa(tarea.empresa).filter(pk=getattr(usuario, "pk", None)).exists():
        raise ValidationError("El usuario no pertenece al contexto de la empresa de la tarea.")

    with transaction.atomic():
        tarea_bloqueada = Tarea.objects.select_for_update().get(pk=tarea.pk)
        if tarea_bloqueada.empresa_id != tarea.empresa_id:
            raise ValidationError("La tarea no pertenece al contexto esperado.")
        fecha_anterior = tarea_bloqueada.fecha_tope
        if fecha_anterior is None or fecha_anterior == fecha_tope_nueva:
            raise ValidationError("La nueva fecha tope debe modificar la fecha existente.")
        tarea_bloqueada.fecha_tope = fecha_tope_nueva
        tarea_bloqueada.save(update_fields=["fecha_tope"])
        historial = Reprogramacion.objects.create(
            tarea=tarea_bloqueada,
            fecha_tope_anterior=fecha_anterior,
            fecha_tope_nueva=fecha_tope_nueva,
            justificacion=justificacion,
            usuario=usuario,
        )
        historial.causas.set(causas_ids)
    tarea.fecha_tope = fecha_tope_nueva
    return historial