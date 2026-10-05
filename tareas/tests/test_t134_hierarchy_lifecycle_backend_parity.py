from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.test import TestCase

from access_control.models import Empresa
from tareas.models import Tarea
from tareas.services.hierarchy_lifecycle_storage import (
    HierarchyLifecycleCommand,
    MySQLHierarchyLifecycleStorage,
)


class MySQLHierarchyLifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="134D", descripcion="Hierarchy")
        cls.connection = MagicMock()

    def _connection(self, annulled=False, state=Tarea.Estado.GESTION, rowcount=1):
        connection = MagicMock()
        cursor = MagicMock()
        cursor.lastrowid = 8
        cursor.rowcount = rowcount
        cursor.fetchone.return_value = (3, self.empresa.pk, state, int(annulled), 1, 2)
        connection.cursor.return_value = cursor
        return connection, cursor

    @patch("tareas.services.hierarchy_lifecycle_storage.open_mysql_connection")
    def test_annul_changes_only_target_and_records_transition(self, open_connection):
        connection, cursor = self._connection()
        open_connection.return_value = nullcontext(connection)

        result = MySQLHierarchyLifecycleStorage(self.connection, "tareas").annul(
            HierarchyLifecycleCommand(3, self.empresa.pk, 2, "Pausa")
        )

        self.assertTrue(result.anulada)
        update_call = next(call for call in cursor.execute.call_args_list if "UPDATE tareas_tarea" in call.args[0])
        self.assertIn("WHERE id=%s AND empresa_id=%s", update_call.args[0])
        self.assertNotIn("descend", update_call.args[0].lower())
        self.assertTrue(any("ANULAR" in call.args[1] for call in cursor.execute.call_args_list if len(call.args) > 1))
        connection.commit.assert_called_once()

    @patch("tareas.services.hierarchy_lifecycle_storage.open_mysql_connection")
    def test_reactivate_preserves_direct_descendant_annulment_contract(self, open_connection):
        connection, cursor = self._connection(annulled=True)
        open_connection.return_value = nullcontext(connection)

        result = MySQLHierarchyLifecycleStorage(self.connection, "tareas").reactivate(
            HierarchyLifecycleCommand(3, self.empresa.pk, 2, "Reanudar")
        )

        self.assertFalse(result.anulada)
        updates = [call.args[0].lower() for call in cursor.execute.call_args_list if "update tareas_tarea" in call.args[0].lower()]
        self.assertEqual(len(updates), 1)
        self.assertNotIn("descendiente", updates[0])
        self.assertTrue(any("REACTIVAR" in call.args[1] for call in cursor.execute.call_args_list if len(call.args) > 1))

    @patch("tareas.services.hierarchy_lifecycle_storage.open_mysql_connection")
    def test_annul_invalid_borrador_rolls_back(self, open_connection):
        connection, cursor = self._connection(state=Tarea.Estado.BORRADOR)
        open_connection.return_value = nullcontext(connection)

        with self.assertRaises(ValidationError):
            MySQLHierarchyLifecycleStorage(self.connection, "tareas").annul(
                HierarchyLifecycleCommand(3, self.empresa.pk, 2)
            )

        connection.rollback.assert_called_once()
        self.assertFalse(connection.commit.called)
        self.assertFalse(any("UPDATE tareas_tarea" in call.args[0] for call in cursor.execute.call_args_list))

    @patch("tareas.services.hierarchy_lifecycle_storage.open_mysql_connection")
    def test_reactivate_requires_direct_annulment(self, open_connection):
        connection, cursor = self._connection(annulled=False)
        open_connection.return_value = nullcontext(connection)

        with self.assertRaises(ValidationError):
            MySQLHierarchyLifecycleStorage(self.connection, "tareas").reactivate(
                HierarchyLifecycleCommand(3, self.empresa.pk, 2)
            )

        connection.rollback.assert_called_once()
        self.assertFalse(connection.commit.called)
