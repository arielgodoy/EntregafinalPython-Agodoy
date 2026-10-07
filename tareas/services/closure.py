from tareas.services.document_storage import resolve_document_storage
"""Closure rules for mini-tasks (T031/T104)."""

from django.core.exceptions import ValidationError
from django.utils import timezone

from access_control.services.permissions import (
    user_has_permission_for_empresa,
)
from tareas.models import EvidenciaCierre, MiniTarea, MiniTareaEvento, Tarea
from tareas.services.assignment import _validate_user_in_task_company
from tareas.services.hierarchy import is_effectively_annulled


def _has_task_permission(tarea, actor, accion):
    return user_has_permission_for_empresa(
        user=actor,
        empresa=tarea.empresa,
        vista_nombre="Tareas",
        accion=accion,
    )


def _is_supervisor(tarea, actor):
    return _has_task_permission(tarea, actor, "supervisor")


def create_mini_task(*, tarea, descripcion, persona, actor=None):
    if actor is not None:
        from .minitask_storage import CreateMiniTaskCommand, resolve_minitask_storage
        storage = resolve_minitask_storage()
        result = _mini_command(storage, "create", CreateMiniTaskCommand(
            tarea.pk, tarea.empresa_id, actor.pk, persona.pk, descripcion,
        ))
        return _mini_compat_result(storage, result, tarea.empresa_id)[0]
    descripcion = str(descripcion or "").strip()
    if not descripcion:
        raise ValidationError("La descripción de la mini-tarea es obligatoria.")
    _validate_user_in_task_company(tarea, persona)
    from .minitask_storage import resolve_minitask_storage
    storage = resolve_minitask_storage()
    result = storage.create_unattributed(
        task_id=tarea.pk,
        persona_id=persona.pk,
        descripcion=descripcion,
    )
    return _mini_compat_result(storage, result, tarea.empresa_id)[0]


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


def can_delete_mini_task(*, tarea, mini_tarea, actor):
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
        and not mini_tarea.hecho
        and not mini_tarea.eventos.exists()
    )


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
    from .minitask_storage import CloseMiniTaskCommand, resolve_minitask_storage
    files = []
    for spec in documentos_nuevos or ():
        if (
            not isinstance(spec, dict) or not spec.get("archivo")
            or spec.get("tipo") != "OTRO" or spec.get("url")
        ):
            raise ValidationError("tareas.messages.generic_error")
        files.append(spec["archivo"])
    storage = resolve_minitask_storage()
    result = _mini_command(storage, "close", CloseMiniTaskCommand(
        tarea.pk, tarea.empresa_id, actor.pk, mini_tarea.pk, comentario,
        tuple(notification_recipient_ids or ()), tuple(email_recipient_ids or ()), tuple(files),
    ))
    return _mini_compat_result(storage, result, tarea.empresa_id)


def reopen_mini_task(*, tarea, mini_tarea, actor, comentario):
    from .minitask_storage import ReopenMiniTaskCommand, resolve_minitask_storage
    storage = resolve_minitask_storage()
    result = _mini_command(storage, "reopen", ReopenMiniTaskCommand(
        tarea.pk, tarea.empresa_id, actor.pk, mini_tarea.pk, comentario,
    ))
    return _mini_compat_result(storage, result, tarea.empresa_id)


def delete_mini_task(*, tarea, mini_tarea, actor):
    from .minitask_storage import DeleteMiniTaskCommand, resolve_minitask_storage
    _mini_command(resolve_minitask_storage(), "delete", DeleteMiniTaskCommand(
        tarea.pk, tarea.empresa_id, actor.pk, mini_tarea.pk,
    ))


def _mini_command(storage, operation, command):
    from django.core.exceptions import PermissionDenied
    from .minitask_storage import MiniTaskNotFound
    try:
        return getattr(storage, operation)(command)
    except (PermissionDenied, MiniTaskNotFound):
        raise ValidationError("tareas.messages.generic_error") from None


def _mini_compat_result(storage, result, empresa_id):
    from .minitask_storage import DjangoMiniTaskStorage
    if isinstance(storage, DjangoMiniTaskStorage):
        mini = MiniTarea.objects.using(storage.alias).get(pk=result.mini_task_id)
        event = (
            MiniTareaEvento.objects.using(storage.alias).get(pk=result.event_id)
            if result.event_id else None
        )
        return mini, event
    detail = storage.detail(task_id=result.task_id, empresa_id=empresa_id)
    mini = next(item for item in detail.mini_tasks if item.id == result.mini_task_id)
    event = next((item for item in mini.eventos_t104 if item.id == result.event_id), None)
    return mini, event


def set_mini_task_done(mini_tarea, hecho=True):
    mini_tarea.hecho = bool(hecho)
    mini_tarea.fecha_completado = timezone.now() if mini_tarea.hecho else None
    mini_tarea.save(update_fields=["hecho", "fecha_completado"])
    return mini_tarea


def has_pending_mini_tasks(tarea):
    from .minitask_storage import resolve_minitask_storage
    return resolve_minitask_storage().has_pending(
        task_id=tarea.pk, empresa_id=tarea.empresa_id,
    )


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

    evidencia_valida = resolve_document_storage().has_valid_closure_evidence(
        task_id=tarea.pk,
        empresa_id=tarea.empresa_id,
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