from __future__ import annotations

from contextlib import contextmanager

from django.db import transaction
from django.utils import timezone

from settings.services.mysql_connections import open_mysql_connection
from tareas.models import Tarea, TodoEvento
from tareas.services.connection_roles import get_tarea_connection, get_tarea_mysql_connection
from tareas.services.task_storage import TaskStorageError


class DjangoOriginStorage:
    def __init__(self, alias: str):
        self.alias = alias

    @contextmanager
    def atomic(self):
        with transaction.atomic(using=self.alias):
            yield self

    def create_task_from_todo(self, task, usuario, comentario):
        task.save(using=self.alias)
        TodoEvento.objects.using(self.alias).create(
            todo_id=task.todo_origen_id,
            tipo=TodoEvento.Tipo.TAREA_CREADA,
            usuario_id=usuario.pk,
            comentario=comentario,
            tarea_id=task.pk,
        )
        return task


class MySQLOriginStorage:
    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    @contextmanager
    def _connection(self):
        with open_mysql_connection(
            self.connection_config, database_name=self.database_name,
        ) as connection:
            cursor = connection.cursor()
            try:
                yield connection, cursor
            finally:
                cursor.close()

    @contextmanager
    def atomic(self):
        with self._connection() as (connection, cursor):
            try:
                if callable(getattr(connection, "begin", None)):
                    connection.begin()
                yield _MySQLOriginUnit(connection, cursor)
                connection.commit()
            except Exception:
                connection.rollback()
                raise


class _MySQLOriginUnit:
    def __init__(self, connection, cursor):
        self.connection = connection
        self.cursor = cursor

    @staticmethod
    def _reserve_number(cursor, empresa_id):
        cursor.execute(
            "INSERT INTO tareas_correlativoempresa "
            "(empresa_id, siguiente_numero) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE empresa_id = empresa_id",
            (empresa_id, 1),
        )
        cursor.execute(
            "SELECT siguiente_numero FROM tareas_correlativoempresa "
            "WHERE empresa_id=%s FOR UPDATE",
            (empresa_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise TaskStorageError("No se pudo reservar el correlativo de Tareas.")
        number = int(row[0])
        cursor.execute(
            "UPDATE tareas_correlativoempresa SET siguiente_numero=%s WHERE empresa_id=%s",
            (number + 1, empresa_id),
        )
        return number

    def create_task_from_todo(self, task, usuario, comentario):
        number = self._reserve_number(self.cursor, task.empresa_id)
        correlativo = f"B{number:07d}"
        created_at = timezone.now()
        self.cursor.execute(
            "INSERT INTO tareas_tarea (titulo,descripcion,prioridad,correlativo,"
            "anulada,fechas_pendientes_confirmacion,cierre_completado,"
            "requiere_evidencia_cierre,estado,responsable_id,empresa_id,"
            "tipo_ambito,local_id,departamento_id,creada_por_id,fecha_creacion,"
            "fecha_publicacion,fecha_asignacion,fecha_tope,fecha_cumplimiento,"
            "todo_origen_id,tarea_origen_id) VALUES ("
            "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                task.titulo, task.descripcion, task.prioridad, correlativo,
                task.anulada, task.fechas_pendientes_confirmacion,
                task.cierre_completado, task.requiere_evidencia_cierre,
                task.estado, task.responsable_id, task.empresa_id,
                task.tipo_ambito, task.local_id, task.departamento_id,
                task.creada_por_id, created_at, task.fecha_publicacion,
                task.fecha_asignacion, task.fecha_tope, task.fecha_cumplimiento,
                task.todo_origen_id, task.tarea_origen_id,
            ),
        )
        task.pk = self.cursor.lastrowid
        task.correlativo = correlativo
        task.fecha_creacion = created_at
        task._state.adding = False
        self.cursor.execute(
            "INSERT INTO tareas_todoevento "
            "(todo_id,tipo,usuario_id,`timestamp`,comentario,tarea_id) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (
                task.todo_origen_id, TodoEvento.Tipo.TAREA_CREADA,
                usuario.pk, created_at, comentario, task.pk,
            ),
        )
        return task


def resolve_origin_storage():
    source = get_tarea_connection("BASE_TAREAS")
    if source["type"] == "DJANGO":
        return DjangoOriginStorage(source["alias"])
    if source["type"] == "MYSQL_CONFIG":
        return MySQLOriginStorage(
            get_tarea_mysql_connection("BASE_TAREAS"), source["database_name"],
        )
    raise TaskStorageError("El backend de BASE_TAREAS no es válido.")
