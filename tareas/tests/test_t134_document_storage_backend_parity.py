from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import connections

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
from tareas.services.task_mutation_locks import lock_orm_task_rows
from tareas.tests.factories import create_tarea


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
        cursor.fetchall.return_value = ((3,),)
        connection.cursor.return_value = cursor
        return connection, cursor

    def test_django_alias_storage_type_is_explicit(self):
        storage = DjangoDocumentStorage("default")
        self.assertEqual(storage.alias, "default")

    def test_django_task_update_locks_and_revalidates_inside_transaction(self):
        actor = User.objects.create_user(username="document-lock-actor")
        task = create_tarea(
            self.empresa,
            actor,
            titulo="Tarea con lock documental",
            correlativo="D1350001",
        )
        storage = DjangoDocumentStorage("default")
        observations = {}

        def lock_and_observe(alias, empresa_id, task_ids=None, **kwargs):
            observations["in_transaction"] = connections[alias].in_atomic_block
            observations["empresa_id"] = empresa_id
            observations["task_ids"] = tuple(task_ids)
            return lock_orm_task_rows(alias, empresa_id, task_ids, **kwargs)

        with patch.object(storage, "_actor"):
            with patch(
                "tareas.services.document_storage.lock_orm_task_rows",
                side_effect=lock_and_observe,
            ):
                storage.configure_evidence(
                    task_id=task.pk,
                    empresa_id=self.empresa.pk,
                    usuario_id=actor.pk,
                    required=True,
                )

        task.refresh_from_db()
        self.assertTrue(observations["in_transaction"])
        self.assertEqual(observations["empresa_id"], self.empresa.pk)
        self.assertEqual(observations["task_ids"], (task.pk,))
        self.assertTrue(task.requiere_evidencia_cierre)

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
        document_insert = next(
            call for call in calls
            if "INSERT INTO tareas_documentotarea" in call.args[0]
        )
        history_insert = next(
            call for call in calls
            if "INSERT INTO tareas_documentohistorial" in call.args[0]
        )
        task_check = next(
            call for call in calls
            if "WHERE id=%s AND empresa_id=%s" in call.args[0]
        )
        self.assertIn("empresa_id=%s", task_check.args[0])
        self.assertEqual(task_check.args[1], (3, self.empresa.pk))
        self.assertTrue(document_insert)
        self.assertTrue(history_insert)
        connection.begin.assert_called_once()
        connection.commit.assert_called_once()
        self.assertTrue(
            any(
                "ORDER BY `id` FOR UPDATE" in call.args[0]
                for call in calls
            )
        )

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
        self.assertTrue(
            any(
                "empresa_id=%s" in call.args[0]
                for call in cursor.execute.call_args_list
            )
        )
        connection.begin.assert_called_once()
        connection.commit.assert_called_once()

    @patch("tareas.services.document_storage.resolve_operational_backend", side_effect=TareaConnectionError("missing role"))
    def test_missing_role_fails_closed(self, _resolver):
        with self.assertRaises(TaskStorageError):
            resolve_document_storage()
