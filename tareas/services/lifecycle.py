"""Lifecycle de tareas: ciclo funcional por estado + anulación por flag.

Remediación Phase 2 (aprobada 2026-09-08): la anulación deja de ser el estado
`ANULADA` y pasa a ser el flag `Tarea.anulada`. Anular/reactivar solo cambian ese flag;
el `estado` funcional nunca se modifica. La auditoría de ANULAR/REACTIVAR se registra en
`TareaTransicion`. No existe jerarquía ni `anulada_efectivamente` todavía (eso llega en
T028); aquí solo hay anulación directa de la tarea.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from tareas.services.closure import validate_closure_requirements
from tareas.services.hierarchy import get_descendants
from tareas.models import Tarea, TareaCierre, TareaParticipante, TareaTransicion
from tareas.services.notifications import emit_task_event, task_recipients


_ALLOWED = {
    Tarea.Estado.ACTIVA: {Tarea.Estado.GESTION},
    Tarea.Estado.GESTION: {
        Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
    },
    Tarea.Estado.PENDIENTE_APROBACION_CIERRE: {
        Tarea.Estado.CERRADA,
        Tarea.Estado.GESTION,
    },
}


def _raise_si_anulada(tarea):
    """Bloquea operaciones de lifecycle mientras la tarea está anulada (flag)."""
    from tareas.services.hierarchy import is_effectively_annulled

    if is_effectively_annulled(tarea):
        raise ValidationError("La tarea está anulada; no admite operaciones de ciclo.")


def _emit_hierarchy_event(tarea, usuario, event, title, body):
    for affected_task in [tarea, *get_descendants(tarea)]:
        emit_task_event(
            tarea=affected_task,
            event=event,
            recipients=task_recipients(
                affected_task,
                actor=usuario,
                include_creator=True,
                include_responsible=True,
                participant_roles=list(TareaParticipante.Rol),
            ),
            title=title,
            body=body,
            actor=usuario,
        )


def transition_task(tarea, destino, usuario, accion_evento, motivo=""):
    _raise_si_anulada(tarea)
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
    _raise_si_anulada(tarea)
    with transaction.atomic():
        tarea.publicar(usuario=usuario)
    return tarea


def complete_task(tarea, usuario):
    _raise_si_anulada(tarea)
    with transaction.atomic():
        tarea.cierre_completado = True
        tarea.fecha_cumplimiento = timezone.now()
        tarea.save(update_fields=["cierre_completado", "fecha_cumplimiento"])
        transition = transition_task(
            tarea,
            Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
            usuario,
            "MARCAR_100",
        )
    emit_task_event(
        tarea=tarea,
        event="solicitud_aprobacion_cierre",
        recipients=task_recipients(
            tarea,
            actor=usuario,
            participant_roles={TareaParticipante.Rol.AUTORIZADOR},
            fallback_creator=True,
        ),
        title="Solicitud de aprobación de cierre",
        body="La tarea está pendiente de aprobación de cierre.",
        actor=usuario,
    )
    return transition


def approve_closure(tarea, usuario, comentario=""):
    _raise_si_anulada(tarea)
    validate_closure_requirements(tarea)
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
    emit_task_event(
        tarea=tarea,
        event="aprobacion_cierre",
        recipients=task_recipients(
            tarea,
            actor=usuario,
            include_creator=True,
            include_responsible=True,
        ),
        title="Cierre de tarea aprobado",
        body="El cierre de la tarea fue aprobado.",
        actor=usuario,
    )
    return transition


def reject_closure(tarea, usuario, comentario=""):
    _raise_si_anulada(tarea)
    with transaction.atomic():
        transition = transition_task(
            tarea,
            Tarea.Estado.GESTION,
            usuario,
            "RECHAZAR_CIERRE",
            comentario,
        )
        tarea.cierre_completado = True
        tarea.fecha_cumplimiento = None
        tarea.save(update_fields=["cierre_completado", "fecha_cumplimiento"])
        TareaCierre.objects.create(
            tarea=tarea,
            usuario=usuario,
            resultado=TareaCierre.Resultado.RECHAZADO,
            comentario=comentario,
        )
    emit_task_event(
        tarea=tarea,
        event="rechazo_cierre",
        recipients=task_recipients(
            tarea,
            actor=usuario,
            include_creator=True,
            include_responsible=True,
        ),
        title="Cierre de tarea rechazado",
        body="El cierre de la tarea fue rechazado.",
        actor=usuario,
    )
    return transition


def annul_task(tarea, usuario, motivo=""):
    """Anula la tarea poniendo el flag `anulada=True`; NO cambia el estado funcional.

    Registra la acción ANULAR en TareaTransicion (auditoría). No crea snapshot para
    restauración de estado (ya no es necesario: el estado nunca cambia).
    """
    if tarea.anulada:
        raise ValidationError("La tarea ya está anulada.")
    if tarea.estado == Tarea.Estado.BORRADOR:
        raise ValidationError("Una tarea en borrador no puede anularse.")
    with transaction.atomic():
        tarea.anulada = True
        tarea.save(update_fields=["anulada"])
        TareaTransicion.objects.create(
            tarea=tarea,
            estado_origen=tarea.estado,
            estado_destino=tarea.estado,
            accion_evento="ANULAR",
            usuario=usuario,
            motivo=motivo,
        )
    _emit_hierarchy_event(tarea, usuario, "anulacion", "Tarea anulada", "La tarea fue anulada.")
    return tarea


def reactivate_task(tarea, usuario, motivo=""):
    """Reactiva la tarea poniendo `anulada=False`; NO restaura ni cambia el estado."""
    if not tarea.anulada:
        raise ValidationError("La tarea no está anulada.")
    with transaction.atomic():
        tarea.anulada = False
        tarea.save(update_fields=["anulada"])
        TareaTransicion.objects.create(
            tarea=tarea,
            estado_origen=tarea.estado,
            estado_destino=tarea.estado,
            accion_evento="REACTIVAR",
            usuario=usuario,
            motivo=motivo,
        )
    _emit_hierarchy_event(
        tarea,
        usuario,
        "reactivacion",
        "Tarea reactivada",
        "La tarea fue reactivada.",
    )
    return tarea
