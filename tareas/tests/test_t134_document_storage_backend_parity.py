from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.core.exceptions import ValidationError

from access_control.models import Empresa
from tareas.services.document_storage import (
    DocumentCreateCommand,
    DjangoDocumentStorage,
    EvidenceCreateCommand,
    MySQLDocumentStorage,
    resolve_document_storage,
)
from tareas.services.connection_roles import TareaConnectionError
from tareas.services.task_storage import TaskStorageError


class DocumentStorageBackendParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="135DOC", descripcion="Documents")
        cls.connection = MagicMock()

    def _connection(self, *, document_id=9, evidence_id=10):
        connection = MagicMock()
        cursor = MagicMock()
        cursor.lastrowid = document_id
        cursor.fetchone.return_value = (3, self.empresa.pk, False)
        connection.cursor.return_value = cursor
        return connection, cursor

    def test_django_alias_storage_type_is_explicit(self):
        storage = DjangoDocumentStorage("default")
        self.assertEqual(storage.alias, "default")

    @patch("tareas.services.document_storage.get_valid_users_for_empresa")
    @patch("tareas.services.document_storage.open_mysql_connection")
    def test_mysql_document_create_history_and_same_pk_scope(self, open_connection, valid_users):
        valid_users.return_value.filter.return_value.exists.return_value = True
        connection, cursor = self._connection()
        open_connection.return_value = nullcontext(connection)
        result = MySQLDocumentStorage(self.connection, "tareas").create_document(
            DocumentCreateCommand(
                tarea_id=3,
                empresa_id=self.empresa.pk,
                usuario_id=2,
                tipo="INFORME",
                formato_archivo="PDF",
                url="https://example.test/document.pdf",
            )
        )

        self.assertEqual(result, 9)
        calls = cursor.execute.call_args_list
        self.assertIn("INSERT INTO tareas_documentotarea", calls[1].args[0])
        self.assertIn("INSERT INTO tareas_documentohistorial", calls[2].args[0])
        self.assertIn("empresa_id=%s", calls[0].args[0])
        self.assertEqual(calls[0].args[1], (3, self.empresa.pk))
        connection.commit.assert_called_once()

    @patch("tareas.services.document_storage.get_valid_users_for_empresa")
    @patch("tareas.services.document_storage.open_mysql_connection")
    def test_mysql_evidence_create_is_parameterized_and_transactional(self, open_connection, valid_users):
        valid_users.return_value.filter.return_value.exists.return_value = True
        connection, cursor = self._connection(evidence_id=11)
        open_connection.return_value = nullcontext(connection)
        result = MySQLDocumentStorage(self.connection, "tareas").register_evidence(
            EvidenceCreateCommand(
                tarea_id=3,
                empresa_id=self.empresa.pk,
                usuario_id=2,
                formato_archivo="PDF",
                url="https://example.test/evidence.pdf",
            )
        )

        self.assertEqual(result, 9)
        evidence_call = next(call for call in cursor.execute.call_args_list if "INSERT INTO tareas_evidenciacierre" in call.args[0])
        self.assertIn("%s", evidence_call.args[0])
        self.assertIn("empresa_id=%s", cursor.execute.call_args_list[0].args[0])
        connection.commit.assert_called_once()

    @patch("tareas.services.document_storage.resolve_operational_backend", side_effect=TareaConnectionError("missing role"))
    def test_missing_role_fails_closed(self, _resolver):
        with self.assertRaises(TaskStorageError):
            resolve_document_storage()
