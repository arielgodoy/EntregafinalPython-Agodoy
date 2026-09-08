"""Phase 2 lifecycle actions for one task only."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from tareas.models import Tarea, TareaAnulacionSnapshot, TareaCierre, TareaTransicion


_ALLOWED = {
    Tarea.Estado.ACTIVA: {Tarea.Estado.GESTION, Tarea.Estado.ANULADA},
    Tarea.Estado.GESTION: {
        Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
        Tarea.Estado.ANULADA,
    },
    Tarea.Estado.PENDIENTE_APROBACION_CIERRE: {
        Tarea.Estado.CERRADA,
        Tarea.Estado.GESTION,
        Tarea.Estado.ANULADA,
    },
}


def transition_task(tarea, destino, usuario, accion_evento, motivo=""):
    if destino not in _ALLOWED.get(tarea.estado, set()):
        raise ValidationError(
            f"Transición no permitida: {tarea.estado} -> {destino}."
        )
    origen = tarea.estado
    tarea.estado = destino
    tarea.full_clean()
    tarea.save(update_fields=["estado"])
    return TareaTransicion.objects.create(
        tarea=tarea,
        estado_origen=origen,
        estado_destino=destino,
        accion_evento=accion_evento,
        usuario=usuario,
        motivo=motivo,
    )


def publish_task(tarea, usuario):
    with transaction.atomic():
        tarea.publicar(usuario=usuario)
    return tarea


def complete_task(tarea, usuario):
    tarea.cierre_completado = True
    tarea.save(update_fields=["cierre_completado"])
    return transition_task(
        tarea,
        Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
        usuario,
        "MARCAR_100",
    )


def approve_closure(tarea, usuario, comentario=""):
    with transaction.atomic():
        transition = transition_task(
            tarea,
            Tarea.Estado.CERRADA,
            usuario,
            "APROBAR_CIERRE",
            comentario,
        )
        tarea.cierre_completado = True
        tarea.save(update_fields=["cierre_completado"])
        TareaCierre.objects.create(
            tarea=tarea,
            usuario=usuario,
            resultado=TareaCierre.Resultado.APROBADO,
            comentario=comentario,
        )
    return transition


def reject_closure(tarea, usuario, comentario=""):
    with transaction.atomic():
        transition = transition_task(
            tarea,
            Tarea.Estado.GESTION,
            usuario,
            "RECHAZAR_CIERRE",
            comentario,
        )
        tarea.cierre_completado = True
        tarea.save(update_fields=["cierre_completado"])
        TareaCierre.objects.create(
            tarea=tarea,
            usuario=usuario,
            resultado=TareaCierre.Resultado.RECHAZADO,
            comentario=comentario,
        )
    return transition


def annul_task(tarea, usuario, motivo=""):
    if tarea.estado in {Tarea.Estado.BORRADOR, Tarea.Estado.CERRADA, Tarea.Estado.ANULADA}:
        raise ValidationError("La tarea no puede anularse desde su estado actual.")
    with transaction.atomic():
        TareaAnulacionSnapshot.objects.create(
            tarea=tarea,
            estado_anterior=tarea.estado,
            fechas_pendientes_confirmacion=tarea.fechas_pendientes_confirmacion,
            usuario_anulo=usuario,
        )
        transition_task(tarea, Tarea.Estado.ANULADA, usuario, "ANULAR", motivo)
    return tarea


def reactivate_task(tarea, usuario, motivo=""):
    snapshot = (
        TareaAnulacionSnapshot.objects.filter(tarea=tarea, usuario_reactivo__isnull=True)
        .order_by("-timestamp_anulacion")
        .first()
    )
    if tarea.estado != Tarea.Estado.ANULADA or snapshot is None:
        raise ValidationError("La tarea no tiene una anulación individual restaurable.")
    with transaction.atomic():
        tarea.estado = snapshot.estado_anterior
        tarea.fechas_pendientes_confirmacion = True
        tarea.save(update_fields=["estado", "fechas_pendientes_confirmacion"])
        snapshot.usuario_reactivo = usuario
        snapshot.timestamp_reactivacion = timezone.now()
        snapshot.save(update_fields=["usuario_reactivo", "timestamp_reactivacion"])
        TareaTransicion.objects.create(
            tarea=tarea,
            estado_origen=Tarea.Estado.ANULADA,
            estado_destino=tarea.estado,
            accion_evento="REACTIVAR",
            usuario=usuario,
            motivo=motivo,
        )
    return tarea
