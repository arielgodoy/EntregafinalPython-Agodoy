from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.core.exceptions import ValidationError

from access_control.models import Empresa
from tareas.models import Tarea
from tareas.services.closure_storage import ClosureCommand, MySQLClosureStorage


class MySQLClosureStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="134C", descripcion="Closure")
        cls.connection = MagicMock()

    def _connection(self, state, *, evidence=False, pending_mini=False, open_child=False, requires_evidence=False, quotation_minimum=None):
        connection = MagicMock()
        cursor = MagicMock()
        cursor.lastrowid = 7
        task_row = (3, self.empresa.pk, state, 0, 0, None, int(requires_evidence), 2, 1)

        def execute(sql, params=()):
            lower = sql.lower()
            cursor._sql = sql
            if "select id, empresa_id, estado" in lower:
                cursor._result = [task_row]
            elif "count(*) from tareas_minitarea" in lower:
                cursor._result = [(1 if pending_mini else 0,)]
            elif "select r.hija_id" in lower:
                cursor._result = [(9, Tarea.Estado.GESTION, 0)] if open_child else []
            elif "from tareas_evidenciacierre" in lower:
                cursor._result = [("PDF", "file.pdf", "")] if evidence else []
            elif "select r.minimo_cotizaciones" in lower:
                cursor._result = [(quotation_minimum,)] if quotation_minimum is not None else []
            elif "select count(distinct c.proveedor_id)" in lower:
                cursor._result = [(0,)]
            else:
                cursor._result = []

        cursor.execute.side_effect = execute
        cursor.fetchone.side_effect = lambda: cursor._result[0] if cursor._result else None
        cursor.fetchall.side_effect = lambda: cursor._result
        connection.cursor.return_value = cursor
        return connection, cursor

    @patch("tareas.services.closure_storage.open_mysql_connection")
    def test_complete_mysql_writes_pending_transition(self, open_connection):
        connection, cursor = self._connection(Tarea.Estado.GESTION)
        open_connection.return_value = nullcontext(connection)

        result = MySQLClosureStorage(self.connection, "tareas").complete(
            ClosureCommand(3, self.empresa.pk, 2)
        )

        self.assertEqual(result.state, Tarea.Estado.PENDIENTE_APROBACION_CIERRE)
        self.assertTrue(any("MARCAR_100" in call.args[1] for call in cursor.execute.call_args_list if len(call.args) > 1))
        connection.commit.assert_called_once()

    @patch("tareas.services.closure_storage.open_mysql_connection")
    def test_approve_mysql_checks_blockers_and_writes_closure(self, open_connection):
        connection, cursor = self._connection(Tarea.Estado.PENDIENTE_APROBACION_CIERRE, evidence=True)
        open_connection.return_value = nullcontext(connection)

        result = MySQLClosureStorage(self.connection, "tareas").approve(
            ClosureCommand(3, self.empresa.pk, 2, "Aprobado")
        )

        self.assertEqual(result.state, Tarea.Estado.CERRADA)
        self.assertTrue(any("APROBAR_CIERRE" in call.args[1] for call in cursor.execute.call_args_list if len(call.args) > 1))
        self.assertTrue(any("TAREAS_TAREACIERRE" in call.args[0].upper() for call in cursor.execute.call_args_list))
        connection.commit.assert_called_once()

    @patch("tareas.services.closure_storage.open_mysql_connection")
    def test_approve_pending_minitask_rolls_back_without_writes(self, open_connection):
        connection, cursor = self._connection(Tarea.Estado.PENDIENTE_APROBACION_CIERRE, pending_mini=True)
        open_connection.return_value = nullcontext(connection)

        with self.assertRaises(ValidationError):
            MySQLClosureStorage(self.connection, "tareas").approve(
                ClosureCommand(3, self.empresa.pk, 2)
            )

        connection.rollback.assert_called_once()
        self.assertFalse(any("UPDATE tareas_tarea" in call.args[0] for call in cursor.execute.call_args_list))
        self.assertFalse(connection.commit.called)

    @patch("tareas.services.closure_storage.open_mysql_connection")
    def test_mysql_approve_blocks_open_descendant(self, open_connection):
        connection, cursor = self._connection(
            Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
            open_child=True,
        )
        open_connection.return_value = nullcontext(connection)

        with self.assertRaises(ValidationError) as error:
            MySQLClosureStorage(self.connection, "tareas").approve(
                ClosureCommand(3, self.empresa.pk, 2)
            )

        self.assertIn("DESCENDANTS_PENDING", str(error.exception))
        connection.rollback.assert_called_once()
        self.assertFalse(any("UPDATE tareas_tarea" in call.args[0] for call in cursor.execute.call_args_list))
        self.assertFalse(any("TAREAS_TAREACIERRE" in call.args[0].upper() for call in cursor.execute.call_args_list))

    @patch("tareas.services.closure_storage.open_mysql_connection")
    def test_mysql_approve_blocks_missing_required_evidence(self, open_connection):
        connection, cursor = self._connection(
            Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
            requires_evidence=True,
            evidence=False,
        )
        open_connection.return_value = nullcontext(connection)

        with self.assertRaises(ValidationError) as error:
            MySQLClosureStorage(self.connection, "tareas").approve(
                ClosureCommand(3, self.empresa.pk, 2)
            )

        self.assertIn("CLOSURE_EVIDENCE_REQUIRED", str(error.exception))
        connection.rollback.assert_called_once()
        self.assertFalse(any("UPDATE tareas_tarea" in call.args[0] for call in cursor.execute.call_args_list))
        self.assertFalse(any("TAREAS_TAREACIERRE" in call.args[0].upper() for call in cursor.execute.call_args_list))

    @patch("tareas.services.closure_storage.open_mysql_connection")
    def test_mysql_approve_blocks_insufficient_quotations(self, open_connection):
        connection, cursor = self._connection(
            Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
            quotation_minimum=2,
        )
        open_connection.return_value = nullcontext(connection)

        with self.assertRaises(ValidationError) as error:
            MySQLClosureStorage(self.connection, "tareas").approve(
                ClosureCommand(3, self.empresa.pk, 2)
            )

        self.assertIn("QUOTATION_MINIMUM_NOT_MET", str(error.exception))
        connection.rollback.assert_called_once()
        self.assertFalse(any("UPDATE tareas_tarea" in call.args[0] for call in cursor.execute.call_args_list))
        self.assertFalse(any("TAREAS_TAREACIERRE" in call.args[0].upper() for call in cursor.execute.call_args_list))

    @patch("tareas.services.closure_storage.open_mysql_connection")
    def test_reject_mysql_clears_completion_and_records_rejection(self, open_connection):
        connection, cursor = self._connection(Tarea.Estado.PENDIENTE_APROBACION_CIERRE)
        open_connection.return_value = nullcontext(connection)

        result = MySQLClosureStorage(self.connection, "tareas").reject(
            ClosureCommand(3, self.empresa.pk, 2, "Falta información")
        )

        self.assertEqual(result.state, Tarea.Estado.GESTION)
        self.assertTrue(any("RECHAZAR_CIERRE" in call.args[1] for call in cursor.execute.call_args_list if len(call.args) > 1))
        self.assertTrue(any("TAREAS_TAREACIERRE" in call.args[0].upper() for call in cursor.execute.call_args_list))
        connection.commit.assert_called_once()
