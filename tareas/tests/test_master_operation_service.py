from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase

from tareas.services.audit import MasterCatalogAuditRetryableError
from tareas.services.audit import log_master_catalog_operation
from tareas.services.master_catalog_common import (
    CompanyContext,
    MasterCatalogConflict,
    MasterCatalogCommitUnknown,
    MutationMetadata,
    mutation_transaction,
)
from tareas.services.master_operation_service import (
    MasterMutationChange,
    execute_master_mutation,
    reconcile_master_operations,
)
from tareas.services.master_operation_store import (
    MasterOperationConflict,
    MasterOperationRecord,
    OperationReservation,
    MasterOperationValidationError,
    mark_audit_status,
)
from tareas.services.task_mutation_locks import TaskMutationCommitError


def _record(
    operation_id,
    *,
    status="PENDING",
    result_id=None,
    result_payload=None,
    audit_status="PENDING",
    audit_error_code="",
):
    return MasterOperationRecord(
        operation_id=operation_id,
        entity_type="LOCAL",
        action="CREATE",
        empresa_id=1,
        actor_id=7,
        payload_hash="a" * 64,
        status=status,
        result_id=result_id,
        result_payload=result_payload,
        audit_status=audit_status,
        audit_event_id=None,
        audit_error_code=audit_error_code,
        created_at=None,
        updated_at=None,
    )


class MasterOperationServiceTests(SimpleTestCase):
    def setUp(self):
        self.operation_id = uuid4()
        self.metadata = MutationMetadata(
            operation_id=str(self.operation_id),
            actor_id=7,
            motivo="Prueba de integración",
        )
        self.context = CompanyContext(empresa_id=1, actor_id=7)
        self.connection = SimpleNamespace(cursor=lambda: SimpleNamespace(close=lambda: None))
        self.transaction_state = {"active": False, "commits": 0, "rollbacks": 0}

    def test_audit_projection_links_active_actor_and_keeps_actor_metadata(self):
        actor = SimpleNamespace(pk=7, is_active=True)
        audit_result = SimpleNamespace(event=SimpleNamespace(pk=101))
        with patch(
            "tareas.services.audit.get_user_model",
            return_value=SimpleNamespace(
                _default_manager=SimpleNamespace(
                    filter=lambda **_kwargs: SimpleNamespace(first=lambda: actor)
                )
            ),
        ), patch(
            "tareas.services.audit.AuditoriaService.log_event_idempotent",
            return_value=audit_result,
        ) as log_event:
            event = log_master_catalog_operation(
                operation_id=self.operation_id,
                entity_type="LOCAL",
                action="CREATE",
                empresa_id=1,
                actor_id=7,
                result_id=42,
                payload_hash="a" * 64,
                result_payload={"changed_fields": ["codigo"], "motivo": "test"},
            )

        self.assertEqual(event.pk, 101)
        self.assertIs(log_event.call_args.kwargs["user"], actor)
        self.assertEqual(log_event.call_args.kwargs["meta"]["actor_id"], 7)

    def test_confirmed_audit_cannot_regress(self):
        operation_id = self.operation_id

        class Cursor:
            def __init__(self):
                self.audit_status = "CONFIRMED"
                self.audit_event_id = 101
                self.updated = False

            def execute(self, sql, params=()):
                self.updated = sql.startswith("UPDATE")

            def fetchone(self):
                return (
                    str(operation_id),
                    "LOCAL",
                    "CREATE",
                    1,
                    7,
                    "a" * 64,
                    "COMMITTED",
                    42,
                    "{}",
                    self.audit_status,
                    self.audit_event_id,
                    "",
                    None,
                    None,
                )

        cursor = Cursor()
        with self.assertRaises(MasterOperationValidationError):
            mark_audit_status(
                cursor,
                operation_id,
                audit_status="ERROR",
                audit_error_code="PERMANENT_TEST",
            )
        self.assertFalse(cursor.updated)

    @contextmanager
    def _transaction(self, _connection):
        self.transaction_state["active"] = True
        try:
            yield
        except Exception:
            self.transaction_state["rollbacks"] += 1
            raise
        else:
            self.transaction_state["commits"] += 1
        finally:
            self.transaction_state["active"] = False

    def _connection_context(self):
        return nullcontext(self.connection)

    def _patch_connection(self):
        return (
            patch(
                "tareas.services.master_operation_service.verified_base_tareas_connection",
                side_effect=self._connection_context,
            ),
            patch(
                "tareas.services.master_operation_service.mutation_transaction",
                side_effect=self._transaction,
            ),
        )

    def test_mutation_and_operation_result_share_one_transaction_then_audit(self):
        pending = _record(self.operation_id)
        committed = _record(
            self.operation_id,
            status="COMMITTED",
            result_id=42,
            result_payload={
                "id": 42,
                "before": None,
                "after": {"id": 42, "codigo": "L-42"},
                "changed_fields": ["codigo"],
            },
        )
        audit_was_outside_transaction = []

        def audit(**_kwargs):
            audit_was_outside_transaction.append(
                not self.transaction_state["active"]
            )
            return SimpleNamespace(pk=101)

        change = MasterMutationChange(
            result_id=42,
            before=None,
            after={"id": 42, "codigo": "L-42"},
            changed_fields=("codigo",),
        )
        with self._patch_connection()[0], self._patch_connection()[1], patch(
            "tareas.services.master_operation_service.reserve_operation",
            return_value=OperationReservation(pending, replayed=False),
        ), patch(
            "tareas.services.master_operation_service.complete_operation",
            return_value=committed,
        ) as complete, patch(
            "tareas.services.master_operation_service.log_master_catalog_operation",
            side_effect=audit,
        ), patch(
            "tareas.services.master_operation_service.mark_audit_status"
        ) as mark:
            result = execute_master_mutation(
                context=self.context,
                metadata=self.metadata,
                entity_type="LOCAL",
                action="CREATE",
                payload={"codigo": "L-42"},
                mutate=lambda _cursor: change,
            )

        self.assertEqual(result.id, 42)
        self.assertEqual(result.audit_status, "CONFIRMED")
        self.assertFalse(result.replayed)
        self.assertEqual(complete.call_count, 1)
        self.assertEqual(audit_was_outside_transaction, [True])
        self.assertEqual(self.transaction_state["commits"], 2)
        mark.assert_called_once()

    def test_replay_returns_saved_result_without_running_mutation(self):
        committed = _record(
            self.operation_id,
            status="COMMITTED",
            result_id=42,
            result_payload={"id": 42, "before": None, "after": {}, "changed_fields": []},
            audit_status="CONFIRMED",
        )
        with self._patch_connection()[0], self._patch_connection()[1], patch(
            "tareas.services.master_operation_service.reserve_operation",
            return_value=OperationReservation(committed, replayed=True),
        ), patch(
            "tareas.services.master_operation_service.complete_operation"
        ) as complete, patch(
            "tareas.services.master_operation_service.log_master_catalog_operation"
        ) as audit:
            result = execute_master_mutation(
                context=self.context,
                metadata=self.metadata,
                entity_type="LOCAL",
                action="CREATE",
                payload={"codigo": "L-42"},
                mutate=lambda _cursor: self.fail("A replay must not mutate again."),
            )

        self.assertEqual(result.id, 42)
        self.assertTrue(result.replayed)
        complete.assert_not_called()
        audit.assert_not_called()

    def test_conflicting_uuid_rolls_back_without_mutation(self):
        with self._patch_connection()[0], self._patch_connection()[1], patch(
            "tareas.services.master_operation_service.reserve_operation",
            side_effect=MasterOperationConflict("conflict"),
        ), patch(
            "tareas.services.master_operation_service.complete_operation"
        ) as complete:
            with self.assertRaises(MasterOperationConflict):
                execute_master_mutation(
                    context=self.context,
                    metadata=self.metadata,
                    entity_type="LOCAL",
                    action="CREATE",
                    payload={"codigo": "different"},
                    mutate=lambda _cursor: self.fail("A conflict must not mutate."),
                )

        self.assertEqual(self.transaction_state["rollbacks"], 1)
        complete.assert_not_called()

    def test_mutation_error_rolls_back_operation_reservation(self):
        pending = _record(self.operation_id)
        with self._patch_connection()[0], self._patch_connection()[1], patch(
            "tareas.services.master_operation_service.reserve_operation",
            return_value=OperationReservation(pending, replayed=False),
        ), patch(
            "tareas.services.master_operation_service.complete_operation"
        ) as complete, patch(
            "tareas.services.master_operation_service.log_master_catalog_operation"
        ) as audit:
            with self.assertRaises(MasterCatalogConflict):
                execute_master_mutation(
                    context=self.context,
                    metadata=self.metadata,
                    entity_type="LOCAL",
                    action="CREATE",
                    payload={"codigo": "L-42"},
                    mutate=lambda _cursor: (_ for _ in ()).throw(
                        MasterCatalogConflict("duplicate")
                    ),
                )

        self.assertEqual(self.transaction_state["rollbacks"], 1)
        complete.assert_not_called()
        audit.assert_not_called()

    def test_audit_failure_is_explicit_and_does_not_repeat_mutation(self):
        pending = _record(self.operation_id)
        committed = _record(
            self.operation_id,
            status="COMMITTED",
            result_id=42,
            result_payload={"id": 42, "before": None, "after": {}, "changed_fields": []},
        )
        change = MasterMutationChange(42, None, {}, ())
        with self._patch_connection()[0], self._patch_connection()[1], patch(
            "tareas.services.master_operation_service.reserve_operation",
            return_value=OperationReservation(pending, replayed=False),
        ), patch(
            "tareas.services.master_operation_service.complete_operation",
            return_value=committed,
        ), patch(
            "tareas.services.master_operation_service.log_master_catalog_operation",
            side_effect=MasterCatalogAuditRetryableError("unavailable"),
        ), patch(
            "tareas.services.master_operation_service.mark_audit_status"
        ) as mark:
            result = execute_master_mutation(
                context=self.context,
                metadata=self.metadata,
                entity_type="LOCAL",
                action="CREATE",
                payload={"codigo": "L-42"},
                mutate=lambda _cursor: change,
            )

        self.assertEqual(result.id, 42)
        self.assertEqual(result.audit_status, "ERROR")
        self.assertEqual(result.audit_error_code, "RETRY_AUDIT_STORAGE")
        mark.assert_called_once()
        self.assertEqual(
            mark.call_args.kwargs["audit_error_code"],
            "RETRY_AUDIT_STORAGE",
        )

    def test_reconciliation_is_bounded_and_leaves_unknown_for_review(self):
        committed = _record(
            self.operation_id,
            status="COMMITTED",
            result_id=42,
            result_payload={"id": 42, "before": None, "after": {}, "changed_fields": []},
            audit_status="ERROR",
            audit_error_code="RETRY_AUDIT_STORAGE",
        )
        unknown = _record(
            uuid4(),
            status="UNKNOWN",
            audit_status="PENDING",
        )
        pending = _record(uuid4(), status="PENDING", audit_status="PENDING")
        with self._patch_connection()[0], self._patch_connection()[1], patch(
            "tareas.services.master_operation_service.list_pending_reconciliation",
            return_value=(committed, unknown, pending),
        ), patch(
            "tareas.services.master_operation_service.log_master_catalog_operation",
            return_value=SimpleNamespace(pk=102),
        ), patch(
            "tareas.services.master_operation_service.mark_audit_status"
        ):
            report = reconcile_master_operations(limit=3)

        self.assertEqual(report.scanned, 3)
        self.assertEqual(report.attempted, 1)
        self.assertEqual(report.confirmed, 1)
        self.assertEqual(report.unknown_operations, 1)
        self.assertEqual(report.pending_operations, 1)
        self.assertEqual(len(report.manual_review), 2)

    def test_commit_failure_is_reported_as_uncertain(self):
        @contextmanager
        def commit_error(_connection):
            yield
            raise TaskMutationCommitError("commit result unavailable")

        with patch(
            "tareas.services.master_catalog_common.bounded_mysql_lock_wait",
            side_effect=lambda _connection: nullcontext(),
        ), patch(
            "tareas.services.master_catalog_common.mysql_mutation_transaction",
            side_effect=commit_error,
        ):
            with self.assertRaises(MasterCatalogCommitUnknown):
                with mutation_transaction(self.connection):
                    pass

    def test_uncertain_commit_recovers_only_durable_committed_result(self):
        pending = _record(self.operation_id)
        committed = _record(
            self.operation_id,
            status="COMMITTED",
            result_id=42,
            result_payload={"id": 42, "changed_fields": []},
        )
        change = MasterMutationChange(42, None, {}, ())

        @contextmanager
        def uncertain_transaction(_connection):
            yield
            raise MasterCatalogCommitUnknown("commit result unavailable")

        with patch(
            "tareas.services.master_operation_service.verified_base_tareas_connection",
            side_effect=self._connection_context,
        ), patch(
            "tareas.services.master_operation_service.mutation_transaction",
            side_effect=uncertain_transaction,
        ), patch(
            "tareas.services.master_operation_service.reserve_operation",
            return_value=OperationReservation(pending, replayed=False),
        ), patch(
            "tareas.services.master_operation_service.complete_operation",
            return_value=committed,
        ), patch(
            "tareas.services.master_operation_service._recover_uncertain_operation",
            return_value=committed,
        ), patch(
            "tareas.services.master_operation_service._project_audit",
            return_value=SimpleNamespace(status="CONFIRMED", error_code=""),
        ):
            result = execute_master_mutation(
                context=self.context,
                metadata=self.metadata,
                entity_type="LOCAL",
                action="CREATE",
                payload={"codigo": "L-42"},
                mutate=lambda _cursor: change,
            )

        self.assertEqual(result.id, 42)
        self.assertTrue(result.replayed)

    def test_django_connection_commit_failure_is_reported_as_uncertain(self):
        @contextmanager
        def atomic_error(*, using):
            yield
            raise RuntimeError("commit result unavailable")

        connection = SimpleNamespace(alias="mysql_runtime")
        with patch(
            "tareas.services.master_catalog_common.bounded_mysql_lock_wait",
            side_effect=lambda _connection: nullcontext(),
        ), patch(
            "tareas.services.task_mutation_locks.transaction.atomic",
            side_effect=atomic_error,
        ):
            with self.assertRaises(MasterCatalogCommitUnknown):
                with mutation_transaction(connection):
                    pass
