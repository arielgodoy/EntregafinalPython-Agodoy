"""Configured persistence for Todos stored with BASE_TAREAS."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Sequence
from typing import Protocol, cast

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from settings.services.mysql_connections import open_mysql_connection
from tareas.models import (
    CorrelativoTodoEmpresa,
    Tarea,
    Todo,
    TodoEvento,
)
from tareas.services.connection_roles import (
    TareaConnectionError,
    get_tarea_connection,
    get_tarea_mysql_connection,
)


class TodoStorageError(ValidationError):
    """A controlled failure while resolving or accessing Todo storage."""


class _MySQLCursor(Protocol):
    lastrowid: int
    rowcount: int

    def execute(self, query: str, params: Sequence[object] = ...) -> object: ...
    def fetchone(self) -> Sequence[object] | None: ...
    def fetchall(self) -> Sequence[Sequence[object]]: ...
    def close(self) -> None: ...


class _MySQLConnection(Protocol):
    def cursor(self) -> _MySQLCursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class DjangoTodoUnit:
    def __init__(self, alias):
        self.alias = alias

    def reserve_todo_number(self, empresa_id):
        manager = CorrelativoTodoEmpresa.objects.using(self.alias)
        atomic_kwargs = {"using": self.alias}
        try:
            sequence = manager.select_for_update().get(empresa_id=empresa_id)
        except CorrelativoTodoEmpresa.DoesNotExist:
            try:
                with transaction.atomic(**atomic_kwargs):
                    sequence = manager.create(
                        empresa_id=empresa_id,
                        siguiente_numero=1,
                    )
            except IntegrityError:
                sequence = manager.select_for_update().get(empresa_id=empresa_id)
        number = sequence.siguiente_numero
        sequence.siguiente_numero = number + 1
        sequence.save(using=self.alias, update_fields=["siguiente_numero"])
        return number

    def create_todo(self, todo, usuario):
        todo.correlativo = f"TD{self.reserve_todo_number(todo.empresa_id):07d}"
        todo.save(using=self.alias)
        TodoEvento(
            todo_id=todo.pk,
            tipo=TodoEvento.Tipo.CREADO,
            usuario_id=usuario.pk,
        ).save(using=self.alias)
        return todo

    def get_todo_state(self, todo_id):
        return Todo.objects.using(self.alias).values_list(
            "estado", flat=True
        ).get(pk=todo_id)

    def get_originated_tasks(self, todo_id):
        return list(
            Tarea.objects.using(self.alias)
            .filter(todo_origen_id=todo_id)
            .values_list("pk", "estado")
        )

    def get_task_annulment_chain(self, task_id):
        chain = (
            Tarea.objects.using(self.alias)
            .filter(pk=task_id)
            .values_list(
                "anulada",
                "relaciones_padre__padre__anulada",
                "relaciones_padre__padre__relaciones_padre__padre__anulada",
            )
            .first()
        )
        if chain is None:
            return ()
        return tuple(bool(value) for value in chain if value is not None)

    def save_closed_todo(self, todo, usuario):
        if todo.pk is None:
            todo.correlativo = f"TD{self.reserve_todo_number(todo.empresa_id):07d}"
            todo.save(using=self.alias)
        else:
            updated = Todo.objects.using(self.alias).filter(pk=todo.pk).update(
                estado=todo.estado,
                cerrada_por_id=todo.cerrada_por_id,
                fecha_cierre=todo.fecha_cierre,
                comentario_cierre=todo.comentario_cierre,
            )
            if updated == 0:
                raise Todo.DoesNotExist
        TodoEvento(
            todo_id=todo.pk,
            tipo=TodoEvento.Tipo.CERRADO,
            usuario_id=usuario.pk,
            comentario=todo.comentario_cierre,
        ).save(using=self.alias)


class DjangoTodoStorage:
    def __init__(self, alias):
        self.alias = alias

    def _unit(self):
        return DjangoTodoUnit(self.alias)

    def create_todo(self, todo, usuario):
        with transaction.atomic(using=self.alias):
            return self._unit().create_todo(todo, usuario)

    def get_todo_state(self, todo_id):
        return self._unit().get_todo_state(todo_id)

    def get_originated_tasks(self, todo_id):
        return self._unit().get_originated_tasks(todo_id)

    def get_task_annulment_chain(self, task_id):
        return self._unit().get_task_annulment_chain(task_id)

    @contextmanager
    def atomic(self):
        with transaction.atomic(using=self.alias):
            yield self._unit()


class MySQLTodoUnit:
    def __init__(self, cursor: _MySQLCursor):
        self.cursor = cursor

    def reserve_todo_number(self, empresa_id):
        self.cursor.execute(
            "INSERT IGNORE INTO tareas_correlativotodoempresa "
            "(empresa_id,siguiente_numero) VALUES (%s,1)",
            (empresa_id,),
        )
        self.cursor.execute(
            "SELECT siguiente_numero FROM tareas_correlativotodoempresa "
            "WHERE empresa_id=%s FOR UPDATE",
            (empresa_id,),
        )
        row = self.cursor.fetchone()
        if row is None:
            raise TodoStorageError("No se pudo reservar el correlativo del TO-DO.")
        raw_number = row[0]
        if not isinstance(raw_number, int):
            raise TodoStorageError("El correlativo almacenado del TO-DO no es válido.")
        number = raw_number
        self.cursor.execute(
            "UPDATE tareas_correlativotodoempresa "
            "SET siguiente_numero=%s WHERE empresa_id=%s",
            (number + 1, empresa_id),
        )
        return number

    def _insert_todo(self, todo):
        todo.correlativo = f"TD{self.reserve_todo_number(todo.empresa_id):07d}"
        todo.fecha_creacion = timezone.now()
        self.cursor.execute(
            "INSERT INTO tareas_todo "
            "(empresa_id,correlativo,titulo,descripcion,estado,creada_por_id,"
            "fecha_creacion,cerrada_por_id,fecha_cierre,comentario_cierre,todo_anterior_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                todo.empresa_id,
                todo.correlativo,
                todo.titulo,
                todo.descripcion,
                todo.estado,
                todo.creada_por_id,
                todo.fecha_creacion,
                todo.cerrada_por_id,
                todo.fecha_cierre,
                todo.comentario_cierre,
                todo.todo_anterior_id,
            ),
        )
        todo.pk = self.cursor.lastrowid
        todo._state.adding = False
        return todo

    def _insert_event(self, todo, usuario, tipo, comentario=""):
        timestamp = timezone.now()
        self.cursor.execute(
            "INSERT INTO tareas_todoevento "
            "(todo_id,tipo,usuario_id,`timestamp`,comentario,tarea_id) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (todo.pk, tipo, usuario.pk, timestamp, comentario, None),
        )

    def create_todo(self, todo, usuario):
        self._insert_todo(todo)
        self._insert_event(todo, usuario, TodoEvento.Tipo.CREADO)
        return todo

    def get_todo_state(self, todo_id):
        self.cursor.execute(
            "SELECT estado FROM tareas_todo WHERE id=%s",
            (todo_id,),
        )
        row = self.cursor.fetchone()
        if row is None:
            raise Todo.DoesNotExist
        return row[0]

    def get_originated_tasks(self, todo_id):
        self.cursor.execute(
            "SELECT id,estado FROM tareas_tarea WHERE todo_origen_id=%s",
            (todo_id,),
        )
        return [(row[0], row[1]) for row in self.cursor.fetchall()]

    def get_task_annulment_chain(self, task_id):
        self.cursor.execute(
            "SELECT task.anulada,parent.anulada,grandparent.anulada "
            "FROM tareas_tarea AS task "
            "LEFT JOIN tareas_tarearelacion AS relation "
            "ON relation.hija_id=task.id "
            "LEFT JOIN tareas_tarea AS parent ON parent.id=relation.padre_id "
            "LEFT JOIN tareas_tarearelacion AS parent_relation "
            "ON parent_relation.hija_id=parent.id "
            "LEFT JOIN tareas_tarea AS grandparent "
            "ON grandparent.id=parent_relation.padre_id "
            "WHERE task.id=%s",
            (task_id,),
        )
        row = self.cursor.fetchone()
        if row is None:
            return ()
        return tuple(bool(value) for value in row if value is not None)

    def save_closed_todo(self, todo, usuario):
        if todo.pk is None:
            self._insert_todo(todo)
        else:
            self.cursor.execute(
                "UPDATE tareas_todo SET estado=%s,cerrada_por_id=%s,fecha_cierre=%s,"
                "comentario_cierre=%s WHERE id=%s",
                (
                    todo.estado,
                    todo.cerrada_por_id,
                    todo.fecha_cierre,
                    todo.comentario_cierre,
                    todo.pk,
                ),
            )
            if self.cursor.rowcount == 0:
                raise Todo.DoesNotExist
        self._insert_event(
            todo,
            usuario,
            TodoEvento.Tipo.CERRADO,
            todo.comentario_cierre,
        )


class MySQLTodoStorage:
    def __init__(self, connection_config, database_name):
        self.connection_config = connection_config
        self.database_name = database_name

    @contextmanager
    def _connection(self):
        with open_mysql_connection(
            self.connection_config,
            database_name=self.database_name,
        ) as connection:
            mysql_connection = cast(_MySQLConnection, connection)
            cursor = mysql_connection.cursor()
            try:
                yield mysql_connection, MySQLTodoUnit(cursor)
            finally:
                cursor.close()

    @contextmanager
    def _transaction(self, connection, unit):
        begin = getattr(connection, "begin", None)
        set_autocommit = getattr(connection, "set_autocommit", None)
        if callable(begin):
            begin()
        elif callable(set_autocommit):
            set_autocommit(False)
        else:
            raise TodoStorageError(
                "La conexión de BASE_TAREAS no permite iniciar transacciones."
            )
        try:
            yield unit
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def create_todo(self, todo, usuario):
        with self._connection() as (connection, unit):
            with self._transaction(connection, unit):
                return unit.create_todo(todo, usuario)

    def get_todo_state(self, todo_id):
        with self._connection() as (_connection, unit):
            return unit.get_todo_state(todo_id)

    def get_originated_tasks(self, todo_id):
        with self._connection() as (_connection, unit):
            return unit.get_originated_tasks(todo_id)

    def get_task_annulment_chain(self, task_id):
        with self._connection() as (_connection, unit):
            return unit.get_task_annulment_chain(task_id)

    @contextmanager
    def atomic(self):
        with self._connection() as (connection, unit):
            with self._transaction(connection, unit):
                yield unit


def resolve_todo_storage():
    try:
        source = get_tarea_connection("BASE_TAREAS")
        if source["type"] == "DJANGO":
            alias = source.get("alias")
            if not alias or alias not in settings.DATABASES:
                raise TodoStorageError(
                    "El alias Django de BASE_TAREAS no está disponible."
                )
            return DjangoTodoStorage(alias)
        if source["type"] == "MYSQL_CONFIG":
            connection = get_tarea_mysql_connection("BASE_TAREAS")
            return MySQLTodoStorage(connection, source["database_name"])
        raise TodoStorageError(
            "El tipo de almacenamiento de BASE_TAREAS no está soportado."
        )
    except TareaConnectionError as exc:
        raise TodoStorageError(
            "No se pudo resolver el almacenamiento configurado de Todos."
        ) from exc
