from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from access_control.models import Empresa
from tareas.models import Tarea
from tareas.services.task_storage import MySQLTaskStorage, TaskStorageError


class MySQLLifecycleStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="134L", descripcion="Lifecycle")
        cls.connection = MagicMock()

    def _connection(self, task_row, *, candidate=False, rowcount=1):
        connection = MagicMock()
        cursor = MagicMock()
        cursor.rowcount = rowcount
        cursor.lastrowid = 9
        cursor.fetchone.side_effect = [task_row, task_row]
        cursor.fetchall.return_value = [(1,)] if candidate else []
        connection.cursor.return_value = cursor
        return connection, cursor

    def _task_row(self, state="BORRADOR", correlativo="B0000003"):
        return (3, self.empresa.pk, correlativo, 0, state, 2, "2026-12-31", None)

    @patch("tareas.services.task_storage.get_valid_users_for_empresa")
    @patch("tareas.services.task_storage.open_mysql_connection")
    def test_publish_mysql_locks_updates_and_inserts_transition(self, open_connection, valid_users):
        valid_users.return_value.filter.return_value.exists.return_value = True
        connection, cursor = self._connection(self._task_row())
        open_connection.return_value = nullcontext(connection)

        result = MySQLTaskStorage(self.connection, "tareas").publish_task(
            task_id=3,
            empresa_id=self.empresa.pk,
            actor_id=2,
        )

        sql = " ".join(call.args[0] for call in cursor.execute.call_args_list)
        self.assertIn("FOR UPDATE", sql)
        self.assertIn("UPDATE tareas_tarea", sql)
        self.assertIn("INSERT INTO tareas_tareatransicion", sql)
        self.assertIn("empresa_id=%s", sql)
        self.assertEqual(result.state, Tarea.Estado.ACTIVA)
        self.assertEqual(result.correlativo, "A0000003")
        connection.commit.assert_called_once()

    @patch("tareas.services.task_storage.open_mysql_connection")
    def test_enter_management_mysql_locks_updates_and_inserts_transition(self, open_connection):
        connection, cursor = self._connection(self._task_row(state=Tarea.Estado.ACTIVA))
        cursor.fetchone.side_effect = None
        cursor.fetchone.return_value = self._task_row(state=Tarea.Estado.ACTIVA)[:5]
        open_connection.return_value = nullcontext(connection)

        result = MySQLTaskStorage(self.connection, "tareas").enter_management(
            task_id=3,
            empresa_id=self.empresa.pk,
            actor_id=2,
        )

        self.assertEqual(result.state, Tarea.Estado.GESTION)
        self.assertTrue(any("FOR UPDATE" in call.args[0] for call in cursor.execute.call_args_list))
        self.assertTrue(any("INICIAR_GESTION" in call.args[1] for call in cursor.execute.call_args_list if len(call.args) > 1))
        connection.commit.assert_called_once()

    @patch("tareas.services.task_storage.open_mysql_connection")
    def test_management_invalid_state_rolls_back_without_write(self, open_connection):
        connection, cursor = self._connection(self._task_row(state=Tarea.Estado.GESTION))
        cursor.fetchone.side_effect = None
        cursor.fetchone.return_value = self._task_row(state=Tarea.Estado.GESTION)[:5]
        open_connection.return_value = nullcontext(connection)

        with self.assertRaises(ValidationError):
            MySQLTaskStorage(self.connection, "tareas").enter_management(
                task_id=3,
                empresa_id=self.empresa.pk,
                actor_id=2,
            )

        connection.rollback.assert_called_once()
        self.assertFalse(any("UPDATE tareas_tarea" in call.args[0] for call in cursor.execute.call_args_list))
        self.assertFalse(connection.commit.called)

    @patch("tareas.services.task_storage.get_valid_users_for_empresa")
    @patch("tareas.services.task_storage.open_mysql_connection")
    def test_publish_similarity_boundary_is_controlled(self, open_connection, valid_users):
        valid_users.return_value.filter.return_value.exists.return_value = True
        connection, cursor = self._connection(self._task_row(), candidate=True)
        open_connection.return_value = nullcontext(connection)

        with self.assertRaises(TaskStorageError):
            MySQLTaskStorage(self.connection, "tareas").publish_task(
                task_id=3,
                empresa_id=self.empresa.pk,
                actor_id=2,
            )

        self.assertFalse(connection.commit.called)
