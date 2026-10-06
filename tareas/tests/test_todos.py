from contextlib import contextmanager
from datetime import date
import sqlite3
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from access_control.models import Empresa
from tareas.models import CorrelativoEmpresa, Tarea, Todo, TodoEvento
from tareas.services.origin import create_task_from_todo
from tareas.services.todos import close_todo, create_todo
from tareas.services import todo_storage
from tareas.services.connection_roles import TareaConnectionRoleNotFoundError
from tareas.services.todo_storage import (
    DjangoTodoStorage,
    MySQLTodoStorage,
    TodoStorageError,
    resolve_todo_storage,
)
from tareas.tests.factories import configure_task_storage


class TodoDomainTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        configure_task_storage()
        cls.empresa = Empresa.objects.create(codigo="TD1", descripcion="Empresa TD 1")
        cls.otra_empresa = Empresa.objects.create(codigo="TD2", descripcion="Empresa TD 2")
        cls.usuario = User.objects.create_user(username="todo_user", password="x")
        cls.otro_usuario = User.objects.create_user(username="todo_other", password="x")

    def test_correlativo_td_independiente_por_empresa(self):
        first = create_todo(self.empresa, self.usuario, "Uno")
        second = create_todo(self.empresa, self.usuario, "Dos")
        other = create_todo(self.otra_empresa, self.otro_usuario, "Otro")

        self.assertEqual(first.correlativo, "TD0000001")
        self.assertEqual(second.correlativo, "TD0000002")
        self.assertEqual(other.correlativo, "TD0000001")
        self.assertEqual(CorrelativoEmpresa.objects.count(), 0)

    def test_todo_abierto_y_cierre_auditado(self):
        todo = create_todo(self.empresa, self.usuario, "Pendiente")
        self.assertEqual(todo.estado, Todo.Estado.ABIERTO)

        close_todo(todo, self.otro_usuario, "Resuelto")
        todo.refresh_from_db()
        evento = TodoEvento.objects.get(todo=todo, tipo=TodoEvento.Tipo.CERRADO)
        self.assertEqual(todo.estado, Todo.Estado.CERRADO)
        self.assertEqual(todo.cerrada_por, self.otro_usuario)
        self.assertIsNotNone(todo.fecha_cierre)
        self.assertEqual(todo.comentario_cierre, "Resuelto")
        self.assertEqual(evento.usuario, self.otro_usuario)
        self.assertEqual(evento.comentario, "Resuelto")

    def test_todo_cerrado_no_se_reabre(self):
        todo = create_todo(self.empresa, self.usuario, "Pendiente")
        close_todo(todo, self.usuario)
        todo.estado = Todo.Estado.ABIERTO
        with self.assertRaises(ValidationError):
            todo.save(update_fields=["estado"])
        with self.assertRaises(ValidationError):
            close_todo(todo, self.usuario)

    def test_cierre_bloqueado_por_tarea_originada_pendiente(self):
        todo = create_todo(self.empresa, self.usuario, "Pendiente")
        create_task_from_todo(todo, self.usuario, "Tarea derivada")
        with self.assertRaises(ValidationError):
            close_todo(todo, self.usuario)

    def test_tarea_cerrada_o_anulada_no_bloquea_y_no_cierra_automaticamente(self):
        closed_todo = create_todo(self.empresa, self.usuario, "Cerrada")
        closed_task = create_task_from_todo(closed_todo, self.usuario, "Cerrada")
        Tarea.objects.filter(pk=closed_task.pk).update(estado=Tarea.Estado.CERRADA)
        close_todo(closed_todo, self.usuario)

        annulled_todo = create_todo(self.empresa, self.usuario, "Anulada")
        annulled_task = create_task_from_todo(annulled_todo, self.usuario, "Anulada")
        Tarea.objects.filter(pk=annulled_task.pk).update(anulada=True)
        close_todo(annulled_todo, self.usuario)

        open_todo = create_todo(self.empresa, self.usuario, "No automático")
        open_task = create_task_from_todo(open_todo, self.usuario, "Pendiente")
        Tarea.objects.filter(pk=open_task.pk).update(estado=Tarea.Estado.CERRADA)
        open_todo.refresh_from_db()
        self.assertEqual(open_todo.estado, Todo.Estado.ABIERTO)

    def test_nuevo_episodio_no_reabre_el_anterior(self):
        previous = create_todo(self.empresa, self.usuario, "Anterior")
        close_todo(previous, self.usuario)
        current = create_todo(self.empresa, self.usuario, "Nuevo episodio", todo_anterior=previous)

        self.assertEqual(current.todo_anterior, previous)
        self.assertEqual(previous.estado, Todo.Estado.CERRADO)
        self.assertEqual(current.estado, Todo.Estado.ABIERTO)

    def test_derivacion_audita_usuario_fecha_comentario_y_origen(self):
        todo = create_todo(self.empresa, self.usuario, "Pendiente")
        task = create_task_from_todo(
            todo,
            self.otro_usuario,
            "Formalizada",
            comentario="Se formaliza",
        )
        evento = TodoEvento.objects.get(todo=todo, tipo=TodoEvento.Tipo.TAREA_CREADA)

        self.assertEqual(task.todo_origen, todo)
        self.assertEqual(task.tarea_origen, None)
        self.assertEqual(evento.usuario, self.otro_usuario)
        self.assertIsNotNone(evento.timestamp)
        self.assertEqual(evento.comentario, "Se formaliza")
        self.assertRegex(task.correlativo, r"^B[0-9]{7}$")

    def test_derivacion_conserva_lifecycle_normal(self):
        todo = create_todo(self.empresa, self.usuario, "Pendiente")
        task = create_task_from_todo(todo, self.usuario, "Formalizada")
        task.responsable = self.usuario
        task.fecha_tope = date.today()
        task.save(update_fields=["responsable", "fecha_tope"])
        task.publicar(self.usuario)
        task.refresh_from_db()

        self.assertEqual(task.estado, Tarea.Estado.ACTIVA)
        self.assertRegex(task.correlativo, r"^A[0-9]{7}$")
        self.assertEqual(task.todo_origen, todo)

    def test_episodio_y_derivacion_respetan_empresa(self):
        previous = create_todo(self.empresa, self.usuario, "Anterior")
        close_todo(previous, self.usuario)
        with self.assertRaises(ValidationError):
            create_todo(self.otra_empresa, self.otro_usuario, "Cruza", todo_anterior=previous)

        todo = create_todo(self.empresa, self.usuario, "Origen")
        with self.assertRaises(ValidationError):
            create_task_from_todo(todo, self.otro_usuario, "Cruza", empresa=self.otra_empresa)

    def test_origen_canonico_no_admite_dos_origenes(self):
        todo = create_todo(self.empresa, self.usuario, "Origen")
        task = Tarea.objects.create(titulo="Tarea", empresa=self.empresa, creada_por=self.usuario)
        invalid = Tarea(
            titulo="Invalida",
            empresa=self.empresa,
            creada_por=self.usuario,
            todo_origen=todo,
            tarea_origen=task,
        )
        with self.assertRaises(ValidationError):
            invalid.full_clean()
        with self.assertRaises(IntegrityError):
            Tarea.objects.create(
                titulo="Invalida DB",
                empresa=self.empresa,
                creada_por=self.usuario,
                todo_origen=todo,
                tarea_origen=task,
            )


class _SQLiteCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, params=()):
        sql = sql.replace("INSERT IGNORE INTO", "INSERT OR IGNORE INTO")
        sql = sql.replace(" FOR UPDATE", "")
        sql = sql.replace("%s", "?")
        values = tuple(
            value.isoformat() if hasattr(value, "isoformat") else value
            for value in params
        )
        self.cursor.execute(sql, values)

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class _SQLiteOperationalConnection:
    def __init__(self):
        self.database = sqlite3.connect(":memory:", isolation_level=None)
        self.database.executescript(
            """
            CREATE TABLE tareas_correlativotodoempresa (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                empresa_id INTEGER UNIQUE,
                siguiente_numero INTEGER
            );
            CREATE TABLE tareas_todo (
                id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER, correlativo TEXT,
                titulo TEXT, descripcion TEXT, estado TEXT, creada_por_id INTEGER,
                fecha_creacion TEXT, cerrada_por_id INTEGER, fecha_cierre TEXT,
                comentario_cierre TEXT, todo_anterior_id INTEGER
            );
            CREATE TABLE tareas_todoevento (
                id INTEGER PRIMARY KEY AUTOINCREMENT, todo_id INTEGER, tipo TEXT,
                usuario_id INTEGER, timestamp TEXT, comentario TEXT, tarea_id INTEGER
            );
            CREATE TABLE tareas_tarea (
                id INTEGER PRIMARY KEY, todo_origen_id INTEGER, estado TEXT,
                anulada INTEGER
            );
            CREATE TABLE tareas_tarearelacion (
                id INTEGER PRIMARY KEY, padre_id INTEGER, hija_id INTEGER
            );
            """
        )

    def cursor(self):
        return _SQLiteCursor(self.database.cursor())

    def begin(self):
        self.database.execute("BEGIN")

    def commit(self):
        self.database.commit()

    def rollback(self):
        self.database.rollback()

    def close(self):
        self.database.close()


class TodoBackendParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        configure_task_storage()
        cls.company = Empresa.objects.create(
            codigo="T135G",
            descripcion="Todos connection parity",
        )
        cls.user = User.objects.create_user(username="todo-parity-user")
        cls.todo = Todo.objects.create(
            empresa=cls.company,
            creada_por=cls.user,
            correlativo="TD0000042",
            titulo="Default Todo content",
            descripcion="Default description",
        )

    def setUp(self):
        self.connection = _SQLiteOperationalConnection()
        self.addCleanup(self.connection.close)
        self.connection.database.execute(
            "INSERT INTO tareas_todo VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.todo.pk,
                self.company.pk,
                "TD0000099",
                "Operational Todo content",
                "Operational description",
                Todo.Estado.ABIERTO,
                self.user.pk,
                "2026-10-01T12:00:00+00:00",
                None,
                None,
                "",
                None,
            ),
        )
        self.connection_patch = patch.object(
            todo_storage,
            "open_mysql_connection",
            self.open_mysql_connection,
        )
        self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)

    @contextmanager
    def open_mysql_connection(self, *args, **kwargs):
        _ = (args, kwargs)
        yield self.connection

    @contextmanager
    def configured_mysql(self):
        source = {"type": "MYSQL_CONFIG", "database_name": "todos_test"}
        with patch.object(todo_storage, "get_tarea_connection", return_value=source):
            with patch.object(
                todo_storage,
                "get_tarea_mysql_connection",
                return_value=object(),
            ):
                yield

    def test_resolver_selects_configured_storage(self):
        with patch.object(
            todo_storage,
            "get_tarea_connection",
            return_value={"type": "DJANGO", "alias": "default"},
        ):
            self.assertIsInstance(resolve_todo_storage(), DjangoTodoStorage)
        with self.configured_mysql():
            self.assertIsInstance(resolve_todo_storage(), MySQLTodoStorage)

    def test_mysql_close_uses_same_pk_and_leaves_default_unchanged(self):
        with self.configured_mysql():
            result = close_todo(self.todo, self.user, "Operational close")

        self.assertIs(result, self.todo)
        self.assertEqual(result.estado, Todo.Estado.CERRADO)
        operational = self.connection.database.execute(
            "SELECT estado,cerrada_por_id,comentario_cierre "
            "FROM tareas_todo WHERE id=?",
            (self.todo.pk,),
        ).fetchone()
        self.assertEqual(
            operational,
            (Todo.Estado.CERRADO, self.user.pk, "Operational close"),
        )
        event = self.connection.database.execute(
            "SELECT todo_id,tipo,usuario_id,comentario "
            "FROM tareas_todoevento"
        ).fetchone()
        self.assertEqual(
            event,
            (
                self.todo.pk,
                TodoEvento.Tipo.CERRADO,
                self.user.pk,
                "Operational close",
            ),
        )
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.estado, Todo.Estado.ABIERTO)
        self.assertFalse(TodoEvento.objects.filter(todo=self.todo).exists())

    def test_mysql_create_writes_todo_and_created_event_to_configured_backend(self):
        default_count = Todo.objects.count()
        with self.configured_mysql():
            created = create_todo(
                self.company,
                self.user,
                "New operational Todo",
                "Created through BASE_TAREAS",
            )

        self.assertEqual(created.correlativo, "TD0000001")
        self.assertEqual(Todo.objects.count(), default_count)
        operational = self.connection.database.execute(
            "SELECT empresa_id,correlativo,titulo,descripcion,estado,creada_por_id "
            "FROM tareas_todo WHERE id=?",
            (created.pk,),
        ).fetchone()
        self.assertEqual(
            operational,
            (
                self.company.pk,
                "TD0000001",
                "New operational Todo",
                "Created through BASE_TAREAS",
                Todo.Estado.ABIERTO,
                self.user.pk,
            ),
        )
        event = self.connection.database.execute(
            "SELECT todo_id,tipo,usuario_id FROM tareas_todoevento"
        ).fetchone()
        self.assertEqual(
            event,
            (created.pk, TodoEvento.Tipo.CREADO, self.user.pk),
        )

    def test_mysql_close_uses_operational_originated_tasks_and_fails_closed(self):
        self.connection.database.execute(
            "INSERT INTO tareas_tarea VALUES (?,?,?,?)",
            (701, self.todo.pk, Tarea.Estado.ACTIVA, 0),
        )
        with self.configured_mysql():
            with self.assertRaisesMessage(
                ValidationError,
                "No se puede cerrar un TO-DO con Tareas originadas pendientes.",
            ):
                close_todo(self.todo, self.user)
        operational_state = self.connection.database.execute(
            "SELECT estado FROM tareas_todo WHERE id=?",
            (self.todo.pk,),
        ).fetchone()[0]
        self.assertEqual(operational_state, Todo.Estado.ABIERTO)

        self.connection.database.execute(
            "DELETE FROM tareas_tarea WHERE id=701"
        )
        self.connection.database.execute(
            "DELETE FROM tareas_todo WHERE id=?",
            (self.todo.pk,),
        )
        self.todo.refresh_from_db()
        with self.configured_mysql():
            with self.assertRaises(Todo.DoesNotExist):
                close_todo(self.todo, self.user)
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.estado, Todo.Estado.ABIERTO)

    def test_mysql_close_ignores_tasks_annulled_through_their_parent(self):
        self.connection.database.execute(
            "INSERT INTO tareas_tarea VALUES (?,?,?,?)",
            (700, None, Tarea.Estado.ACTIVA, 1),
        )
        self.connection.database.execute(
            "INSERT INTO tareas_tarea VALUES (?,?,?,?)",
            (701, self.todo.pk, Tarea.Estado.ACTIVA, 0),
        )
        self.connection.database.execute(
            "INSERT INTO tareas_tarearelacion VALUES (?,?,?)",
            (1, 700, 701),
        )

        with self.configured_mysql():
            close_todo(self.todo, self.user)

        state = self.connection.database.execute(
            "SELECT estado FROM tareas_todo WHERE id=?",
            (self.todo.pk,),
        ).fetchone()[0]
        self.assertEqual(state, Todo.Estado.CERRADO)

    def test_mysql_close_does_not_persist_an_unsaved_todo(self):
        unsaved = Todo(
            empresa=self.company,
            creada_por=self.user,
            titulo="Unsaved Todo",
        )
        with self.configured_mysql():
            with self.assertRaises(ValueError):
                close_todo(unsaved, self.user)
        count = self.connection.database.execute(
            "SELECT COUNT(*) FROM tareas_todo"
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_missing_connection_role_fails_closed(self):
        with patch.object(
            todo_storage,
            "get_tarea_connection",
            side_effect=TareaConnectionRoleNotFoundError("missing"),
        ):
            with self.assertRaises(TodoStorageError):
                close_todo(self.todo, self.user)