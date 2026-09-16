import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from access_control.services.permissions import get_valid_users_for_empresa

from tareas.models import ReunionParticipante, ReunionRevision, ReunionTarea, Tarea
from tareas.services.lifecycle import publish_task
from tareas.services.notifications import notify_task_event, send_task_email

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


def _validate_agenda(reunion):
    priority_order = {
        Tarea.Prioridad.CRITICA: 0,
        Tarea.Prioridad.URGENTE: 1,
        Tarea.Prioridad.NORMAL: 2,
        Tarea.Prioridad.SIMPLE: 3,
    }
    previous_priority = -1
    for item in reunion.agenda.select_related("tarea").order_by("orden", "pk"):
        current_priority = priority_order[item.tarea.prioridad]
        if current_priority < previous_priority:
            raise ValidationError("La agenda debe ordenar las prioridades de forma descendente.")
        previous_priority = current_priority


@transaction.atomic
def create_meeting(*, empresa, creada_por, titulo, descripcion, fecha_hora_programada,
                   modalidad, lugar_o_enlace, tipo_ambito, local=None, departamento=None):
    _ensure_valid_company_user(empresa, creada_por)
    _validate_meeting_scope(empresa, tipo_ambito, local, departamento)
    planned_task = Tarea.objects.create(
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
    reunion.save()
    return reunion


@transaction.atomic
def update_meeting(reunion, **changes):
    editable_fields = (
        "titulo", "descripcion", "fecha_hora_programada", "modalidad",
        "lugar_o_enlace", "tipo_ambito", "local", "departamento",
    )
    for field in editable_fields:
        if field in changes:
            setattr(reunion, field, changes[field])
    planned_task = reunion.tarea_planificada
    planned_task.titulo = f"Reunión: {reunion.titulo}"
    planned_task.descripcion = reunion.descripcion
    planned_task.fecha_tope = reunion.fecha_hora_programada.date()
    planned_task.tipo_ambito = reunion.tipo_ambito
    planned_task.local = reunion.local
    planned_task.departamento = reunion.departamento
    planned_task.full_clean()
    reunion.full_clean()
    planned_task.save(update_fields=["titulo", "descripcion", "fecha_tope", "tipo_ambito", "local", "departamento"])
    reunion.save()
    return reunion


@transaction.atomic
def add_task_to_meeting(*, reunion, tarea, orden, comentario_revision=""):
    item = ReunionTarea(reunion=reunion, tarea=tarea, orden=orden, comentario_revision=comentario_revision)
    item.full_clean()
    item.save()
    _validate_agenda(reunion)
    return item


def remove_task_from_meeting(*, reunion, tarea):
    return reunion.agenda.filter(tarea=tarea).delete()


@transaction.atomic
def add_meeting_participant(*, reunion, usuario):
    _ensure_valid_company_user(reunion.empresa, usuario)
    participant = ReunionParticipante(reunion=reunion, usuario=usuario)
    participant.full_clean()
    participant.save()
    return participant


def remove_meeting_participant(*, reunion, usuario):
    return reunion.participantes.filter(usuario=usuario).delete()


@transaction.atomic
def convene_meeting(reunion, *, actor=None):
    if reunion.convocada_at is not None:
        raise ValidationError("La reunión ya fue convocada.")
    participants = list(reunion.participantes.select_related("usuario"))
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
    reunion.save(update_fields=["convocada_at", "updated_at"])
    return reunion


@transaction.atomic
def mark_meeting_completed(reunion, *, comentarios=None):
    comentarios = comentarios or {}
    items = list(reunion.agenda.all())
    for item in items:
        if item.pk in comentarios:
            item.comentario_cierre = str(comentarios[item.pk]).strip()
            item.save(update_fields=["comentario_cierre"])
    if any(not item.comentario_cierre.strip() for item in items):
        raise ValidationError("Cada tarea de la agenda requiere comentario de cierre.")
    if reunion.estado != ReunionRevision.Estado.PLANIFICADA:
        raise ValidationError("La reunión ya fue realizada.")
    reunion.estado = ReunionRevision.Estado.REALIZADA
    reunion.save(update_fields=["estado", "updated_at"])
    return reunion
