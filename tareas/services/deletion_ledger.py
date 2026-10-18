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
    )


def _operation_record_from_row(row) -> DeletionOperationRecord:
    values = dict(zip(_OPERATION_COLUMNS, row))
    operation_id = values["operation_id"]
    motivo = values["motivo"]
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

    def get_operation(self, operation_id: UUID) -> DeletionOperationRecord | None:
        model = (
            TareaEliminacionOperacion.objects.using(self.alias)
            .filter(operation_id=operation_id.hex)
            .first()
        )
        return _operation_record_from_model(model) if model is not None else None

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
            Tarea.objects.using(self.alias)
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
    ):
        self.connection = connection
        self.backend_identity = backend_identity
        self.config_version = config_version

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

    def get_operation(self, operation_id: UUID) -> DeletionOperationRecord | None:
        row = self._operation_row(operation_id, lock=False)
        return _operation_record_from_row(row) if row is not None else None

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

    def _inventory_rows(self, operation_id: UUID):
        cursor = self._execute(
            "SELECT `tipo`, `object_id` FROM `tareas_eliminacion_elemento` "
            "WHERE `operacion_id` = %s",
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
