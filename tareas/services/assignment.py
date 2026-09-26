"""Assignment services for Phase 3 (T025-T027).

All functional logic stays inside tareas/. Company membership is validated by
consuming the existing access_control user/company helpers without modifying them.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from access_control.services.permissions import (
    get_valid_users_for_empresa,
    user_has_permission_for_empresa,
)
from tareas.models import Comentario, Tarea, TareaLectura, TareaParticipante, TareaReasignacion
from tareas.services.hierarchy import is_effectively_annulled
from tareas.services.notifications import emit_task_event, task_recipients


def _validate_active_user(user):
    if user is None or not user.is_active:
        raise ValidationError("El usuario debe estar activo.")


def _validate_user_in_task_company(tarea, user):
    _validate_active_user(user)
    if not get_valid_users_for_empresa(tarea.empresa).filter(pk=user.pk).exists():
        raise ValidationError("El usuario no pertenece al contexto de la empresa de la tarea.")


def _lock_task_for_participant_admin(tarea, actor):
    """Participant administration needs VICMEAS `modificar`, not being a participant."""
    tarea_actual = Tarea.objects.select_for_update().get(pk=tarea.pk)
    _validate_user_in_task_company(tarea_actual, actor)
    if not user_has_permission_for_empresa(
        user=actor,
        empresa=tarea_actual.empresa,
        vista_nombre="Tareas",
        accion="modificar",
    ):
        raise ValidationError("El usuario no tiene autorización para administrar participantes.")
    if tarea_actual.estado == Tarea.Estado.CERRADA or is_effectively_annulled(tarea_actual):
        raise ValidationError("La tarea no admite cambios de participantes.")
    return tarea_actual


@transaction.atomic
def add_participant(tarea, user, rol=TareaParticipante.Rol.PARTICIPANTE, *, actor):
    """Add or update one task participant and initialize comment reading."""
    tarea = _lock_task_for_participant_admin(tarea, actor)
    _validate_user_in_task_company(tarea, user)
    participante, created = TareaParticipante.objects.update_or_create(
        tarea=tarea,
        usuario=user,
        defaults={"rol": rol},
    )
    comentario_reciente = (
        Comentario.objects.filter(tarea=tarea)
        .order_by("-created_at", "-pk")
        .first()
    )
    lectura, lectura_created = TareaLectura.objects.get_or_create(
        tarea=tarea,
        usuario=user,
        defaults={"comentario_leido_hasta": comentario_reciente},
    )
    if created and not lectura_created and tarea.responsable_id != user.pk:
        lectura.comentario_leido_hasta = comentario_reciente
        lectura.save(update_fields=["comentario_leido_hasta"])
    return participante


@transaction.atomic
def remove_participant(tarea, user, *, actor):
    """Remove the derived access link without deleting reading or comment history."""
    tarea = _lock_task_for_participant_admin(tarea, actor)
    return TareaParticipante.objects.filter(tarea=tarea, usuario=user).delete()


def mark_task_read(tarea, user, *, leido=True):
    """Record read/unread state independently for a user and task."""
    _validate_user_in_task_company(tarea, user)
    lectura, _created = TareaLectura.objects.update_or_create(
        tarea=tarea,
        usuario=user,
        defaults={
            "leido": leido,
            "fecha_lectura": timezone.now() if leido else None,
        },
    )
    return lectura


def assign_responsible(tarea, new_responsible, changed_by, motivo=""):
    """Assign/reassign the task's lead responsible user with history."""
    _validate_user_in_task_company(tarea, new_responsible)
    _validate_user_in_task_company(tarea, changed_by)
    anterior = tarea.responsable
    if anterior_id := getattr(anterior, "pk", None):
        if anterior_id == new_responsible.pk:
            return None
    with transaction.atomic():
        tarea.responsable = new_responsible
        tarea.full_clean()
        tarea.save(update_fields=["responsable"])
        comentario_reciente = (
            Comentario.objects.filter(tarea=tarea)
            .order_by("-created_at", "-pk")
            .first()
        )
        TareaLectura.objects.get_or_create(
            tarea=tarea,
            usuario=new_responsible,
            defaults={"comentario_leido_hasta": comentario_reciente},
        )
        reasignacion = TareaReasignacion.objects.create(
            tarea=tarea,
            responsable_anterior=anterior,
            responsable_nuevo=new_responsible,
            usuario=changed_by,
            motivo=motivo,
        )
    emit_task_event(
        tarea=tarea,
        event="reasignacion",
        recipients=task_recipients(tarea, include_responsible=True, actor=changed_by),
        title="Tarea reasignada",
        body="La tarea tiene un nuevo responsable.",
        actor=changed_by,
    )
    return reasignacion


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
