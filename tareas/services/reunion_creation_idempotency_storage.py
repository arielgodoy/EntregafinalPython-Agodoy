from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone
from typing import Iterator, Protocol
from uuid import UUID

from django.conf import settings
from django.db import DatabaseError, connections, transaction
from django.utils import timezone

from settings.services.mysql_connections import (
    MySQLConnectionOpenError,
    open_mysql_connection,
)

from ..models import ReunionCreationRequest
from .connection_roles import TareaConnectionError, resolve_operational_backend
from .task_mutation_locks import (
    TaskMutationLockError,
    bounded_mysql_lock_wait,
    mysql_mutation_transaction,
)


class ReunionCreationRequestStorageError(RuntimeError):
    """A controlled failure while accessing BASE_TAREAS request storage."""


@dataclass(frozen=True)
class CreationRequestRecord:
    request_id: UUID
    empresa_id: int
    actor_id: int
    payload_hash: str
    review_fingerprint: str
    status: str
    expires_at: datetime
    task_id: int | None
    meeting_id: int | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    audit_status: str
    audit_event_id: int | None
    audit_error_code: str


class ReunionCreationRequestUnitOfWork(Protocol):
    backend_type: str
    alias: str | None
    connection: object | None

    def get_request(
        self,
        request_id: UUID,
        *,
        lock: bool = False,
    ) -> CreationRequestRecord | None: ...

    def insert_or_get_request(
        self,
        record: CreationRequestRecord,
    ) -> CreationRequestRecord: ...

    def transition_request(
        self,
        request_id: UUID,
        *,
        expected_status: str,
        values: dict[str, object],
    ) -> bool: ...


class DjangoReunionCreationRequestUnit:
    backend_type = "DJANGO"

    def __init__(self, alias: str):
        self.alias = alias
        self.connection = connections[alias]

    def get_request(self, request_id: UUID, *, lock: bool = False):
        query = ReunionCreationRequest.objects.using(self.alias)
        if lock and self.connection.features.has_select_for_update:
            query = query.select_for_update()
        model = query.filter(request_id=request_id).first()
        return _record_from_model(model) if model is not None else None

    def insert_or_get_request(self, record: CreationRequestRecord):
        defaults = _model_values(record)
        model, _created = ReunionCreationRequest.objects.using(
            self.alias
        ).get_or_create(
            request_id=record.request_id,
            defaults=defaults,
        )
        if self.connection.features.has_select_for_update:
            model = (
                ReunionCreationRequest.objects.using(self.alias)
                .select_for_update()
                .get(request_id=record.request_id)
            )
        return _record_from_model(model)

    def transition_request(
        self,
        request_id: UUID,
        *,
        expected_status: str,
        values: dict[str, object],
    ) -> bool:
        updates = dict(values)
        updates["updated_at"] = timezone.now()
        return bool(
            ReunionCreationRequest.objects.using(self.alias)
            .filter(request_id=request_id, status=expected_status)
            .update(**updates)
        )


class MySQLReunionCreationRequestUnit:
    backend_type = "MYSQL_CONFIG"

    def __init__(self, connection, cursor):
        self.alias = None
        self.connection = connection
        self.cursor = cursor
        self._table = _quote(ReunionCreationRequest._meta.db_table)
        self._columns = tuple(
            _quote(ReunionCreationRequest._meta.get_field(name).column)
            for name in (
                "request_id",
                "empresa_id",
                "actor_id",
                "payload_hash",
                "review_fingerprint",
                "status",
                "expires_at",
                "task_id",
                "meeting_id",
                "created_at",
                "updated_at",
                "completed_at",
                "audit_status",
                "audit_event_id",
                "audit_error_code",
            )
        )

    def get_request(self, request_id: UUID, *, lock: bool = False):
        self.cursor.execute(
            f"SELECT {', '.join(self._columns)} FROM {self._table} "
            "WHERE `request_id`=%s"
            + (" FOR UPDATE" if lock else ""),
            (request_id.hex,),
        )
        row = self.cursor.fetchone()
        return _record_from_mysql_row(row) if row is not None else None

    def insert_or_get_request(self, record: CreationRequestRecord):
        placeholders = ", ".join("%s" for _column in self._columns)
        self.cursor.execute(
            f"INSERT INTO {self._table} ({', '.join(self._columns)}) "
            f"VALUES ({placeholders}) "
            "ON DUPLICATE KEY UPDATE `request_id`=VALUES(`request_id`)",
            _mysql_values(record),
        )
        existing = self.get_request(record.request_id, lock=True)
        if existing is None:
            raise ReunionCreationRequestStorageError(
                "No se pudo recuperar la solicitud técnica."
            )
        return existing

    def transition_request(
        self,
        request_id: UUID,
        *,
        expected_status: str,
        values: dict[str, object],
    ) -> bool:
        allowed_columns = {
            "status",
            "review_fingerprint",
            "expires_at",
            "task_id",
            "meeting_id",
            "completed_at",
            "audit_status",
            "audit_event_id",
            "audit_error_code",
        }
        if not values or not set(values).issubset(allowed_columns):
            raise ValueError("Los campos de transición no son válidos.")
        assignments = [
            f"{_quote(ReunionCreationRequest._meta.get_field(name).column)}=%s"
            for name in values
        ]
        assignments.append(
            f"{_quote(ReunionCreationRequest._meta.get_field('updated_at').column)}=%s"
        )
        params = [*values.values(), timezone.now(), request_id.hex, expected_status]
        self.cursor.execute(
            f"UPDATE {self._table} SET {', '.join(assignments)} "
            "WHERE `request_id`=%s AND `status`=%s",
            tuple(params),
        )
        return self.cursor.rowcount == 1


class DjangoReunionCreationRequestStorage:
    def __init__(self, alias: str):
        self.alias = alias

    @contextmanager
    def atomic(self) -> Iterator[ReunionCreationRequestUnitOfWork]:
        try:
            with transaction.atomic(using=self.alias):
                yield DjangoReunionCreationRequestUnit(self.alias)
        except DatabaseError as exc:
            raise ReunionCreationRequestStorageError(
                "No se pudo completar la transacción de idempotencia."
            ) from exc


class MySQLReunionCreationRequestStorage:
    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    @contextmanager
    def atomic(self) -> Iterator[ReunionCreationRequestUnitOfWork]:
        try:
            with open_mysql_connection(
                self.connection_config,
                database_name=self.database_name,
            ) as connection:
                with bounded_mysql_lock_wait(connection):
                    with mysql_mutation_transaction(connection):
                        cursor = connection.cursor()
                        try:
                            yield MySQLReunionCreationRequestUnit(
                                connection,
                                cursor,
                            )
                        finally:
                            cursor.close()
        except MySQLConnectionOpenError as exc:
            raise ReunionCreationRequestStorageError(
                "No se pudo abrir el almacenamiento operacional de Tareas."
            ) from exc
        except TaskMutationLockError as exc:
            raise ReunionCreationRequestStorageError(
                "No se pudo confirmar la transacción de idempotencia."
            ) from exc
        except DatabaseError as exc:
            raise ReunionCreationRequestStorageError(
                "No se pudo completar la transacción de idempotencia."
            ) from exc


def resolve_reunion_creation_request_storage():
    try:
        context = resolve_operational_backend("BASE_TAREAS")
    except TareaConnectionError as exc:
        raise ReunionCreationRequestStorageError(
            "No se pudo resolver BASE_TAREAS para idempotencia."
        ) from exc

    if context.backend_type == "DJANGO":
        alias = context.django_alias
        if not alias or alias not in settings.DATABASES:
            raise ReunionCreationRequestStorageError(
                "El alias Django de BASE_TAREAS no está disponible."
            )
        return DjangoReunionCreationRequestStorage(alias)

    if (
        context.backend_type == "MYSQL_CONFIG"
        and context.mysql_connection is not None
        and context.database_name == "tareas"
    ):
        return MySQLReunionCreationRequestStorage(
            context.mysql_connection,
            context.database_name,
        )

    raise ReunionCreationRequestStorageError(
        "BASE_TAREAS no tiene un backend permitido para idempotencia."
    )


def _record_from_model(model: ReunionCreationRequest) -> CreationRequestRecord:
    return CreationRequestRecord(
        request_id=model.request_id,
        empresa_id=model.empresa_id,
        actor_id=model.actor_id,
        payload_hash=model.payload_hash,
        review_fingerprint=model.review_fingerprint,
        status=model.status,
        expires_at=model.expires_at,
        task_id=model.task_id,
        meeting_id=model.meeting_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
        audit_status=model.audit_status,
        audit_event_id=model.audit_event_id,
        audit_error_code=model.audit_error_code,
    )


def _record_from_mysql_row(row) -> CreationRequestRecord:
    request_id = row[0]
    if isinstance(request_id, (bytes, bytearray)):
        request_id = request_id.decode("ascii")
    try:
        normalized_request_id = UUID(str(request_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ReunionCreationRequestStorageError(
            "El request_id persistido no es válido."
        ) from exc
    return CreationRequestRecord(
        request_id=normalized_request_id,
        empresa_id=int(row[1]),
        actor_id=int(row[2]),
        payload_hash=str(row[3]),
        review_fingerprint=str(row[4]),
        status=str(row[5]),
        expires_at=_required_mysql_datetime(row[6], "expires_at"),
        task_id=int(row[7]) if row[7] is not None else None,
        meeting_id=int(row[8]) if row[8] is not None else None,
        created_at=_required_mysql_datetime(row[9], "created_at"),
        updated_at=_required_mysql_datetime(row[10], "updated_at"),
        completed_at=_optional_mysql_datetime(row[11], "completed_at"),
        audit_status=str(row[12]),
        audit_event_id=int(row[13]) if row[13] is not None else None,
        audit_error_code=str(row[14] or ""),
    )


def _required_mysql_datetime(value, field_name: str) -> datetime:
    normalized = _optional_mysql_datetime(value, field_name)
    if normalized is None:
        raise ReunionCreationRequestStorageError(
            f"Falta {field_name} en la solicitud técnica persistida."
        )
    return normalized


def _optional_mysql_datetime(value, field_name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ReunionCreationRequestStorageError(
                f"{field_name} no tiene un formato válido."
            ) from exc
    if not isinstance(value, datetime):
        raise ReunionCreationRequestStorageError(
            f"{field_name} no tiene un tipo válido."
        )
    if timezone.is_naive(value) and settings.USE_TZ:
        return timezone.make_aware(value, datetime_timezone.utc)
    return value


def _model_values(record: CreationRequestRecord) -> dict[str, object]:
    return {
        "empresa_id": record.empresa_id,
        "actor_id": record.actor_id,
        "payload_hash": record.payload_hash,
        "review_fingerprint": record.review_fingerprint,
        "status": record.status,
        "expires_at": record.expires_at,
        "task_id": record.task_id,
        "meeting_id": record.meeting_id,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "completed_at": record.completed_at,
        "audit_status": record.audit_status,
        "audit_event_id": record.audit_event_id,
        "audit_error_code": record.audit_error_code,
    }


def _mysql_values(record: CreationRequestRecord) -> tuple[object, ...]:
    return (
        record.request_id.hex,
        record.empresa_id,
        record.actor_id,
        record.payload_hash,
        record.review_fingerprint,
        record.status,
        record.expires_at,
        record.task_id,
        record.meeting_id,
        record.created_at,
        record.updated_at,
        record.completed_at,
        record.audit_status,
        record.audit_event_id,
        record.audit_error_code,
    )


def _quote(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError("Identificador SQL no válido.")
    return f"`{identifier}`"
