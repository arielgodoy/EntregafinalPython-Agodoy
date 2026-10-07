"""Configured persistence for meeting records stored with BASE_TAREAS."""

from __future__ import annotations

import logging
from datetime import date, datetime

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

logger = logging.getLogger(__name__)


class MeetingStorageError(RuntimeError):
    """A controlled failure while resolving or accessing meeting storage."""


class MeetingNotFound(MeetingStorageError):
    """The requested meeting is absent from the configured operational store."""


def _mark_persisted(instance):
    instance._state.adding = False
    return instance


def _mysql_transaction(connection):
    if callable(getattr(connection, "begin", None)):
        connection.begin()


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
            task.save(
                using=self.alias,
                update_fields=[
                    "titulo", "descripcion", "fecha_tope", "tipo_ambito", "local", "departamento",
                ],
            )
            meeting.save(using=self.alias)

    def add_agenda_item(self, item):
        with transaction.atomic(using=self.alias):
            item.save(using=self.alias)
        return item

    def remove_agenda_item(self, meeting_id, task_id):
        with transaction.atomic(using=self.alias):
            return ReunionTarea.objects.using(self.alias).filter(
                reunion_id=meeting_id, tarea_id=task_id
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
            for item in agenda_items:
                item.save(using=self.alias, update_fields=["comentario_cierre"])
            meeting.save(using=self.alias, update_fields=["estado", "updated_at"])

    def mark_convened(self, meeting):
        with transaction.atomic(using=self.alias):
            meeting.save(using=self.alias, update_fields=["convocada_at", "updated_at"])
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
                cursor = connection.cursor()
                try:
                    _mysql_transaction(connection)
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
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()
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
            cursor = connection.cursor()
            try:
                _mysql_transaction(connection)
                cursor.execute(
                    "UPDATE tareas_tarea SET titulo=%s,descripcion=%s,fecha_tope=%s,"
                    "tipo_ambito=%s,local_id=%s,departamento_id=%s WHERE id=%s",
                    (
                        task.titulo, task.descripcion, task.fecha_tope, task.tipo_ambito,
                        task.local_id, task.departamento_id, task.pk,
                    ),
                )
                cursor.execute(
                    "UPDATE tareas_reunionrevision SET titulo=%s,descripcion=%s,"
                    "fecha_hora_programada=%s,modalidad=%s,lugar_o_enlace=%s,tipo_ambito=%s,"
                    "local_id=%s,departamento_id=%s,updated_at=%s WHERE id=%s",
                    (
                        meeting.titulo, meeting.descripcion, meeting.fecha_hora_programada,
                        meeting.modalidad, meeting.lugar_o_enlace, meeting.tipo_ambito,
                        meeting.local_id, meeting.departamento_id, meeting.updated_at, meeting.pk,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def add_agenda_item(self, item):
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                _mysql_transaction(connection)
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
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
        return item

    def remove_agenda_item(self, meeting_id, task_id):
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                _mysql_transaction(connection)
                cursor.execute(
                    "DELETE FROM tareas_reuniontarea WHERE reunion_id=%s AND tarea_id=%s",
                    (meeting_id, task_id),
                )
                count = cursor.rowcount
                connection.commit()
                return count, {"tareas.ReunionTarea": count} if count else {}
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def add_participant(self, participant):
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                _mysql_transaction(connection)
                participant.created_at = participant.created_at or timezone.now()
                cursor.execute(
                    "INSERT INTO tareas_reunionparticipante (reunion_id,usuario_id,created_at) "
                    "VALUES (%s,%s,%s)",
                    (participant.reunion_id, participant.usuario_id, participant.created_at),
                )
                participant.pk = cursor.lastrowid
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
        return participant

    def remove_participant(self, meeting_id, user_id):
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                _mysql_transaction(connection)
                cursor.execute(
                    "DELETE FROM tareas_reunionparticipante WHERE reunion_id=%s AND usuario_id=%s",
                    (meeting_id, user_id),
                )
                count = cursor.rowcount
                connection.commit()
                return count, {"tareas.ReunionParticipante": count} if count else {}
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def complete_meeting(self, meeting, agenda_items):
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                _mysql_transaction(connection)
                for item in agenda_items:
                    cursor.execute(
                        "UPDATE tareas_reuniontarea SET comentario_cierre=%s WHERE id=%s",
                        (item.comentario_cierre, item.pk),
                    )
                cursor.execute(
                    "UPDATE tareas_reunionrevision SET estado=%s,updated_at=%s WHERE id=%s",
                    (meeting.estado, meeting.updated_at, meeting.pk),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def mark_convened(self, meeting):
        with self._connection() as connection:
            cursor = connection.cursor()
            try:
                _mysql_transaction(connection)
                cursor.execute(
                    "UPDATE tareas_reunionrevision SET convocada_at=%s,updated_at=%s WHERE id=%s",
                    (meeting.convocada_at, meeting.updated_at, meeting.pk),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
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
