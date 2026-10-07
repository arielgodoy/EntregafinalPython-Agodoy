import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from access_control.services.permissions import get_valid_users_for_empresa

from tareas.models import ReunionParticipante, ReunionRevision, ReunionTarea, Tarea
from tareas.services.lifecycle import publish_task
from tareas.services.meeting_storage import (
    DjangoMeetingStorage,
    MeetingStorageError,
    MySQLMeetingStorage,
    resolve_meeting_storage,
)
from tareas.services.notifications import notify_task_event, send_task_email
from tareas.services.task_storage import TaskStorageError

logger = logging.getLogger(__name__)


def _ensure_valid_company_user(empresa, usuario):
    if usuario is None or not usuario.is_active:
        raise ValidationError("El usuario debe estar activo.")
    if not get_valid_users_for_empresa(empresa, active_only=True).filter(pk=usuario.pk).exists():
        raise ValidationError("El usuario no pertenece a la Empresa.")


def _validate_meeting_scope(empresa, tipo_ambito, local, departamento):
    if tipo_ambito == ReunionRevision.TipoAmbito.LOCAL:
        if local is None or departamento is not None:
            raise ValidationError("El ámbito LOCAL requiere únicamente un Local.")
        if local.empresa_id != empresa.pk:
            raise ValidationError("El Local debe pertenecer a la Empresa.")
    elif tipo_ambito == ReunionRevision.TipoAmbito.DEPARTAMENTO:
        if departamento is None or local is not None:
            raise ValidationError("El ámbito DEPARTAMENTO requiere únicamente un Departamento.")
        if departamento.empresa_id != empresa.pk:
            raise ValidationError("El Departamento debe pertenecer a la Empresa.")
    else:
        raise ValidationError("El tipo de ámbito no es válido.")


def _validate_agenda(reunion, items):
    priority_order = {
        Tarea.Prioridad.CRITICA: 0,
        Tarea.Prioridad.URGENTE: 1,
        Tarea.Prioridad.NORMAL: 2,
        Tarea.Prioridad.SIMPLE: 3,
    }
    previous_priority = -1
    for item in sorted(items, key=lambda agenda_item: (agenda_item.orden, agenda_item.pk or 0)):
        current_priority = priority_order[item.tarea.prioridad]
        if current_priority < previous_priority:
            raise ValidationError("La agenda debe ordenar las prioridades de forma descendente.")
        previous_priority = current_priority


def _full_clean(instance, storage, *, mysql_exclude=()):
    if isinstance(storage, MySQLMeetingStorage):
        instance.full_clean(
            exclude=list(mysql_exclude),
            validate_unique=False,
            validate_constraints=False,
        )
    else:
        instance.full_clean()


def create_meeting(*, empresa, creada_por, titulo, descripcion, fecha_hora_programada,
                   modalidad, lugar_o_enlace, tipo_ambito, local=None, departamento=None):
    try:
        storage = resolve_meeting_storage()
    except MeetingStorageError as exc:
        raise TaskStorageError("tareas.assignment.errors.backend") from exc
    if not isinstance(storage, DjangoMeetingStorage):
        raise TaskStorageError("tareas.assignment.errors.backend")
    with transaction.atomic(using=storage.alias):
        return _create_meeting(
            storage=storage,
            empresa=empresa,
            creada_por=creada_por,
            titulo=titulo,
            descripcion=descripcion,
            fecha_hora_programada=fecha_hora_programada,
            modalidad=modalidad,
            lugar_o_enlace=lugar_o_enlace,
            tipo_ambito=tipo_ambito,
            local=local,
            departamento=departamento,
        )


def _create_meeting(*, storage, empresa, creada_por, titulo, descripcion,
                    fecha_hora_programada, modalidad, lugar_o_enlace, tipo_ambito,
                    local, departamento):
    _ensure_valid_company_user(empresa, creada_por)
    _validate_meeting_scope(empresa, tipo_ambito, local, departamento)
    planned_task = Tarea(
        titulo=f"Reunión: {titulo}",
        descripcion=descripcion,
        prioridad=Tarea.Prioridad.NORMAL,
        empresa=empresa,
        creada_por=creada_por,
        responsable=creada_por,
        fecha_tope=fecha_hora_programada.date(),
        tipo_ambito=tipo_ambito,
        local=local,
        departamento=departamento,
    )
    planned_task.save(using=storage.alias)
    publish_task(planned_task, creada_por)
    reunion = ReunionRevision(
        empresa=empresa,
        titulo=titulo,
        descripcion=descripcion,
        fecha_hora_programada=fecha_hora_programada,
        modalidad=modalidad,
        lugar_o_enlace=lugar_o_enlace,
        tipo_ambito=tipo_ambito,
        local=local,
        departamento=departamento,
        tarea_planificada=planned_task,
        creada_por=creada_por,
    )
    reunion.full_clean()
    reunion.save(using=storage.alias)
    return reunion


def update_meeting(reunion, **changes):
    original_reunion = reunion
    storage = resolve_meeting_storage()
    reunion = storage.get_meeting(reunion.pk)
    editable_fields = (
        "titulo", "descripcion", "fecha_hora_programada", "modalidad",
        "lugar_o_enlace", "tipo_ambito", "local", "departamento",
    )
    for field in editable_fields:
        if field in changes:
            setattr(reunion, field, changes[field])
    planned_task = storage.get_task(reunion.tarea_planificada_id)
    planned_task.titulo = f"Reunión: {reunion.titulo}"
    planned_task.descripcion = reunion.descripcion
    planned_task.fecha_tope = reunion.fecha_hora_programada.date()
    planned_task.tipo_ambito = reunion.tipo_ambito
    planned_task.local = reunion.local
    planned_task.departamento = reunion.departamento
    _full_clean(planned_task, storage)
    _full_clean(reunion, storage, mysql_exclude=("tarea_planificada",))
    reunion.updated_at = timezone.now()
    storage.save_meeting_and_task(meeting=reunion, task=planned_task)
    for field in (*editable_fields, "updated_at"):
        setattr(original_reunion, field, getattr(reunion, field))
    original_state = getattr(original_reunion, "_state", None)
    original_task = (
        original_state.fields_cache.get("tarea_planificada")
        if original_state is not None
        else None
    )
    if original_task is not None:
        for field in (
            "titulo", "descripcion", "fecha_tope", "tipo_ambito", "local", "departamento",
        ):
            setattr(original_task, field, getattr(planned_task, field))
    return original_reunion


def add_task_to_meeting(*, reunion, tarea, orden, comentario_revision=""):
    storage = resolve_meeting_storage()
    reunion = storage.get_meeting(reunion.pk)
    tarea = storage.get_task(tarea.pk)
    item = ReunionTarea(
        reunion=reunion,
        tarea=tarea,
        orden=orden,
        comentario_revision=comentario_revision,
    )
    _full_clean(item, storage, mysql_exclude=("reunion", "tarea"))
    _validate_agenda(reunion, [*storage.get_agenda(reunion.pk), item])
    return storage.add_agenda_item(item)


def remove_task_from_meeting(*, reunion, tarea):
    storage = resolve_meeting_storage()
    return storage.remove_agenda_item(reunion.pk, tarea.pk)


def add_meeting_participant(*, reunion, usuario):
    storage = resolve_meeting_storage()
    reunion = storage.get_meeting(reunion.pk)
    _ensure_valid_company_user(reunion.empresa, usuario)
    participant = ReunionParticipante(reunion=reunion, usuario=usuario)
    _full_clean(participant, storage, mysql_exclude=("reunion",))
    return storage.add_participant(participant)


def remove_meeting_participant(*, reunion, usuario):
    storage = resolve_meeting_storage()
    return storage.remove_participant(reunion.pk, usuario.pk)


def convene_meeting(reunion, *, actor=None):
    storage = resolve_meeting_storage()
    with transaction.atomic(using=storage.alias):
        return _convene_meeting(reunion, actor=actor, storage=storage)


def _convene_meeting(reunion, *, actor=None, storage):
    original_reunion = reunion
    reunion = storage.get_meeting(reunion.pk)
    if reunion.convocada_at is not None:
        raise ValidationError("La reunión ya fue convocada.")
    participants = storage.get_participants(reunion.pk)
    for participant in participants:
        _ensure_valid_company_user(reunion.empresa, participant.usuario)

    detail_url = reverse("tareas:reunion_revision_detalle", kwargs={"pk": reunion.pk})
    title = f"Convocatoria: {reunion.titulo}"
    body = (
        f"{reunion.titulo}\n"
        f"Fecha: {reunion.fecha_hora_programada}\n"
        f"Modalidad: {reunion.get_modalidad_display()}\n"
        f"Lugar o enlace: {reunion.lugar_o_enlace or 'No indicado'}\n"
        f"Empresa: {reunion.empresa}\n"
        f"Ver reunión: {detail_url}"
    )
    for participant in participants:
        try:
            notify_task_event(
                tarea=reunion.tarea_planificada,
                destinatario=participant.usuario,
                titulo=title,
                cuerpo=body,
                url=detail_url,
                actor=actor,
                dedupe_key=f"reunion:{reunion.pk}:convocatoria:{participant.usuario.pk}",
            )
        except Exception:
            logger.exception("Meeting in-app notification failed: reunion=%s recipient=%s", reunion.pk, participant.usuario.pk)
        if participant.usuario.email:
            try:
                send_task_email(
                    tarea=reunion.tarea_planificada,
                    subject=title,
                    body_text=body,
                    to_emails=[participant.usuario.email],
                )
            except Exception:
                logger.exception("Meeting email notification failed: reunion=%s recipient=%s", reunion.pk, participant.usuario.pk)
    reunion.convocada_at = timezone.now()
    reunion.updated_at = reunion.convocada_at
    persisted = storage.mark_convened(reunion)
    original_reunion.convocada_at = persisted.convocada_at
    original_reunion.updated_at = persisted.updated_at
    return original_reunion


def mark_meeting_completed(reunion, *, comentarios=None):
    original_reunion = reunion
    storage = resolve_meeting_storage()
    reunion = storage.get_meeting(reunion.pk)
    comentarios = comentarios or {}
    items = storage.get_agenda(reunion.pk)
    for item in items:
        if item.pk in comentarios:
            item.comentario_cierre = str(comentarios[item.pk]).strip()
    if reunion.estado != ReunionRevision.Estado.PLANIFICADA:
        raise ValidationError("La reunión ya fue realizada.")
    if any(not item.comentario_cierre.strip() for item in items):
        raise ValidationError("Cada tarea de la agenda requiere comentario de cierre.")
    reunion.estado = ReunionRevision.Estado.REALIZADA
    reunion.updated_at = timezone.now()
    storage.complete_meeting(reunion, items)
    original_reunion.estado = reunion.estado
    original_reunion.updated_at = reunion.updated_at
    return original_reunion
