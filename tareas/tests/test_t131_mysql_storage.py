from contextlib import nullcontext
from datetime import date
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from settings.models import SettingsMySQLConnection
from tareas.models import Tarea, TareaConnectionRole
from tareas.services.task_storage import (
    CreateTaskDraftInput,
    CreatedTaskResult,
    MySQLTaskStorage,
    create_task_draft,
)


class MySQLTaskStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="131M", descripcion="Empresa")
        cls.catalog = Empresa.objects.create(codigo="00", descripcion="Catálogo")
        cls.user = User.objects.create_user(username="t131-mysql", password="pass")
        cls.responsible = User.objects.create_user(
            username="t131-mysql-responsible", password="pass"
        )
        cls.vista = Vista.objects.create(nombre="Tareas")
        for user in (cls.user, cls.responsible):
            Permiso.objects.create(
                usuario=user,
                empresa=cls.empresa,
                vista=cls.vista,
                ingresar=True,
                crear=user == cls.user,
            )
        cls.connection = SettingsMySQLConnection.objects.create(
            empresa=cls.catalog,
            nombre_logico="mysqldjango",
            host="mysql.example.test",
            user="mysql-user",
            password="mysql-password",
            db_name="system",
            is_active=True,
        )
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS",
            source_type="MYSQL_CONFIG",
            mysql_connection=cls.connection,
            database_name="tareas",
        )

    def _input(self, responsable_id=None):
        return CreateTaskDraftInput(
            titulo="Título con %s y 'comillas'",
            descripcion="Descripción",
            prioridad=Tarea.Prioridad.NORMAL,
            responsable_id=responsable_id,
            fecha_tope=date(2026, 10, 20),
        )

    def _connection(self, *, existing_number=1, insert_fails=False):
        connection = MagicMock(name="mysql_connection")
        cursor = MagicMock(name="mysql_cursor")
        cursor.fetchone.return_value = (
            None if existing_number is None else (existing_number,)
        )
        cursor.lastrowid = 812
        if insert_fails:
            cursor.execute.side_effect = [None, None, None, RuntimeError("insert failed")]
        connection.cursor.return_value = cursor
        return connection, cursor

    @patch("tareas.services.task_storage.open_mysql_connection")
    def test_creates_mysql_draft_with_one_commit_and_parameterized_sql(self, open_connection):
        connection, cursor = self._connection(existing_number=7)
        open_connection.return_value = nullcontext(connection)
        storage = MySQLTaskStorage(self.connection, "tareas")

        result = storage.create_draft(
            self._input(),
            empresa_id=self.empresa.pk,
            creador_id=self.user.pk,
        )

        self.assertIsInstance(result, CreatedTaskResult)
        self.assertEqual(result.id, 812)
        self.assertEqual(result.correlativo, "B0000007")
        self.assertIsNone(result.responsable_id)
        self.assertEqual(result.estado, Tarea.Estado.BORRADOR)
        open_connection.assert_called_once_with(self.connection, database_name="tareas")
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        insert_calls = [call for call in cursor.execute.call_args_list if "INSERT INTO tareas_tarea" in call.args[0]]
        self.assertEqual(len(insert_calls), 1)
        self.assertNotIn(self._input().titulo, insert_calls[0].args[0])
        self.assertIn(self._input().titulo, insert_calls[0].args[1])
        self.assertEqual(insert_calls[0].args[1][10], self.empresa.pk)

    @patch("tareas.services.task_storage.open_mysql_connection")
    def test_existing_sequence_is_locked_and_incremented(self, open_connection):
        connection, cursor = self._connection(existing_number=12)
        open_connection.return_value = nullcontext(connection)

        MySQLTaskStorage(self.connection, "tareas").create_draft(
            self._input(responsable_id=self.responsible.pk),
            empresa_id=self.empresa.pk,
            creador_id=self.user.pk,
        )

        select_calls = [call for call in cursor.execute.call_args_list if "FOR UPDATE" in call.args[0]]
        update_calls = [call for call in cursor.execute.call_args_list if "siguiente_numero =" in call.args[0]]
        self.assertEqual(select_calls[0].args[1], (self.empresa.pk,))
        self.assertEqual(update_calls[0].args[1], (13, self.empresa.pk))

    @patch("tareas.services.task_storage.open_mysql_connection")
    def test_missing_sequence_initializes_first_number(self, open_connection):
        connection, cursor = self._connection(existing_number=1)
        open_connection.return_value = nullcontext(connection)

        result = MySQLTaskStorage(self.connection, "tareas").create_draft(
            self._input(),
            empresa_id=self.empresa.pk,
            creador_id=self.user.pk,
        )

        self.assertEqual(result.correlativo, "B0000001")
        sequence_insert = cursor.execute.call_args_list[0]
        self.assertIn("ON DUPLICATE KEY UPDATE", sequence_insert.args[0])

    @patch("tareas.services.task_storage.open_mysql_connection")
    def test_insert_failure_rolls_back_and_does_not_commit(self, open_connection):
        connection, cursor = self._connection(insert_fails=True)
        open_connection.return_value = nullcontext(connection)

        with self.assertRaises(Exception):
            MySQLTaskStorage(self.connection, "tareas").create_draft(
                self._input(),
                empresa_id=self.empresa.pk,
                creador_id=self.user.pk,
            )

        connection.rollback.assert_called_once_with()
        connection.commit.assert_not_called()

    @patch("tareas.services.task_storage.open_mysql_connection")
    def test_mysql_create_does_not_use_django_storage_or_fallback(self, open_connection):
        connection, cursor = self._connection()
        open_connection.return_value = nullcontext(connection)
        with patch("tareas.services.task_storage.DjangoTaskStorage.create_draft") as django_create:
            result = create_task_draft(
                self._input(),
                active_company=self.empresa,
                actor=self.user,
            )

        django_create.assert_not_called()
        self.assertEqual(result.id, 812)
        self.assertFalse(Tarea.objects.exists())

    @patch("tareas.services.notifications.notify_task_event", side_effect=RuntimeError("notify"))
    @patch("tareas.services.task_storage.open_mysql_connection")
    def test_notification_failure_does_not_rollback_committed_mysql_write(
        self, open_connection, _notify
    ):
        connection, _cursor = self._connection()
        open_connection.return_value = nullcontext(connection)

        result = create_task_draft(
            self._input(responsable_id=self.responsible.pk),
            active_company=self.empresa,
            actor=self.user,
        )

        self.assertEqual(result.id, 812)
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
