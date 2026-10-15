"""Configured persistence for meeting records stored with BASE_TAREAS."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import date, datetime
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from access_control.models import Empresa
from organizacion.models import Departamento, Local
from settings.services.mysql_connections import open_mysql_connection
from tareas.models import ReunionParticipante, ReunionRevision, ReunionTarea, Tarea
from tareas.services.connection_roles import (
    TareaConnectionError,
    resolve_operational_backend,
)
from tareas.services.task_mutation_locks import (
    TaskMutationScopeError,
    bounded_django_lock_wait,
    bounded_mysql_lock_wait,
    lock_mysql_task_rows,
    lock_orm_task_groups,
    lock_orm_task_rows,
    mysql_mutation_transaction,
)

logger = logging.getLogger(__name__)


class MeetingStorageError(RuntimeError):
    """A controlled failure while resolving or accessing meeting storage."""


class MeetingNotFound(MeetingStorageError):
    """The requested meeting is absent from the configured operational store."""


def _mark_persisted(instance):
    instance._state.adding = False
    return instance


@contextmanager
def _mysql_mutation(connection, *, company_id=None, task_ids=None):
    with bounded_mysql_lock_wait(connection):
        with mysql_mutation_transaction(connection):
            if company_id is not None:
                lock_mysql_task_rows(connection, company_id, task_ids)
            cursor = connection.cursor()
            try:
                yield cursor
            finally:
                cursor.close()


def _default_related(model, object_id):
    if object_id is None:
        return None
    return model.objects.using("default").get(pk=object_id)


def _as_datetime(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _as_date(value):
    return date.fromisoformat(value) if isinstance(value, str) else value


class DjangoMeetingStorage:
    def __init__(self, alias: str):
        self.alias = alias

    def get_meeting(self, meeting_id):
        try:
            return (
                ReunionRevision.objects.using(self.alias)
                .select_related(
                    "empresa", "local", "departamento", "tarea_planificada", "creada_por"
                )
                .get(pk=meeting_id)
            )
        except ReunionRevision.DoesNotExist as exc:
            raise MeetingNotFound("La reunión no existe en BASE_TAREAS.") from exc

    def list_meetings(self, empresa_id):
        return list(
            ReunionRevision.objects.using(self.alias)
            .filter(empresa_id=empresa_id)
            .select_related("empresa", "local", "departamento", "tarea_planificada", "creada_por")
        )

    def get_task(self, task_id):
        try:
            return Tarea.objects.using(self.alias).get(pk=task_id)
        except Tarea.DoesNotExist as exc:
            raise MeetingStorageError("La tarea no existe en BASE_TAREAS.") from exc

    def get_agenda(self, meeting_id):
        return list(
            ReunionTarea.objects.using(self.alias)
            .filter(reunion_id=meeting_id)
            .select_related("reunion", "tarea")
            .order_by("orden", "pk")
        )

    def get_participants(self, meeting_id):
        return list(
            ReunionParticipante.objects.using(self.alias)
            .filter(reunion_id=meeting_id)
            .select_related("reunion", "usuario")
        )

    def save_meeting_and_task(self, meeting, task):
        with transaction.atomic(using=self.alias):
            with bounded_django_lock_wait(self.alias):
                try:
                    lock_orm_task_rows(
                        self.alias,
                        task.empresa_id,
                        (task.pk,),
                    )
                except TaskMutationScopeError as exc:
                    raise MeetingNotFound(
                        "La tarea planificada ya no existe en la empresa."
                    ) from exc
                try:
                    current_meeting = (
                        ReunionRevision.objects.using(self.alias)
                        .select_for_update()
                        .get(
                            pk=meeting.pk,
                            empresa_id=task.empresa_id,
                            tarea_planificada_id=task.pk,
                        )
                    )
                    current_task = Tarea.objects.using(self.alias).get(
                        pk=task.pk,
                        empresa_id=task.empresa_id,
                    )
                except (ReunionRevision.DoesNotExist, Tarea.DoesNotExist) as exc:
                    raise MeetingNotFound(
                        "La reunión o su tarea planificada ya no existe."
                    ) from exc
                for field in (
                    "titulo",
                    "descripcion",
                    "fecha_tope",
                    "tipo_ambito",
                    "local",
                    "departamento",
                ):
                    setattr(current_task, field, getattr(task, field))
                current_task.save(
                    using=self.alias,
                    update_fields=[
                        "titulo", "descripcion", "fecha_tope", "tipo_ambito",
                        "local", "departamento",
                    ],
                )
                for field in (
                    "titulo",
                    "descripcion",
                    "fecha_hora_programada",
                    "modalidad",
                    "lugar_o_enlace",
                    "tipo_ambito",
                    "local",
                    "departamento",
                    "updated_at",
                ):
                    setattr(current_meeting, field, getattr(meeting, field))
                current_meeting.save(
                    using=self.alias,
                    update_fields=[
                        "titulo", "descripcion", "fecha_hora_programada",
                        "modalidad", "lugar_o_enlace", "tipo_ambito", "local",
                        "departamento", "updated_at",
                    ],
                )

    def add_agenda_item(self, item):
        with transaction.atomic(using=self.alias):
            company_id = item.reunion.empresa_id
            with bounded_django_lock_wait(self.alias):
                try:
                    locked = lock_orm_task_rows(
                        self.alias,
                        company_id,
                        (item.tarea_id,),
                    )
                except TaskMutationScopeError as exc:
                    raise MeetingNotFound(
                        "La tarea no existe en la empresa de la reunión."
                    ) from exc
                if not locked:
                    raise MeetingNotFound(
                        "La tarea no existe en la empresa de la reunión."
                    )
                try:
                    meeting = (
                        ReunionRevision.objects.using(self.alias)
                        .select_for_update()
                        .get(pk=item.reunion_id, empresa_id=company_id)
                    )
                except ReunionRevision.DoesNotExist as exc:
                    raise MeetingNotFound from exc
                item.reunion = meeting
                item.tarea = locked[0]
                existing = list(
                    ReunionTarea.objects.using(self.alias)
                    .filter(reunion_id=meeting.pk)
                    .select_related("tarea")
                    .order_by("orden", "pk")
                )
                if any(item.tarea.empresa_id != company_id for item in existing):
                    raise ValidationError(
                        "La agenda contiene una tarea de otra empresa."
                    )
                if any(
                    current.tarea_id == item.tarea_id
                    or current.orden == item.orden
                    for current in existing
                ):
                    raise ValidationError(
                        "La tarea o el orden ya está presente en la agenda."
                    )
                from tareas.services.meetings import _validate_agenda
                _validate_agenda(meeting, [*existing, item])
                item.full_clean()
                item.save(using=self.alias)
        return item

    def remove_agenda_item(self, meeting_id, task_id):
        with transaction.atomic(using=self.alias):
            company_id = (
                ReunionRevision.objects.using(self.alias)
                .filter(pk=meeting_id)
                .values_list("empresa_id", flat=True)
                .first()
            )
            if company_id is None:
                raise MeetingNotFound
            with bounded_django_lock_wait(self.alias):
                try:
                    lock_orm_task_rows(
                        self.alias,
                        company_id,
                        (task_id,),
                    )
                except TaskMutationScopeError as exc:
                    raise MeetingNotFound(
                        "La tarea no existe en la empresa de la reunión."
                    ) from exc
                meeting = (
                    ReunionRevision.objects.using(self.alias)
                    .select_for_update()
                    .filter(pk=meeting_id, empresa_id=company_id)
                    .first()
                )
                if meeting is None:
                    raise MeetingNotFound
                return ReunionTarea.objects.using(self.alias).filter(
                    reunion_id=meeting.pk,
                    tarea_id=task_id,
                ).delete()

    def add_participant(self, participant):
        with transaction.atomic(using=self.alias):
            participant.save(using=self.alias)
        return participant

    def remove_participant(self, meeting_id, user_id):
        with transaction.atomic(using=self.alias):
            return ReunionParticipante.objects.using(self.alias).filter(
                reunion_id=meeting_id, usuario_id=user_id
            ).delete()

    def complete_meeting(self, meeting, agenda_items):
        with transaction.atomic(using=self.alias):
            company_id = meeting.empresa_id
            task_ids = tuple(item.tarea_id for item in agenda_items)
            with bounded_django_lock_wait(self.alias):
                try:
                    lock_orm_task_groups(
                        self.alias,
                        {company_id: task_ids},
                    )
                except TaskMutationScopeError as exc:
                    raise MeetingNotFound(
                        "Una tarea de la agenda ya no existe en la empresa."
                    ) from exc
                current_meeting = (
                    ReunionRevision.objects.using(self.alias)
                    .select_for_update()
                    .filter(pk=meeting.pk, empresa_id=company_id)
                    .first()
                )
                if current_meeting is None:
                    raise MeetingNotFound
                if current_meeting.estado != ReunionRevision.Estado.PLANIFICADA:
                    raise ValidationError("La reunión ya fue realizada.")
                current_items = tuple(
                    ReunionTarea.objects.using(self.alias)
                    .select_for_update()
                    .filter(reunion_id=current_meeting.pk)
                    .order_by("tarea_id", "pk")
                )
                if {item.tarea_id for item in current_items} != set(task_ids):
                    raise ValidationError(
                        "La agenda cambió durante la operación; vuelva a intentarlo."
                    )
                supplied_comments = {
                    item.tarea_id: item.comentario_cierre for item in agenda_items
                }
                if any(
                    not (supplied_comments.get(item.tarea_id) or "").strip()
                    for item in current_items
                ):
                    raise ValidationError(
                        "Cada tarea de la agenda requiere comentario de cierre."
                    )
                for item in current_items:
                    item.comentario_cierre = supplied_comments[item.tarea_id]
                    item.save(
                        using=self.alias,
                        update_fields=["comentario_cierre"],
                    )
                current_meeting.estado = meeting.estado
                current_meeting.updated_at = meeting.updated_at
                current_meeting.save(
                    using=self.alias,
                    update_fields=["estado", "updated_at"],
                )

    def mark_convened(self, meeting):
        with transaction.atomic(using=self.alias):
            current = (
                ReunionRevision.objects.using(self.alias)
                .select_for_update()
                .filter(pk=meeting.pk, empresa_id=meeting.empresa_id)
                .first()
            )
            if current is None:
                raise MeetingNotFound
            current.convocada_at = meeting.convocada_at
            current.updated_at = meeting.updated_at
            current.save(using=self.alias, update_fields=["convocada_at", "updated_at"])
        return meeting


class MySQLMeetingStorage:
    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    def _connection(self):
        return open_mysql_connection(
            self.connection_config,
            database_name=self.database_name,
        )

    def _task(self, task_id):
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT id,titulo,descripcion,prioridad,correlativo,anulada,estado,"
                    "responsable_id,empresa_id,tipo_ambito,local_id,departamento_id,"
                    "creada_por_id,fecha_publicacion,fecha_asignacion,fecha_tope "
                    "FROM tareas_tarea WHERE id=%s",
                    (task_id,),
                )
                row = cursor.fetchone()
            finally:
                cursor.close()
        if row is None:
            raise MeetingStorageError("La tarea no existe en BASE_TAREAS.")
        names = (
            "id", "titulo", "descripcion", "prioridad", "correlativo", "anulada", "estado",
            "responsable_id", "empresa_id", "tipo_ambito", "local_id", "departamento_id",
            "creada_por_id", "fecha_publicacion", "fecha_asignacion", "fecha_tope",
        )
        task_values = dict(zip(names, row))
        task_values["fecha_publicacion"] = _as_datetime(task_values["fecha_publicacion"])
        task_values["fecha_asignacion"] = _as_datetime(task_values["fecha_asignacion"])
        task_values["fecha_tope"] = _as_date(task_values["fecha_tope"])
        task = _mark_persisted(Tarea(**task_values))
        task._persisted_clean_values = {
            field: task_values[field]
            for field in ("estado", "fecha_publicacion", "fecha_asignacion")
        }
        task.empresa = _default_related(Empresa, task.empresa_id)
        task.creada_por = _default_related(User, task.creada_por_id)
        task.responsable = _default_related(User, task.responsable_id)
        task.local = _default_related(Local, task.local_id)
        task.departamento = _default_related(Departamento, task.departamento_id)
        return task

    def create_meeting_and_task(self, meeting, task, *, actor_id):
        try:
            with self._connection() as connection:
                with _mysql_mutation(connection) as cursor:
                    cursor.execute(
                        "INSERT INTO tareas_correlativoempresa "
                        "(empresa_id,siguiente_numero) VALUES (%s,%s) "
                        "ON DUPLICATE KEY UPDATE empresa_id=empresa_id",
                        (task.empresa_id, 1),
                    )
                    cursor.execute(
                        "SELECT siguiente_numero FROM tareas_correlativoempresa "
                        "WHERE empresa_id=%s FOR UPDATE",
                        (task.empresa_id,),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise MeetingStorageError(
                            "No se pudo reservar el correlativo de Tareas."
                        )
                    number = int(row[0])
                    cursor.execute(
                        "UPDATE tareas_correlativoempresa SET siguiente_numero=%s "
                        "WHERE empresa_id=%s",
                        (number + 1, task.empresa_id),
                    )

                    now = timezone.now()
                    draft_correlativo = f"B{number:07d}"
                    active_correlativo = f"A{number:07d}"
                    task_fields = (
                        "titulo,descripcion,prioridad,correlativo,anulada,"
                        "fechas_pendientes_confirmacion,cierre_completado,"
                        "requiere_evidencia_cierre,estado,responsable_id,empresa_id,"
                        "tipo_ambito,local_id,departamento_id,creada_por_id,"
                        "fecha_creacion,fecha_publicacion,fecha_asignacion,fecha_tope,"
                        "fecha_cumplimiento,todo_origen_id,tarea_origen_id"
                    )
                    cursor.execute(
                        f"INSERT INTO tareas_tarea ({task_fields}) VALUES "
                        "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            task.titulo,
                            task.descripcion,
                            task.prioridad,
                            draft_correlativo,
                            False,
                            False,
                            False,
                            False,
                            Tarea.Estado.BORRADOR,
                            task.responsable_id,
                            task.empresa_id,
                            task.tipo_ambito,
                            task.local_id,
                            task.departamento_id,
                            task.creada_por_id,
                            now,
                            None,
                            None,
                            task.fecha_tope,
                            None,
                            None,
                            None,
                        ),
                    )
                    task.pk = cursor.lastrowid
                    task._state.adding = False
                    task.correlativo = active_correlativo
                    task.estado = Tarea.Estado.ACTIVA
                    task.fecha_creacion = now
                    task.fecha_publicacion = now
                    task.fecha_asignacion = now

                    meeting.tarea_planificada = task
                    meeting.full_clean(
                        exclude=["tarea_planificada"],
                        validate_unique=False,
                        validate_constraints=False,
                    )
                    cursor.execute(
                        "UPDATE tareas_tarea SET estado=%s,correlativo=%s,"
                        "fecha_publicacion=%s,fecha_asignacion=%s "
                        "WHERE id=%s AND empresa_id=%s",
                        (
                            Tarea.Estado.ACTIVA,
                            active_correlativo,
                            now,
                            now,
                            task.pk,
                            task.empresa_id,
                        ),
                    )
                    cursor.execute(
                        "INSERT INTO tareas_tareatransicion "
                        "(tarea_id,estado_origen,estado_destino,accion_evento,"
                        "usuario_id,timestamp,motivo) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (
                            task.pk,
                            Tarea.Estado.BORRADOR,
                            Tarea.Estado.ACTIVA,
                            "PUBLICAR",
                            actor_id,
                            now,
                            "",
                        ),
                    )
                    meeting.created_at = now
                    meeting.updated_at = now
                    meeting.estado = ReunionRevision.Estado.PLANIFICADA
                    cursor.execute(
                        "INSERT INTO tareas_reunionrevision "
                        "(empresa_id,titulo,descripcion,fecha_hora_programada,"
                        "modalidad,lugar_o_enlace,tipo_ambito,local_id,"
                        "departamento_id,tarea_planificada_id,creada_por_id,estado,"
                        "convocada_at,created_at,updated_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            meeting.empresa_id,
                            meeting.titulo,
                            meeting.descripcion,
                            meeting.fecha_hora_programada,
                            meeting.modalidad,
                            meeting.lugar_o_enlace,
                            meeting.tipo_ambito,
                            meeting.local_id,
                            meeting.departamento_id,
                            task.pk,
                            meeting.creada_por_id,
                            meeting.estado,
                            None,
                            now,
                            now,
                        ),
                    )
                    meeting.pk = cursor.lastrowid
                    meeting._state.adding = False
        except (MeetingStorageError, ValidationError):
            raise
        except Exception as exc:
            logger.error("MySQL meeting and planned-task creation failed.")
            raise MeetingStorageError(
                "No se pudo crear la reunión en BASE_TAREAS."
            ) from exc
        return meeting

    def get_task(self, task_id):
        return self._task(task_id)

    def get_meeting(self, meeting_id):
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT id,empresa_id,titulo,descripcion,fecha_hora_programada,modalidad,"
                    "lugar_o_enlace,tipo_ambito,local_id,departamento_id,tarea_planificada_id,"
                    "creada_por_id,estado,convocada_at,created_at,updated_at "
                    "FROM tareas_reunionrevision WHERE id=%s",
                    (meeting_id,),
                )
                row = cursor.fetchone()
            finally:
                cursor.close()
        if row is None:
            raise MeetingNotFound("La reunión no existe en BASE_TAREAS.")
        names = (
            "id", "empresa_id", "titulo", "descripcion", "fecha_hora_programada",
            "modalidad", "lugar_o_enlace", "tipo_ambito", "local_id", "departamento_id",
            "tarea_planificada_id", "creada_por_id", "estado", "convocada_at", "created_at",
            "updated_at",
        )
        meeting_values = dict(zip(names, row))
        for field in ("fecha_hora_programada", "convocada_at", "created_at", "updated_at"):
            meeting_values[field] = _as_datetime(meeting_values[field])
        meeting = _mark_persisted(ReunionRevision(**meeting_values))
        meeting.empresa = _default_related(Empresa, meeting.empresa_id)
        meeting.local = _default_related(Local, meeting.local_id)
        meeting.departamento = _default_related(Departamento, meeting.departamento_id)
        meeting.creada_por = _default_related(User, meeting.creada_por_id)
        meeting.tarea_planificada = self._task(meeting.tarea_planificada_id)
        return meeting

    def list_meetings(self, empresa_id):
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT id FROM tareas_reunionrevision "
                    "WHERE empresa_id=%s ORDER BY id",
                    (empresa_id,),
                )
                meeting_ids = [row[0] for row in cursor.fetchall()]
            finally:
                cursor.close()
        return [self.get_meeting(meeting_id) for meeting_id in meeting_ids]

    def get_agenda(self, meeting_id):
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT id,reunion_id,tarea_id,orden,comentario_revision,comentario_cierre,"
                    "created_at FROM tareas_reuniontarea WHERE reunion_id=%s ORDER BY orden,id",
                    (meeting_id,),
                )
                rows = cursor.fetchall()
            finally:
                cursor.close()
        meeting = self.get_meeting(meeting_id)
        items = []
        for row in rows:
            item = _mark_persisted(
                ReunionTarea(
                    pk=row[0], reunion_id=row[1], tarea_id=row[2], orden=row[3],
                    comentario_revision=row[4], comentario_cierre=row[5],
                    created_at=_as_datetime(row[6]),
                )
            )
            item.reunion = meeting
            item.tarea = self._task(item.tarea_id)
            items.append(item)
        return items

    def get_participants(self, meeting_id):
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT id,reunion_id,usuario_id,created_at FROM tareas_reunionparticipante "
                    "WHERE reunion_id=%s ORDER BY id",
                    (meeting_id,),
                )
                rows = cursor.fetchall()
            finally:
                cursor.close()
        meeting = self.get_meeting(meeting_id)
        return [
            _participant_instance(row, meeting)
            for row in rows
        ]

    def save_meeting_and_task(self, meeting, task):
        with self._connection() as connection:
            with _mysql_mutation(
                connection,
                company_id=task.empresa_id,
                task_ids=(task.pk,),
            ) as cursor:
                cursor.execute(
                    "SELECT empresa_id,tarea_planificada_id "
                    "FROM tareas_reunionrevision WHERE id=%s FOR UPDATE",
                    (meeting.pk,),
                )
                linked_meeting = cursor.fetchone()
                if (
                    linked_meeting is None
                    or linked_meeting[0] != task.empresa_id
                    or linked_meeting[1] != task.pk
                ):
                    raise MeetingNotFound(
                        "La reunión ya no está vinculada a la tarea planificada."
                    )
                cursor.execute(
                    "UPDATE tareas_tarea SET titulo=%s,descripcion=%s,fecha_tope=%s,"
                    "tipo_ambito=%s,local_id=%s,departamento_id=%s "
                    "WHERE id=%s AND empresa_id=%s",
                    (
                        task.titulo, task.descripcion, task.fecha_tope, task.tipo_ambito,
                        task.local_id, task.departamento_id, task.pk, task.empresa_id,
                    ),
                )
                cursor.execute(
                    "UPDATE tareas_reunionrevision SET titulo=%s,descripcion=%s,"
                    "fecha_hora_programada=%s,modalidad=%s,lugar_o_enlace=%s,tipo_ambito=%s,"
                    "local_id=%s,departamento_id=%s,updated_at=%s "
                    "WHERE id=%s AND empresa_id=%s AND tarea_planificada_id=%s",
                    (
                        meeting.titulo, meeting.descripcion, meeting.fecha_hora_programada,
                        meeting.modalidad, meeting.lugar_o_enlace, meeting.tipo_ambito,
                        meeting.local_id, meeting.departamento_id, meeting.updated_at,
                        meeting.pk, task.empresa_id, task.pk,
                    ),
                )

    def add_agenda_item(self, item):
        with self._connection() as connection:
            company_id = item.reunion.empresa_id
            with _mysql_mutation(
                connection,
                company_id=company_id,
                task_ids=(item.tarea_id,),
            ) as cursor:
                cursor.execute(
                    "SELECT id,empresa_id,estado FROM tareas_reunionrevision "
                    "WHERE id=%s FOR UPDATE",
                    (item.reunion_id,),
                )
                meeting_row = cursor.fetchone()
                if meeting_row is None or meeting_row[1] != company_id:
                    raise MeetingNotFound
                cursor.execute(
                    "SELECT id,prioridad,empresa_id FROM tareas_tarea "
                    "WHERE id=%s AND empresa_id=%s",
                    (item.tarea_id, company_id),
                )
                task_row = cursor.fetchone()
                if task_row is None:
                    raise MeetingNotFound(
                        "La tarea no existe en la empresa de la reunión."
                    )
                item.tarea.empresa_id = task_row[2]
                item.tarea.prioridad = task_row[1]
                cursor.execute(
                    "SELECT agenda.orden,task.prioridad,agenda.tarea_id,task.empresa_id "
                    "FROM tareas_reuniontarea AS agenda "
                    "INNER JOIN tareas_tarea AS task ON task.id=agenda.tarea_id "
                    "WHERE agenda.reunion_id=%s ORDER BY agenda.orden,agenda.id",
                    (item.reunion_id,),
                )
                existing_rows = cursor.fetchall()
                if any(row[3] != company_id for row in existing_rows):
                    raise ValidationError(
                        "La agenda contiene una tarea de otra empresa."
                    )
                if any(
                    task_id == item.tarea_id or order == item.orden
                    for order, _priority, task_id, _company in existing_rows
                ):
                    raise ValidationError(
                        "La tarea o el orden ya está presente en la agenda."
                    )
                from tareas.services.meetings import _validate_agenda
                current_items = [
                    SimpleNamespace(
                        orden=order,
                        tarea=SimpleNamespace(prioridad=priority),
                    )
                    for order, priority, _task_id, _company in existing_rows
                ]
                _validate_agenda(
                    item.reunion,
                    [*current_items, item],
                )
                item.created_at = item.created_at or timezone.now()
                cursor.execute(
                    "INSERT INTO tareas_reuniontarea "
                    "(reunion_id,tarea_id,orden,comentario_revision,comentario_cierre,created_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        item.reunion_id, item.tarea_id, item.orden, item.comentario_revision,
                        item.comentario_cierre, item.created_at,
                    ),
                )
                item.pk = cursor.lastrowid
        return item

    def remove_agenda_item(self, meeting_id, task_id):
        with self._connection() as connection:
            with bounded_mysql_lock_wait(connection):
                with mysql_mutation_transaction(connection):
                    cursor = connection.cursor()
                    try:
                        cursor.execute(
                            "SELECT empresa_id FROM tareas_reunionrevision WHERE id=%s",
                            (meeting_id,),
                        )
                        meeting_row = cursor.fetchone()
                        if meeting_row is None:
                            raise MeetingNotFound
                        company_id = meeting_row[0]
                        try:
                            lock_mysql_task_rows(
                                connection,
                                company_id,
                                (task_id,),
                            )
                        except TaskMutationScopeError as exc:
                            raise MeetingNotFound(
                                "La tarea no existe en la empresa de la reunión."
                            ) from exc
                        cursor.execute(
                            "SELECT empresa_id FROM tareas_reunionrevision "
                            "WHERE id=%s FOR UPDATE",
                            (meeting_id,),
                        )
                        current_meeting = cursor.fetchone()
                        if current_meeting is None or current_meeting[0] != company_id:
                            raise MeetingNotFound
                        cursor.execute(
                            "DELETE FROM tareas_reuniontarea "
                            "WHERE reunion_id=%s AND tarea_id=%s",
                            (meeting_id, task_id),
                        )
                        count = cursor.rowcount
                    finally:
                        cursor.close()
        return count, {"tareas.ReunionTarea": count} if count else {}

    def add_participant(self, participant):
        with self._connection() as connection:
            with _mysql_mutation(connection) as cursor:
                cursor.execute(
                    "SELECT empresa_id FROM tareas_reunionrevision "
                    "WHERE id=%s FOR UPDATE",
                    (participant.reunion_id,),
                )
                meeting = cursor.fetchone()
                if meeting is None or meeting[0] != participant.reunion.empresa_id:
                    raise MeetingNotFound
                participant.created_at = participant.created_at or timezone.now()
                cursor.execute(
                    "INSERT INTO tareas_reunionparticipante (reunion_id,usuario_id,created_at) "
                    "VALUES (%s,%s,%s)",
                    (participant.reunion_id, participant.usuario_id, participant.created_at),
                )
                participant.pk = cursor.lastrowid
        return participant

    def remove_participant(self, meeting_id, user_id):
        with self._connection() as connection:
            with _mysql_mutation(connection) as cursor:
                cursor.execute(
                    "SELECT id FROM tareas_reunionrevision WHERE id=%s FOR UPDATE",
                    (meeting_id,),
                )
                if cursor.fetchone() is None:
                    raise MeetingNotFound
                cursor.execute(
                    "DELETE FROM tareas_reunionparticipante WHERE reunion_id=%s AND usuario_id=%s",
                    (meeting_id, user_id),
                )
                count = cursor.rowcount
        return count, {"tareas.ReunionParticipante": count} if count else {}

    def complete_meeting(self, meeting, agenda_items):
        with self._connection() as connection:
            task_ids = tuple(item.tarea_id for item in agenda_items)
            with _mysql_mutation(
                connection,
                company_id=meeting.empresa_id,
                task_ids=task_ids,
            ) as cursor:
                cursor.execute(
                    "SELECT id,empresa_id,estado FROM tareas_reunionrevision "
                    "WHERE id=%s FOR UPDATE",
                    (meeting.pk,),
                )
                current_meeting = cursor.fetchone()
                if (
                    current_meeting is None
                    or current_meeting[1] != meeting.empresa_id
                ):
                    raise MeetingNotFound
                if current_meeting[2] != ReunionRevision.Estado.PLANIFICADA:
                    raise ValidationError("La reunión ya fue realizada.")
                cursor.execute(
                    "SELECT tarea_id FROM tareas_reuniontarea "
                    "WHERE reunion_id=%s ORDER BY tarea_id,id FOR UPDATE",
                    (meeting.pk,),
                )
                current_task_ids = tuple(row[0] for row in cursor.fetchall())
                if set(current_task_ids) != set(task_ids):
                    raise ValidationError(
                        "La agenda cambió durante la operación; vuelva a intentarlo."
                    )
                comments = {
                    item.tarea_id: item.comentario_cierre for item in agenda_items
                }
                if any(
                    not (comments.get(task_id) or "").strip()
                    for task_id in current_task_ids
                ):
                    raise ValidationError(
                        "Cada tarea de la agenda requiere comentario de cierre."
                    )
                for task_id in current_task_ids:
                    cursor.execute(
                        "UPDATE tareas_reuniontarea SET comentario_cierre=%s "
                        "WHERE reunion_id=%s AND tarea_id=%s",
                        (comments[task_id], meeting.pk, task_id),
                    )
                cursor.execute(
                    "UPDATE tareas_reunionrevision SET estado=%s,updated_at=%s "
                    "WHERE id=%s AND empresa_id=%s",
                    (
                        meeting.estado,
                        meeting.updated_at,
                        meeting.pk,
                        meeting.empresa_id,
                    ),
                )

    def mark_convened(self, meeting):
        with self._connection() as connection:
            with _mysql_mutation(connection) as cursor:
                cursor.execute(
                    "SELECT id,empresa_id FROM tareas_reunionrevision "
                    "WHERE id=%s FOR UPDATE",
                    (meeting.pk,),
                )
                current = cursor.fetchone()
                if current is None or current[1] != meeting.empresa_id:
                    raise MeetingNotFound
                cursor.execute(
                    "UPDATE tareas_reunionrevision SET convocada_at=%s,updated_at=%s "
                    "WHERE id=%s AND empresa_id=%s",
                    (
                        meeting.convocada_at,
                        meeting.updated_at,
                        meeting.pk,
                        meeting.empresa_id,
                    ),
                )
        return meeting


def _participant_instance(row, meeting):
    participant = _mark_persisted(
        ReunionParticipante(
            pk=row[0], reunion_id=row[1], usuario_id=row[2], created_at=_as_datetime(row[3])
        )
    )
    participant.reunion = meeting
    participant.usuario = User.objects.using("default").get(pk=participant.usuario_id)
    return participant


def resolve_meeting_storage():
    try:
        context = resolve_operational_backend("BASE_TAREAS")
        if context.backend_type == "DJANGO":
            alias = context.django_alias
            if not alias or alias not in settings.DATABASES:
                raise MeetingStorageError("El alias Django de BASE_TAREAS no está disponible.")
            return DjangoMeetingStorage(alias)
        if context.backend_type == "MYSQL_CONFIG":
            connection = context.mysql_connection
            database_name = context.database_name
            if not database_name:
                raise MeetingStorageError("La base de BASE_TAREAS no está configurada.")
            return MySQLMeetingStorage(connection, database_name)
        raise MeetingStorageError("El backend configurado de BASE_TAREAS no es compatible.")
    except MeetingStorageError:
        raise
    except (TareaConnectionError, KeyError, TypeError, ValueError) as exc:
        logger.error("Meeting BASE_TAREAS resolution failed.")
        raise MeetingStorageError("No se pudo resolver el almacenamiento de reuniones.") from exc
    except Exception as exc:
        logger.error("Meeting BASE_TAREAS resolution failed.")
        raise MeetingStorageError("No se pudo resolver el almacenamiento de reuniones.") from exc
