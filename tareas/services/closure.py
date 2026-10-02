"""Closure rules for mini-tasks (T031/T104)."""

import logging

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from access_control.services.permissions import (
    get_valid_users_for_empresa,
    user_has_permission_for_empresa,
)
from tareas.models import EvidenciaCierre, MiniTarea, MiniTareaEvento, Tarea
from tareas.services.assignment import _validate_user_in_task_company
from tareas.services.comments import _create_mini_task_close_comment
from tareas.services.hierarchy import is_effectively_annulled
from tareas.services.notifications import emit_task_event, send_task_email
from tareas.services.participants import effective_participant_ids

logger = logging.getLogger(__name__)


def _validate_operational_task(tarea):
    if tarea.estado not in {Tarea.Estado.ACTIVA, Tarea.Estado.GESTION}:
        raise ValidationError("La tarea no admite cambios de mini-tareas en este estado.")
    if is_effectively_annulled(tarea):
        raise ValidationError("La tarea está anulada; no admite cambios de mini-tareas.")


def _has_task_permission(tarea, actor, accion):
    return user_has_permission_for_empresa(
        user=actor,
        empresa=tarea.empresa,
        vista_nombre="Tareas",
        accion=accion,
    )


def _is_supervisor(tarea, actor):
    return _has_task_permission(tarea, actor, "supervisor")


def _validate_actor(tarea, actor, *, accion, allowed_ids):
    _validate_user_in_task_company(tarea, actor)
    if not _has_task_permission(tarea, actor, accion):
        raise ValidationError("El usuario no tiene autorización para esta operación.")
    if actor.pk not in allowed_ids and not _is_supervisor(tarea, actor):
        raise ValidationError("El usuario no puede ejecutar esta operación.")


def _eligible_recipients(tarea, actor, recipient_ids, *, require_email=False):
    requested_ids = {int(value) for value in (recipient_ids or [])}
    requested_ids.discard(actor.pk)
    allowed_ids = effective_participant_ids(tarea)
    if not requested_ids.issubset(allowed_ids):
        raise ValidationError("Los destinatarios deben estar relacionados con la tarea.")
    valid_ids = allowed_ids & requested_ids
    users = list(
        get_valid_users_for_empresa(tarea.empresa, active_only=True).filter(
            pk__in=valid_ids,
        ).order_by("pk")
    )
    valid_user_ids = {user.pk for user in users}
    if valid_user_ids != valid_ids:
        raise ValidationError("Los destinatarios deben ser usuarios activos relacionados con la tarea.")
    if require_email and any(not user.email or not user.email.strip() for user in users):
        raise ValidationError("Todos los destinatarios de email deben tener un email válido.")
    return users


def _dispatch_mini_task_close(
    *,
    tarea_id,
    mini_tarea_id,
    actor_id,
    descripcion,
    comentario,
    notification_ids,
    email_addresses,
):
    try:
        tarea = Tarea.objects.select_related("empresa").get(pk=tarea_id)
        actor = User.objects.get(pk=actor_id)
        recipients = User.objects.filter(pk__in=notification_ids, is_active=True)
        title = "MiniTarea cerrada"
        body = (
            f"{actor.username} cerró la MiniTarea '{descripcion}' de la tarea "
            f"'{tarea.titulo}'. Comentario: {comentario}"
        )
        if notification_ids:
            emit_task_event(
                tarea=tarea,
                event=f"mini_tarea_cierre:{mini_tarea_id}",
                recipients=recipients,
                title=title,
                body=body,
                actor=actor,
                send_email=False,
            )
        if email_addresses:
            try:
                send_task_email(
                    tarea=tarea,
                    subject=title,
                    body_text=body,
                    to_emails=email_addresses,
                )
            except Exception:
                logger.exception(
                    "T104 mini-task email failure: tarea=%s mini_tarea=%s",
                    tarea_id,
                    mini_tarea_id,
                )
    except Exception:
        logger.exception(
            "T104 mini-task notification failure: tarea=%s mini_tarea=%s",
            tarea_id,
            mini_tarea_id,
        )


@transaction.atomic
def create_mini_task(*, tarea, descripcion, persona, actor=None):
    descripcion = str(descripcion or "").strip()
    if not descripcion:
        raise ValidationError("La descripción de la mini-tarea es obligatoria.")
    if actor is not None:
        tarea = Tarea.objects.select_for_update().get(pk=tarea.pk)
        _validate_operational_task(tarea)
        _validate_actor(
            tarea,
            actor,
            accion="crear",
            allowed_ids={tarea.responsable_id},
        )
    _validate_user_in_task_company(tarea, persona)
    return MiniTarea.objects.create(
        tarea=tarea,
        descripcion=descripcion,
        persona=persona,
    )


def can_create_mini_task(*, tarea, actor):
    return bool(
        actor
        and actor.is_active
        and _has_task_permission(tarea, actor, "crear")
        and (
            actor.pk == tarea.responsable_id
            or _is_supervisor(tarea, actor)
        )
        and tarea.estado in {Tarea.Estado.ACTIVA, Tarea.Estado.GESTION}
        and not is_effectively_annulled(tarea)
    )


def can_close_mini_task(*, tarea, mini_tarea, actor):
    return bool(
        actor
        and actor.is_active
        and _has_task_permission(tarea, actor, "modificar")
        and (
            actor.pk == mini_tarea.persona_id
            or actor.pk == tarea.responsable_id
            or _is_supervisor(tarea, actor)
        )
        and tarea.estado in {Tarea.Estado.ACTIVA, Tarea.Estado.GESTION}
        and not is_effectively_annulled(tarea)
        and not mini_tarea.hecho
    )


def can_reopen_mini_task(*, tarea, mini_tarea, actor):
    return bool(
        actor
        and actor.is_active
        and _has_task_permission(tarea, actor, "modificar")
        and (
            actor.pk == tarea.responsable_id
            or _is_supervisor(tarea, actor)
        )
        and tarea.estado in {Tarea.Estado.ACTIVA, Tarea.Estado.GESTION}
        and not is_effectively_annulled(tarea)
        and mini_tarea.hecho
    )


@transaction.atomic
def close_mini_task(
    *,
    tarea,
    mini_tarea,
    actor,
    comentario,
    notification_recipient_ids=None,
    email_recipient_ids=None,
    documentos_nuevos=None,
):
    tarea = Tarea.objects.select_for_update().select_related("empresa").get(pk=tarea.pk)
    mini_tarea = MiniTarea.objects.select_for_update().get(
        pk=mini_tarea.pk,
        tarea_id=tarea.pk,
    )
    comentario = str(comentario or "").strip()
    if not comentario:
        raise ValidationError("El comentario de cierre es obligatorio.")
    _validate_operational_task(tarea)
    _validate_actor(
        tarea,
        actor,
        accion="modificar",
        allowed_ids={mini_tarea.persona_id, tarea.responsable_id},
    )
    if mini_tarea.hecho:
        raise ValidationError("La mini-tarea ya está hecha.")
    notification_users = _eligible_recipients(
        tarea,
        actor,
        notification_recipient_ids,
    )
    email_users = _eligible_recipients(
        tarea,
        actor,
        email_recipient_ids,
        require_email=True,
    )
    mini_tarea.hecho = True
    mini_tarea.fecha_completado = timezone.now()
    mini_tarea.save(update_fields=["hecho", "fecha_completado"])
    evento = MiniTareaEvento.objects.create(
        mini_tarea=mini_tarea,
        tipo=MiniTareaEvento.Tipo.CIERRE,
        actor=actor,
        comentario=comentario,
        destinatarios_notificacion=[user.pk for user in notification_users],
        destinatarios_email=[user.pk for user in email_users],
    )
    comentario_feed = _create_mini_task_close_comment(
        tarea=tarea,
        mini_tarea=mini_tarea,
        usuario=actor,
        comentario_cierre=comentario,
        documentos_nuevos=documentos_nuevos,
    )
    evento.comentario_feed = comentario_feed
    evento.save(update_fields=["comentario_feed"])
    transaction.on_commit(
        lambda: _dispatch_mini_task_close(
            tarea_id=tarea.pk,
            mini_tarea_id=mini_tarea.pk,
            actor_id=actor.pk,
            descripcion=mini_tarea.descripcion,
            comentario=comentario,
            notification_ids=evento.destinatarios_notificacion,
            email_addresses=[user.email.strip() for user in email_users],
        )
    )
    return mini_tarea, evento


@transaction.atomic
def reopen_mini_task(*, tarea, mini_tarea, actor, comentario):
    tarea = Tarea.objects.select_for_update().select_related("empresa").get(pk=tarea.pk)
    mini_tarea = MiniTarea.objects.select_for_update().get(
        pk=mini_tarea.pk,
        tarea_id=tarea.pk,
    )
    comentario = str(comentario or "").strip()
    if not comentario:
        raise ValidationError("El motivo de reapertura es obligatorio.")
    _validate_operational_task(tarea)
    _validate_actor(
        tarea,
        actor,
        accion="modificar",
        allowed_ids={tarea.responsable_id},
    )
    if not mini_tarea.hecho:
        raise ValidationError("La mini-tarea ya está pendiente.")
    mini_tarea.hecho = False
    mini_tarea.fecha_completado = None
    mini_tarea.save(update_fields=["hecho", "fecha_completado"])
    evento = MiniTareaEvento.objects.create(
        mini_tarea=mini_tarea,
        tipo=MiniTareaEvento.Tipo.REAPERTURA,
        actor=actor,
        comentario=comentario,
    )
    return mini_tarea, evento


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