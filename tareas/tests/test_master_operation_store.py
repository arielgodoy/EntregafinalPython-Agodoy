from uuid import uuid4

from django.test import SimpleTestCase

from tareas.services.master_operation_store import (
    MasterOperationConflict,
    MasterOperationValidationError,
    canonicalize_payload,
    complete_operation,
    hash_payload,
    list_pending_reconciliation,
    mark_audit_status,
    normalize_operation_id,
    reserve_operation,
)


class FakeCursor:
    def __init__(self):
        self.rows = {}
        self._one = None
        self._many = ()

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split()).upper()
        operation_id = str(params[0]) if params else None
        if normalized.startswith("SELECT") and "WHERE OPERATION_ID" in normalized:
            row = self.rows.get(operation_id)
            self._one = tuple(row) if row is not None else None
            return
        if normalized.startswith("SELECT") and "STATUS IN" in normalized:
            self._many = tuple(
                row
                for row in self.rows.values()
                if row[6] in {"COMMITTED", "UNKNOWN"} and row[9] != "CONFIRMED"
            )
            return
        if normalized.startswith("INSERT"):
            operation_id, entity_type, action, empresa_id, actor_id, payload_hash = params
            if operation_id in self.rows:
                error = RuntimeError("duplicate")
                error.args = (1062, "duplicate")
                raise error
            self.rows[operation_id] = [
                operation_id,
                entity_type,
                action,
                empresa_id,
                actor_id,
                payload_hash,
                "PENDING",
                None,
                None,
                "PENDING",
                None,
                "",
                None,
                None,
            ]
            return
        if normalized.startswith("UPDATE") and "STATUS = 'COMMITTED'" in normalized:
            result_id, result_payload, operation_id = params
            row = self.rows[operation_id]
            row[6] = "COMMITTED"
            row[7] = result_id
            row[8] = result_payload
            return
        if normalized.startswith("UPDATE") and "AUDIT_STATUS" in normalized:
            audit_status, audit_event_id, audit_error_code, operation_id = params
            row = self.rows[operation_id]
            row[9] = audit_status
            row[10] = audit_event_id
            row[11] = audit_error_code
            return
        raise AssertionError(f"SQL no contemplado por el doble: {sql}")

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many


class MasterOperationStoreTests(SimpleTestCase):
    def test_canonical_payload_and_hash_are_stable(self):
        first = {"name": "Proveedor", "tags": ["b", "a"]}
        second = {"tags": ["b", "a"], "name": "Proveedor"}
        self.assertEqual(canonicalize_payload(first), canonicalize_payload(second))
        self.assertEqual(hash_payload(first), hash_payload(second))
        self.assertNotEqual(hash_payload(first), hash_payload({"name": "Otro"}))

    def test_uuid_validation_rejects_nil_and_invalid_values(self):
        operation_id = uuid4()
        self.assertEqual(normalize_operation_id(str(operation_id)), operation_id)
        with self.assertRaises(MasterOperationValidationError):
            normalize_operation_id("not-a-uuid")
        with self.assertRaises(MasterOperationValidationError):
            normalize_operation_id("00000000-0000-0000-0000-000000000000")

    def test_reservation_replays_same_payload_and_rejects_different_identity(self):
        cursor = FakeCursor()
        operation_id = uuid4()
        reservation = reserve_operation(
            cursor,
            operation_id=operation_id,
            entity_type="PROVEEDOR",
            action="CREATE",
            empresa_id=10,
            actor_id=20,
            payload={"nombre": "Acme"},
        )
        self.assertFalse(reservation.replayed)
        replay = reserve_operation(
            cursor,
            operation_id=operation_id,
            entity_type="PROVEEDOR",
            action="CREATE",
            empresa_id=10,
            actor_id=20,
            payload={"nombre": "Acme"},
        )
        self.assertTrue(replay.replayed)
        with self.assertRaises(MasterOperationConflict):
            reserve_operation(
                cursor,
                operation_id=operation_id,
                entity_type="PROVEEDOR",
                action="UPDATE",
                empresa_id=10,
                actor_id=20,
                payload={"nombre": "Acme"},
            )

    def test_confirmed_result_is_recoverable_and_audit_can_be_confirmed(self):
        cursor = FakeCursor()
        operation_id = uuid4()
        reserve_operation(
            cursor,
            operation_id=operation_id,
            entity_type="LOCAL",
            action="CREATE",
            empresa_id=10,
            actor_id=20,
            payload={"codigo": "L1"},
        )
        committed = complete_operation(
            cursor,
            operation_id,
            result_id=99,
            result_payload={"id": 99, "codigo": "L1"},
        )
        self.assertEqual(committed.status, "COMMITTED")
        self.assertEqual(committed.result_payload, {"id": 99, "codigo": "L1"})
        audited = mark_audit_status(
            cursor,
            operation_id,
            audit_status="CONFIRMED",
            audit_event_id=123,
        )
        self.assertEqual(audited.audit_status, "CONFIRMED")
        self.assertEqual(list_pending_reconciliation(cursor), ())

    def test_invalid_audit_transition_is_rejected(self):
        cursor = FakeCursor()
        operation_id = uuid4()
        reserve_operation(
            cursor,
            operation_id=operation_id,
            entity_type="DEPARTAMENTO",
            action="UPDATE",
            empresa_id=10,
            actor_id=20,
            payload={"nombre": "Finanzas"},
        )
        with self.assertRaises(MasterOperationValidationError):
            mark_audit_status(
                cursor,
                operation_id,
                audit_status="CONFIRMED",
            )
        with self.assertRaises(MasterOperationValidationError):
            mark_audit_status(
                cursor,
                operation_id,
                audit_status="ERROR",
                audit_error_code="raw database exception",
            )
