from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import TestCase

from tareas.models import (
    Tarea,
    TareaEliminacionArchivo,
    TareaEliminacionElemento,
    TareaEliminacionOperacion,
)
from tareas.services.deletion_ledger import (
    DeletionFileReference,
    DeletionInventoryItem,
    DeletionLedgerBackendError,
    DeletionLedgerConflict,
    DeletionLedgerError,
    DeletionLedgerSchemaError,
    DeletionLedgerStateError,
    DeletionOperationInput,
    DjangoDeletionLedgerStorage,
    MySQLDeletionLedgerStorage,
    MySQLDeletionLedgerUnitOfWork,
    _OPERATION_COLUMNS,
    _check_mysql_transactional_tables,
    _required_logical_deletion_columns,
)
from tareas.tests.factories import create_empresa, create_tarea, create_user


class _MetadataCursor:
    def __init__(
        self,
        database_name="tareas",
        engine="InnoDB",
        support="YES",
        missing_columns=(),
    ):
        self.database_name = database_name
        self.engine = engine
        self.support = support
        self.missing_columns = set(missing_columns)
        self.rows = ()
        self.row = None

    def execute(self, sql, params=()):
        if "SELECT DATABASE()" in sql:
            self.row = (self.database_name,)
        elif "information_schema.tables" in sql:
            names = params[1:]
            self.rows = tuple((name, self.engine) for name in names)
        elif "information_schema.columns" in sql:
            self.rows = tuple(
                (table_name, column_name)
                for table_name, columns in _required_logical_deletion_columns().items()
                for column_name in columns
                if (table_name, column_name) not in self.missing_columns
            )
        else:
            self.row = (self.support,)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row

    def close(self):
        return None


class _MetadataConnection:
    def __init__(
        self,
        engine="InnoDB",
        support="YES",
        database_name="tareas",
        missing_columns=(),
    ):
        self.database_name = database_name
        self.engine = engine
        self.support = support
        self.missing_columns = set(missing_columns)
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    def cursor(self):
        return _MetadataCursor(
            database_name=self.database_name,
            engine=self.engine,
            support=self.support,
            missing_columns=self.missing_columns,
        )

    def begin(self):
        self.begin_count += 1

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


class DeletionLedgerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa("LDG", "Empresa ledger")
        cls.actor = create_user("ledger-actor")
        cls.task = create_tarea(
            cls.empresa,
            cls.actor,
            titulo="Raíz del ledger",
            correlativo="L0000001",
        )

    def setUp(self):
        self.storage = DjangoDeletionLedgerStorage("default", "test-config")
        self.operation = DeletionOperationInput(
            actor_id=self.actor.pk,
            empresa_id=self.empresa.pk,
            root_task_id=self.task.pk,
            root_correlativo=self.task.correlativo,
            fingerprint="a" * 64,
            dependency_summary={"tareas.tarea": 1},
            operation_id=uuid4(),
            motivo="Resguardo administrativo autorizado",
        )
        self.items = (DeletionInventoryItem("tareas.tarea", self.task.pk),)
        self.files = (DeletionFileReference("default", "tareas/test/privado.pdf"),)

    def test_mysql_root_operations_are_company_scoped_ordered_and_locked(self):
        unit = MySQLDeletionLedgerUnitOfWork(
            MagicMock(),
            "mysql_config:7:tareas",
            "test-config",
            database_name="tareas",
        )
        cursor = MagicMock()
        cursor.fetchall.return_value = ()

        with patch(
            "tareas.services.deletion_ledger._check_mysql_restoration_schema"
        ) as schema_check:
            with patch.object(unit, "_execute", return_value=cursor) as execute:
                operations = unit.get_root_operations(
                    self.empresa.pk,
                    self.task.pk,
                )

        self.assertEqual(operations, ())
        schema_check.assert_called_once()
        sql, params = execute.call_args.args
        self.assertIn("`empresa_id` = %s AND `root_task_id` = %s", sql)
        self.assertIn(
            "ORDER BY `created_at`, `operation_id` FOR UPDATE",
            sql,
        )
        self.assertIn("`reverses_operation_id`", sql)
        self.assertEqual(params, (self.empresa.pk, self.task.pk))

    def _persist_pending(self, *, include_files=False):
        with self.storage.atomic() as unit:
            unit.create_pending(self.operation)
            unit.save_manifest(
                self.operation.operation_id,
                self.items,
                self.files if include_files else (),
            )

    def test_duplicate_uuid_is_idempotent_and_payload_conflicts_are_rejected(self):
        self._persist_pending(include_files=True)

        with self.storage.atomic() as unit:
            record = unit.create_pending(self.operation)
            unit.save_manifest(
                self.operation.operation_id,
                self.items,
                self.files,
            )

        self.assertEqual(record.operation_id, self.operation.operation_id)
        self.assertEqual(record.motivo, self.operation.motivo)
        self.assertEqual(TareaEliminacionOperacion.objects.count(), 1)
        self.assertEqual(
            TareaEliminacionOperacion.objects.get().motivo,
            "Resguardo administrativo autorizado",
        )
        self.assertEqual(TareaEliminacionElemento.objects.count(), 1)
        self.assertEqual(TareaEliminacionArchivo.objects.count(), 1)

        conflicting = DeletionOperationInput(
            actor_id=self.actor.pk + 1,
            empresa_id=self.empresa.pk,
            root_task_id=self.task.pk,
            root_correlativo=self.task.correlativo,
            fingerprint="a" * 64,
            dependency_summary={"tareas.tarea": 1},
            operation_id=self.operation.operation_id,
        )
        with self.storage.atomic() as unit:
            with self.assertRaises(DeletionLedgerConflict):
                unit.create_pending(conflicting)

    def test_reusing_uuid_with_different_reason_is_a_payload_conflict(self):
        self._persist_pending()
        conflicting = DeletionOperationInput(
            actor_id=self.operation.actor_id,
            empresa_id=self.operation.empresa_id,
            root_task_id=self.operation.root_task_id,
            root_correlativo=self.operation.root_correlativo,
            fingerprint=self.operation.fingerprint,
            dependency_summary=self.operation.dependency_summary,
            operation_id=self.operation.operation_id,
            motivo="Motivo diferente",
        )

        with self.storage.atomic() as unit:
            with self.assertRaises(DeletionLedgerConflict):
                unit.create_pending(conflicting)

    def test_transaction_rollback_removes_operation_and_manifests(self):
        with self.assertRaises(DeletionLedgerError):
            with self.storage.atomic() as unit:
                unit.create_pending(self.operation)
                unit.save_manifest(
                    self.operation.operation_id,
                    self.items,
                    self.files,
                )
                raise RuntimeError("simulated failure")

        self.assertFalse(
            TareaEliminacionOperacion.objects.filter(
                operation_id=self.operation.operation_id.hex
            ).exists()
        )
        self.assertFalse(TareaEliminacionElemento.objects.exists())
        self.assertFalse(TareaEliminacionArchivo.objects.exists())

    def test_operation_cannot_be_committed_while_root_remains(self):
        self._persist_pending()

        with self.storage.atomic() as unit:
            with self.assertRaises(DeletionLedgerStateError):
                unit.mark_committed(self.operation.operation_id)

        operation = TareaEliminacionOperacion.objects.get(
            operation_id=self.operation.operation_id.hex
        )
        self.assertEqual(operation.status, TareaEliminacionOperacion.Estado.PENDIENTE)
        self.assertEqual(
            operation.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.NO_ENCOLADA,
        )

    def test_committed_operation_recovers_audit_and_file_work(self):
        self._persist_pending(include_files=True)
        Tarea.objects.filter(pk=self.task.pk).delete()

        with self.storage.atomic() as unit:
            committed = unit.mark_committed(self.operation.operation_id)

        self.assertEqual(committed.status, TareaEliminacionOperacion.Estado.COMMITTED)
        self.assertEqual(
            committed.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
        )
        self.assertEqual(
            tuple(item.operation_id for item in self.storage.pending_audits()),
            (self.operation.operation_id,),
        )
        self.assertEqual(
            tuple(item.file_name for item in self.storage.pending_files()),
            ("tareas/test/privado.pdf",),
        )

        with self.storage.atomic() as unit:
            failed_audit = unit.record_audit_result(
                self.operation.operation_id,
                confirmed=False,
                error_code="CENTRAL_UNAVAILABLE",
            )
        self.assertEqual(failed_audit.audit_attempts, 1)
        self.assertEqual(len(self.storage.pending_audits()), 1)

        with self.storage.atomic() as unit:
            confirmed = unit.record_audit_result(
                self.operation.operation_id,
                confirmed=True,
                event_id=81,
            )
        self.assertEqual(confirmed.audit_status, "CONFIRMED")
        self.assertEqual(self.storage.pending_audits(), ())

        with self.storage.atomic() as unit:
            file_record = unit.record_file_cleanup_result(
                self.operation.operation_id,
                self.files[0],
                completed=False,
                error_code="STORAGE_UNAVAILABLE",
            )
        self.assertEqual(file_record.attempts, 1)
        self.assertEqual(len(self.storage.pending_files()), 1)

        with self.storage.atomic() as unit:
            completed_file = unit.record_file_cleanup_result(
                self.operation.operation_id,
                self.files[0],
                completed=True,
            )
        self.assertEqual(completed_file.status, "COMPLETE")
        with self.storage.atomic() as unit:
            repeated_completion = unit.record_file_cleanup_result(
                self.operation.operation_id,
                self.files[0],
                completed=True,
            )
        self.assertEqual(repeated_completion.attempts, completed_file.attempts)
        self.assertEqual(self.storage.pending_files(), ())

    def test_operation_requires_the_selected_root_to_exist_in_company(self):
        invalid = DeletionOperationInput(
            actor_id=self.actor.pk,
            empresa_id=self.empresa.pk + 1,
            root_task_id=self.task.pk,
            root_correlativo=self.task.correlativo,
            fingerprint="a" * 64,
            dependency_summary={"tareas.tarea": 1},
        )
        with self.storage.atomic() as unit:
            with self.assertRaises(DeletionLedgerStateError):
                unit.create_pending(invalid)

    def test_mysql_contract_requires_all_affected_tables_to_be_innodb(self):
        _check_mysql_transactional_tables(
            _MetadataConnection(),
            "tareas",
        )
        with self.assertRaises(DeletionLedgerBackendError):
            _check_mysql_transactional_tables(
                _MetadataConnection(engine="MyISAM"),
                "tareas",
            )
        with self.assertRaises(DeletionLedgerBackendError):
            _check_mysql_transactional_tables(
                _MetadataConnection(database_name="other_database"),
                "tareas",
            )
        required_columns = _required_logical_deletion_columns()
        first_table, first_columns = next(iter(required_columns.items()))
        with self.assertRaises(DeletionLedgerSchemaError):
            _check_mysql_transactional_tables(
                _MetadataConnection(
                    missing_columns={(first_table, first_columns[0])}
                ),
                "tareas",
            )

    def test_mysql_adapter_uses_explicit_transaction_and_rolls_back_failures(self):
        connection_config = SimpleNamespace(
            pk=7,
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        connection = _MetadataConnection()

        @contextmanager
        def opened_connection(*args, **kwargs):
            yield connection

        storage = MySQLDeletionLedgerStorage(connection_config, "tareas")
        with patch(
            "tareas.services.deletion_ledger.open_mysql_connection",
            side_effect=opened_connection,
        ):
            with storage.atomic():
                pass
            self.assertEqual(connection.begin_count, 1)
            self.assertEqual(connection.commit_count, 1)
            self.assertEqual(connection.rollback_count, 0)

            with self.assertRaises(DeletionLedgerError):
                with storage.atomic():
                    raise RuntimeError("simulated failure")
        self.assertEqual(connection.begin_count, 2)
        self.assertEqual(connection.rollback_count, 1)

    def test_mysql_pending_insert_is_idempotent_and_locks_root(self):
        operation = self.operation
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        row_values = {
            "operation_id": operation.operation_id.hex,
            "actor_id": operation.actor_id,
            "empresa_id": operation.empresa_id,
            "root_task_id": operation.root_task_id,
            "root_correlativo": operation.root_correlativo,
            "backend_type": "MYSQL_CONFIG",
            "backend_identity": "mysql_config:7:tareas",
            "backend_config_version": "2026-01-01T00:00:00+00:00",
            "fingerprint": operation.fingerprint,
            "dependency_summary": '{"tareas.tarea":1}',
            "status": "PENDING",
            "result_code": "",
            "audit_status": "NOT_QUEUED",
            "audit_attempts": 0,
            "audit_last_attempt_at": None,
            "audit_event_id": None,
            "audit_error_code": "",
            "file_cleanup_status": "NOT_REQUIRED",
            "created_at": now,
            "updated_at": now,
            "committed_at": None,
            "motivo": operation.motivo,
        }
        row = tuple(row_values[name] for name in _OPERATION_COLUMNS)
        root_cursor = MagicMock()
        root_cursor.fetchone.return_value = (operation.root_task_id,)
        insert_cursor = MagicMock()
        unit = MySQLDeletionLedgerUnitOfWork(
            MagicMock(),
            "mysql_config:7:tareas",
            "2026-01-01T00:00:00+00:00",
        )
        unit._operation_row = MagicMock(side_effect=[None, row])
        unit._execute = MagicMock(side_effect=[root_cursor, insert_cursor])

        record = unit.create_pending(operation)

        self.assertEqual(record.operation_id, operation.operation_id)
        self.assertEqual(record.status, "PENDING")
        self.assertEqual(record.motivo, operation.motivo)
        statements = [entry.args[0] for entry in unit._execute.call_args_list]
        self.assertIn("FOR UPDATE", statements[0])
        self.assertIn("ON DUPLICATE KEY UPDATE", statements[1])
        self.assertIn("`motivo`", statements[1])
        self.assertEqual(
            unit._execute.call_args_list[1].args[1][-1],
            operation.motivo,
        )
