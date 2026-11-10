"""Durable idempotency storage for Tareas master-catalog mutations."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping
from uuid import UUID

from .master_catalog_common import MasterCatalogError, verified_base_tareas_connection
from .task_mutation_locks import bounded_mysql_lock_wait, mysql_mutation_transaction


ENTITY_TYPES = frozenset({"PROVEEDOR", "LOCAL", "DEPARTAMENTO"})
ACTION_TYPES = frozenset({"CREATE", "UPDATE", "DELETE", "RESTORE"})
OPERATION_STATUSES = frozenset({"PENDING", "COMMITTED", "FAILED", "UNKNOWN"})
AUDIT_STATUSES = frozenset({"PENDING", "CONFIRMED", "ERROR"})
_ERROR_CODE_PATTERN = re.compile(r"^[A-Z0-9_.-]{1,64}$")


class MasterOperationError(MasterCatalogError):
    """Base error for the technical operation register."""


class MasterOperationValidationError(MasterOperationError):
    """Input or state does not satisfy the operation-register contract."""


class MasterOperationConflict(MasterOperationError):
    """The UUID is already associated with a different operation."""


class MasterOperationStorageError(MasterOperationError):
    """A safe storage failure while accessing the operation register."""


class MasterOperationNotFound(MasterOperationError):
    """The requested operation does not exist."""


class MasterOperationOutcomeUnknown(MasterOperationError):
    """A prior attempt has no confirmed result and must not be executed again."""


class MasterOperationPreviouslyFailed(MasterOperationError):
    """A prior operation with this UUID was recorded as failed."""


@dataclass(frozen=True)
class MasterOperationRecord:
    operation_id: UUID
    entity_type: str
    action: str
    empresa_id: int
    actor_id: int
    payload_hash: str
    status: str
    result_id: int | None
    result_payload: Any
    audit_status: str
    audit_event_id: int | None
    audit_error_code: str
    created_at: Any
    updated_at: Any


@dataclass(frozen=True)
class OperationReservation:
    record: MasterOperationRecord
    replayed: bool


def canonicalize_payload(payload: Mapping[str, Any]) -> str:
    """Serialize a JSON payload deterministically without volatile fields."""

    if not isinstance(payload, Mapping):
        raise MasterOperationValidationError("El payload debe ser un mapa.")
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise MasterOperationValidationError(
            "El payload no es serializable de forma canónica."
        ) from exc


def hash_payload(payload: Mapping[str, Any]) -> str:
    """Return the SHA-256 hash of the canonical operation payload."""

    canonical = canonicalize_payload(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalize_operation_id(operation_id: UUID | str) -> UUID:
    if isinstance(operation_id, str):
        try:
            operation_id = UUID(operation_id)
        except ValueError as exc:
            raise MasterOperationValidationError(
                "El identificador de operación no es un UUID válido."
            ) from exc
    if not isinstance(operation_id, UUID) or operation_id.int == 0:
        raise MasterOperationValidationError(
            "El identificador de operación no es válido."
        )
    return operation_id


def _positive_id(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MasterOperationValidationError(f"{field_name} no es válido.")
    return value


def _validate_identity(
    *,
    operation_id: UUID | str,
    entity_type: str,
    action: str,
    empresa_id: int,
    actor_id: int,
    payload: Mapping[str, Any],
) -> tuple[UUID, str]:
    operation_id = normalize_operation_id(operation_id)
    if entity_type not in ENTITY_TYPES:
        raise MasterOperationValidationError("El tipo de entidad no es válido.")
    if action not in ACTION_TYPES:
        raise MasterOperationValidationError("La acción no es válida.")
    _positive_id(empresa_id, "empresa_id")
    _positive_id(actor_id, "actor_id")
    return operation_id, hash_payload(payload)


def _json_value(value: object) -> Any:
    if value is None or isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise MasterOperationStorageError(
                "El resultado almacenado no tiene JSON válido."
            ) from exc
    raise MasterOperationStorageError("El resultado almacenado no es válido.")


def _record_from_row(row: tuple[object, ...]) -> MasterOperationRecord:
    if len(row) != 14:
        raise MasterOperationStorageError("La fila del registro técnico no coincide.")
    try:
        operation_id = UUID(str(row[0]))
    except (ValueError, TypeError) as exc:
        raise MasterOperationStorageError(
            "El registro técnico contiene un UUID inválido."
        ) from exc
    return MasterOperationRecord(
        operation_id=operation_id,
        entity_type=str(row[1]),
        action=str(row[2]),
        empresa_id=int(row[3]),
        actor_id=int(row[4]),
        payload_hash=str(row[5]),
        status=str(row[6]),
        result_id=int(row[7]) if row[7] is not None else None,
        result_payload=_json_value(row[8]),
        audit_status=str(row[9]),
        audit_event_id=int(row[10]) if row[10] is not None else None,
        audit_error_code=str(row[11] or ""),
        created_at=row[12],
        updated_at=row[13],
    )


_SELECT_COLUMNS = """
    operation_id, entity_type, action, empresa_id, actor_id, payload_hash,
    status, result_id, result_payload, audit_status, audit_event_id,
    audit_error_code, created_at, updated_at
"""


def _is_duplicate_error(exc: BaseException) -> bool:
    return getattr(exc, "errno", None) == 1062 or (
        getattr(exc, "args", ()) and getattr(exc, "args", ())[0] == 1062
    )


def _fetch_operation(cursor, operation_id: UUID, *, lock: bool) -> MasterOperationRecord | None:
    cursor.execute(
        f"SELECT {_SELECT_COLUMNS} FROM tareas_master_operation "
        "WHERE operation_id = %s" + (" FOR UPDATE" if lock else ""),
        (str(operation_id),),
    )
    row = cursor.fetchone()
    return _record_from_row(row) if row is not None else None


def _assert_same_identity(
    record: MasterOperationRecord,
    *,
    entity_type: str,
    action: str,
    empresa_id: int,
    actor_id: int,
    payload_hash: str,
) -> None:
    if (
        record.entity_type != entity_type
        or record.action != action
        or record.empresa_id != empresa_id
        or record.actor_id != actor_id
        or record.payload_hash != payload_hash
    ):
        raise MasterOperationConflict(
            "El UUID ya fue utilizado con una operación diferente."
        )


def reserve_operation(
    cursor,
    *,
    operation_id: UUID | str,
    entity_type: str,
    action: str,
    empresa_id: int,
    actor_id: int,
    payload: Mapping[str, Any],
) -> OperationReservation:
    """Reserve or replay an operation inside the caller's active transaction."""

    operation_id, payload_hash = _validate_identity(
        operation_id=operation_id,
        entity_type=entity_type,
        action=action,
        empresa_id=empresa_id,
        actor_id=actor_id,
        payload=payload,
    )
    existing = _fetch_operation(cursor, operation_id, lock=True)
    if existing is not None:
        _assert_same_identity(
            existing,
            entity_type=entity_type,
            action=action,
            empresa_id=empresa_id,
            actor_id=actor_id,
            payload_hash=payload_hash,
        )
        return OperationReservation(record=existing, replayed=True)

    try:
        cursor.execute(
            "INSERT INTO tareas_master_operation "
            "(operation_id, entity_type, action, empresa_id, actor_id, payload_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                str(operation_id),
                entity_type,
                action,
                empresa_id,
                actor_id,
                payload_hash,
            ),
        )
    except Exception as exc:
        if not _is_duplicate_error(exc):
            raise MasterOperationStorageError(
                "No se pudo reservar la operación."
            ) from exc
        existing = _fetch_operation(cursor, operation_id, lock=True)
        if existing is None:
            raise MasterOperationStorageError(
                "No se pudo recuperar la operación concurrente."
            ) from exc
        _assert_same_identity(
            existing,
            entity_type=entity_type,
            action=action,
            empresa_id=empresa_id,
            actor_id=actor_id,
            payload_hash=payload_hash,
        )
        return OperationReservation(record=existing, replayed=True)

    record = _fetch_operation(cursor, operation_id, lock=True)
    if record is None:
        raise MasterOperationStorageError(
            "La operación reservada no pudo recuperarse."
        )
    return OperationReservation(record=record, replayed=False)


def get_operation(cursor, operation_id: UUID | str, *, lock: bool = False) -> MasterOperationRecord:
    operation_id = normalize_operation_id(operation_id)
    record = _fetch_operation(cursor, operation_id, lock=lock)
    if record is None:
        raise MasterOperationNotFound("La operación no existe.")
    return record


def complete_operation(
    cursor,
    operation_id: UUID | str,
    *,
    result_id: int,
    result_payload: Mapping[str, Any],
) -> MasterOperationRecord:
    result_id = _positive_id(result_id, "result_id")
    canonical_result = canonicalize_payload(result_payload)
    operation_id = normalize_operation_id(operation_id)
    record = get_operation(cursor, operation_id, lock=True)
    if record.status != "PENDING":
        raise MasterOperationValidationError(
            "Solo una operación pendiente puede confirmarse."
        )
    cursor.execute(
        "UPDATE tareas_master_operation "
        "SET status = 'COMMITTED', result_id = %s, result_payload = %s "
        "WHERE operation_id = %s",
        (result_id, canonical_result, str(operation_id)),
    )
    return get_operation(cursor, operation_id, lock=True)


def fail_operation(
    cursor,
    operation_id: UUID | str,
    *,
    error_code: str,
) -> MasterOperationRecord:
    if not isinstance(error_code, str) or not _ERROR_CODE_PATTERN.fullmatch(error_code):
        raise MasterOperationValidationError("El código de error no es válido.")
    operation_id = normalize_operation_id(operation_id)
    record = get_operation(cursor, operation_id, lock=True)
    if record.status != "PENDING":
        raise MasterOperationValidationError(
            "Solo una operación pendiente puede marcarse como fallida."
        )
    cursor.execute(
        "UPDATE tareas_master_operation "
        "SET status = 'FAILED', result_payload = %s "
        "WHERE operation_id = %s",
        (json.dumps({"error_code": error_code}, separators=(",", ":")),
         str(operation_id)),
    )
    return get_operation(cursor, operation_id, lock=True)


def mark_unknown_operation(cursor, operation_id: UUID | str) -> MasterOperationRecord:
    operation_id = normalize_operation_id(operation_id)
    record = get_operation(cursor, operation_id, lock=True)
    if record.status not in {"PENDING", "UNKNOWN"}:
        raise MasterOperationValidationError(
            "Solo una operación pendiente puede quedar en estado UNKNOWN."
        )
    cursor.execute(
        "UPDATE tareas_master_operation SET status = 'UNKNOWN' "
        "WHERE operation_id = %s",
        (str(operation_id),),
    )
    return get_operation(cursor, operation_id, lock=True)


def mark_audit_status(
    cursor,
    operation_id: UUID | str,
    *,
    audit_status: str,
    audit_event_id: int | None = None,
    audit_error_code: str = "",
) -> MasterOperationRecord:
    operation_id = normalize_operation_id(operation_id)
    if audit_status not in AUDIT_STATUSES:
        raise MasterOperationValidationError("El estado de auditoría no es válido.")
    if audit_status == "CONFIRMED" and audit_event_id is None:
        raise MasterOperationValidationError(
            "La auditoría confirmada requiere identificador de evento."
        )
    if audit_status == "ERROR" and not _ERROR_CODE_PATTERN.fullmatch(
        audit_error_code
    ):
        raise MasterOperationValidationError(
            "La auditoría con error requiere un código sanitizado."
        )
    if audit_status != "ERROR" and audit_error_code:
        raise MasterOperationValidationError(
            "Solo una auditoría con error puede tener código de error."
        )
    if audit_event_id is not None:
        _positive_id(audit_event_id, "audit_event_id")
    record = get_operation(cursor, operation_id, lock=True)
    if record.audit_status == "CONFIRMED":
        if audit_status != "CONFIRMED" or audit_event_id != record.audit_event_id:
            raise MasterOperationValidationError(
                "Una auditoría confirmada no puede retroceder ni reemplazarse."
            )
        return record
    if audit_status == "PENDING" and record.audit_status == "ERROR":
        raise MasterOperationValidationError(
            "Una auditoría con error no puede volver a estado pendiente."
        )
    cursor.execute(
        "UPDATE tareas_master_operation "
        "SET audit_status = %s, audit_event_id = %s, audit_error_code = %s "
        "WHERE operation_id = %s AND audit_status <> 'CONFIRMED'",
        (audit_status, audit_event_id, audit_error_code, str(operation_id)),
    )
    updated = get_operation(cursor, operation_id, lock=True)
    if updated.audit_status == "CONFIRMED" and audit_status != "CONFIRMED":
        raise MasterOperationValidationError(
            "La auditoría fue confirmada concurrentemente y no puede retroceder."
        )
    return updated


def list_pending_reconciliation(cursor, *, limit: int = 100) -> tuple[MasterOperationRecord, ...]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise MasterOperationValidationError("El límite de reconciliación no es válido.")
    cursor.execute(
        f"SELECT {_SELECT_COLUMNS} FROM tareas_master_operation "
        "WHERE status IN ('PENDING', 'COMMITTED', 'UNKNOWN') "
        "AND audit_status <> 'CONFIRMED' "
        "ORDER BY updated_at, operation_id LIMIT %s",
        (limit,),
    )
    return tuple(_record_from_row(row) for row in cursor.fetchall())


@contextmanager
def master_operation_transaction(connection) -> Iterator[None]:
    """Run storage and future master mutation in one InnoDB transaction."""

    with bounded_mysql_lock_wait(connection):
        with mysql_mutation_transaction(connection):
            yield


@contextmanager
def verified_master_operation_connection() -> Iterator[object]:
    """Open the already verified BASE_TAREAS connection for this storage."""

    with verified_base_tareas_connection() as connection:
        yield connection


__all__ = [
    "ACTION_TYPES",
    "AUDIT_STATUSES",
    "ENTITY_TYPES",
    "MasterOperationConflict",
    "MasterOperationError",
    "MasterOperationNotFound",
    "MasterOperationOutcomeUnknown",
    "MasterOperationPreviouslyFailed",
    "MasterOperationRecord",
    "MasterOperationStorageError",
    "MasterOperationValidationError",
    "OPERATION_STATUSES",
    "OperationReservation",
    "canonicalize_payload",
    "complete_operation",
    "fail_operation",
    "get_operation",
    "hash_payload",
    "list_pending_reconciliation",
    "mark_audit_status",
    "mark_unknown_operation",
    "master_operation_transaction",
    "normalize_operation_id",
    "reserve_operation",
    "verified_master_operation_connection",
]
