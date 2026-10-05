from contextlib import nullcontext
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from settings.models import SettingsMySQLConnection
from tareas.models import Tarea
from tareas.services.task_storage import (
    MySQLTaskListStorage,
    TaskListFilters,
    TaskListResult,
)


class MySQLTaskListStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="132M", descripcion="Empresa")
        cls.catalog = Empresa.objects.create(codigo="00", descripcion="Catálogo")
        cls.creator = User.objects.create_user(username="t132-list-creator", password="pass")
        cls.responsible = User.objects.create_user(
            username="francisca-list", password="pass"
        )
        cls.participant = User.objects.create_user(
            username="t132-list-participant", password="pass"
        )
        cls.vista = Vista.objects.create(nombre="Tareas")
        for user in (cls.creator, cls.responsible, cls.participant):
            Permiso.objects.create(
                usuario=user,
                empresa=cls.empresa,
                vista=cls.vista,
                ingresar=True,
            )
        cls.connection = SettingsMySQLConnection.objects.create(
            empresa=cls.catalog,
            nombre_logico="mysql-list-real",
            host="mysql.example.test",
            user="user",
            password="secret",
            db_name="system",
            is_active=True,
        )

    def _storage(self):
        return MySQLTaskListStorage(self.connection, "tareas")

    def _connection(self, task_rows=None, participant_rows=None):
        connection = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
        cursor = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
        task_rows = task_rows or []
        participant_rows = participant_rows or []
        def execute(sql, params=()):
            cursor._last_sql = sql
            if "SELECT COUNT(*)" in sql:
                cursor._result = [(1, 0, 1, 0)]
            elif "FROM tareas_tareaparticipante" in sql:
                cursor._result = participant_rows
            elif "SELECT id, empresa_id" in sql:
                cursor._result = task_rows
            else:
                cursor._result = []
        cursor.execute.side_effect = execute
        cursor.fetchall.side_effect = lambda: cursor._result
        cursor.fetchone.side_effect = lambda: cursor._result[0] if cursor._result else None
        connection.cursor.return_value = cursor
        return connection, cursor

    @patch("tareas.services.task_storage.open_mysql_connection")
    def test_returns_task_list_result_with_summary_and_bulk_participants(self, open_connection):
        task_rows = [
            (
                3,
                self.empresa.pk,
                self.creator.pk,
                self.responsible.pk,
                "B0000003",
                "MYSQL CON RESPONSABLE",
                "NORMAL",
                "BORRADOR",
                "2026-10-31",
                "2026-10-05",
            )
        ]
        participant_rows = [(3, self.participant.pk, "INVITADO_OBSERVADOR")]
        connection, cursor = self._connection(task_rows, participant_rows)
        open_connection.return_value = nullcontext(connection)

        result = self._storage().list_tasks(
            empresa_id=self.empresa.pk,
            filters=TaskListFilters(),
        )

        self.assertIsInstance(result, TaskListResult)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].id, 3)
        self.assertEqual(result.items[0].correlativo, "B0000003")
        self.assertEqual(result.items[0].responsable_username, self.responsible.username)
        self.assertEqual(result.items[0].participantes_restantes, 0)
        self.assertEqual(result.summary["total"], 1)
        self.assertEqual(result.summary["gestion"], 1)
        self.assertTrue(any("empresa_id = %s" in call.args[0] for call in cursor.execute.call_args_list))
        open_connection.assert_called_once_with(self.connection, database_name="tareas")

    @patch("tareas.services.task_storage.open_mysql_connection")
    def test_responsible_username_search_uses_external_ids_without_join(self, open_connection):
        connection, cursor = self._connection(
            task_rows=[
                (3, self.empresa.pk, self.creator.pk, self.responsible.pk, "B0000003", "Task", "NORMAL", "BORRADOR", "2026-10-31", "2026-10-05")
            ]
        )
        open_connection.return_value = nullcontext(connection)

        self._storage().list_tasks(
            empresa_id=self.empresa.pk,
            filters=TaskListFilters(search="francisca-list"),
        )

        task_calls = [call for call in cursor.execute.call_args_list if "SELECT id, empresa_id" in call.args[0]]
        self.assertEqual(len(task_calls), 1)
        self.assertIn("responsable_id IN", task_calls[0].args[0])
        self.assertIn(self.responsible.pk, task_calls[0].args[1])
        self.assertNotIn("auth_user", task_calls[0].args[0].lower())

    @patch("tareas.services.task_storage.open_mysql_connection")
    def test_empty_result_does_not_issue_invalid_participant_in_query(self, open_connection):
        connection, cursor = self._connection()
        open_connection.return_value = nullcontext(connection)

        result = self._storage().list_tasks(
            empresa_id=self.empresa.pk,
            filters=TaskListFilters(),
        )

        self.assertEqual(result.items, ())
        self.assertFalse(any("tareas_tareaparticipante" in call.args[0] for call in cursor.execute.call_args_list))
