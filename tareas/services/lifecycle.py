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
from tareas.services.task_storage import (
    DjangoTaskStorage,
    TaskStorageError,
    resolve_edit_storage,
)


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


def _django_task_storage(tarea):
    storage = resolve_edit_storage()
    if not isinstance(storage, DjangoTaskStorage):
        raise TaskStorageError("tareas.messages.generic_error")
    try:
        storage.get_task_for_edit(task_id=tarea.pk, empresa_id=tarea.empresa_id)
    except Exception as exc:
        raise TaskStorageError("tareas.messages.generic_error") from exc
    return storage


def _task_storage():
    storage = resolve_edit_storage()
    if not callable(getattr(storage, "publish_task", None)):
        raise TaskStorageError("tareas.messages.generic_error")
    return storage


def _raise_si_anulada(tarea):
    """Bloquea operaciones de lifecycle mientras la tarea está anulada (flag)."""
    from tareas.services.hierarchy import is_effectively_annulled

    if is_effectively_annulled(tarea):
        raise ValidationError("La tarea está anulada; no admite operaciones de ciclo.")


def _lock_task(tarea, storage):
    try:
        return (
            Tarea.objects.using(storage.alias)
            .select_for_update()
            .get(pk=tarea.pk, empresa_id=tarea.empresa_id)
        )
    except Tarea.DoesNotExist as exc:
        raise TaskStorageError("tareas.messages.generic_error") from exc


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
    storage = _django_task_storage(tarea)
    with transaction.atomic(using=storage.alias):
        locked_tarea = _lock_task(tarea, storage)
        _raise_si_anulada(locked_tarea)
        if destino not in _ALLOWED.get(locked_tarea.estado, set()):
            raise ValidationError(
                f"Transición no permitida: {locked_tarea.estado} -> {destino}."
            )
        origen = locked_tarea.estado
        if destino == Tarea.Estado.GESTION and origen == Tarea.Estado.ACTIVA:
            storage.enter_management(
                task_id=locked_tarea.pk,
                empresa_id=locked_tarea.empresa_id,
                actor_id=usuario.pk,
            )
            locked_tarea.refresh_from_db(using=storage.alias)
            tarea.estado = locked_tarea.estado
            tarea.anulada = locked_tarea.anulada
            return TareaTransicion.objects.using(storage.alias).filter(
                tarea_id=locked_tarea.pk,
                estado_destino=destino,
            ).order_by("-pk").first()
        locked_tarea.estado = destino
        locked_tarea.full_clean()
        locked_tarea.save(using=storage.alias, update_fields=["estado"])
        transition = TareaTransicion.objects.using(storage.alias).create(
            tarea=locked_tarea,
            estado_origen=origen,
            estado_destino=destino,
            accion_evento=accion_evento,
            usuario=usuario,
            motivo=motivo,
        )
        tarea.estado = locked_tarea.estado
        tarea.anulada = locked_tarea.anulada
        return transition


def publish_task(tarea, usuario):
    _raise_si_anulada(tarea)
    result = _task_storage().publish_task(
        task_id=tarea.pk,
        empresa_id=tarea.empresa_id,
        actor_id=usuario.pk,
    )
    tarea.estado = result.state
    tarea.correlativo = result.correlativo
    tarea.fecha_publicacion = result.fecha_publicacion
    tarea.fecha_asignacion = result.fecha_asignacion
    return tarea


def complete_task(tarea, usuario):
    storage = _django_task_storage(tarea)
    with transaction.atomic(using=storage.alias):
        transition = transition_task(
            tarea,
            Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
            usuario,
            "MARCAR_100",
        )
        tarea.cierre_completado = True
        tarea.fecha_cumplimiento = timezone.now()
        tarea.save(using=storage.alias, update_fields=["cierre_completado", "fecha_cumplimiento"])
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
    storage = _django_task_storage(tarea)
    with transaction.atomic(using=storage.alias):
        locked_tarea = _lock_task(tarea, storage)
        _raise_si_anulada(locked_tarea)
        validate_closure_requirements(locked_tarea)
        transition = transition_task(
            locked_tarea,
            Tarea.Estado.CERRADA,
            usuario,
            "APROBAR_CIERRE",
            comentario,
        )
        locked_tarea.cierre_completado = True
        locked_tarea.save(using=storage.alias, update_fields=["cierre_completado"])
        TareaCierre.objects.using(storage.alias).create(
            tarea=locked_tarea,
            usuario=usuario,
            resultado=TareaCierre.Resultado.APROBADO,
            comentario=comentario,
        )
        tarea.estado = locked_tarea.estado
        tarea.cierre_completado = locked_tarea.cierre_completado
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
    storage = _django_task_storage(tarea)
    with transaction.atomic(using=storage.alias):
        transition = transition_task(
            tarea,
            Tarea.Estado.GESTION,
            usuario,
            "RECHAZAR_CIERRE",
            comentario,
        )
        tarea.cierre_completado = True
        tarea.fecha_cumplimiento = None
        tarea.save(using=storage.alias, update_fields=["cierre_completado", "fecha_cumplimiento"])
        TareaCierre.objects.using(storage.alias).create(
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
    storage = _django_task_storage(tarea)
    with transaction.atomic(using=storage.alias):
        locked_tarea = _lock_task(tarea, storage)
        if locked_tarea.anulada:
            raise ValidationError("La tarea ya está anulada.")
        if locked_tarea.estado == Tarea.Estado.BORRADOR:
            raise ValidationError("Una tarea en borrador no puede anularse.")
        locked_tarea.anulada = True
        locked_tarea.save(using=storage.alias, update_fields=["anulada"])
        TareaTransicion.objects.using(storage.alias).create(
            tarea=locked_tarea,
            estado_origen=locked_tarea.estado,
            estado_destino=locked_tarea.estado,
            accion_evento="ANULAR",
            usuario=usuario,
            motivo=motivo,
        )
        tarea.anulada = locked_tarea.anulada
    _emit_hierarchy_event(tarea, usuario, "anulacion", "Tarea anulada", "La tarea fue anulada.")
    return tarea


def reactivate_task(tarea, usuario, motivo=""):
    """Reactiva la tarea poniendo `anulada=False`; NO restaura ni cambia el estado."""
    storage = _django_task_storage(tarea)
    with transaction.atomic(using=storage.alias):
        locked_tarea = _lock_task(tarea, storage)
        if not locked_tarea.anulada:
            raise ValidationError("La tarea no está anulada.")
        locked_tarea.anulada = False
        locked_tarea.save(using=storage.alias, update_fields=["anulada"])
        TareaTransicion.objects.using(storage.alias).create(
            tarea=locked_tarea,
            estado_origen=locked_tarea.estado,
            estado_destino=locked_tarea.estado,
            accion_evento="REACTIVAR",
            usuario=usuario,
            motivo=motivo,
        )
        tarea.anulada = locked_tarea.anulada
    _emit_hierarchy_event(
        tarea,
        usuario,
        "reactivacion",
        "Tarea reactivada",
        "La tarea fue reactivada.",
    )
    return tarea
