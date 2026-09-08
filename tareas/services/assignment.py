"""Assignment services for Phase 3 (T025-T027).

All functional logic stays inside tareas/. Company membership is validated by
consuming the existing access_control user/company helpers without modifying them.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from access_control.services.permissions import get_valid_users_for_empresa
from tareas.models import Tarea, TareaLectura, TareaParticipante, TareaReasignacion


def _validate_active_user(user):
    if user is None or not user.is_active:
        raise ValidationError("El usuario debe estar activo.")


def _validate_user_in_task_company(tarea, user):
    _validate_active_user(user)
    if not get_valid_users_for_empresa(tarea.empresa).filter(pk=user.pk).exists():
        raise ValidationError("El usuario no pertenece al contexto de la empresa de la tarea.")


def add_participant(tarea, user, rol=TareaParticipante.Rol.PARTICIPANTE):
    """Add or update one task participant without changing the lead assignee."""
    _validate_user_in_task_company(tarea, user)
    participante, _created = TareaParticipante.objects.update_or_create(
        tarea=tarea,
        usuario=user,
        defaults={"rol": rol},
    )
    return participante


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
        return TareaReasignacion.objects.create(
            tarea=tarea,
            responsable_anterior=anterior,
            responsable_nuevo=new_responsible,
            usuario=changed_by,
            motivo=motivo,
        )


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
    return tareas
