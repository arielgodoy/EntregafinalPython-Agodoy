"""Shared SQL boundary for the Tareas master catalogs."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator
from uuid import UUID

from settings.services.mysql_connections import (
    MySQLConnectionOpenError,
    open_mysql_connection,
)

from .connection_roles import (
    TareaConnectionError,
    resolve_operational_backend,
)
from .task_mutation_locks import (
    TaskMutationCommitError,
    TaskMutationRollbackError,
    bounded_mysql_lock_wait,
    mysql_mutation_transaction,
)


class MasterCatalogError(RuntimeError):
    """Base error for SQL master-catalog operations."""


class MasterCatalogBackendError(MasterCatalogError):
    """BASE_TAREAS is not a verified MySQL development connection."""


class MasterCatalogValidationError(MasterCatalogError):
    """The command does not satisfy the catalog contract."""


class MasterCatalogNotFound(MasterCatalogError):
    """The requested row is absent or outside the company scope."""


class MasterCatalogConflict(MasterCatalogError):
    """The requested mutation conflicts with a protected or unique row."""


class MasterCatalogCapabilityBlocked(MasterCatalogError):
    """The operation requires an unresolved external contract."""


class MasterCatalogDatabaseError(MasterCatalogError):
    """A database failure translated to a safe domain error."""


class MasterCatalogCommitUnknown(MasterCatalogDatabaseError):
    """The operation outcome must be recovered using the same operation UUID."""


@dataclass(frozen=True)
class CompanyContext:
    """Caller-validated company context; never construct it from raw HTTP input."""

    empresa_id: int
    actor_id: int | None = None

    def validate(self) -> None:
        if (
            not isinstance(self.empresa_id, int)
            or isinstance(self.empresa_id, bool)
            or self.empresa_id <= 0
        ):
            raise MasterCatalogValidationError("La Empresa activa no es válida.")
        if self.actor_id is not None and (
            not isinstance(self.actor_id, int)
            or
            isinstance(self.actor_id, bool) or self.actor_id <= 0
        ):
            raise MasterCatalogValidationError("El actor no es válido.")


@dataclass(frozen=True)
class MutationMetadata:
    """Trace metadata retained for the future approved audit integration."""

    operation_id: str
    actor_id: int
    motivo: str

    def validate(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id.strip() or len(self.operation_id) > 64:
            raise MasterCatalogValidationError("El identificador de operación no es válido.")
        if (
            not isinstance(self.actor_id, int)
            or isinstance(self.actor_id, bool)
            or self.actor_id <= 0
        ):
            raise MasterCatalogValidationError("El actor no es válido.")
        if (
            not isinstance(self.motivo, str)
            or not self.motivo.strip()
            or len(self.motivo.strip()) > 1000
        ):
            raise MasterCatalogValidationError("El motivo es obligatorio.")


@dataclass(frozen=True)
class MutationResult:
    id: int
    operation_id: str
    audit_status: str = "PENDING"
    replayed: bool = False
    audit_error_code: str = ""


def require_metadata(metadata: MutationMetadata) -> None:
    if not isinstance(metadata, MutationMetadata):
        raise MasterCatalogValidationError(
            "La mutación requiere metadatos de actor, operación y motivo."
        )
    metadata.validate()
    try:
        UUID(metadata.operation_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise MasterCatalogValidationError(
            "El identificador de operación debe ser un UUID."
        ) from exc


def require_company_context(context: CompanyContext) -> None:
    if not isinstance(context, CompanyContext):
        raise MasterCatalogValidationError(
            "La operación requiere un contexto de Empresa validado."
        )
    context.validate()


def verify_base_tareas_database(connection) -> None:
    """Verify that a MySQL connection points to the authorized physical database."""
    cursor = connection.cursor()
    try:
        try:
            cursor.execute("SELECT DATABASE()")
            row = cursor.fetchone()
        except Exception as exc:
            raise MasterCatalogBackendError(
                "No se pudo verificar la base física de BASE_TAREAS."
            ) from exc
    finally:
        cursor.close()
    if not row:
        raise MasterCatalogBackendError(
            "La verificación de BASE_TAREAS no devolvió una base."
        )
    if row[0] != "tareas":
        raise MasterCatalogBackendError(
            "La conexión de BASE_TAREAS no apunta a la base autorizada."
        )


@contextmanager
def verified_base_tareas_connection() -> Iterator[object]:
    """Yield the single verified BASE_TAREAS connection for one operation."""
    try:
        backend = resolve_operational_backend("BASE_TAREAS")
    except TareaConnectionError as exc:
        raise MasterCatalogBackendError(
            "No se pudo resolver el rol BASE_TAREAS."
        ) from exc
    if backend.backend_type != "MYSQL_CONFIG" or backend.mysql_connection is None:
        raise MasterCatalogBackendError(
            "Los catálogos SQL requieren BASE_TAREAS como MYSQL_CONFIG."
        )
    try:
        with open_mysql_connection(
            backend.mysql_connection,
            database_name=backend.database_name,
        ) as connection:
            verify_base_tareas_database(connection)
            yield connection
    except MySQLConnectionOpenError as exc:
        raise MasterCatalogBackendError(
            "No se pudo abrir la conexión de BASE_TAREAS."
        ) from exc


@contextmanager
def mutation_transaction(connection) -> Iterator[None]:
    """Bound lock waits and commit/rollback one InnoDB mutation."""
    try:
        with bounded_mysql_lock_wait(connection):
            with mysql_mutation_transaction(connection):
                yield
    except MasterCatalogError:
        raise
    except Exception as exc:
        cause = exc
        seen = set()
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, (TaskMutationCommitError, TaskMutationRollbackError)):
                raise MasterCatalogCommitUnknown(
                    "El resultado de la transacción es incierto; "
                    "recupérelo con el mismo UUID."
                ) from exc
            if isinstance(cause, MasterCatalogError):
                raise cause
            cause = cause.__cause__ or cause.__context__
        raise MasterCatalogDatabaseError(
            "No se pudo completar la mutación del catálogo."
        ) from exc


def execute_or_raise_conflict(cursor, sql: str, params: tuple[object, ...]) -> None:
    try:
        cursor.execute(sql, params)
    except Exception as exc:
        code = getattr(exc, "errno", None)
        args = getattr(exc, "args", ())
        if code == 1062 or (args and args[0] == 1062):
            raise MasterCatalogConflict(
                "La operación viola una unicidad o restricción del catálogo."
            ) from exc
        raise MasterCatalogDatabaseError(
            "No se pudo escribir el catálogo."
        ) from exc


def execute_or_raise_database(cursor, sql: str, params: tuple[object, ...]) -> None:
    try:
        cursor.execute(sql, params)
    except MasterCatalogError:
        raise
    except Exception as exc:
        raise MasterCatalogDatabaseError(
            "No se pudo consultar el catálogo."
        ) from exc


def normalize_required_text(value: object, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise MasterCatalogValidationError(f"{field_name} debe ser texto.")
    normalized = value.strip()
    if not normalized:
        raise MasterCatalogValidationError(f"{field_name} es obligatorio.")
    if len(normalized) > max_length:
        raise MasterCatalogValidationError(f"{field_name} excede su longitud máxima.")
    return normalized


def normalize_optional_text(
    value: object,
    field_name: str,
    max_length: int,
) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise MasterCatalogValidationError(f"{field_name} debe ser texto.")
    normalized = value.strip()
    if len(normalized) > max_length:
        raise MasterCatalogValidationError(f"{field_name} excede su longitud máxima.")
    return normalized
