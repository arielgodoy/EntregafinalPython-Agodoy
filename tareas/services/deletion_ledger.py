"""Transactional persistence boundary for future permanent task deletion."""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import re
from typing import Generator, Mapping, Protocol, TypeGuard
from uuid import UUID, uuid4

from django.db import IntegrityError, connections, transaction
from django.utils import timezone

from settings.services.mysql_connections import (
    MySQLConnectionOpenError,
    open_mysql_connection,
)

from ..models import (
    LOGICAL_DELETION_RESULT_CODE,
    LOGICAL_RESTORATION_RESULT_CODE,
    Tarea,
    TareaEliminacionArchivo,
    TareaEliminacionElemento,
    TareaEliminacionOperacion,
)
from .base_tareas_schema import (
    get_deletion_item_models,
    get_deletion_ledger_models,
)
from .connection_roles import TareaConnectionError, resolve_operational_backend


class DeletionLedgerError(RuntimeError):
    """Base error for the deletion ledger."""


class DeletionLedgerConflict(DeletionLedgerError):
    """An idempotency key or manifest was reused with different data."""


class DeletionLedgerSchemaError(DeletionLedgerError):
    """The operational database is missing the required transactional schema."""


class DeletionLedgerBackendError(DeletionLedgerError):
    """The selected operational database cannot provide the required guarantees."""


class DeletionLedgerCommitUncertain(DeletionLedgerError):
    """The transaction outcome must be resolved by operation_id before retrying."""


class DeletionLedgerStateError(DeletionLedgerError):
    """An operation state transition is not valid."""


@dataclass(frozen=True)
class DeletionOperationInput:
    actor_id: int
    empresa_id: int
    root_task_id: int
    root_correlativo: str
    fingerprint: str
    dependency_summary: Mapping[str, int]
    operation_id: UUID = field(default_factory=uuid4)
    motivo: str = ""


@dataclass(frozen=True)
class RestorationOperationInput:
    actor_id: int
    empresa_id: int
    reverses_operation_id: UUID
    fingerprint: str
    manifest: tuple["DeletionInventoryItem", ...]
    operation_id: UUID = field(default_factory=uuid4)
    motivo: str = ""


@dataclass(frozen=True, order=True)
class DeletionInventoryItem:
    model_label: str
    object_id: int


@dataclass(frozen=True, order=True)
class DeletionFileReference:
    storage_key: str
    file_name: str


@dataclass(frozen=True)
class DeletionOperationRecord:
    operation_id: UUID
    actor_id: int
    empresa_id: int
    root_task_id: int
    root_correlativo: str
    backend_type: str
    backend_identity: str
    backend_config_version: str
    fingerprint: str
    dependency_summary: dict[str, int]
    status: str
    result_code: str
    audit_status: str
    audit_attempts: int
    audit_last_attempt_at: datetime | None
    audit_event_id: int | None
    audit_error_code: str
    file_cleanup_status: str
    created_at: datetime
    updated_at: datetime
    committed_at: datetime | None
    motivo: str | None = None
    reverses_operation_id: UUID | None = None


@dataclass(frozen=True)
class DeletionFileRecord:
    operation_id: UUID
    storage_key: str
    file_name: str
    status: str
    attempts: int
    last_attempt_at: datetime | None
    error_code: str


_FINGERPRINT = re.compile(r"^[0-9a-fA-F]{64}$")
_SAFE_CODE = re.compile(r"^[A-Z0-9_.-]{1,64}$")
_SUMMARY_KEY = re.compile(r"^[a-z0-9_.-]{1,64}$")
_STORAGE_KEY = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_PENDING_LIMIT = 500
_DELETE_RESULT = "DELETED"
_OPERATION_COLUMNS = (
    "operation_id",
    "actor_id",
    "empresa_id",
    "root_task_id",
    "root_correlativo",
    "backend_type",
    "backend_identity",
    "backend_config_version",
    "fingerprint",
    "dependency_summary",
    "status",
    "result_code",
    "audit_status",
    "audit_attempts",
    "audit_last_attempt_at",
    "audit_event_id",
    "audit_error_code",
    "file_cleanup_status",
    "created_at",
    "updated_at",
    "committed_at",
    "motivo",
)
_OPERATION_COLUMN_SQL = ", ".join(f"`{name}`" for name in _OPERATION_COLUMNS)
_RESTORATION_OPERATION_COLUMNS = (*_OPERATION_COLUMNS, "reverses_operation_id")
_RESTORATION_OPERATION_COLUMN_SQL = ", ".join(
    f"`{name}`" for name in _RESTORATION_OPERATION_COLUMNS
)


class _DBAPICursor(Protocol):
    rowcount: int

    def execute(self, sql: str, params: object = ()) -> object: ...

    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...

    def close(self) -> None: ...


class _CursorConnection(Protocol):
    def cursor(self) -> _DBAPICursor: ...


class _TransactionalMySQLConnection(_CursorConnection, Protocol):
    def begin(self) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def _is_dbapi_cursor(value: object) -> TypeGuard[_DBAPICursor]:
    return all(
        callable(getattr(value, method, None))
        for method in ("execute", "fetchone", "fetchall", "close")
    )


def _is_cursor_connection(value: object) -> TypeGuard[_CursorConnection]:
    return callable(getattr(value, "cursor", None))


def _cursor_from_connection(value: object) -> _DBAPICursor:
    cursor_factory = getattr(value, "cursor", None)
    if not callable(cursor_factory):
        raise DeletionLedgerBackendError(
            "La conexión MySQL no ofrece un cursor."
        )
    cursor = cursor_factory()
    if not _is_dbapi_cursor(cursor):
        raise DeletionLedgerBackendError(
            "El cursor MySQL no ofrece las operaciones requeridas."
        )
    return cursor


def _is_transactional_mysql_connection(
    value: object,
) -> TypeGuard[_TransactionalMySQLConnection]:
    return all(
        callable(getattr(value, method, None))
        for method in ("cursor", "begin", "commit", "rollback")
    )


def _positive_id(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} debe ser un entero positivo.")
    return value


def _normalize_operation(operation: DeletionOperationInput) -> DeletionOperationInput:
    if not isinstance(operation, DeletionOperationInput):
        raise TypeError("operation debe ser DeletionOperationInput.")
    try:
        operation_id = (
            operation.operation_id
            if isinstance(operation.operation_id, UUID)
            else UUID(str(operation.operation_id))
        )
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("operation_id no es un UUID válido.") from exc
    _positive_id(operation.actor_id, "actor_id")
    _positive_id(operation.empresa_id, "empresa_id")
    _positive_id(operation.root_task_id, "root_task_id")
    if (
        not isinstance(operation.root_correlativo, str)
        or not operation.root_correlativo
        or len(operation.root_correlativo) > 9
    ):
        raise ValueError("root_correlativo no es válido.")
    if not isinstance(operation.fingerprint, str) or not _FINGERPRINT.fullmatch(
        operation.fingerprint
    ):
        raise ValueError("fingerprint debe ser SHA-256 hexadecimal.")
    if not isinstance(operation.dependency_summary, Mapping):
        raise ValueError("dependency_summary debe ser un mapa de cantidades.")
    summary = {}
    for key, count in operation.dependency_summary.items():
        if not isinstance(key, str) or not _SUMMARY_KEY.fullmatch(key):
            raise ValueError("dependency_summary contiene una clave no válida.")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("dependency_summary contiene una cantidad no válida.")
        summary[key] = count
    if len(summary) > 64:
        raise ValueError("dependency_summary contiene demasiadas categorías.")
    if not isinstance(operation.motivo, str):
        raise ValueError("motivo debe ser texto.")
    return DeletionOperationInput(
        actor_id=operation.actor_id,
        empresa_id=operation.empresa_id,
        root_task_id=operation.root_task_id,
        root_correlativo=operation.root_correlativo,
        fingerprint=operation.fingerprint.lower(),
        dependency_summary=dict(sorted(summary.items())),
        operation_id=operation_id,
        motivo=operation.motivo.strip(),
    )


def _normalize_restoration_operation(
    operation: RestorationOperationInput,
) -> RestorationOperationInput:
    if not isinstance(operation, RestorationOperationInput):
        raise TypeError("operation debe ser RestorationOperationInput.")
    try:
        operation_id = (
            operation.operation_id
            if isinstance(operation.operation_id, UUID)
            else UUID(str(operation.operation_id))
        )
        reverses_operation_id = (
            operation.reverses_operation_id
            if isinstance(operation.reverses_operation_id, UUID)
            else UUID(str(operation.reverses_operation_id))
        )
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Los UUID de restauración no son válidos.") from exc
    if operation_id == reverses_operation_id:
        raise ValueError("Una restauración no puede reutilizar el UUID de eliminación.")
    _positive_id(operation.actor_id, "actor_id")
    _positive_id(operation.empresa_id, "empresa_id")
    if not isinstance(operation.fingerprint, str) or not _FINGERPRINT.fullmatch(
        operation.fingerprint
    ):
        raise ValueError("fingerprint debe ser SHA-256 hexadecimal.")
    if not isinstance(operation.motivo, str) or not operation.motivo.strip():
        raise ValueError("El motivo de restauración es obligatorio.")
    if not isinstance(operation.manifest, (tuple, list)):
        raise ValueError("manifest debe ser una secuencia de elementos.")
    return RestorationOperationInput(
        actor_id=operation.actor_id,
        empresa_id=operation.empresa_id,
        reverses_operation_id=reverses_operation_id,
        fingerprint=operation.fingerprint.lower(),
        manifest=tuple(operation.manifest),
        operation_id=operation_id,
        motivo=operation.motivo.strip(),
    )


def _normalize_manifest(
    items: tuple[DeletionInventoryItem, ...] | list[DeletionInventoryItem],
    files: tuple[DeletionFileReference, ...] | list[DeletionFileReference],
    root_task_id: int,
) -> tuple[tuple[DeletionInventoryItem, ...], tuple[DeletionFileReference, ...]]:
    allowed_labels = {
        model._meta.label_lower for model in get_deletion_item_models()
    }
    normalized_items = []
    for item in items:
        if not isinstance(item, DeletionInventoryItem):
            raise TypeError("Cada elemento debe ser DeletionInventoryItem.")
        if item.model_label not in allowed_labels:
            raise ValueError("El manifiesto contiene un tipo de modelo no permitido.")
        normalized_items.append(
            DeletionInventoryItem(
                model_label=item.model_label,
                object_id=_positive_id(item.object_id, "object_id"),
            )
        )
    if len(set(normalized_items)) != len(normalized_items):
        raise ValueError("El manifiesto contiene elementos duplicados.")
    if DeletionInventoryItem("tareas.tarea", root_task_id) not in normalized_items:
        raise ValueError("El manifiesto debe incluir la tarea raíz.")

    normalized_files = []
    for file_reference in files:
        if not isinstance(file_reference, DeletionFileReference):
            raise TypeError("Cada archivo debe ser DeletionFileReference.")
        if (
            not isinstance(file_reference.storage_key, str)
            or not _STORAGE_KEY.fullmatch(file_reference.storage_key)
        ):
            raise ValueError("storage_key no es válido.")
        if (
            not isinstance(file_reference.file_name, str)
            or not file_reference.file_name
            or len(file_reference.file_name) > 500
            or "\x00" in file_reference.file_name
        ):
            raise ValueError("file_name no es válido.")
        normalized_files.append(file_reference)
    if len(set(normalized_files)) != len(normalized_files):
        raise ValueError("El manifiesto de archivos contiene referencias duplicadas.")
    return tuple(sorted(normalized_items)), tuple(sorted(normalized_files))


def _normalize_restoration_manifest(
    items: tuple[DeletionInventoryItem, ...] | list[DeletionInventoryItem],
    *,
    root_task_id: int,
    source_manifest: tuple[DeletionInventoryItem, ...],
) -> tuple[DeletionInventoryItem, ...]:
    normalized_items, normalized_files = _normalize_manifest(
        items,
        (),
        root_task_id,
    )
    if normalized_files or any(
        item.model_label != "tareas.tarea" for item in normalized_items
    ):
        raise DeletionLedgerStateError(
            "El manifiesto de restauración solo admite tareas."
        )
    if not source_manifest or any(
        item.model_label != "tareas.tarea" for item in source_manifest
    ):
        raise DeletionLedgerSchemaError(
            "El manifiesto de eliminación no contiene solo tareas."
        )
    if (
        DeletionInventoryItem("tareas.tarea", root_task_id)
        not in source_manifest
        or normalized_items != tuple(sorted(source_manifest))
    ):
        raise DeletionLedgerConflict(
            "El manifiesto de restauración debe coincidir exactamente con la eliminación."
        )
    return normalized_items


def _reference_hash(file_reference: DeletionFileReference) -> str:
    value = f"{file_reference.storage_key}\0{file_reference.file_name}".encode(
        "utf-8"
    )
    return hashlib.sha256(value).hexdigest()


def _summary_json(summary: Mapping[str, int]) -> str:
    return json.dumps(summary, sort_keys=True, separators=(",", ":"))


def _summary_from_json(value) -> dict[str, int]:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    try:
        result = json.loads(value or "{}")
    except (TypeError, ValueError) as exc:
        raise DeletionLedgerSchemaError(
            "El resumen almacenado del ledger no es válido."
        ) from exc
    if not isinstance(result, dict) or any(
        not isinstance(key, str)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
        for key, count in result.items()
    ):
        raise DeletionLedgerSchemaError(
            "El resumen almacenado del ledger no es válido."
        )
    return result


def _operation_record_from_model(model) -> DeletionOperationRecord:
    reverses_operation_id = getattr(model, "reverses_operation_id", None)
    return DeletionOperationRecord(
        operation_id=(
            model.operation_id
            if isinstance(model.operation_id, UUID)
            else UUID(str(model.operation_id))
        ),
        actor_id=model.actor_id,
        empresa_id=model.empresa_id,
        root_task_id=model.root_task_id,
        root_correlativo=model.root_correlativo,
        backend_type=model.backend_type,
        backend_identity=model.backend_identity,
        backend_config_version=model.backend_config_version,
        fingerprint=model.fingerprint,
        dependency_summary=_summary_from_json(model.dependency_summary),
        status=model.status,
        result_code=model.result_code,
        audit_status=model.audit_status,
        audit_attempts=model.audit_attempts,
        audit_last_attempt_at=model.audit_last_attempt_at,
        audit_event_id=model.audit_event_id,
        audit_error_code=model.audit_error_code,
        file_cleanup_status=model.file_cleanup_status,
        created_at=model.created_at,
        updated_at=model.updated_at,
        committed_at=model.committed_at,
        motivo=model.motivo,
        reverses_operation_id=(
            UUID(str(reverses_operation_id))
            if reverses_operation_id is not None
            else None
        ),
    )


def _operation_record_from_row(
    row,
    *,
    columns: tuple[str, ...] = _OPERATION_COLUMNS,
) -> DeletionOperationRecord:
    values = dict(zip(columns, row))
    operation_id = values["operation_id"]
    motivo = values["motivo"]
    reverses_operation_id = values.get("reverses_operation_id")
    if isinstance(motivo, bytes):
        motivo = motivo.decode("utf-8")
    if motivo is not None and not isinstance(motivo, str):
        raise DeletionLedgerSchemaError("El motivo del ledger no es texto.")
    return DeletionOperationRecord(
        operation_id=operation_id
        if isinstance(operation_id, UUID)
        else UUID(str(operation_id)),
        actor_id=values["actor_id"],
        empresa_id=values["empresa_id"],
        root_task_id=values["root_task_id"],
        root_correlativo=values["root_correlativo"],
        backend_type=values["backend_type"],
        backend_identity=values["backend_identity"],
        backend_config_version=values["backend_config_version"],
        fingerprint=values["fingerprint"],
        dependency_summary=_summary_from_json(values["dependency_summary"]),
        status=values["status"],
        result_code=values["result_code"],
        audit_status=values["audit_status"],
        audit_attempts=values["audit_attempts"],
        audit_last_attempt_at=values["audit_last_attempt_at"],
        audit_event_id=values["audit_event_id"],
        audit_error_code=values["audit_error_code"],
        file_cleanup_status=values["file_cleanup_status"],
        created_at=values["created_at"],
        updated_at=values["updated_at"],
        committed_at=values["committed_at"],
        motivo=motivo,
        reverses_operation_id=(
            UUID(str(reverses_operation_id))
            if reverses_operation_id is not None
            else None
        ),
    )


def _validate_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_PENDING_LIMIT:
        raise ValueError(f"limit debe estar entre 1 y {_MAX_PENDING_LIMIT}.")
    return limit


def _validate_result_code(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_CODE.fullmatch(value):
        raise ValueError(f"{field_name} no es un código válido.")
    return value


def _item_model_map():
    return {
        model._meta.label_lower: model for model in get_deletion_item_models()
    }


def _required_tables():
    return tuple(
        model._meta.db_table
        for model in (*get_deletion_item_models(), *get_deletion_ledger_models())
    )


def _mysql_identifier(value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise DeletionLedgerSchemaError("El contrato del ledger contiene un identificador no válido.")
    return f"`{value}`"


def _mysql_field_identifier(model, field_name: str) -> str:
    column = model._meta.get_field(field_name).column
    if column is None:
        raise DeletionLedgerSchemaError(
            "El contrato del ledger contiene una columna sin nombre físico."
        )
    return _mysql_identifier(column)


def _mysql_primary_key_identifier(model) -> str:
    column = model._meta.pk.column
    if column is None:
        raise DeletionLedgerSchemaError(
            "El esquema del ledger contiene una PK sin nombre físico."
        )
    return _mysql_identifier(column)


def _database_string(value: object, field_name: str) -> str:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DeletionLedgerSchemaError(
                f"El campo {field_name} del ledger no es texto UTF-8."
            ) from exc
    if not isinstance(value, str):
        raise DeletionLedgerSchemaError(
            f"El campo {field_name} del ledger no es texto."
        )
    return value


def _database_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DeletionLedgerSchemaError(
            f"El campo {field_name} del ledger no es entero."
        )
    return value


def _database_datetime(
    value: object,
    field_name: str,
) -> datetime | None:
    if value is not None and not isinstance(value, datetime):
        raise DeletionLedgerSchemaError(
            f"El campo {field_name} del ledger no es una fecha válida."
        )
    return value


def _check_mysql_transactional_tables(
    connection: object,
    database_name: str,
) -> None:
    tables = tuple(dict.fromkeys(_required_tables()))
    placeholders = ", ".join("%s" for _ in tables)
    cursor = _cursor_from_connection(connection)
    try:
        cursor.execute("SELECT DATABASE()")
        selected_database = cursor.fetchone()
        if not selected_database or selected_database[0] != database_name:
            raise DeletionLedgerBackendError(
                "La conexión no está seleccionada sobre la base de BASE_TAREAS."
            )
        cursor.execute(
            "SELECT table_name, engine FROM information_schema.tables "
            f"WHERE table_schema = %s AND table_name IN ({placeholders})",
            (database_name, *tables),
        )
        found = {
            table_name: engine
            for table_name, engine in cursor.fetchall()
        }
        missing = set(tables) - set(found)
        if missing:
            raise DeletionLedgerSchemaError(
                "Faltan tablas operacionales o del ledger en BASE_TAREAS."
            )
        if any(str(engine).casefold() != "innodb" for engine in found.values()):
            raise DeletionLedgerBackendError(
                "Todas las tablas afectadas deben utilizar InnoDB."
            )
        cursor.execute(
            "SELECT support FROM information_schema.engines "
            "WHERE engine = 'InnoDB' LIMIT 1"
        )
        engine = cursor.fetchone()
        if not engine or str(engine[0]).upper() not in {"YES", "DEFAULT"}:
            raise DeletionLedgerBackendError(
                "El servidor no ofrece transacciones InnoDB."
            )
        required_columns = _required_logical_deletion_columns()
        column_tables = tuple(required_columns)
        column_placeholders = ", ".join("%s" for _ in column_tables)
        cursor.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            f"WHERE table_schema = %s AND table_name IN ({column_placeholders})",
            (database_name, *column_tables),
        )
        existing_columns = {
            (str(table_name), str(column_name))
            for table_name, column_name in cursor.fetchall()
        }
        missing_columns = {
            (table_name, column_name)
            for table_name, columns in required_columns.items()
            for column_name in columns
            if (table_name, column_name) not in existing_columns
        }
        if missing_columns:
            raise DeletionLedgerSchemaError(
                "Faltan columnas requeridas para el ledger de eliminación lógica."
            )
    finally:
        cursor.close()


def _check_mysql_restoration_schema(
    connection: object,
    database_name: str,
) -> None:
    if database_name != "tareas":
        raise DeletionLedgerBackendError(
            "El ledger de restauración solo está habilitado sobre la base tareas."
        )
    table = TareaEliminacionOperacion._meta.db_table
    column = TareaEliminacionOperacion._meta.get_field(
        "reverses_operation"
    ).column
    cursor = _cursor_from_connection(connection)
    try:
        cursor.execute("SELECT DATABASE()")
        selected_database = cursor.fetchone()
        if not selected_database or selected_database[0] != database_name:
            raise DeletionLedgerBackendError(
                "La conexión no está seleccionada sobre la base autorizada tareas."
            )
        cursor.execute(
            "SELECT engine FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s",
            (database_name, table),
        )
        table_row = cursor.fetchone()
        if not table_row or str(table_row[0]).casefold() != "innodb":
            raise DeletionLedgerSchemaError(
                "La tabla de operaciones no está disponible en InnoDB."
            )
        cursor.execute(
            "SELECT data_type, character_maximum_length, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
            (database_name, table, column),
        )
        column_row = cursor.fetchone()
        if (
            not column_row
            or str(column_row[0]).casefold() not in {"char", "varchar"}
            or int(column_row[1] or 0) != 32
            or str(column_row[2]).upper() != "YES"
        ):
            raise DeletionLedgerSchemaError(
                "La referencia de restauración no tiene el tipo o nullabilidad esperados."
            )
        cursor.execute(
            "SELECT index_name, non_unique, column_name "
            "FROM information_schema.statistics "
            "WHERE table_schema = %s AND table_name = %s "
            "ORDER BY index_name, seq_in_index",
            (database_name, table),
        )
        unique_rows = cursor.fetchall()
        indexes: dict[str, tuple[int, list[str]]] = {}
        for index_name, non_unique, column_name in unique_rows:
            key = str(index_name)
            if key not in indexes:
                indexes[key] = (int(non_unique), [])
            indexes[key][1].append(str(column_name))
        if not any(
            non_unique == 0 and columns == [column]
            for non_unique, columns in indexes.values()
        ):
            raise DeletionLedgerSchemaError(
                "La referencia de restauración no está protegida por unicidad."
            )
        cursor.execute(
            "SELECT kcu.referenced_table_name, kcu.referenced_column_name, "
            "rc.delete_rule, rc.update_rule "
            "FROM information_schema.key_column_usage AS kcu "
            "JOIN information_schema.referential_constraints AS rc "
            "ON rc.constraint_schema = kcu.constraint_schema "
            "AND rc.table_name = kcu.table_name "
            "AND rc.constraint_name = kcu.constraint_name "
            "WHERE kcu.table_schema = %s AND kcu.table_name = %s "
            "AND kcu.column_name = %s AND kcu.referenced_table_name IS NOT NULL",
            (database_name, table, column),
        )
        foreign_key_rows = cursor.fetchall()
        if not any(
            str(row[0]) == table
            and str(row[1])
            == TareaEliminacionOperacion._meta.pk.column
            and str(row[2]).upper() in {"RESTRICT", "NO ACTION"}
            and str(row[3]).upper() in {"RESTRICT", "NO ACTION"}
            for row in foreign_key_rows
        ):
            raise DeletionLedgerSchemaError(
                "La referencia de restauración debe proteger el ledger de origen."
            )
    finally:
        cursor.close()


def _required_logical_deletion_columns() -> dict[str, tuple[str, ...]]:
    return {
        Tarea._meta.db_table: tuple(
            Tarea._meta.get_field(field_name).column
            for field_name in (
                "eliminada",
                "eliminada_en",
                "eliminada_por",
                "eliminacion_operacion_id",
            )
        ),
        TareaEliminacionOperacion._meta.db_table: (
            TareaEliminacionOperacion._meta.get_field("motivo").column,
        ),
    }


def _check_django_schema(alias: str) -> None:
    connection = connections[alias]
    if not connection.features.supports_transactions:
        raise DeletionLedgerBackendError(
            "El backend Django de BASE_TAREAS no soporta transacciones."
        )
    try:
        existing = set(connection.introspection.table_names())
    except Exception as exc:
        raise DeletionLedgerSchemaError(
            "No se pudo verificar el esquema de BASE_TAREAS."
        ) from exc
    if set(_required_tables()) - existing:
        raise DeletionLedgerSchemaError(
            "Faltan tablas operacionales o del ledger en BASE_TAREAS."
        )
    required_columns = _required_logical_deletion_columns()
    try:
        with connection.cursor() as cursor:
            missing_columns = {
                (table_name, column_name)
                for table_name, columns in required_columns.items()
                for column_name in columns
                if column_name
                not in {
                    column.name
                    for column in connection.introspection.get_table_description(
                        cursor,
                        table_name,
                    )
                }
            }
    except Exception as exc:
        raise DeletionLedgerSchemaError(
            "No se pudo verificar el esquema del ledger de eliminación."
        ) from exc
    if missing_columns:
        raise DeletionLedgerSchemaError(
            "Faltan columnas requeridas para el ledger de eliminación lógica."
        )
    if connection.vendor == "mysql":
        _check_mysql_transactional_tables(
            connection,
            connection.settings_dict["NAME"],
        )


def _operation_values(operation, backend_type, backend_identity, config_version):
    return {
        "actor_id": operation.actor_id,
        "empresa_id": operation.empresa_id,
        "root_task_id": operation.root_task_id,
        "root_correlativo": operation.root_correlativo,
        "backend_type": backend_type,
        "backend_identity": backend_identity,
        "backend_config_version": config_version,
        "fingerprint": operation.fingerprint,
        "dependency_summary": _summary_json(operation.dependency_summary),
        "motivo": operation.motivo,
    }


def _restoration_operation_values(
    operation: RestorationOperationInput,
    *,
    source: DeletionOperationRecord,
    manifest: tuple[DeletionInventoryItem, ...],
    backend_type: str,
    backend_identity: str,
    config_version: str,
):
    return _operation_values(
        DeletionOperationInput(
            actor_id=operation.actor_id,
            empresa_id=operation.empresa_id,
            root_task_id=source.root_task_id,
            root_correlativo=source.root_correlativo,
            fingerprint=operation.fingerprint,
            dependency_summary={"tareas.tarea": len(manifest)},
            operation_id=operation.operation_id,
            motivo=operation.motivo,
        ),
        backend_type,
        backend_identity,
        config_version,
    ) | {
        "reverses_operation_id": source.operation_id.hex,
        "status": TareaEliminacionOperacion.Estado.PENDIENTE,
        "result_code": "",
        "audit_status": TareaEliminacionOperacion.EstadoAuditoria.NO_ENCOLADA,
        "audit_attempts": 0,
        "audit_last_attempt_at": None,
        "audit_event_id": None,
        "audit_error_code": "",
        "file_cleanup_status": TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA,
        "committed_at": None,
    }


def _assert_operation_matches(model, operation, backend_type, backend_identity, config_version):
    expected = _operation_values(
        operation,
        backend_type,
        backend_identity,
        config_version,
    )
    actual = {
        key: getattr(model, key)
        for key in expected
    }
    if actual != expected:
        raise DeletionLedgerConflict(
            "operation_id ya existe con datos diferentes."
        )


def _assert_restoration_source(
    operation: RestorationOperationInput,
    source: DeletionOperationRecord | None,
    *,
    backend_type: str,
    backend_identity: str,
    config_version: str,
) -> DeletionOperationRecord:
    if source is None:
        raise DeletionLedgerStateError(
            "La operación de eliminación que se intenta revertir no existe."
        )
    if source.operation_id == operation.operation_id:
        raise DeletionLedgerConflict(
            "Una restauración debe usar un UUID nuevo."
        )
    if source.reverses_operation_id is not None:
        raise DeletionLedgerStateError(
            "La operación origen ya es una restauración lógica."
        )
    if source.empresa_id != operation.empresa_id:
        raise DeletionLedgerConflict(
            "La operación de eliminación pertenece a otra empresa."
        )
    if (
        source.status != TareaEliminacionOperacion.Estado.COMMITTED
        or source.result_code != LOGICAL_DELETION_RESULT_CODE
        or source.file_cleanup_status
        != TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA
        or not source.motivo
        or not source.motivo.strip()
        or source.backend_type != backend_type
        or source.backend_identity != backend_identity
        or source.backend_config_version != config_version
    ):
        raise DeletionLedgerStateError(
            "La operación de origen no es una eliminación lógica vigente en BASE_TAREAS."
        )
    return source


def _assert_restoration_operation_matches(
    model,
    operation: RestorationOperationInput,
    *,
    source: DeletionOperationRecord,
    manifest: tuple[DeletionInventoryItem, ...],
    backend_type: str,
    backend_identity: str,
    config_version: str,
) -> DeletionOperationRecord:
    expected = _restoration_operation_values(
        operation,
        source=source,
        manifest=manifest,
        backend_type=backend_type,
        backend_identity=backend_identity,
        config_version=config_version,
    )
    payload_fields = (
        "actor_id",
        "empresa_id",
        "root_task_id",
        "root_correlativo",
        "backend_type",
        "backend_identity",
        "backend_config_version",
        "fingerprint",
        "dependency_summary",
        "motivo",
        "reverses_operation_id",
    )
    expected_payload = {key: expected[key] for key in payload_fields}
    actual = {key: getattr(model, key) for key in payload_fields}
    if isinstance(model, DeletionOperationRecord):
        expected_payload["dependency_summary"] = _summary_from_json(
            expected_payload["dependency_summary"]
        )
        actual["reverses_operation_id"] = (
            model.reverses_operation_id.hex
            if model.reverses_operation_id is not None
            else None
        )
    if (
        UUID(str(model.operation_id)) != operation.operation_id
        or actual != expected_payload
    ):
        raise DeletionLedgerConflict(
            "operation_id ya existe con datos diferentes."
        )
    pending_audit_states = {
        TareaEliminacionOperacion.EstadoAuditoria.NO_ENCOLADA,
    }
    committed_audit_states = {
        TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
        TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
        TareaEliminacionOperacion.EstadoAuditoria.ERROR,
    }
    if (
        model.status
        not in {
            TareaEliminacionOperacion.Estado.PENDIENTE,
            TareaEliminacionOperacion.Estado.COMMITTED,
        }
        or (
            model.status == TareaEliminacionOperacion.Estado.PENDIENTE
            and model.result_code != ""
        )
        or (
            model.status == TareaEliminacionOperacion.Estado.COMMITTED
            and model.result_code != LOGICAL_RESTORATION_RESULT_CODE
        )
        or model.file_cleanup_status
        != TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA
        or model.audit_status
        not in (
            pending_audit_states
            if model.status == TareaEliminacionOperacion.Estado.PENDIENTE
            else committed_audit_states
        )
    ):
        raise DeletionLedgerStateError(
            "El estado persistido de la restauración no es válido."
        )
    return (
        model
        if isinstance(model, DeletionOperationRecord)
        else _operation_record_from_model(model)
    )


def _validate_restoration_record_state(
    record: DeletionOperationRecord,
) -> DeletionOperationRecord:
    pending = (
        record.status == TareaEliminacionOperacion.Estado.PENDIENTE
        and record.result_code == ""
    )
    committed = (
        record.status == TareaEliminacionOperacion.Estado.COMMITTED
        and record.result_code == LOGICAL_RESTORATION_RESULT_CODE
    )
    if (
        record.reverses_operation_id is None
        or not (pending or committed)
        or record.file_cleanup_status
        != TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA
    ):
        raise DeletionLedgerStateError(
            "El estado persistido de la operación de restauración no es válido."
        )
    return record


def _validate_source_manifest(
    source: DeletionOperationRecord,
    manifest: tuple[DeletionInventoryItem, ...],
) -> tuple[DeletionInventoryItem, ...]:
    expected_root = DeletionInventoryItem("tareas.tarea", source.root_task_id)
    if (
        not manifest
        or any(item.model_label != "tareas.tarea" for item in manifest)
        or expected_root not in manifest
        or source.dependency_summary.get("tareas.tarea") != len(manifest)
    ):
        raise DeletionLedgerSchemaError(
            "El manifiesto de eliminación no es íntegro para una restauración."
        )
    return tuple(sorted(manifest))


def _check_django_restoration_schema(alias: str) -> None:
    connection = connections[alias]
    if not connection.features.supports_transactions:
        raise DeletionLedgerBackendError(
            "BASE_TAREAS no admite transacciones para el ledger de restauración."
        )
    operation_table = TareaEliminacionOperacion._meta.db_table
    reverse_column = TareaEliminacionOperacion._meta.get_field(
        "reverses_operation"
    ).column
    try:
        existing_tables = set(connection.introspection.table_names())
        if operation_table not in existing_tables:
            raise DeletionLedgerSchemaError(
                "Falta la tabla de operaciones para el ledger de restauración."
            )
        with connection.cursor() as cursor:
            columns = {
                column.name
                for column in connection.introspection.get_table_description(
                    cursor,
                    operation_table,
                )
            }
            constraints = connection.introspection.get_constraints(
                cursor,
                operation_table,
            )
    except DeletionLedgerError:
        raise
    except Exception as exc:
        raise DeletionLedgerSchemaError(
            "No se pudo verificar el esquema del ledger de restauración."
        ) from exc

    has_unique_source = any(
        item.get("unique") and item.get("columns") == [reverse_column]
        for item in constraints.values()
    )
    source_table = TareaEliminacionOperacion._meta.db_table
    source_column = TareaEliminacionOperacion._meta.pk.column
    has_source_foreign_key = any(
        item.get("foreign_key") == (source_table, source_column)
        and item.get("columns") == [reverse_column]
        for item in constraints.values()
    )
    if (
        reverse_column not in columns
        or not has_unique_source
        or not has_source_foreign_key
    ):
        raise DeletionLedgerSchemaError(
            "Falta la referencia única al origen requerida por el ledger de restauración."
        )


class DjangoDeletionLedgerUnitOfWork:
    def __init__(self, alias: str, backend_identity: str, config_version: str):
        self.alias = alias
        self.backend_identity = backend_identity
        self.config_version = config_version

    def _operation(self, operation_id: UUID, *, lock: bool = True):
        query = TareaEliminacionOperacion.objects.using(self.alias)
        if lock:
            query = query.select_for_update()
        try:
            return query.get(operation_id=operation_id.hex)
        except TareaEliminacionOperacion.DoesNotExist as exc:
            raise DeletionLedgerStateError("La operación no existe en el ledger.") from exc

    def get_operation(
        self,
        operation_id: UUID,
        *,
        lock: bool = False,
    ) -> DeletionOperationRecord | None:
        query = TareaEliminacionOperacion.objects.using(self.alias).filter(
            operation_id=operation_id.hex
        )
        if lock:
            query = query.select_for_update()
        model = query.first()
        return _operation_record_from_model(model) if model is not None else None

    def get_restoration_source_operation(
        self,
        operation_id: UUID,
        *,
        lock: bool = False,
    ) -> DeletionOperationRecord | None:
        _check_django_restoration_schema(self.alias)
        query = TareaEliminacionOperacion.objects.using(self.alias).filter(
            operation_id=operation_id.hex
        )
        if lock:
            query = query.select_for_update()
        model = query.first()
        return _operation_record_from_model(model) if model is not None else None

    def get_restoration_operation(
        self,
        operation_id: UUID,
    ) -> DeletionOperationRecord | None:
        _check_django_restoration_schema(self.alias)
        model = (
            TareaEliminacionOperacion.objects.using(self.alias)
            .filter(operation_id=operation_id.hex)
            .first()
        )
        if model is None or getattr(model, "reverses_operation_id", None) is None:
            return None
        return _validate_restoration_record_state(
            _operation_record_from_model(model)
        )

    def get_restoration_for_source(
        self,
        source_operation_id: UUID,
        *,
        lock: bool = False,
    ) -> DeletionOperationRecord | None:
        _check_django_restoration_schema(self.alias)
        query = TareaEliminacionOperacion.objects.using(self.alias).filter(
            reverses_operation_id=source_operation_id.hex
        )
        if lock:
            query = query.select_for_update()
        model = query.first()
        if model is None:
            return None
        return _validate_restoration_record_state(
            _operation_record_from_model(model)
        )

    def get_manifest(
        self,
        operation_id: UUID,
        *,
        lock: bool = False,
    ) -> tuple[DeletionInventoryItem, ...]:
        self._operation(operation_id, lock=lock)
        query = TareaEliminacionElemento.objects.using(self.alias).filter(
            operacion_id=operation_id.hex
        ).order_by("tipo", "object_id")
        if lock and connections[self.alias].features.has_select_for_update:
            query = query.select_for_update()
        return tuple(
            sorted(
                DeletionInventoryItem(model_label=kind, object_id=object_id)
                for kind, object_id in query.values_list("tipo", "object_id")
            )
        )

    def get_root_operation(
        self,
        empresa_id: int,
        root_task_id: int,
    ) -> DeletionOperationRecord | None:
        model = (
            TareaEliminacionOperacion.objects.using(self.alias)
            .select_for_update()
            .filter(empresa_id=empresa_id, root_task_id=root_task_id)
            .order_by("created_at", "operation_id")
            .first()
        )
        return _operation_record_from_model(model) if model is not None else None

    def get_root_operations(
        self,
        empresa_id: int,
        root_task_id: int,
        *,
        lock: bool = True,
    ) -> tuple[DeletionOperationRecord, ...]:
        _check_django_restoration_schema(self.alias)
        query = (
            TareaEliminacionOperacion.objects.using(self.alias)
            .filter(empresa_id=empresa_id, root_task_id=root_task_id)
            .order_by("created_at", "operation_id")
        )
        if lock:
            query = query.select_for_update()
        return tuple(_operation_record_from_model(model) for model in query)

    def create_pending(self, operation: DeletionOperationInput) -> DeletionOperationRecord:
        operation = _normalize_operation(operation)
        defaults = _operation_values(
            operation,
            "DJANGO",
            self.backend_identity,
            self.config_version,
        )
        existing = (
            TareaEliminacionOperacion.objects.using(self.alias)
            .select_for_update()
            .filter(operation_id=operation.operation_id.hex)
            .first()
        )
        if existing is not None:
            _assert_operation_matches(
                existing,
                operation,
                "DJANGO",
                self.backend_identity,
                self.config_version,
            )
            return _operation_record_from_model(existing)
        root_exists = (
            Tarea.all_objects.using(self.alias)
            .select_for_update()
            .filter(
                pk=operation.root_task_id,
                empresa_id=operation.empresa_id,
                correlativo=operation.root_correlativo,
            )
            .exists()
        )
        if not root_exists:
            raise DeletionLedgerStateError(
                "La tarea raíz no existe en la empresa operativa indicada."
            )
        try:
            with transaction.atomic(using=self.alias):
                model = (
                    TareaEliminacionOperacion.objects.using(self.alias)
                    .get_or_create(
                        operation_id=operation.operation_id.hex,
                        defaults=defaults,
                    )[0]
                )
        except IntegrityError:
            model = self._operation(operation.operation_id)
        _assert_operation_matches(
            model,
            operation,
            "DJANGO",
            self.backend_identity,
            self.config_version,
        )
        return _operation_record_from_model(model)

    def create_restoration_pending(
        self,
        operation: RestorationOperationInput,
    ) -> DeletionOperationRecord:
        operation = _normalize_restoration_operation(operation)
        source = self.get_restoration_source_operation(
            operation.reverses_operation_id,
            lock=True,
        )
        source = _assert_restoration_source(
            operation,
            source,
            backend_type="DJANGO",
            backend_identity=self.backend_identity,
            config_version=self.config_version,
        )
        if TareaEliminacionArchivo.objects.using(self.alias).filter(
            operacion_id=source.operation_id.hex
        ).exists():
            raise DeletionLedgerStateError(
                "Una restauración lógica no puede vincular archivos de eliminación física."
            )
        source_manifest = _validate_source_manifest(
            source,
            self.get_manifest(source.operation_id),
        )
        manifest = _normalize_restoration_manifest(
            operation.manifest,
            root_task_id=source.root_task_id,
            source_manifest=source_manifest,
        )

        existing = (
            TareaEliminacionOperacion.objects.using(self.alias)
            .select_for_update()
            .filter(reverses_operation_id=source.operation_id.hex)
            .first()
        )
        if existing is not None:
            record = _assert_restoration_operation_matches(
                existing,
                operation,
                source=source,
                manifest=manifest,
                backend_type="DJANGO",
                backend_identity=self.backend_identity,
                config_version=self.config_version,
            )
            if self.get_manifest(record.operation_id) != manifest:
                raise DeletionLedgerConflict(
                    "El manifiesto persistido de restauración no coincide."
                )
            return record

        existing_id = (
            TareaEliminacionOperacion.objects.using(self.alias)
            .select_for_update()
            .filter(operation_id=operation.operation_id.hex)
            .first()
        )
        if existing_id is not None:
            record = _assert_restoration_operation_matches(
                existing_id,
                operation,
                source=source,
                manifest=manifest,
                backend_type="DJANGO",
                backend_identity=self.backend_identity,
                config_version=self.config_version,
            )
            if self.get_manifest(record.operation_id) != manifest:
                raise DeletionLedgerConflict(
                    "El manifiesto persistido de restauración no coincide."
                )
            return record

        defaults = _restoration_operation_values(
            operation,
            source=source,
            manifest=manifest,
            backend_type="DJANGO",
            backend_identity=self.backend_identity,
            config_version=self.config_version,
        )
        try:
            with transaction.atomic(using=self.alias):
                model = TareaEliminacionOperacion.objects.using(self.alias).create(
                    operation_id=operation.operation_id.hex,
                    **defaults,
                )
        except IntegrityError as exc:
            existing_id = (
                TareaEliminacionOperacion.objects.using(self.alias)
                .select_for_update()
                .filter(operation_id=operation.operation_id.hex)
                .first()
            )
            existing = (
                TareaEliminacionOperacion.objects.using(self.alias)
                .select_for_update()
                .filter(reverses_operation_id=source.operation_id.hex)
                .first()
            )
            collision = existing_id or existing
            if collision is None:
                raise DeletionLedgerSchemaError(
                    "No se pudo registrar la operación de restauración."
                ) from exc
            record = _assert_restoration_operation_matches(
                collision,
                operation,
                source=source,
                manifest=manifest,
                backend_type="DJANGO",
                backend_identity=self.backend_identity,
                config_version=self.config_version,
            )
            if self.get_manifest(record.operation_id) != manifest:
                raise DeletionLedgerConflict(
                    "El manifiesto persistido de restauración no coincide."
                ) from exc
            return record

        self.save_manifest(operation.operation_id, manifest)
        return _operation_record_from_model(model)

    def save_manifest(
        self,
        operation_id: UUID,
        items: tuple[DeletionInventoryItem, ...] | list[DeletionInventoryItem],
        files: tuple[DeletionFileReference, ...] | list[DeletionFileReference] = (),
    ) -> None:
        operation = self._operation(operation_id)
        normalized_items, normalized_files = _normalize_manifest(
            items,
            files,
            operation.root_task_id,
        )
        existing_items = tuple(
            sorted(
                DeletionInventoryItem(model_label=kind, object_id=object_id)
                for kind, object_id in (
                    TareaEliminacionElemento.objects.using(self.alias)
                    .filter(operacion_id=operation_id.hex)
                    .values_list("tipo", "object_id")
                )
            )
        )
        if existing_items and existing_items != normalized_items:
            raise DeletionLedgerConflict(
                "El manifiesto de elementos ya existe con contenido diferente."
            )
        if not existing_items and normalized_items:
            TareaEliminacionElemento.objects.using(self.alias).bulk_create(
                [
                    TareaEliminacionElemento(
                        operacion_id=operation_id.hex,
                        tipo=item.model_label,
                        object_id=item.object_id,
                    )
                    for item in normalized_items
                ]
            )

        existing_files = tuple(
            sorted(
                DeletionFileReference(storage_key=storage_key, file_name=file_name)
                for storage_key, file_name in (
                    TareaEliminacionArchivo.objects.using(self.alias)
                    .filter(operacion_id=operation_id.hex)
                    .values_list("storage_key", "file_name")
                )
            )
        )
        if existing_files and existing_files != normalized_files:
            raise DeletionLedgerConflict(
                "El manifiesto de archivos ya existe con contenido diferente."
            )
        if not existing_files and normalized_files:
            TareaEliminacionArchivo.objects.using(self.alias).bulk_create(
                [
                    TareaEliminacionArchivo(
                        operacion_id=operation_id.hex,
                        storage_key=item.storage_key,
                        file_name=item.file_name,
                        reference_hash=_reference_hash(item),
                        status=TareaEliminacionArchivo.Estado.PENDIENTE,
                    )
                    for item in normalized_files
                ]
            )
        if operation.file_cleanup_status == TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA and normalized_files:
            operation.file_cleanup_status = TareaEliminacionOperacion.EstadoArchivos.PENDIENTE
            operation.save(using=self.alias, update_fields=["file_cleanup_status", "updated_at"])

    def _ensure_inventory_removed(self, operation):
        elements = tuple(
            TareaEliminacionElemento.objects.using(self.alias)
            .filter(operacion_id=operation.operation_id)
            .values_list("tipo", "object_id")
        )
        if not elements or (
            "tareas.tarea",
            operation.root_task_id,
        ) not in elements:
            raise DeletionLedgerStateError(
                "No se puede confirmar una operación sin el manifiesto completo."
            )
        models = _item_model_map()
        grouped = defaultdict(set)
        for model_label, object_id in elements:
            model = models.get(model_label)
            if model is None:
                raise DeletionLedgerSchemaError(
                    "El manifiesto incluye un tipo de elemento desconocido."
                )
            grouped[model].add(object_id)
        for model, identifiers in grouped.items():
            if model.objects.using(self.alias).filter(pk__in=identifiers).exists():
                raise DeletionLedgerStateError(
                    "El inventario todavía contiene registros; no se confirmó el borrado."
                )

    def verify_committed_inventory(
        self,
        operation_id: UUID,
    ) -> DeletionOperationRecord:
        operation = self._operation(operation_id)
        if operation.status != TareaEliminacionOperacion.Estado.COMMITTED:
            raise DeletionLedgerStateError(
                "La operación no está confirmada en el ledger."
            )
        self._ensure_inventory_removed(operation)
        return _operation_record_from_model(operation)

    def mark_committed(self, operation_id: UUID) -> DeletionOperationRecord:
        operation = self._operation(operation_id)
        if operation.status == TareaEliminacionOperacion.Estado.COMMITTED:
            if operation.result_code != _DELETE_RESULT:
                raise DeletionLedgerStateError(
                    "El resultado persistido de la operación no es válido."
                )
            return _operation_record_from_model(operation)
        if operation.status != TareaEliminacionOperacion.Estado.PENDIENTE:
            raise DeletionLedgerStateError("El estado de operación no es válido.")
        self._ensure_inventory_removed(operation)
        now = timezone.now()
        operation.status = TareaEliminacionOperacion.Estado.COMMITTED
        operation.result_code = _DELETE_RESULT
        operation.audit_status = TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE
        operation.committed_at = now
        operation.updated_at = now
        operation.save(
            using=self.alias,
            update_fields=[
                "status",
                "result_code",
                "audit_status",
                "committed_at",
                "updated_at",
            ],
        )
        return _operation_record_from_model(operation)

    def mark_logically_deleted(
        self,
        operation_id: UUID,
    ) -> DeletionOperationRecord:
        operation = self._operation(operation_id)
        if operation.status == TareaEliminacionOperacion.Estado.COMMITTED:
            if (
                operation.result_code != LOGICAL_DELETION_RESULT_CODE
                or operation.file_cleanup_status
                != TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA
            ):
                raise DeletionLedgerStateError(
                    "El resultado persistido de la operación lógica no es válido."
                )
            return _operation_record_from_model(operation)
        if operation.status != TareaEliminacionOperacion.Estado.PENDIENTE:
            raise DeletionLedgerStateError("El estado de operación no es válido.")
        if not operation.motivo or not operation.motivo.strip():
            raise DeletionLedgerStateError(
                "La operación lógica requiere un motivo no vacío."
            )
        elements = self.get_manifest(operation_id)
        if not elements or (
            "tareas.tarea",
            operation.root_task_id,
        ) not in {(item.model_label, item.object_id) for item in elements}:
            raise DeletionLedgerStateError(
                "No se puede confirmar una operación lógica sin su manifiesto."
            )
        if any(item.model_label != "tareas.tarea" for item in elements):
            raise DeletionLedgerStateError(
                "El manifiesto lógico contiene elementos no admitidos."
            )
        if TareaEliminacionArchivo.objects.using(self.alias).filter(
            operacion_id=operation_id.hex
        ).exists():
            raise DeletionLedgerStateError(
                "Una operación lógica no puede programar limpieza de archivos."
            )
        now = timezone.now()
        operation.status = TareaEliminacionOperacion.Estado.COMMITTED
        operation.result_code = LOGICAL_DELETION_RESULT_CODE
        operation.audit_status = TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE
        operation.file_cleanup_status = (
            TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA
        )
        operation.committed_at = now
        operation.updated_at = now
        operation.save(
            using=self.alias,
            update_fields=[
                "status",
                "result_code",
                "audit_status",
                "file_cleanup_status",
                "committed_at",
                "updated_at",
            ],
        )
        return _operation_record_from_model(operation)

    def mark_logically_restored(
        self,
        operation_id: UUID,
    ) -> DeletionOperationRecord:
        _check_django_restoration_schema(self.alias)
        operation_model = self._operation(operation_id)
        operation = _operation_record_from_model(operation_model)
        if operation.reverses_operation_id is None:
            raise DeletionLedgerStateError(
                "La operación no es una restauración lógica."
            )

        source_model = self._operation(operation.reverses_operation_id)
        source = _operation_record_from_model(source_model)
        manifest = self.get_manifest(operation_id)
        source_manifest = _validate_source_manifest(
            source,
            self.get_manifest(source.operation_id),
        )
        restoration_input = RestorationOperationInput(
            actor_id=operation.actor_id,
            empresa_id=operation.empresa_id,
            reverses_operation_id=source.operation_id,
            fingerprint=operation.fingerprint,
            manifest=manifest,
            operation_id=operation.operation_id,
            motivo=operation.motivo or "",
        )
        _assert_restoration_source(
            restoration_input,
            source,
            backend_type="DJANGO",
            backend_identity=self.backend_identity,
            config_version=self.config_version,
        )
        _normalize_restoration_manifest(
            manifest,
            root_task_id=source.root_task_id,
            source_manifest=source_manifest,
        )
        _assert_restoration_operation_matches(
            operation,
            restoration_input,
            source=source,
            manifest=source_manifest,
            backend_type="DJANGO",
            backend_identity=self.backend_identity,
            config_version=self.config_version,
        )
        if TareaEliminacionArchivo.objects.using(self.alias).filter(
            operacion_id=operation_id.hex
        ).exists():
            raise DeletionLedgerStateError(
                "Una restauración lógica no puede programar limpieza de archivos."
            )
        if operation.status == TareaEliminacionOperacion.Estado.COMMITTED:
            if operation.result_code != LOGICAL_RESTORATION_RESULT_CODE:
                raise DeletionLedgerStateError(
                    "El resultado persistido de la restauración no es válido."
                )
            return _validate_restoration_record_state(operation)
        if (
            operation.status != TareaEliminacionOperacion.Estado.PENDIENTE
            or operation.result_code != ""
            or operation.audit_status
            != TareaEliminacionOperacion.EstadoAuditoria.NO_ENCOLADA
            or not operation.motivo
            or not operation.motivo.strip()
        ):
            raise DeletionLedgerStateError(
                "La operación pendiente no puede confirmarse como restauración."
            )

        now = timezone.now()
        operation_model.status = TareaEliminacionOperacion.Estado.COMMITTED
        operation_model.result_code = LOGICAL_RESTORATION_RESULT_CODE
        operation_model.audit_status = (
            TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE
        )
        operation_model.file_cleanup_status = (
            TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA
        )
        operation_model.committed_at = now
        operation_model.updated_at = now
        operation_model.save(
            using=self.alias,
            update_fields=[
                "status",
                "result_code",
                "audit_status",
                "file_cleanup_status",
                "committed_at",
                "updated_at",
            ],
        )
        return _validate_restoration_record_state(
            _operation_record_from_model(operation_model)
        )

    def record_audit_result(
        self,
        operation_id: UUID,
        *,
        confirmed: bool,
        event_id: int | None = None,
        error_code: str = "",
    ) -> DeletionOperationRecord:
        operation = self._operation(operation_id)
        self._require_committed(operation)
        if confirmed:
            if event_id is None:
                raise ValueError("event_id es obligatorio cuando la auditoría se confirma.")
            _positive_id(event_id, "event_id")
            if operation.audit_status == TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA:
                if operation.audit_event_id != event_id:
                    raise DeletionLedgerConflict(
                        "La operación ya está asociada a otro evento central."
                    )
                return _operation_record_from_model(operation)
            operation.audit_status = TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA
            operation.audit_event_id = event_id
            operation.audit_error_code = ""
        else:
            if (
                operation.audit_status
                == TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA
            ):
                return _operation_record_from_model(operation)
            operation.audit_status = TareaEliminacionOperacion.EstadoAuditoria.ERROR
            operation.audit_event_id = None
            operation.audit_error_code = _validate_result_code(
                error_code,
                "error_code",
            )
        operation.audit_attempts += 1
        now = timezone.now()
        operation.audit_last_attempt_at = now
        operation.updated_at = now
        operation.save(
            using=self.alias,
            update_fields=[
                "audit_status",
                "audit_event_id",
                "audit_error_code",
                "audit_attempts",
                "audit_last_attempt_at",
                "updated_at",
            ],
        )
        return _operation_record_from_model(operation)

    def record_file_cleanup_result(
        self,
        operation_id: UUID,
        file_reference: DeletionFileReference,
        *,
        completed: bool,
        error_code: str = "",
    ) -> DeletionFileRecord:
        operation = self._operation(operation_id)
        self._require_committed(operation)
        reference_hash = _reference_hash(file_reference)
        try:
            file_record = (
                TareaEliminacionArchivo.objects.using(self.alias)
                .select_for_update()
                .get(
                    operacion_id=operation_id.hex,
                    storage_key=file_reference.storage_key,
                    reference_hash=reference_hash,
                )
            )
        except TareaEliminacionArchivo.DoesNotExist as exc:
            raise DeletionLedgerStateError(
                "El archivo no forma parte del manifiesto de la operación."
            ) from exc
        if file_record.file_name != file_reference.file_name:
            raise DeletionLedgerConflict(
                "La referencia de archivo no coincide con el manifiesto."
            )
        if file_record.status == TareaEliminacionArchivo.Estado.COMPLETO:
            if completed:
                return DeletionFileRecord(
                    operation_id=operation_id,
                    storage_key=file_record.storage_key,
                    file_name=file_record.file_name,
                    status=file_record.status,
                    attempts=file_record.attempts,
                    last_attempt_at=file_record.last_attempt_at,
                    error_code=file_record.error_code,
                )
            raise DeletionLedgerStateError(
                "No se puede cambiar el resultado de una limpieza ya completada."
            )
        if completed:
            file_record.status = TareaEliminacionArchivo.Estado.COMPLETO
            file_record.error_code = ""
        else:
            file_record.status = TareaEliminacionArchivo.Estado.ERROR
            file_record.error_code = _validate_result_code(
                error_code,
                "error_code",
            )
        file_record.attempts += 1
        now = timezone.now()
        file_record.last_attempt_at = now
        file_record.updated_at = now
        file_record.save(
            using=self.alias,
            update_fields=[
                "status",
                "error_code",
                "attempts",
                "last_attempt_at",
                "updated_at",
            ],
        )
        statuses = tuple(
            TareaEliminacionArchivo.objects.using(self.alias)
            .filter(operacion_id=operation_id.hex)
            .values_list("status", flat=True)
        )
        if statuses and all(
            status == TareaEliminacionArchivo.Estado.COMPLETO
            for status in statuses
        ):
            operation.file_cleanup_status = (
                TareaEliminacionOperacion.EstadoArchivos.COMPLETA
            )
        elif any(
            status == TareaEliminacionArchivo.Estado.ERROR for status in statuses
        ):
            operation.file_cleanup_status = (
                TareaEliminacionOperacion.EstadoArchivos.ERROR
            )
        else:
            operation.file_cleanup_status = (
                TareaEliminacionOperacion.EstadoArchivos.PENDIENTE
            )
        operation.updated_at = now
        operation.save(
            using=self.alias,
            update_fields=["file_cleanup_status", "updated_at"],
        )
        return DeletionFileRecord(
            operation_id=operation_id,
            storage_key=file_record.storage_key,
            file_name=file_record.file_name,
            status=file_record.status,
            attempts=file_record.attempts,
            last_attempt_at=file_record.last_attempt_at,
            error_code=file_record.error_code,
        )

    def pending_audits(self, limit: int) -> tuple[DeletionOperationRecord, ...]:
        limit = _validate_limit(limit)
        models = (
            TareaEliminacionOperacion.objects.using(self.alias)
            .filter(
                status=TareaEliminacionOperacion.Estado.COMMITTED,
                audit_status__in=(
                    TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
                    TareaEliminacionOperacion.EstadoAuditoria.ERROR,
                ),
            )
            .order_by("created_at", "operation_id")[:limit]
        )
        return tuple(_operation_record_from_model(item) for item in models)

    def pending_files(self, limit: int) -> tuple[DeletionFileRecord, ...]:
        limit = _validate_limit(limit)
        records = (
            TareaEliminacionArchivo.objects.using(self.alias)
            .filter(
                operacion__status=TareaEliminacionOperacion.Estado.COMMITTED,
                status__in=(
                    TareaEliminacionArchivo.Estado.PENDIENTE,
                    TareaEliminacionArchivo.Estado.ERROR,
                ),
            )
            .order_by("created_at", "pk")[:limit]
            .values_list(
                "operacion_id",
                "storage_key",
                "file_name",
                "status",
                "attempts",
                "last_attempt_at",
                "error_code",
            )
        )
        return tuple(
            DeletionFileRecord(
                operation_id=UUID(str(operation_id)),
                storage_key=storage_key,
                file_name=file_name,
                status=status,
                attempts=attempts,
                last_attempt_at=last_attempt_at,
                error_code=error_code,
            )
            for (
                operation_id,
                storage_key,
                file_name,
                status,
                attempts,
                last_attempt_at,
                error_code,
            ) in records
        )

    @staticmethod
    def _require_committed(operation) -> None:
        if operation.status != TareaEliminacionOperacion.Estado.COMMITTED:
            raise DeletionLedgerStateError(
                "La operación debe estar confirmada antes de entregar auditoría o limpiar archivos."
            )


class DjangoDeletionLedgerStorage:
    def __init__(self, alias: str, config_version: str = ""):
        if not alias:
            raise DeletionLedgerBackendError(
                "BASE_TAREAS requiere un alias Django explícito."
            )
        self.alias = alias
        self.backend_identity = f"django:{alias}"
        self.config_version = config_version

    @contextmanager
    def atomic(self) -> Generator[DjangoDeletionLedgerUnitOfWork, None, None]:
        _check_django_schema(self.alias)
        failure = None
        try:
            with transaction.atomic(using=self.alias):
                try:
                    yield DjangoDeletionLedgerUnitOfWork(
                        self.alias,
                        self.backend_identity,
                        self.config_version,
                    )
                except BaseException as exc:
                    failure = exc
                    raise
        except Exception as exc:
            if failure is exc:
                if isinstance(exc, DeletionLedgerError):
                    raise
                raise DeletionLedgerError(
                    "Falló una operación del ledger dentro de la transacción."
                ) from exc
            if isinstance(exc, DeletionLedgerError):
                raise
            raise DeletionLedgerCommitUncertain(
                "No se pudo confirmar con certeza la transacción del ledger; "
                "consulte operation_id antes de reintentar."
            ) from exc

    def get_operation(self, operation_id: UUID) -> DeletionOperationRecord | None:
        with self.atomic() as unit:
            return unit.get_operation(operation_id)

    def get_restoration_operation(
        self,
        operation_id: UUID,
    ) -> DeletionOperationRecord | None:
        with self.atomic() as unit:
            return unit.get_restoration_operation(operation_id)

    def pending_audits(self, limit: int = 100) -> tuple[DeletionOperationRecord, ...]:
        with self.atomic() as unit:
            return unit.pending_audits(limit)

    def pending_files(self, limit: int = 100) -> tuple[DeletionFileRecord, ...]:
        with self.atomic() as unit:
            return unit.pending_files(limit)


class MySQLDeletionLedgerUnitOfWork:
    def __init__(
        self,
        connection: _CursorConnection,
        backend_identity: str,
        config_version: str,
        database_name: str | None = None,
    ):
        self.connection = connection
        self.backend_identity = backend_identity
        self.config_version = config_version
        self.database_name = database_name

    def _execute(self, sql: str, params=()) -> _DBAPICursor:
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params)
            return cursor
        except Exception:
            cursor.close()
            raise

    def _operation_row(self, operation_id: UUID, *, lock: bool = True):
        sql = (
            f"SELECT {_OPERATION_COLUMN_SQL} "
            "FROM `tareas_eliminacion_operacion` WHERE `operation_id` = %s"
        )
        if lock:
            sql += " FOR UPDATE"
        cursor = self._execute(sql, (operation_id.hex,))
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    def _restoration_operation_row(
        self,
        operation_id: UUID,
        *,
        lock: bool = True,
    ):
        sql = (
            f"SELECT {_RESTORATION_OPERATION_COLUMN_SQL} "
            "FROM `tareas_eliminacion_operacion` WHERE `operation_id` = %s"
        )
        if lock:
            sql += " FOR UPDATE"
        cursor = self._execute(sql, (operation_id.hex,))
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    def _restoration_by_source(self, source_operation_id: UUID, *, lock: bool = True):
        column = _mysql_field_identifier(
            TareaEliminacionOperacion,
            "reverses_operation",
        )
        sql = (
            f"SELECT {_RESTORATION_OPERATION_COLUMN_SQL} "
            "FROM `tareas_eliminacion_operacion` "
            f"WHERE {column} = %s ORDER BY `operation_id` LIMIT 1"
        )
        if lock:
            sql += " FOR UPDATE"
        cursor = self._execute(sql, (source_operation_id.hex,))
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    def get_operation(
        self,
        operation_id: UUID,
        *,
        lock: bool = False,
    ) -> DeletionOperationRecord | None:
        row = self._operation_row(operation_id, lock=lock)
        return _operation_record_from_row(row) if row is not None else None

    def get_restoration_source_operation(
        self,
        operation_id: UUID,
        *,
        lock: bool = False,
    ) -> DeletionOperationRecord | None:
        if not self.database_name:
            raise DeletionLedgerBackendError(
                "BASE_TAREAS requiere una base para el ledger de restauración."
            )
        _check_mysql_restoration_schema(self.connection, self.database_name)
        row = self._restoration_operation_row(operation_id, lock=lock)
        return (
            _operation_record_from_row(
                row,
                columns=_RESTORATION_OPERATION_COLUMNS,
            )
            if row is not None
            else None
        )

    def get_restoration_operation(
        self,
        operation_id: UUID,
    ) -> DeletionOperationRecord | None:
        if not self.database_name:
            raise DeletionLedgerBackendError(
                "BASE_TAREAS requiere una base para el ledger de restauración."
            )
        _check_mysql_restoration_schema(self.connection, self.database_name)
        row = self._restoration_operation_row(operation_id, lock=False)
        if row is None:
            return None
        record = _operation_record_from_row(
            row,
            columns=_RESTORATION_OPERATION_COLUMNS,
        )
        if record.reverses_operation_id is None:
            return None
        return _validate_restoration_record_state(record)

    def get_restoration_for_source(
        self,
        source_operation_id: UUID,
        *,
        lock: bool = False,
    ) -> DeletionOperationRecord | None:
        if not self.database_name:
            raise DeletionLedgerBackendError(
                "BASE_TAREAS requiere una base para el ledger de restauración."
            )
        _check_mysql_restoration_schema(self.connection, self.database_name)
        row = self._restoration_by_source(source_operation_id, lock=lock)
        if row is None:
            return None
        record = _operation_record_from_row(
            row,
            columns=_RESTORATION_OPERATION_COLUMNS,
        )
        return _validate_restoration_record_state(record)

    def get_manifest(
        self,
        operation_id: UUID,
        *,
        lock: bool = False,
    ) -> tuple[DeletionInventoryItem, ...]:
        if self._operation_row(operation_id, lock=lock) is None:
            raise DeletionLedgerStateError("La operación no existe en el ledger.")
        return tuple(
            sorted(
                DeletionInventoryItem(model_label=kind, object_id=object_id)
                for kind, object_id in self._inventory_rows(
                    operation_id,
                    lock=lock,
                )
            )
        )

    def get_root_operation(
        self,
        empresa_id: int,
        root_task_id: int,
    ) -> DeletionOperationRecord | None:
        cursor = self._execute(
            f"SELECT {_OPERATION_COLUMN_SQL} "
            "FROM `tareas_eliminacion_operacion` "
            "WHERE `empresa_id` = %s AND `root_task_id` = %s "
            "ORDER BY `created_at`, `operation_id` LIMIT 1 FOR UPDATE",
            (empresa_id, root_task_id),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        return _operation_record_from_row(row) if row is not None else None

    def get_root_operations(
        self,
        empresa_id: int,
        root_task_id: int,
        *,
        lock: bool = True,
    ) -> tuple[DeletionOperationRecord, ...]:
        if not self.database_name:
            raise DeletionLedgerBackendError(
                "BASE_TAREAS requiere una base para el ledger de restauración."
            )
        _check_mysql_restoration_schema(self.connection, self.database_name)
        sql = (
            f"SELECT {_RESTORATION_OPERATION_COLUMN_SQL} "
            "FROM `tareas_eliminacion_operacion` "
            "WHERE `empresa_id` = %s AND `root_task_id` = %s "
            "ORDER BY `created_at`, `operation_id`"
        )
        if lock:
            sql += " FOR UPDATE"
        cursor = self._execute(sql, (empresa_id, root_task_id))
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        return tuple(
            _operation_record_from_row(
                row,
                columns=_RESTORATION_OPERATION_COLUMNS,
            )
            for row in rows
        )

    def create_pending(self, operation: DeletionOperationInput) -> DeletionOperationRecord:
        operation = _normalize_operation(operation)
        existing = self._operation_row(operation.operation_id)
        if existing is not None:
            record = _operation_record_from_row(existing)
            expected_existing = _operation_values(
                operation,
                "MYSQL_CONFIG",
                self.backend_identity,
                self.config_version,
            )
            expected_existing["dependency_summary"] = dict(
                operation.dependency_summary
            )
            if {
                key: getattr(record, key) for key in expected_existing
            } != expected_existing:
                raise DeletionLedgerConflict(
                    "operation_id ya existe con datos diferentes."
                )
            return record
        task_table = _mysql_identifier(Tarea._meta.db_table)
        task_id_column = _mysql_primary_key_identifier(Tarea)
        task_empresa_column = _mysql_field_identifier(Tarea, "empresa")
        task_correlativo_column = _mysql_field_identifier(Tarea, "correlativo")
        cursor = self._execute(
            f"SELECT {task_id_column} FROM {task_table} "
            f"WHERE {task_id_column} = %s AND {task_empresa_column} = %s "
            f"AND {task_correlativo_column} = %s FOR UPDATE",
            (
                operation.root_task_id,
                operation.empresa_id,
                operation.root_correlativo,
            ),
        )
        try:
            root_exists = cursor.fetchone() is not None
        finally:
            cursor.close()
        if not root_exists:
            raise DeletionLedgerStateError(
                "La tarea raíz no existe en la empresa operativa indicada."
            )
        summary = _summary_json(operation.dependency_summary)
        now = timezone.now()
        table = "`tareas_eliminacion_operacion`"
        columns = (
            "`operation_id`, `actor_id`, `empresa_id`, `root_task_id`, "
            "`root_correlativo`, `backend_type`, `backend_identity`, "
            "`backend_config_version`, `fingerprint`, `dependency_summary`, "
            "`status`, `result_code`, `audit_status`, `audit_attempts`, "
            "`audit_last_attempt_at`, `audit_event_id`, `audit_error_code`, "
            "`file_cleanup_status`, `created_at`, `updated_at`, `committed_at`, "
            "`motivo`"
        )
        sql = (
            f"INSERT INTO {table} ({columns}) VALUES "
            "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE `operation_id` = VALUES(`operation_id`)"
        )
        params = (
            operation.operation_id.hex,
            operation.actor_id,
            operation.empresa_id,
            operation.root_task_id,
            operation.root_correlativo,
            "MYSQL_CONFIG",
            self.backend_identity,
            self.config_version,
            operation.fingerprint,
            summary,
            TareaEliminacionOperacion.Estado.PENDIENTE,
            "",
            TareaEliminacionOperacion.EstadoAuditoria.NO_ENCOLADA,
            0,
            None,
            None,
            "",
            TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA,
            now,
            now,
            None,
            operation.motivo,
        )
        cursor = self._execute(sql, params)
        cursor.close()
        row = self._operation_row(operation.operation_id)
        if row is None:
            raise DeletionLedgerSchemaError(
                "No se pudo recuperar la operación recién registrada."
            )
        record = _operation_record_from_row(row)
        expected = _operation_values(
            operation,
            "MYSQL_CONFIG",
            self.backend_identity,
            self.config_version,
        )
        expected["dependency_summary"] = dict(operation.dependency_summary)
        actual = {
            key: getattr(record, key)
            for key in expected
        }
        if actual != expected:
            raise DeletionLedgerConflict(
                "operation_id ya existe con datos diferentes."
            )
        return record

    def create_restoration_pending(
        self,
        operation: RestorationOperationInput,
    ) -> DeletionOperationRecord:
        operation = _normalize_restoration_operation(operation)
        if not self.database_name:
            raise DeletionLedgerBackendError(
                "BASE_TAREAS requiere una base para el ledger de restauración."
            )
        source = self.get_restoration_source_operation(
            operation.reverses_operation_id,
            lock=True,
        )
        source = _assert_restoration_source(
            operation,
            source,
            backend_type="MYSQL_CONFIG",
            backend_identity=self.backend_identity,
            config_version=self.config_version,
        )
        file_table = _mysql_identifier(TareaEliminacionArchivo._meta.db_table)
        cursor = self._execute(
            f"SELECT 1 FROM {file_table} WHERE `operacion_id` = %s LIMIT 1",
            (source.operation_id.hex,),
        )
        try:
            has_files = cursor.fetchone() is not None
        finally:
            cursor.close()
        if has_files:
            raise DeletionLedgerStateError(
                "Una restauración lógica no puede vincular archivos de eliminación física."
            )

        source_manifest = _validate_source_manifest(
            source,
            self.get_manifest(source.operation_id),
        )
        manifest = _normalize_restoration_manifest(
            operation.manifest,
            root_task_id=source.root_task_id,
            source_manifest=source_manifest,
        )

        existing = self._restoration_by_source(source.operation_id)
        if existing is not None:
            record = _operation_record_from_row(
                existing,
                columns=_RESTORATION_OPERATION_COLUMNS,
            )
            record = _assert_restoration_operation_matches(
                record,
                operation,
                source=source,
                manifest=manifest,
                backend_type="MYSQL_CONFIG",
                backend_identity=self.backend_identity,
                config_version=self.config_version,
            )
            if self.get_manifest(record.operation_id) != manifest:
                raise DeletionLedgerConflict(
                    "El manifiesto persistido de restauración no coincide."
                )
            return record

        existing_id = self._restoration_operation_row(operation.operation_id)
        if existing_id is not None:
            record = _operation_record_from_row(
                existing_id,
                columns=_RESTORATION_OPERATION_COLUMNS,
            )
            record = _assert_restoration_operation_matches(
                record,
                operation,
                source=source,
                manifest=manifest,
                backend_type="MYSQL_CONFIG",
                backend_identity=self.backend_identity,
                config_version=self.config_version,
            )
            if self.get_manifest(record.operation_id) != manifest:
                raise DeletionLedgerConflict(
                    "El manifiesto persistido de restauración no coincide."
                )
            return record

        legacy_existing = self._operation_row(operation.operation_id)
        if legacy_existing is not None:
            raise DeletionLedgerConflict(
                "operation_id ya pertenece a otra operación del ledger."
            )

        values = _restoration_operation_values(
            operation,
            source=source,
            manifest=manifest,
            backend_type="MYSQL_CONFIG",
            backend_identity=self.backend_identity,
            config_version=self.config_version,
        )
        now = timezone.now()
        values.update(
            {
                "operation_id": operation.operation_id.hex,
                "created_at": now,
                "updated_at": now,
            }
        )
        columns = ", ".join(
            f"`{column}`" for column in _RESTORATION_OPERATION_COLUMNS
        )
        placeholders = ", ".join("%s" for _ in _RESTORATION_OPERATION_COLUMNS)
        cursor = self._execute(
            f"INSERT INTO `tareas_eliminacion_operacion` ({columns}) "
            f"VALUES ({placeholders}) "
            "ON DUPLICATE KEY UPDATE `operation_id` = `operation_id`",
            tuple(values[column] for column in _RESTORATION_OPERATION_COLUMNS),
        )
        cursor.close()

        row = self._restoration_operation_row(operation.operation_id)
        if row is None:
            existing = self._restoration_by_source(source.operation_id)
            if existing is None:
                raise DeletionLedgerConflict(
                    "La eliminación ya tiene una operación de restauración."
                )
            record = _operation_record_from_row(
                existing,
                columns=_RESTORATION_OPERATION_COLUMNS,
            )
        else:
            record = _operation_record_from_row(
                row,
                columns=_RESTORATION_OPERATION_COLUMNS,
            )
        record = _assert_restoration_operation_matches(
            record,
            operation,
            source=source,
            manifest=manifest,
            backend_type="MYSQL_CONFIG",
            backend_identity=self.backend_identity,
            config_version=self.config_version,
        )
        self.save_manifest(operation.operation_id, manifest)
        return record

    def save_manifest(
        self,
        operation_id: UUID,
        items: tuple[DeletionInventoryItem, ...] | list[DeletionInventoryItem],
        files: tuple[DeletionFileReference, ...] | list[DeletionFileReference] = (),
    ) -> None:
        operation_row = self._operation_row(operation_id)
        if operation_row is None:
            raise DeletionLedgerStateError("La operación no existe en el ledger.")
        operation = _operation_record_from_row(operation_row)
        normalized_items, normalized_files = _normalize_manifest(
            items,
            files,
            operation.root_task_id,
        )
        cursor = self._execute(
            "SELECT `tipo`, `object_id` FROM `tareas_eliminacion_elemento` "
            "WHERE `operacion_id` = %s FOR UPDATE",
            (operation_id.hex,),
        )
        try:
            existing_items = tuple(
                sorted(
                    DeletionInventoryItem(
                        model_label=_database_string(kind, "tipo"),
                        object_id=_database_integer(object_id, "object_id"),
                    )
                    for kind, object_id in cursor.fetchall()
                )
            )
        finally:
            cursor.close()
        if existing_items and existing_items != normalized_items:
            raise DeletionLedgerConflict(
                "El manifiesto de elementos ya existe con contenido diferente."
            )
        if not existing_items:
            for item in normalized_items:
                cursor = self._execute(
                    "INSERT INTO `tareas_eliminacion_elemento` "
                    "(`operacion_id`, `tipo`, `object_id`) VALUES (%s, %s, %s)",
                    (operation_id.hex, item.model_label, item.object_id),
                )
                cursor.close()

        cursor = self._execute(
            "SELECT `storage_key`, `file_name` FROM `tareas_eliminacion_archivo` "
            "WHERE `operacion_id` = %s FOR UPDATE",
            (operation_id.hex,),
        )
        try:
            existing_files = tuple(
                sorted(
                    DeletionFileReference(
                        storage_key=_database_string(storage_key, "storage_key"),
                        file_name=_database_string(file_name, "file_name"),
                    )
                    for storage_key, file_name in cursor.fetchall()
                )
            )
        finally:
            cursor.close()
        if existing_files and existing_files != normalized_files:
            raise DeletionLedgerConflict(
                "El manifiesto de archivos ya existe con contenido diferente."
            )
        if not existing_files:
            for file_reference in normalized_files:
                cursor = self._execute(
                    "INSERT INTO `tareas_eliminacion_archivo` "
                    "(`operacion_id`, `storage_key`, `file_name`, `reference_hash`, "
                    "`status`, `attempts`, `last_attempt_at`, `error_code`, "
                    "`created_at`, `updated_at`) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        operation_id.hex,
                        file_reference.storage_key,
                        file_reference.file_name,
                        _reference_hash(file_reference),
                        TareaEliminacionArchivo.Estado.PENDIENTE,
                        0,
                        None,
                        "",
                        timezone.now(),
                        timezone.now(),
                    ),
                )
                cursor.close()
        if (
            operation.file_cleanup_status
            == TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA
            and normalized_files
        ):
            self._update_operation(
                operation_id,
                {"file_cleanup_status": TareaEliminacionOperacion.EstadoArchivos.PENDIENTE},
            )

    def _inventory_rows(self, operation_id: UUID, *, lock: bool = False):
        sql = (
            "SELECT `tipo`, `object_id` FROM `tareas_eliminacion_elemento` "
            "WHERE `operacion_id` = %s ORDER BY `tipo`, `object_id`"
        )
        if lock:
            sql += " FOR UPDATE"
        cursor = self._execute(
            sql,
            (operation_id.hex,),
        )
        try:
            return tuple(
                (
                    _database_string(model_label, "tipo"),
                    _database_integer(object_id, "object_id"),
                )
                for model_label, object_id in cursor.fetchall()
            )
        finally:
            cursor.close()

    def _ensure_inventory_removed(self, operation):
        elements = self._inventory_rows(operation.operation_id)
        if not elements or (
            "tareas.tarea",
            operation.root_task_id,
        ) not in elements:
            raise DeletionLedgerStateError(
                "No se puede confirmar una operación sin el manifiesto completo."
            )
        models = _item_model_map()
        grouped = defaultdict(set)
        for model_label, object_id in elements:
            model = models.get(model_label)
            if model is None:
                raise DeletionLedgerSchemaError(
                    "El manifiesto incluye un tipo de elemento desconocido."
                )
            grouped[model].add(object_id)
        for model, identifiers in grouped.items():
            pk_column = _mysql_primary_key_identifier(model)
            table = _mysql_identifier(model._meta.db_table)
            ids = tuple(identifiers)
            for offset in range(0, len(ids), 500):
                chunk = ids[offset:offset + 500]
                placeholders = ", ".join("%s" for _ in chunk)
                cursor = self._execute(
                    f"SELECT 1 FROM {table} WHERE {pk_column} IN ({placeholders}) LIMIT 1",
                    chunk,
                )
                try:
                    exists = cursor.fetchone() is not None
                finally:
                    cursor.close()
                if exists:
                    raise DeletionLedgerStateError(
                        "El inventario todavía contiene registros; no se confirmó el borrado."
                    )

    def verify_committed_inventory(
        self,
        operation_id: UUID,
    ) -> DeletionOperationRecord:
        row = self._operation_row(operation_id)
        if row is None:
            raise DeletionLedgerStateError("La operación no existe en el ledger.")
        operation = _operation_record_from_row(row)
        if operation.status != TareaEliminacionOperacion.Estado.COMMITTED:
            raise DeletionLedgerStateError(
                "La operación no está confirmada en el ledger."
            )
        self._ensure_inventory_removed(operation)
        return operation

    def _update_operation(self, operation_id: UUID, values: Mapping[str, object]):
        assignments = ", ".join(f"`{key}` = %s" for key in values)
        params = (*values.values(), timezone.now(), operation_id.hex)
        cursor = self._execute(
            "UPDATE `tareas_eliminacion_operacion` SET "
            f"{assignments}, `updated_at` = %s WHERE `operation_id` = %s",
            params,
        )
        cursor.close()

    def mark_committed(self, operation_id: UUID) -> DeletionOperationRecord:
        row = self._operation_row(operation_id)
        if row is None:
            raise DeletionLedgerStateError("La operación no existe en el ledger.")
        operation = _operation_record_from_row(row)
        if operation.status == TareaEliminacionOperacion.Estado.COMMITTED:
            if operation.result_code != _DELETE_RESULT:
                raise DeletionLedgerStateError(
                    "El resultado persistido de la operación no es válido."
                )
            return operation
        if operation.status != TareaEliminacionOperacion.Estado.PENDIENTE:
            raise DeletionLedgerStateError("El estado de operación no es válido.")
        self._ensure_inventory_removed(operation)
        now = timezone.now()
        self._update_operation(
            operation_id,
            {
                "status": TareaEliminacionOperacion.Estado.COMMITTED,
                "result_code": _DELETE_RESULT,
                "audit_status": TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
                "committed_at": now,
            },
        )
        updated = self._operation_row(operation_id)
        if updated is None:
            raise DeletionLedgerSchemaError(
                "No se pudo recuperar la operación confirmada."
            )
        return _operation_record_from_row(updated)

    def mark_logically_deleted(
        self,
        operation_id: UUID,
    ) -> DeletionOperationRecord:
        row = self._operation_row(operation_id)
        if row is None:
            raise DeletionLedgerStateError("La operación no existe en el ledger.")
        operation = _operation_record_from_row(row)
        if operation.status == TareaEliminacionOperacion.Estado.COMMITTED:
            if (
                operation.result_code != LOGICAL_DELETION_RESULT_CODE
                or operation.file_cleanup_status
                != TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA
            ):
                raise DeletionLedgerStateError(
                    "El resultado persistido de la operación lógica no es válido."
                )
            return operation
        if operation.status != TareaEliminacionOperacion.Estado.PENDIENTE:
            raise DeletionLedgerStateError("El estado de operación no es válido.")
        if not operation.motivo or not operation.motivo.strip():
            raise DeletionLedgerStateError(
                "La operación lógica requiere un motivo no vacío."
            )
        elements = self.get_manifest(operation_id)
        if not elements or (
            "tareas.tarea",
            operation.root_task_id,
        ) not in {(item.model_label, item.object_id) for item in elements}:
            raise DeletionLedgerStateError(
                "No se puede confirmar una operación lógica sin su manifiesto."
            )
        if any(item.model_label != "tareas.tarea" for item in elements):
            raise DeletionLedgerStateError(
                "El manifiesto lógico contiene elementos no admitidos."
            )
        cursor = self._execute(
            "SELECT 1 FROM `tareas_eliminacion_archivo` "
            "WHERE `operacion_id` = %s LIMIT 1",
            (operation_id.hex,),
        )
        try:
            has_files = cursor.fetchone() is not None
        finally:
            cursor.close()
        if has_files:
            raise DeletionLedgerStateError(
                "Una operación lógica no puede programar limpieza de archivos."
            )
        self._update_operation(
            operation_id,
            {
                "status": TareaEliminacionOperacion.Estado.COMMITTED,
                "result_code": LOGICAL_DELETION_RESULT_CODE,
                "audit_status": TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
                "file_cleanup_status": (
                    TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA
                ),
                "committed_at": timezone.now(),
            },
        )
        updated = self._operation_row(operation_id)
        if updated is None:
            raise DeletionLedgerSchemaError(
                "No se pudo recuperar la operación lógica confirmada."
            )
        return _operation_record_from_row(updated)

    def mark_logically_restored(
        self,
        operation_id: UUID,
    ) -> DeletionOperationRecord:
        if not self.database_name:
            raise DeletionLedgerBackendError(
                "BASE_TAREAS requiere una base para el ledger de restauración."
            )
        _check_mysql_restoration_schema(self.connection, self.database_name)
        row = self._restoration_operation_row(operation_id)
        if row is None:
            raise DeletionLedgerStateError("La operación no existe en el ledger.")
        operation = _operation_record_from_row(
            row,
            columns=_RESTORATION_OPERATION_COLUMNS,
        )
        if operation.reverses_operation_id is None:
            raise DeletionLedgerStateError(
                "La operación no es una restauración lógica."
            )

        source_row = self._restoration_operation_row(
            operation.reverses_operation_id
        )
        if source_row is None:
            raise DeletionLedgerStateError(
                "La operación de eliminación que se intenta revertir no existe."
            )
        source = _operation_record_from_row(
            source_row,
            columns=_RESTORATION_OPERATION_COLUMNS,
        )
        manifest = self.get_manifest(operation_id)
        source_manifest = _validate_source_manifest(
            source,
            self.get_manifest(source.operation_id),
        )
        restoration_input = RestorationOperationInput(
            actor_id=operation.actor_id,
            empresa_id=operation.empresa_id,
            reverses_operation_id=source.operation_id,
            fingerprint=operation.fingerprint,
            manifest=manifest,
            operation_id=operation.operation_id,
            motivo=operation.motivo or "",
        )
        _assert_restoration_source(
            restoration_input,
            source,
            backend_type="MYSQL_CONFIG",
            backend_identity=self.backend_identity,
            config_version=self.config_version,
        )
        _normalize_restoration_manifest(
            manifest,
            root_task_id=source.root_task_id,
            source_manifest=source_manifest,
        )
        _assert_restoration_operation_matches(
            operation,
            restoration_input,
            source=source,
            manifest=source_manifest,
            backend_type="MYSQL_CONFIG",
            backend_identity=self.backend_identity,
            config_version=self.config_version,
        )
        file_table = _mysql_identifier(TareaEliminacionArchivo._meta.db_table)
        cursor = self._execute(
            f"SELECT 1 FROM {file_table} WHERE `operacion_id` = %s LIMIT 1",
            (operation_id.hex,),
        )
        try:
            has_files = cursor.fetchone() is not None
        finally:
            cursor.close()
        if has_files:
            raise DeletionLedgerStateError(
                "Una restauración lógica no puede programar limpieza de archivos."
            )
        if operation.status == TareaEliminacionOperacion.Estado.COMMITTED:
            if operation.result_code != LOGICAL_RESTORATION_RESULT_CODE:
                raise DeletionLedgerStateError(
                    "El resultado persistido de la restauración no es válido."
                )
            return _validate_restoration_record_state(operation)
        if (
            operation.status != TareaEliminacionOperacion.Estado.PENDIENTE
            or operation.result_code != ""
            or operation.audit_status
            != TareaEliminacionOperacion.EstadoAuditoria.NO_ENCOLADA
            or not operation.motivo
            or not operation.motivo.strip()
        ):
            raise DeletionLedgerStateError(
                "La operación pendiente no puede confirmarse como restauración."
            )

        self._update_operation(
            operation_id,
            {
                "status": TareaEliminacionOperacion.Estado.COMMITTED,
                "result_code": LOGICAL_RESTORATION_RESULT_CODE,
                "audit_status": TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
                "file_cleanup_status": (
                    TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA
                ),
                "committed_at": timezone.now(),
            },
        )
        updated = self._restoration_operation_row(operation_id)
        if updated is None:
            raise DeletionLedgerSchemaError(
                "No se pudo recuperar la restauración lógica confirmada."
            )
        return _validate_restoration_record_state(
            _operation_record_from_row(
                updated,
                columns=_RESTORATION_OPERATION_COLUMNS,
            )
        )

    def record_audit_result(
        self,
        operation_id: UUID,
        *,
        confirmed: bool,
        event_id: int | None = None,
        error_code: str = "",
    ) -> DeletionOperationRecord:
        row = self._operation_row(operation_id)
        if row is None:
            raise DeletionLedgerStateError("La operación no existe en el ledger.")
        operation = _operation_record_from_row(row)
        self._require_committed(operation)
        if confirmed:
            if event_id is None:
                raise ValueError("event_id es obligatorio cuando la auditoría se confirma.")
            _positive_id(event_id, "event_id")
            if operation.audit_status == TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA:
                if operation.audit_event_id != event_id:
                    raise DeletionLedgerConflict(
                        "La operación ya está asociada a otro evento central."
                    )
                return operation
            values = {
                "audit_status": TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
                "audit_event_id": event_id,
                "audit_error_code": "",
                "audit_attempts": operation.audit_attempts + 1,
                "audit_last_attempt_at": timezone.now(),
            }
        else:
            if (
                operation.audit_status
                == TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA
            ):
                return operation
            values = {
                "audit_status": TareaEliminacionOperacion.EstadoAuditoria.ERROR,
                "audit_event_id": None,
                "audit_error_code": _validate_result_code(error_code, "error_code"),
                "audit_attempts": operation.audit_attempts + 1,
                "audit_last_attempt_at": timezone.now(),
            }
        self._update_operation(operation_id, values)
        updated = self._operation_row(operation_id)
        return _operation_record_from_row(updated)

    def record_file_cleanup_result(
        self,
        operation_id: UUID,
        file_reference: DeletionFileReference,
        *,
        completed: bool,
        error_code: str = "",
    ) -> DeletionFileRecord:
        row = self._operation_row(operation_id)
        if row is None:
            raise DeletionLedgerStateError("La operación no existe en el ledger.")
        operation = _operation_record_from_row(row)
        self._require_committed(operation)
        reference_hash = _reference_hash(file_reference)
        cursor = self._execute(
            "SELECT `id`, `file_name`, `status`, `attempts`, `last_attempt_at`, "
            "`error_code` FROM `tareas_eliminacion_archivo` "
            "WHERE `operacion_id` = %s AND `storage_key` = %s "
            "AND `reference_hash` = %s FOR UPDATE",
            (operation_id.hex, file_reference.storage_key, reference_hash),
        )
        try:
            file_row = cursor.fetchone()
        finally:
            cursor.close()
        if file_row is None:
            raise DeletionLedgerStateError(
                "El archivo no forma parte del manifiesto de la operación."
            )
        file_id = _database_integer(file_row[0], "id")
        file_name = _database_string(file_row[1], "file_name")
        file_status = _database_string(file_row[2], "status")
        attempts = _database_integer(file_row[3], "attempts")
        last_attempt = _database_datetime(file_row[4], "last_attempt_at")
        stored_error = _database_string(file_row[5], "error_code")
        if file_name != file_reference.file_name:
            raise DeletionLedgerStateError(
                "El archivo no forma parte del manifiesto de la operación."
            )
        if file_status == TareaEliminacionArchivo.Estado.COMPLETO:
            if completed:
                return DeletionFileRecord(
                    operation_id=operation_id,
                    storage_key=file_reference.storage_key,
                    file_name=file_reference.file_name,
                    status=file_status,
                    attempts=attempts,
                    last_attempt_at=last_attempt,
                    error_code=stored_error,
                )
            raise DeletionLedgerStateError(
                "No se puede cambiar el resultado de una limpieza ya completada."
            )
        status = (
            TareaEliminacionArchivo.Estado.COMPLETO
            if completed
            else TareaEliminacionArchivo.Estado.ERROR
        )
        code = "" if completed else _validate_result_code(error_code, "error_code")
        now = timezone.now()
        cursor = self._execute(
            "UPDATE `tareas_eliminacion_archivo` SET `status` = %s, "
            "`attempts` = %s, `last_attempt_at` = %s, `error_code` = %s, "
            "`updated_at` = %s WHERE `id` = %s",
            (status, attempts + 1, now, code, now, file_id),
        )
        cursor.close()
        cursor = self._execute(
            "SELECT `status` FROM `tareas_eliminacion_archivo` "
            "WHERE `operacion_id` = %s",
            (operation_id.hex,),
        )
        try:
            statuses = tuple(item[0] for item in cursor.fetchall())
        finally:
            cursor.close()
        if statuses and all(
            value == TareaEliminacionArchivo.Estado.COMPLETO for value in statuses
        ):
            operation_status = TareaEliminacionOperacion.EstadoArchivos.COMPLETA
        elif any(
            value == TareaEliminacionArchivo.Estado.ERROR for value in statuses
        ):
            operation_status = TareaEliminacionOperacion.EstadoArchivos.ERROR
        else:
            operation_status = TareaEliminacionOperacion.EstadoArchivos.PENDIENTE
        self._update_operation(
            operation_id,
            {"file_cleanup_status": operation_status},
        )
        return DeletionFileRecord(
            operation_id=operation_id,
            storage_key=file_reference.storage_key,
            file_name=file_reference.file_name,
            status=status,
            attempts=attempts + 1,
            last_attempt_at=now,
            error_code=code,
        )

    def pending_audits(self, limit: int) -> tuple[DeletionOperationRecord, ...]:
        limit = _validate_limit(limit)
        cursor = self._execute(
            f"SELECT {_OPERATION_COLUMN_SQL} FROM `tareas_eliminacion_operacion` "
            "WHERE `status` = %s AND `audit_status` IN (%s, %s) "
            "ORDER BY `created_at`, `operation_id` LIMIT %s",
            (
                TareaEliminacionOperacion.Estado.COMMITTED,
                TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
                TareaEliminacionOperacion.EstadoAuditoria.ERROR,
                limit,
            ),
        )
        try:
            return tuple(_operation_record_from_row(row) for row in cursor.fetchall())
        finally:
            cursor.close()

    def pending_files(self, limit: int) -> tuple[DeletionFileRecord, ...]:
        limit = _validate_limit(limit)
        cursor = self._execute(
            "SELECT f.`operacion_id`, f.`storage_key`, f.`file_name`, f.`status`, "
            "f.`attempts`, f.`last_attempt_at`, f.`error_code` "
            "FROM `tareas_eliminacion_archivo` AS f "
            "INNER JOIN `tareas_eliminacion_operacion` AS o "
            "ON o.`operation_id` = f.`operacion_id` "
            "WHERE o.`status` = %s AND f.`status` IN (%s, %s) "
            "ORDER BY f.`created_at`, f.`id` LIMIT %s",
            (
                TareaEliminacionOperacion.Estado.COMMITTED,
                TareaEliminacionArchivo.Estado.PENDIENTE,
                TareaEliminacionArchivo.Estado.ERROR,
                limit,
            ),
        )
        try:
            return tuple(
                DeletionFileRecord(
                    operation_id=(
                        row[0] if isinstance(row[0], UUID) else UUID(str(row[0]))
                    ),
                    storage_key=_database_string(row[1], "storage_key"),
                    file_name=_database_string(row[2], "file_name"),
                    status=_database_string(row[3], "status"),
                    attempts=_database_integer(row[4], "attempts"),
                    last_attempt_at=_database_datetime(row[5], "last_attempt_at"),
                    error_code=_database_string(row[6], "error_code"),
                )
                for row in cursor.fetchall()
            )
        finally:
            cursor.close()

    @staticmethod
    def _require_committed(operation: DeletionOperationRecord) -> None:
        if operation.status != TareaEliminacionOperacion.Estado.COMMITTED:
            raise DeletionLedgerStateError(
                "La operación debe estar confirmada antes de entregar auditoría o limpiar archivos."
            )


class MySQLDeletionLedgerStorage:
    def __init__(self, connection_config, database_name: str):
        if not database_name:
            raise DeletionLedgerBackendError(
                "BASE_TAREAS requiere un nombre de base operacional."
            )
        self.connection_config = connection_config
        self.database_name = database_name
        self.backend_identity = (
            f"mysql_config:{connection_config.pk}:{database_name}"
        )
        self.config_version = connection_config.updated_at.isoformat()

    @contextmanager
    def atomic(self) -> Generator[MySQLDeletionLedgerUnitOfWork, None, None]:
        try:
            with open_mysql_connection(
                self.connection_config,
                database_name=self.database_name,
            ) as raw_connection:
                if not _is_cursor_connection(raw_connection):
                    raise DeletionLedgerBackendError(
                        "La conexión MySQL no ofrece un cursor operacional."
                    )
                connection = raw_connection
                _check_mysql_transactional_tables(connection, self.database_name)
                unit = MySQLDeletionLedgerUnitOfWork(
                    connection,
                    self.backend_identity,
                    self.config_version,
                    self.database_name,
                )
                alias = getattr(connection, "alias", None)
                if alias:
                    failure = None
                    try:
                        with transaction.atomic(using=alias):
                            try:
                                yield unit
                            except BaseException as exc:
                                failure = exc
                                raise
                    except Exception as exc:
                        if failure is exc:
                            raise
                        if isinstance(exc, DeletionLedgerError):
                            raise
                        raise DeletionLedgerCommitUncertain(
                            "No se pudo confirmar con certeza la transacción del ledger; "
                            "consulte operation_id antes de reintentar."
                        ) from exc
                else:
                    if not _is_transactional_mysql_connection(connection):
                        raise DeletionLedgerBackendError(
                            "La conexión MySQL no ofrece una interfaz transaccional completa."
                        )
                    try:
                        connection.begin()
                    except Exception as exc:
                        raise DeletionLedgerBackendError(
                            "No se pudo iniciar la transacción del ledger MySQL."
                        ) from exc
                    try:
                        yield unit
                    except BaseException as exc:
                        try:
                            connection.rollback()
                        except Exception as rollback_error:
                            raise DeletionLedgerCommitUncertain(
                                "Falló el rollback del ledger; consulte operation_id."
                            ) from rollback_error
                        if isinstance(exc, DeletionLedgerError):
                            raise
                        if isinstance(exc, Exception):
                            raise DeletionLedgerError(
                                "Falló una operación del ledger y se revirtió la transacción."
                            ) from exc
                        raise
                    try:
                        connection.commit()
                    except Exception as exc:
                        raise DeletionLedgerCommitUncertain(
                            "No se pudo confirmar con certeza la transacción del ledger; "
                            "consulte operation_id antes de reintentar."
                        ) from exc
        except DeletionLedgerError:
            raise
        except MySQLConnectionOpenError as exc:
            raise DeletionLedgerBackendError(
                "No se pudo abrir la conexión operacional BASE_TAREAS."
            ) from exc
        except Exception as exc:
            raise DeletionLedgerError(
                "Falló una operación transaccional del ledger MySQL."
            ) from exc

    def get_operation(self, operation_id: UUID) -> DeletionOperationRecord | None:
        with self.atomic() as unit:
            return unit.get_operation(operation_id)

    def get_restoration_operation(
        self,
        operation_id: UUID,
    ) -> DeletionOperationRecord | None:
        with self.atomic() as unit:
            return unit.get_restoration_operation(operation_id)

    def pending_audits(self, limit: int = 100) -> tuple[DeletionOperationRecord, ...]:
        with self.atomic() as unit:
            return unit.pending_audits(limit)

    def pending_files(self, limit: int = 100) -> tuple[DeletionFileRecord, ...]:
        with self.atomic() as unit:
            return unit.pending_files(limit)


def resolve_deletion_ledger_storage():
    """Resolve the ledger against BASE_TAREAS without falling back to default."""
    try:
        context = resolve_operational_backend("BASE_TAREAS")
    except TareaConnectionError as exc:
        raise DeletionLedgerBackendError(
            "No se pudo resolver la conexión operacional BASE_TAREAS."
        ) from exc
    if context.backend_type == "DJANGO":
        alias = context.django_alias
        if not alias:
            raise DeletionLedgerBackendError(
                "BASE_TAREAS no proporcionó un alias Django válido."
            )
        config = connections[alias].settings_dict
        signature = "|".join(
            str(config.get(key) or "") for key in ("ENGINE", "NAME", "HOST", "PORT")
        )
        config_version = hashlib.sha256(signature.encode("utf-8")).hexdigest()
        return DjangoDeletionLedgerStorage(alias, config_version)
    if (
        context.backend_type == "MYSQL_CONFIG"
        and context.mysql_connection is not None
        and context.database_name
    ):
        return MySQLDeletionLedgerStorage(
            context.mysql_connection,
            context.database_name,
        )
    raise DeletionLedgerBackendError(
        "El backend de BASE_TAREAS no está soportado para el ledger."
    )
