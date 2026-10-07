from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from contextlib import contextmanager
import sqlite3
from unittest.mock import patch

from access_control.models import Empresa
from tareas.models import Tarea, Todo, TodoEvento
from tareas.services.origin import create_task_from_todo
from tareas.services import origin_storage
from tareas.services.connection_roles import BackendContext


class _OriginSQLiteConnection:
    def __init__(self):
        self.database = sqlite3.connect(":memory:", isolation_level=None)
        self.database.executescript(
            """
            CREATE TABLE tareas_correlativoempresa (empresa_id INTEGER UNIQUE, siguiente_numero INTEGER);
            CREATE TABLE tareas_tarea (
                id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT, descripcion TEXT,
                prioridad TEXT, correlativo TEXT, anulada INTEGER,
                fechas_pendientes_confirmacion INTEGER, cierre_completado INTEGER,
                requiere_evidencia_cierre INTEGER, estado TEXT, responsable_id INTEGER,
                empresa_id INTEGER, tipo_ambito TEXT, local_id INTEGER,
                departamento_id INTEGER, creada_por_id INTEGER, fecha_creacion TEXT,
                fecha_publicacion TEXT, fecha_asignacion TEXT, fecha_tope TEXT,
                fecha_cumplimiento TEXT, todo_origen_id INTEGER, tarea_origen_id INTEGER
            );
            CREATE TABLE tareas_todoevento (
                id INTEGER PRIMARY KEY AUTOINCREMENT, todo_id INTEGER, tipo TEXT,
                usuario_id INTEGER, timestamp TEXT, comentario TEXT, tarea_id INTEGER
            );
            """
        )

    def cursor(self):
        return _OriginSQLiteCursor(self.database.cursor())

    def begin(self):
        self.database.execute("BEGIN")

    def commit(self):
        self.database.commit()

    def rollback(self):
        self.database.rollback()


class _OriginSQLiteCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, params=()):
        if "correlativoempresa" in sql:
            sql = sql.replace("INSERT INTO", "INSERT OR IGNORE INTO")
            sql = sql.replace(" ON DUPLICATE KEY UPDATE empresa_id = empresa_id", "")
        sql = sql.replace(" FOR UPDATE", "").replace("%s", "?")
        self.cursor.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class OriginDomainTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="OR1", descripcion="Empresa origen")
        self.user = User.objects.create_user(username="origin_user", password="x")

    def test_tarea_a_tarea_sigue_permitiendo_cadena_directa(self):
        source = Tarea.objects.create(
            titulo="Origen",
            empresa=self.empresa,
            creada_por=self.user,
        )
        derived = Tarea.objects.create(
            titulo="Derivada",
            empresa=self.empresa,
            creada_por=self.user,
            tarea_origen=source,
        )
        self.assertEqual(derived.tarea_origen, source)
        self.assertIsNone(derived.todo_origen)

    def test_task_from_todo_no_acepta_origen_tarea(self):
        todo = Todo.objects.create(
            empresa=self.empresa,
            creada_por=self.user,
            titulo="Pendiente",
        )
        source = Tarea.objects.create(
            titulo="Origen",
            empresa=self.empresa,
            creada_por=self.user,
        )
        with self.assertRaises(ValidationError):
            create_task_from_todo(
                todo,
                self.user,
                "Invalida",
                tarea_origen=source,
            )

    def test_mysql_config_writes_task_and_event_to_configured_backend(self):
        connection = _OriginSQLiteConnection()
        self.addCleanup(connection.database.close)
        with connection.database:
            pass
        with patch.object(
            origin_storage,
            "resolve_operational_backend",
            return_value=BackendContext(
                logical_role="BASE_TAREAS",
                backend_type="MYSQL_CONFIG",
                mysql_connection=object(),
                database_name="origin_test",
            ),
        ), patch.object(
            origin_storage,
            "open_mysql_connection",
            return_value=_OriginConnectionContext(connection),
        ):
            todo = Todo.objects.create(
                empresa=self.empresa, creada_por=self.user, titulo="Origen operativo",
            )
            task = create_task_from_todo(todo, self.user, "Derivada MYSQL")

        self.assertEqual(task.todo_origen_id, todo.pk)
        row = connection.database.execute(
            "SELECT id, todo_origen_id, titulo FROM tareas_tarea WHERE id=?",
            (task.pk,),
        ).fetchone()
        event = connection.database.execute(
            "SELECT todo_id, tipo, tarea_id FROM tareas_todoevento"
        ).fetchone()
        self.assertEqual(row[1:], (todo.pk, "Derivada MYSQL"))
        self.assertEqual(event, (todo.pk, TodoEvento.Tipo.TAREA_CREADA, task.pk))
        self.assertFalse(Tarea.objects.filter(pk=task.pk).exists())


class _OriginConnectionContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc_value, traceback):
        return False