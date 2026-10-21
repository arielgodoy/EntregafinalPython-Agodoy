from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from tareas.models import (
    LOGICAL_DELETION_RESULT_CODE,
    LOGICAL_RESTORATION_RESULT_CODE,
    Tarea,
    TareaEliminacionArchivo,
    TareaEliminacionElemento,
    TareaEliminacionOperacion,
)
from tareas.services.deletion_ledger import (
    DeletionInventoryItem,
    DeletionLedgerConflict,
    DeletionLedgerError,
    DeletionLedgerStateError,
    DjangoDeletionLedgerStorage,
    MySQLDeletionLedgerUnitOfWork,
    _OPERATION_COLUMNS,
    _RESTORATION_OPERATION_COLUMNS,
    RestorationOperationInput,
)
from tareas.tests.factories import create_empresa, create_tarea, create_user


class LogicalRestorationLedgerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa("RLG", "Empresa restoration ledger")
        cls.actor = create_user("restoration-ledger-actor")
        cls.task = create_tarea(
            cls.empresa,
            cls.actor,
            titulo="Raíz de restauración",
            correlativo="R0000001",
        )

    def setUp(self):
        self.storage = DjangoDeletionLedgerStorage("default", "test-config")
        self.deletion_operation_id = uuid4()
        self.deletion = self._create_source_deletion(
            operation_id=self.deletion_operation_id,
        )
        self.manifest = (
            DeletionInventoryItem("tareas.tarea", self.task.pk),
        )
        self.restoration_operation_id = uuid4()

    def _create_source_deletion(
        self,
        *,
        operation_id=None,
        empresa_id=None,
        status=TareaEliminacionOperacion.Estado.COMMITTED,
        result_code=LOGICAL_DELETION_RESULT_CODE,
        root_task_id=None,
        reverses_operation_id=None,
        file_cleanup_status=TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA,
    ):
        operation_id = operation_id or uuid4()
        root_task_id = root_task_id or self.task.pk
        task = Tarea.all_objects.get(pk=root_task_id)
        record = TareaEliminacionOperacion.objects.create(
            operation_id=operation_id.hex,
            actor_id=self.actor.pk,
            empresa_id=empresa_id or self.empresa.pk,
            root_task_id=root_task_id,
            root_correlativo=task.correlativo,
            backend_type="DJANGO",
            backend_identity=self.storage.backend_identity,
            backend_config_version=self.storage.config_version,
            fingerprint="a" * 64,
            dependency_summary='{"tareas.tarea":1}',
            motivo="Eliminación original autorizada",
            status=status,
            result_code=result_code,
            audit_status=TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
            file_cleanup_status=file_cleanup_status,
            committed_at=(
                timezone.now()
                if status == TareaEliminacionOperacion.Estado.COMMITTED
                else None
            ),
            reverses_operation_id=reverses_operation_id,
        )
        TareaEliminacionElemento.objects.create(
            operacion=record,
            tipo="tareas.tarea",
            object_id=root_task_id,
        )
        return record

    def _restoration_input(
        self,
        *,
        operation_id=None,
        reverses_operation_id=None,
        empresa_id=None,
        motivo="Restauración autorizada",
        manifest=None,
    ):
        return RestorationOperationInput(
            actor_id=self.actor.pk,
            empresa_id=empresa_id or self.empresa.pk,
            reverses_operation_id=reverses_operation_id or self.deletion_operation_id,
            fingerprint="b" * 64,
            manifest=self.manifest if manifest is None else manifest,
            operation_id=operation_id or self.restoration_operation_id,
            motivo=motivo,
        )

    def _task_deletion_markers(self):
        task = Tarea.all_objects.get(pk=self.task.pk)
        return (
            task.eliminada,
            task.eliminada_en,
            task.eliminada_por_id,
            task.eliminacion_operacion_id,
        )

    def test_pending_restore_records_link_and_exact_manifest_without_touching_task(self):
        original = (
            self.deletion.actor_id,
            self.deletion.empresa_id,
            self.deletion.root_task_id,
            self.deletion.root_correlativo,
            self.deletion.motivo,
            self.deletion.status,
            self.deletion.result_code,
            self.deletion.committed_at,
        )
        task_markers = self._task_deletion_markers()

        with self.storage.atomic() as unit:
            restoration = unit.create_restoration_pending(
                self._restoration_input()
            )
            restored_manifest = unit.get_manifest(restoration.operation_id)

        self.assertEqual(restoration.operation_id, self.restoration_operation_id)
        self.assertEqual(
            restoration.reverses_operation_id,
            self.deletion_operation_id,
        )
        self.assertEqual(restoration.status, TareaEliminacionOperacion.Estado.PENDIENTE)
        self.assertEqual(restoration.result_code, "")
        self.assertEqual(restored_manifest, self.manifest)
        self.assertEqual(self._task_deletion_markers(), task_markers)
        self.assertFalse(
            TareaEliminacionArchivo.objects.filter(
                operacion_id=self.restoration_operation_id.hex,
            ).exists()
        )

        self.deletion.refresh_from_db()
        self.assertEqual(
            (
                self.deletion.actor_id,
                self.deletion.empresa_id,
                self.deletion.root_task_id,
                self.deletion.root_correlativo,
                self.deletion.motivo,
                self.deletion.status,
                self.deletion.result_code,
                self.deletion.committed_at,
            ),
            original,
        )
        self.assertIsNone(self.deletion.reverses_operation_id)

    def test_same_uuid_and_payload_replays_pending_ledger_registration(self):
        first = self._restoration_input()
        with self.storage.atomic() as unit:
            original = unit.create_restoration_pending(first)
        with self.storage.atomic() as unit:
            replay = unit.create_restoration_pending(first)

        self.assertEqual(replay.operation_id, original.operation_id)
        self.assertEqual(replay.reverses_operation_id, original.reverses_operation_id)
        self.assertEqual(
            TareaEliminacionOperacion.objects.filter(
                reverses_operation_id=self.deletion_operation_id.hex,
            ).count(),
            1,
        )

    def test_same_uuid_with_different_reason_conflicts(self):
        with self.storage.atomic() as unit:
            unit.create_restoration_pending(self._restoration_input())
        conflicting = self._restoration_input(motivo="Motivo distinto")

        with self.storage.atomic() as unit:
            with self.assertRaises(DeletionLedgerConflict):
                unit.create_restoration_pending(conflicting)

    def test_second_restore_uuid_for_same_deletion_is_rejected(self):
        with self.storage.atomic() as unit:
            unit.create_restoration_pending(self._restoration_input())
        second = self._restoration_input(
            operation_id=uuid4(),
            motivo="Segundo intento",
        )

        with self.storage.atomic() as unit:
            with self.assertRaises(DeletionLedgerConflict):
                unit.create_restoration_pending(second)

    def test_restore_uuid_cannot_reuse_source_deletion_uuid(self):
        invalid = self._restoration_input(
            operation_id=self.deletion_operation_id,
        )
        with self.storage.atomic() as unit:
            with self.assertRaises(ValueError):
                unit.create_restoration_pending(invalid)

    def test_restore_uuid_cannot_collide_with_another_deletion_uuid(self):
        other_deletion = self._create_source_deletion()
        invalid = self._restoration_input(
            operation_id=UUID(other_deletion.operation_id),
        )

        with self.storage.atomic() as unit:
            with self.assertRaises(DeletionLedgerConflict):
                unit.create_restoration_pending(invalid)

    def test_only_confirmed_logical_deletion_in_same_company_is_eligible(self):
        other_company = create_empresa("RLO", "Otra empresa")
        other_task = create_tarea(
            other_company,
            self.actor,
            titulo="Raíz de otra empresa",
            correlativo="O0000001",
        )
        source = self._create_source_deletion(
            empresa_id=other_company.pk,
            root_task_id=other_task.pk,
        )
        wrong_company = self._restoration_input(
            reverses_operation_id=UUID(source.operation_id),
        )
        with self.storage.atomic() as unit:
            with self.assertRaises(DeletionLedgerConflict):
                unit.create_restoration_pending(wrong_company)

        pending = self._create_source_deletion(
            status=TareaEliminacionOperacion.Estado.PENDIENTE,
            result_code="",
        )
        with self.storage.atomic() as unit:
            with self.assertRaises(DeletionLedgerStateError):
                unit.create_restoration_pending(
                    self._restoration_input(
                        reverses_operation_id=UUID(pending.operation_id),
                        operation_id=uuid4(),
                    )
                )

        physical = self._create_source_deletion(result_code="DELETED")
        with self.storage.atomic() as unit:
            with self.assertRaises(DeletionLedgerStateError):
                unit.create_restoration_pending(
                    self._restoration_input(
                        reverses_operation_id=UUID(physical.operation_id),
                        operation_id=uuid4(),
                    )
                )

    def test_source_with_reverse_link_is_not_an_original_deletion(self):
        with self.storage.atomic() as unit:
            source = unit.get_operation(self.deletion_operation_id)
        if source is None:
            raise AssertionError("No se encontró la operación de origen.")
        invalid_source = replace(source, reverses_operation_id=uuid4())

        with self.storage.atomic() as unit:
            with patch.object(
                unit,
                "get_restoration_source_operation",
                return_value=invalid_source,
            ):
                with self.assertRaises(DeletionLedgerStateError):
                    unit.create_restoration_pending(self._restoration_input())

    def test_restoration_cannot_reverse_a_restoration_or_file_cleanup_operation(self):
        restoration = TareaEliminacionOperacion.objects.create(
            operation_id=uuid4().hex,
            actor_id=self.actor.pk,
            empresa_id=self.empresa.pk,
            root_task_id=self.task.pk,
            root_correlativo=self.task.correlativo,
            backend_type="DJANGO",
            backend_identity=self.storage.backend_identity,
            backend_config_version=self.storage.config_version,
            fingerprint="c" * 64,
            dependency_summary='{"tareas.tarea":1}',
            motivo="Restauración histórica",
            status=TareaEliminacionOperacion.Estado.COMMITTED,
            result_code=LOGICAL_RESTORATION_RESULT_CODE,
            audit_status=TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
            file_cleanup_status=TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA,
            committed_at=timezone.now(),
            reverses_operation=self.deletion,
        )
        with self.storage.atomic() as unit:
            with self.assertRaises(DeletionLedgerStateError):
                unit.create_restoration_pending(
                    self._restoration_input(
                        reverses_operation_id=UUID(restoration.operation_id),
                        operation_id=uuid4(),
                    )
                )

        source_with_file = self._create_source_deletion(
            operation_id=uuid4(),
        )
        TareaEliminacionArchivo.objects.create(
            operacion=source_with_file,
            storage_key="default",
            file_name="retained.pdf",
            reference_hash="d" * 64,
        )
        with self.storage.atomic() as unit:
            with self.assertRaises(DeletionLedgerStateError):
                unit.create_restoration_pending(
                    self._restoration_input(
                        reverses_operation_id=UUID(source_with_file.operation_id),
                        operation_id=uuid4(),
                    )
                )

    def test_manifest_must_match_source_operation_exactly(self):
        extra_task = create_tarea(
            self.empresa,
            self.actor,
            titulo="No pertenece al manifiesto",
            correlativo="R0000002",
        )
        invalid = self._restoration_input(
            manifest=(
                *self.manifest,
                DeletionInventoryItem("tareas.tarea", extra_task.pk),
            ),
        )

        with self.storage.atomic() as unit:
            with self.assertRaises(DeletionLedgerConflict):
                unit.create_restoration_pending(invalid)

        missing = self._restoration_input(
            operation_id=uuid4(),
            manifest=(),
        )
        with self.storage.atomic() as unit:
            with self.assertRaises(ValueError):
                unit.create_restoration_pending(missing)

        self.assertFalse(
            TareaEliminacionOperacion.objects.filter(
                reverses_operation_id=self.deletion_operation_id.hex,
            ).exists()
        )

    def test_failed_outer_transaction_rolls_back_only_new_ledger_rows(self):
        task_markers = self._task_deletion_markers()
        source_snapshot = (
            self.deletion.status,
            self.deletion.result_code,
            self.deletion.motivo,
            self.deletion.reverses_operation_id,
        )

        with self.assertRaises(DeletionLedgerError):
            with self.storage.atomic() as unit:
                unit.create_restoration_pending(self._restoration_input())
                raise RuntimeError("simulated ledger rollback")

        self.deletion.refresh_from_db()
        self.assertEqual(
            (
                self.deletion.status,
                self.deletion.result_code,
                self.deletion.motivo,
                self.deletion.reverses_operation_id,
            ),
            source_snapshot,
        )
        self.assertFalse(
            TareaEliminacionOperacion.objects.filter(
                reverses_operation_id=self.deletion_operation_id.hex,
            ).exists()
        )
        self.assertEqual(self._task_deletion_markers(), task_markers)

    def test_ledger_can_represent_multiple_cycles_without_root_uniqueness(self):
        first_restore_id = uuid4()
        second_deletion = self._create_source_deletion(operation_id=uuid4())
        second_restore_id = uuid4()

        with self.storage.atomic() as unit:
            first = unit.create_restoration_pending(
                self._restoration_input(operation_id=first_restore_id)
            )
            second = unit.create_restoration_pending(
                self._restoration_input(
                    operation_id=second_restore_id,
                    reverses_operation_id=UUID(second_deletion.operation_id),
                )
            )

        self.assertNotEqual(first.operation_id, second.operation_id)
        self.assertEqual(first.reverses_operation_id, self.deletion_operation_id)
        self.assertEqual(
            second.reverses_operation_id,
            UUID(second_deletion.operation_id),
        )
        self.assertEqual(
            TareaEliminacionOperacion.objects.filter(
                reverses_operation__isnull=False,
            ).count(),
            2,
        )
        self.assertFalse(Tarea.all_objects.get(pk=self.task.pk).eliminada)


class MySQLRestorationLedgerTests(TestCase):
    def setUp(self):
        self.empresa = create_empresa("RLM", "Empresa MySQL ledger mock")
        self.actor = create_user("mysql-restoration-ledger-actor")
        self.task = create_tarea(
            self.empresa,
            self.actor,
            titulo="Raíz MySQL",
            correlativo="M0000001",
        )
        self.source_operation_id = uuid4()
        self.restoration_operation_id = uuid4()
        self.backend_identity = "mysql_config:17:tareas"
        self.config_version = "2026-10-19T00:00:00+00:00"
        self.operation = RestorationOperationInput(
            actor_id=self.actor.pk,
            empresa_id=self.empresa.pk,
            reverses_operation_id=self.source_operation_id,
            fingerprint="b" * 64,
            manifest=(DeletionInventoryItem("tareas.tarea", self.task.pk),),
            operation_id=self.restoration_operation_id,
            motivo="Restauración MySQL simulada",
        )

    def _operation_row(self, *, operation_id, reverse_id=None, restore=False):
        now = timezone.now()
        values = {
            "operation_id": operation_id.hex,
            "actor_id": self.actor.pk,
            "empresa_id": self.empresa.pk,
            "root_task_id": self.task.pk,
            "root_correlativo": self.task.correlativo,
            "backend_type": "MYSQL_CONFIG",
            "backend_identity": self.backend_identity,
            "backend_config_version": self.config_version,
            "fingerprint": "b" * 64 if restore else "a" * 64,
            "dependency_summary": '{"tareas.tarea":1}',
            "status": (
                TareaEliminacionOperacion.Estado.PENDIENTE
                if restore
                else TareaEliminacionOperacion.Estado.COMMITTED
            ),
            "result_code": "" if restore else LOGICAL_DELETION_RESULT_CODE,
            "audit_status": TareaEliminacionOperacion.EstadoAuditoria.NO_ENCOLADA,
            "audit_attempts": 0,
            "audit_last_attempt_at": None,
            "audit_event_id": None,
            "audit_error_code": "",
            "file_cleanup_status": (
                TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA
            ),
            "created_at": now,
            "updated_at": now,
            "committed_at": None if restore else now,
            "motivo": (
                "Restauración MySQL simulada"
                if restore
                else "Eliminación MySQL simulada"
            ),
            "reverses_operation_id": reverse_id.hex if reverse_id else None,
        }
        columns = (
            _RESTORATION_OPERATION_COLUMNS if restore else _OPERATION_COLUMNS
        )
        return tuple(values[column] for column in columns)

    def test_mysql_insert_is_parameterized_and_does_not_touch_task_rows(self):
        source_row = self._operation_row(operation_id=self.source_operation_id)
        source_restoration_row = (*source_row, None)
        restoration_row = self._operation_row(
            operation_id=self.restoration_operation_id,
            reverse_id=self.source_operation_id,
            restore=True,
        )
        file_cursor = MagicMock()
        file_cursor.fetchone.return_value = None
        insert_cursor = MagicMock()
        unit = MySQLDeletionLedgerUnitOfWork(
            MagicMock(),
            self.backend_identity,
            self.config_version,
            "tareas",
        )
        unit._operation_row = MagicMock(return_value=None)
        unit._restoration_by_source = MagicMock(return_value=None)
        unit._restoration_operation_row = MagicMock(
            side_effect=[source_restoration_row, None, restoration_row]
        )
        unit._execute = MagicMock(side_effect=[file_cursor, insert_cursor])
        unit.get_manifest = MagicMock(
            return_value=(DeletionInventoryItem("tareas.tarea", self.task.pk),)
        )
        unit.save_manifest = MagicMock()
        markers_before = (
            self.task.eliminada,
            self.task.eliminada_en,
            self.task.eliminada_por_id,
            self.task.eliminacion_operacion_id,
        )

        with patch(
            "tareas.services.deletion_ledger._check_mysql_restoration_schema"
        ):
            record = unit.create_restoration_pending(self.operation)

        insert_sql, insert_params = unit._execute.call_args_list[1].args
        self.assertIn("`reverses_operation_id`", insert_sql)
        self.assertIn("VALUES (%s", insert_sql)
        self.assertIn(
            "ON DUPLICATE KEY UPDATE `operation_id` = `operation_id`",
            insert_sql,
        )
        self.assertNotIn("VALUES(`operation_id`)", insert_sql)
        self.assertIn(self.source_operation_id.hex, insert_params)
        self.assertEqual(record.reverses_operation_id, self.source_operation_id)
        self.assertEqual(record.result_code, "")
        self.assertEqual(record.status, TareaEliminacionOperacion.Estado.PENDIENTE)
        unit.save_manifest.assert_called_once_with(
            self.restoration_operation_id,
            (DeletionInventoryItem("tareas.tarea", self.task.pk),),
        )
        task_after = Tarea.all_objects.get(pk=self.task.pk)
        self.assertEqual(
            (
                task_after.eliminada,
                task_after.eliminada_en,
                task_after.eliminada_por_id,
                task_after.eliminacion_operacion_id,
            ),
            markers_before,
        )

    def test_mysql_adapter_rejects_reverse_linked_source_even_if_result_says_deleted(self):
        source_operation_id = uuid4()
        invalid_source_row = (
            *self._operation_row(operation_id=source_operation_id),
            uuid4().hex,
        )
        unit = MySQLDeletionLedgerUnitOfWork(
            MagicMock(),
            self.backend_identity,
            self.config_version,
            "tareas",
        )
        unit._restoration_operation_row = MagicMock(
            return_value=invalid_source_row
        )

        with patch(
            "tareas.services.deletion_ledger._check_mysql_restoration_schema"
        ):
            with self.assertRaises(DeletionLedgerStateError):
                unit.create_restoration_pending(
                    RestorationOperationInput(
                        actor_id=self.actor.pk,
                        empresa_id=self.empresa.pk,
                        reverses_operation_id=source_operation_id,
                        fingerprint="b" * 64,
                        manifest=(
                            DeletionInventoryItem("tareas.tarea", self.task.pk),
                        ),
                        operation_id=uuid4(),
                        motivo="No revertir una restauración",
                    )
                )
        unit._restoration_operation_row.assert_called_once_with(
            source_operation_id,
            lock=True,
        )

    def test_mysql_restoration_transition_commits_only_a_valid_pending_operation(self):
        pending_row = self._operation_row(
            operation_id=self.restoration_operation_id,
            reverse_id=self.source_operation_id,
            restore=True,
        )
        source_row = (
            *self._operation_row(operation_id=self.source_operation_id),
            None,
        )
        committed_values = dict(
            zip(_RESTORATION_OPERATION_COLUMNS, pending_row)
        )
        committed_values.update(
            {
                "status": TareaEliminacionOperacion.Estado.COMMITTED,
                "result_code": LOGICAL_RESTORATION_RESULT_CODE,
                "audit_status": TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
                "committed_at": timezone.now(),
            }
        )
        committed_row = tuple(
            committed_values[column]
            for column in _RESTORATION_OPERATION_COLUMNS
        )
        file_cursor = MagicMock()
        file_cursor.fetchone.return_value = None
        unit = MySQLDeletionLedgerUnitOfWork(
            MagicMock(),
            self.backend_identity,
            self.config_version,
            "tareas",
        )
        unit._restoration_operation_row = MagicMock(
            side_effect=[pending_row, source_row, committed_row]
        )
        unit.get_manifest = MagicMock(return_value=self.operation.manifest)
        unit._execute = MagicMock(return_value=file_cursor)
        unit._update_operation = MagicMock()

        with patch(
            "tareas.services.deletion_ledger._check_mysql_restoration_schema"
        ):
            record = unit.mark_logically_restored(self.restoration_operation_id)

        self.assertEqual(record.operation_id, self.restoration_operation_id)
        self.assertEqual(record.reverses_operation_id, self.source_operation_id)
        self.assertEqual(
            record.result_code,
            LOGICAL_RESTORATION_RESULT_CODE,
        )
        self.assertEqual(record.status, TareaEliminacionOperacion.Estado.COMMITTED)
        self.assertEqual(
            record.audit_status,
            TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
        )
        unit._update_operation.assert_called_once()
        update_values = unit._update_operation.call_args.args[1]
        self.assertEqual(
            update_values["result_code"],
            LOGICAL_RESTORATION_RESULT_CODE,
        )
        self.assertEqual(
            update_values["status"],
            TareaEliminacionOperacion.Estado.COMMITTED,
        )


class RestorationLedgerConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.empresa = create_empresa("RLC", "Empresa restoration concurrente")
        self.actor = create_user("restoration-ledger-concurrent-actor")
        self.task = create_tarea(
            self.empresa,
            self.actor,
            titulo="Raíz concurrente",
            correlativo="C0000001",
        )
        self.deletion_operation_id = uuid4()
        self.restore_manifest = (
            DeletionInventoryItem("tareas.tarea", self.task.pk),
        )
        self.source = TareaEliminacionOperacion.objects.create(
            operation_id=self.deletion_operation_id.hex,
            actor_id=self.actor.pk,
            empresa_id=self.empresa.pk,
            root_task_id=self.task.pk,
            root_correlativo=self.task.correlativo,
            backend_type="DJANGO",
            backend_identity="django:default",
            backend_config_version="test-config",
            fingerprint="e" * 64,
            dependency_summary='{"tareas.tarea":1}',
            motivo="Eliminación concurrente",
            status=TareaEliminacionOperacion.Estado.COMMITTED,
            result_code=LOGICAL_DELETION_RESULT_CODE,
            audit_status=TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
            file_cleanup_status=TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA,
            committed_at=timezone.now(),
        )
        TareaEliminacionElemento.objects.create(
            operacion=self.source,
            tipo="tareas.tarea",
            object_id=self.task.pk,
        )

    def test_two_concurrent_restore_registrations_cannot_link_twice(self):
        barrier = Barrier(2)

        def register(operation_id):
            close_old_connections()
            storage = DjangoDeletionLedgerStorage("default", "test-config")
            operation = RestorationOperationInput(
                actor_id=self.actor.pk,
                empresa_id=self.empresa.pk,
                reverses_operation_id=self.deletion_operation_id,
                fingerprint="f" * 64,
                manifest=self.restore_manifest,
                operation_id=operation_id,
                motivo="Restauración concurrente",
            )
            try:
                barrier.wait(timeout=10)
                with storage.atomic() as unit:
                    record = unit.create_restoration_pending(operation)
                return ("created", record.operation_id)
            except Exception as exc:
                return ("rejected", type(exc).__name__)
            finally:
                close_old_connections()

        operation_ids = (uuid4(), uuid4())
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(register, operation_ids))

        self.assertEqual(sum(result[0] == "created" for result in results), 1)
        self.assertEqual(
            TareaEliminacionOperacion.objects.filter(
                reverses_operation_id=self.deletion_operation_id.hex,
            ).count(),
            1,
        )
