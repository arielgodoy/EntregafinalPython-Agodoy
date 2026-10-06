"""Assignment services for Phase 3 (T025-T027).

All functional logic stays inside tareas/. Company membership is validated by
consuming the existing access_control user/company helpers without modifying them.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from access_control.services.permissions import (
    get_valid_users_for_empresa,
)
from tareas.models import Tarea, TareaLectura, TareaParticipante, TareaReasignacion
from tareas.services.notifications import emit_task_event, task_recipients
from tareas.services.participant_storage import (
    AddParticipantCommand,
    ReassignResponsibleCommand,
    RemoveParticipantCommand,
    MarkTaskReadCommand,
    resolve_participant_storage,
)


def _validate_active_user(user):
    if user is None or not user.is_active:
        raise ValidationError("El usuario debe estar activo.")


def _validate_user_in_task_company(tarea, user):
    _validate_active_user(user)
    if not get_valid_users_for_empresa(tarea.empresa).filter(pk=user.pk).exists():
        raise ValidationError("El usuario no pertenece al contexto de la empresa de la tarea.")


def add_participant(tarea, user, rol=TareaParticipante.Rol.PARTICIPANTE, *, actor):
    """Compatibility adapter; persistence and validation live in the ID command."""
    storage = resolve_participant_storage()
    try:
        result = storage.add(AddParticipantCommand(
            task_id=tarea.pk, empresa_id=tarea.empresa_id,
            actor_id=getattr(actor, "pk", None), user_id=getattr(user, "pk", None), role=rol,
        ))
    except PermissionDenied as exc:
        raise ValidationError("tareas.assignment.errors.permission") from exc
    if hasattr(storage, "alias"):
        return TareaParticipante.objects.using(storage.alias).get(pk=result.participant_id)
    return result


def remove_participant(tarea, user, *, actor):
    """Remove only the explicit link using the configured task backend."""
    storage = resolve_participant_storage()
    try:
        return storage.remove(RemoveParticipantCommand(
            task_id=tarea.pk, empresa_id=tarea.empresa_id,
            actor_id=getattr(actor, "pk", None), user_id=getattr(user, "pk", None),
        ))
    except PermissionDenied as exc:
        raise ValidationError("tareas.assignment.errors.permission") from exc


def mark_task_read(tarea, user, *, leido=True):
    """Record read/unread state independently for a user and task."""
    _validate_user_in_task_company(tarea, user)
    storage = resolve_participant_storage()
    return storage.mark_task_read(MarkTaskReadCommand(
        task_id=tarea.pk,
        empresa_id=tarea.empresa_id,
        user_id=user.pk,
        leido=leido,
    ))


def assign_responsible(tarea, new_responsible, changed_by, motivo=""):
    """Keep legacy Django return values without a second assignment policy."""
    storage = resolve_participant_storage()
    try:
        result = storage.reassign(ReassignResponsibleCommand(
            task_id=tarea.pk, empresa_id=tarea.empresa_id,
            actor_id=getattr(changed_by, "pk", None),
            new_responsible_id=getattr(new_responsible, "pk", None), reason=motivo,
        ))
    except PermissionDenied as exc:
        raise ValidationError("tareas.assignment.errors.permission") from exc
    if not result.changed or result.reassignment_id is None:
        return None
    if hasattr(storage, "alias"):
        return TareaReasignacion.objects.using(storage.alias).get(pk=result.reassignment_id)
    return result


def create_independent_tasks_for_responsibles(
    *,
    empresa,
    creada_por,
    responsables,
    titulos_por_usuario,
    descripcion="",
    prioridad=Tarea.Prioridad.NORMAL,
    fecha_comun=None,
    motivo="Asignación masiva",
):
    """Create N independent tasks, one per responsible, without hierarchy.

    `titulos_por_usuario` must provide a title for each responsible user id. This keeps
    the "nombre propio" contract explicit instead of inventing a naming convention.
    """
    if fecha_comun is None:
        fecha_comun = timezone.now()
    responsables = list(responsables)
    if not responsables:
        raise ValidationError("Debe seleccionar al menos un responsable.")
    _validate_active_user(creada_por)

    valid_user_ids = set(
        get_valid_users_for_empresa(empresa).values_list("pk", flat=True)
    )
    if creada_por.pk not in valid_user_ids:
        raise ValidationError("El creador debe pertenecer a la empresa.")
    missing_titles = []
    for user in responsables:
        if user is None or not user.is_active:
            raise ValidationError("Todos los responsables deben estar activos.")
        if user.pk not in valid_user_ids:
            raise ValidationError("Todos los responsables deben pertenecer a la empresa.")
        if user.pk not in titulos_por_usuario or not str(titulos_por_usuario[user.pk]).strip():
            missing_titles.append(user.pk)
    if missing_titles:
        raise ValidationError(
            f"Falta nombre propio para responsables: {missing_titles}."
        )

    with transaction.atomic():
        tareas = []
        for responsable in responsables:
            tarea = Tarea.objects.create(
                titulo=str(titulos_por_usuario[responsable.pk]).strip(),
                descripcion=descripcion,
                prioridad=prioridad,
                empresa=empresa,
                creada_por=creada_por,
                responsable=responsable,
            )
            TareaReasignacion.objects.create(
                tarea=tarea,
                responsable_anterior=None,
                responsable_nuevo=responsable,
                usuario=creada_por,
                fecha=fecha_comun,
                motivo=motivo,
            )
            tareas.append(tarea)
    for tarea in tareas:
        emit_task_event(
            tarea=tarea,
            event="asignacion",
            recipients=task_recipients(
                tarea,
                actor=creada_por,
                include_responsible=True,
            ),
            title="Tarea asignada",
            body="Se te asignó una nueva tarea.",
            actor=creada_por,
        )
    return tareas
