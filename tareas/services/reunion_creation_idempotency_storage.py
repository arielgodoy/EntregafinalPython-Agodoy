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

from ..models import ReunionCreationRequest, ReunionRevision, Tarea
from .connection_roles import TareaConnectionError, resolve_operational_backend
from .task_mutation_locks import (
    TaskMutationConflict,
    TaskMutationLockError,
    bounded_mysql_lock_wait,
    is_task_mutation_conflict,
    mysql_mutation_transaction,
)


class ReunionCreationRequestStorageError(RuntimeError):
    """A controlled failure while accessing BASE_TAREAS request storage."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "STORAGE_FAILURE",
        outcome_unknown: bool = False,
        commit_confirmed: bool = False,
    ):
        self.category = category
        self.outcome_unknown = outcome_unknown
        self.commit_confirmed = commit_confirmed
        super().__init__(message)


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
    transaction_active: bool

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

    def validate_creation_result(
        self,
        *,
        request_id: UUID,
        empresa_id: int,
        task_id: int,
        meeting_id: int,
    ) -> bool: ...

    def assert_committable(self) -> None: ...

_MUTABLE_TRANSITION_FIELDS = frozenset(
    {
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
)
_AUDIT_TRANSITION_FIELDS = frozenset(
    {"audit_status", "audit_event_id", "audit_error_code"}
)
_RETRYABLE_DRIVER_CODES = {5, 6, 1205, 1213, "40001", "40P01", "55P03"}
_CHECK_DRIVER_CODES = {3819, 4025}


def _is_fingerprint(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_transition(
    *,
    expected_status: str,
    values: dict[str, object],
    transaction_active: bool,
) -> None:
    if not transaction_active:
        raise ValueError("Las transiciones requieren una unidad transaccional activa.")
    if not isinstance(values, dict) or not values:
        raise ValueError("Los campos de transición no son válidos.")
    keys = set(values)
    if not keys.issubset(_MUTABLE_TRANSITION_FIELDS):
        raise ValueError("Los campos de transición no son válidos.")

    status = values.get("status")
    if status is not None:
        if (
            expected_status == ReunionCreationRequest.Estado.REVISION_PENDIENTE
            and keys == {"status"}
            and status
            in {
                ReunionCreationRequest.Estado.EN_PROGRESO,
                ReunionCreationRequest.Estado.CANCELADA,
                ReunionCreationRequest.Estado.EXPIRADA,
            }
        ):
            return
        if (
            expected_status == ReunionCreationRequest.Estado.REVISION_PENDIENTE
            and status == ReunionCreationRequest.Estado.COMPLETADA
            and keys == {"status", "task_id", "meeting_id", "completed_at"}
        ):
            pass
        elif (
            expected_status == ReunionCreationRequest.Estado.EN_PROGRESO
            and status == ReunionCreationRequest.Estado.COMPLETADA
            and keys == {"status", "task_id", "meeting_id", "completed_at"}
        ):
            pass
        else:
            raise ValueError("La transición de estado no está permitida.")

        if (
            isinstance(values.get("task_id"), bool)
            or not isinstance(values.get("task_id"), int)
            or values["task_id"] < 1
            or isinstance(values.get("meeting_id"), bool)
            or not isinstance(values.get("meeting_id"), int)
            or values["meeting_id"] < 1
            or not isinstance(values.get("completed_at"), datetime)
            or timezone.is_naive(values["completed_at"])
        ):
            raise ValueError("El resultado completado no es válido.")
        return

    if (
        expected_status == ReunionCreationRequest.Estado.REVISION_PENDIENTE
        and keys == {"review_fingerprint", "expires_at"}
    ):
        if (
            not _is_fingerprint(values["review_fingerprint"])
            or not isinstance(values["expires_at"], datetime)
            or timezone.is_naive(values["expires_at"])
        ):
            raise ValueError("La revisión actualizada no es válida.")
        return

    if (
        expected_status
        in {
            ReunionCreationRequest.Estado.COMPLETADA,
            ReunionCreationRequest.Estado.CANCELADA,
        }
        and keys == _AUDIT_TRANSITION_FIELDS
    ):
        audit_status = values["audit_status"]
        audit_event_id = values["audit_event_id"]
        audit_error_code = values["audit_error_code"]
        if audit_status not in {
            ReunionCreationRequest.EstadoAuditoria.PENDIENTE,
            ReunionCreationRequest.EstadoAuditoria.CONFIRMADA,
            ReunionCreationRequest.EstadoAuditoria.ERROR,
        }:
            raise ValueError("El estado de auditoría no es válido.")
        if audit_status == ReunionCreationRequest.EstadoAuditoria.CONFIRMADA:
            if (
                isinstance(audit_event_id, bool)
                or not isinstance(audit_event_id, int)
                or audit_event_id < 1
                or audit_error_code != ""
            ):
                raise ValueError("La confirmación de auditoría no es válida.")
        elif audit_event_id is not None:
            raise ValueError("El evento solo se admite para auditoría confirmada.")
        if not isinstance(audit_error_code, str) or len(audit_error_code) > 64:
            raise ValueError("El código de error de auditoría no es válido.")
        return

    raise ValueError("Los campos no corresponden a una transición permitida.")


def _exception_chain(error: BaseException):
    current = error
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _database_error_code(error: BaseException):
    for current in _exception_chain(error):
        for attribute in ("errno", "pgcode", "sqlstate"):
            value = getattr(current, attribute, None)
            if value is not None:
                return value
        args = getattr(current, "args", ())
        if args and isinstance(args[0], (int, str)):
            return args[0]
    return None


def _database_error_category(error: BaseException) -> str:
    code = _database_error_code(error)
    message = str(error).casefold()
    if code == 1062 or "duplicate entry" in message or "unique constraint failed" in message:
        return "CONFLICT"
    if code in _CHECK_DRIVER_CODES or "check constraint failed" in message:
        return "INVALID_STATE"
    if (
        code in _RETRYABLE_DRIVER_CODES
        or "database is locked" in message
        or "database table is locked" in message
        or is_task_mutation_conflict(error)
    ):
        return "RETRYABLE"
    return "STORAGE_FAILURE"


def _database_storage_error(error: BaseException) -> ReunionCreationRequestStorageError:
    category = _database_error_category(error)
    return ReunionCreationRequestStorageError(
        "No se pudo completar la operación de idempotencia.",
        category=category,
    )


def _is_pymysql_error(error: BaseException) -> bool:
    return type(error).__module__.split(".", 1)[0] == "pymysql"


class _TransactionPhaseError(RuntimeError):
    def __init__(self, phase: str):
        self.phase = phase
        super().__init__(phase)


class _TrackedTransactionConnection:
    alias = None

    def __init__(self, connection):
        self.connection = connection
        self.phase = "not_started"
        self.commit_confirmed = False
        self.rollback_confirmed = False

    def begin(self):
        self.phase = "begin"
        try:
            result = self.connection.begin()
        except Exception as exc:
            raise _TransactionPhaseError("begin") from exc
        self.phase = "work"
        return result

    def commit(self):
        self.phase = "commit"
        try:
            result = self.connection.commit()
        except Exception as exc:
            raise _TransactionPhaseError("commit") from exc
        self.commit_confirmed = True
        self.phase = "committed"
        return result

    def rollback(self):
        self.phase = "rollback"
        try:
            result = self.connection.rollback()
        except Exception as exc:
            raise _TransactionPhaseError("rollback") from exc
        self.rollback_confirmed = True
        self.phase = "rolled_back"
        return result


def _transaction_phase(error: BaseException) -> str | None:
    for current in _exception_chain(error):
        if isinstance(current, _TransactionPhaseError):
            return current.phase
    return None


def _transaction_storage_error(
    error: BaseException,
    transaction_connection: _TrackedTransactionConnection,
) -> ReunionCreationRequestStorageError:
    phase = _transaction_phase(error)
    if phase in {"commit", "rollback"}:
        return ReunionCreationRequestStorageError(
            "El resultado de la transacción de idempotencia es incierto.",
            category="UNKNOWN_COMMIT_RESULT",
            outcome_unknown=True,
        )
    return ReunionCreationRequestStorageError(
        "No se pudo iniciar o completar la transacción de idempotencia.",
        category="STORAGE_FAILURE",
        commit_confirmed=transaction_connection.commit_confirmed,
    )


class DjangoReunionCreationRequestUnit:
    backend_type = "DJANGO"

    def __init__(self, alias: str):
        self.alias = alias
        self.connection = connections[alias]
        self.mutated = False
        self._in_progress_request_ids: set[UUID] = set()
        self._validated_completion: tuple[UUID, int, int, int] | None = None

    @property
    def transaction_active(self) -> bool:
        return self.connection.in_atomic_block

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
        self.mutated = self.mutated or _created
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
        _validate_transition(
            expected_status=expected_status,
            values=values,
            transaction_active=self.transaction_active,
        )
        if values.get("status") == ReunionCreationRequest.Estado.COMPLETADA:
            if (
                self._validated_completion is None
                or self._validated_completion[0] != request_id
                or self._validated_completion[2] != values["task_id"]
                or self._validated_completion[3] != values["meeting_id"]
            ):
                raise ValueError(
                    "La finalización requiere un resultado validado en esta unidad."
                )
        updates = dict(values)
        updates["updated_at"] = timezone.now()
        changed = bool(
            ReunionCreationRequest.objects.using(self.alias)
            .filter(request_id=request_id, status=expected_status)
            .update(**updates)
        )
        self.mutated = self.mutated or changed
        if changed and "status" in values:
            if values["status"] == ReunionCreationRequest.Estado.EN_PROGRESO:
                self._in_progress_request_ids.add(request_id)
            elif values["status"] in {
                ReunionCreationRequest.Estado.COMPLETADA,
                ReunionCreationRequest.Estado.CANCELADA,
                ReunionCreationRequest.Estado.EXPIRADA,
            }:
                self._in_progress_request_ids.discard(request_id)
                if values["status"] == ReunionCreationRequest.Estado.COMPLETADA:
                    self._validated_completion = None
        return changed

    def validate_creation_result(
        self,
        *,
        request_id: UUID,
        empresa_id: int,
        task_id: int,
        meeting_id: int,
    ) -> bool:
        if not self.transaction_active:
            return False
        request = self.get_request(request_id, lock=True)
        if request is None or request.empresa_id != empresa_id:
            return False
        tasks = Tarea.objects.using(self.alias).filter(
            pk=task_id,
            empresa_id=empresa_id,
        )
        meetings = ReunionRevision.objects.using(self.alias).filter(
            pk=meeting_id,
            empresa_id=empresa_id,
            tarea_planificada_id=task_id,
            tarea_planificada__empresa_id=empresa_id,
        )
        if self.connection.features.has_select_for_update:
            tasks = tasks.select_for_update()
            meetings = meetings.select_for_update()
        valid = tasks.exists() and meetings.exists()
        if valid:
            self._validated_completion = (
                request_id,
                empresa_id,
                task_id,
                meeting_id,
            )
        return valid

    def assert_committable(self) -> None:
        if self._in_progress_request_ids:
            raise ReunionCreationRequestStorageError(
                "Una solicitud no puede confirmar el estado IN_PROGRESS.",
                category="INVALID_STATE",
            )


class MySQLReunionCreationRequestUnit:
    backend_type = "MYSQL_CONFIG"

    def __init__(self, connection, cursor, *, transaction_active: bool = False):
        self.alias = None
        self.connection = connection
        self.cursor = cursor
        self.transaction_active = transaction_active
        self.mutated = False
        self._in_progress_request_ids: set[UUID] = set()
        self._validated_completion: tuple[UUID, int, int, int] | None = None
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
        rowcount = self.cursor.rowcount
        self.mutated = self.mutated or (
            isinstance(rowcount, int) and rowcount > 0
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
        _validate_transition(
            expected_status=expected_status,
            values=values,
            transaction_active=self.transaction_active,
        )
        if values.get("status") == ReunionCreationRequest.Estado.COMPLETADA:
            if (
                self._validated_completion is None
                or self._validated_completion[0] != request_id
                or self._validated_completion[2] != values["task_id"]
                or self._validated_completion[3] != values["meeting_id"]
            ):
                raise ValueError(
                    "La finalización requiere un resultado validado en esta unidad."
                )
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
        changed = self.cursor.rowcount == 1
        self.mutated = self.mutated or changed
        if changed and "status" in values:
            if values["status"] == ReunionCreationRequest.Estado.EN_PROGRESO:
                self._in_progress_request_ids.add(request_id)
            elif values["status"] in {
                ReunionCreationRequest.Estado.COMPLETADA,
                ReunionCreationRequest.Estado.CANCELADA,
                ReunionCreationRequest.Estado.EXPIRADA,
            }:
                self._in_progress_request_ids.discard(request_id)
                if values["status"] == ReunionCreationRequest.Estado.COMPLETADA:
                    self._validated_completion = None
        return changed

    def validate_creation_result(
        self,
        *,
        request_id: UUID,
        empresa_id: int,
        task_id: int,
        meeting_id: int,
    ) -> bool:
        if not self.transaction_active:
            return False
        request = self.get_request(request_id, lock=True)
        if request is None or request.empresa_id != empresa_id:
            return False
        self.cursor.execute(
            "SELECT task.`id` FROM `tareas_tarea` task "
            "INNER JOIN `tareas_reunionrevision` meeting "
            "ON meeting.`tarea_planificada_id`=task.`id` "
            "WHERE task.`id`=%s AND task.`empresa_id`=%s "
            "AND meeting.`id`=%s AND meeting.`empresa_id`=%s "
            "FOR UPDATE",
            (task_id, empresa_id, meeting_id, empresa_id),
        )
        valid = self.cursor.fetchone() is not None
        if valid:
            self._validated_completion = (
                request_id,
                empresa_id,
                task_id,
                meeting_id,
            )
        return valid

    def assert_committable(self) -> None:
        if self._in_progress_request_ids:
            raise ReunionCreationRequestStorageError(
                "Una solicitud no puede confirmar el estado IN_PROGRESS.",
                category="INVALID_STATE",
            )


class DjangoReunionCreationRequestStorage:
    def __init__(self, alias: str):
        self.alias = alias

    @contextmanager
    def atomic(self) -> Iterator[ReunionCreationRequestUnitOfWork]:
        unit = None
        body_failed = False
        try:
            with transaction.atomic(using=self.alias):
                unit = DjangoReunionCreationRequestUnit(self.alias)
                try:
                    yield unit
                    unit.assert_committable()
                except TaskMutationConflict as exc:
                    body_failed = True
                    raise ReunionCreationRequestStorageError(
                        "La operación está bloqueada por otra mutación.",
                        category="RETRYABLE",
                    ) from exc
                except DatabaseError as exc:
                    body_failed = True
                    raise _database_storage_error(exc) from exc
        except ReunionCreationRequestStorageError:
            raise
        except DatabaseError as exc:
            raise ReunionCreationRequestStorageError(
                "No se pudo completar la transacción de idempotencia.",
                category=(
                    "UNKNOWN_COMMIT_RESULT"
                    if body_failed or (unit is not None and unit.mutated)
                    else "STORAGE_FAILURE"
                ),
                outcome_unknown=body_failed or (unit is not None and unit.mutated),
            ) from exc


class MySQLReunionCreationRequestStorage:
    def __init__(self, connection_config, database_name: str):
        self.connection_config = connection_config
        self.database_name = database_name

    @contextmanager
    def atomic(self) -> Iterator[ReunionCreationRequestUnitOfWork]:
        transaction_connection = None
        transaction_tracker = None
        unit = None
        body_failed = False
        work_completed = False
        try:
            with open_mysql_connection(
                self.connection_config,
                database_name=self.database_name,
            ) as connection:
                if (
                    getattr(self.connection_config, "nombre_logico", None)
                    != "django_tareas"
                    or self.database_name != "tareas"
                    or _get_active_database(connection) != "tareas"
                ):
                    raise ReunionCreationRequestStorageError(
                        "La conexión operacional no apunta a la base autorizada."
                    )
                if getattr(connection, "alias", None):
                    transaction_connection = connection
                else:
                    transaction_tracker = _TrackedTransactionConnection(connection)
                    transaction_connection = transaction_tracker
                with bounded_mysql_lock_wait(connection):
                    try:
                        with mysql_mutation_transaction(transaction_connection):
                            cursor = connection.cursor()
                            try:
                                unit = MySQLReunionCreationRequestUnit(
                                    connection,
                                    cursor,
                                    transaction_active=True,
                                )
                                try:
                                    yield unit
                                    unit.assert_committable()
                                except TaskMutationConflict as exc:
                                    body_failed = True
                                    raise ReunionCreationRequestStorageError(
                                        "La operación está bloqueada por otra mutación.",
                                        category="RETRYABLE",
                                    ) from exc
                                except DatabaseError as exc:
                                    body_failed = True
                                    raise _database_storage_error(exc) from exc
                                except Exception as exc:
                                    if _is_pymysql_error(exc):
                                        body_failed = True
                                        raise _database_storage_error(exc) from exc
                                    raise
                            finally:
                                cursor.close()
                            work_completed = True
                    except TaskMutationLockError as exc:
                        if transaction_tracker is not None:
                            raise _transaction_storage_error(
                                exc,
                                transaction_tracker,
                            ) from exc
                        raise ReunionCreationRequestStorageError(
                            "No se pudo completar la transacción de idempotencia.",
                            category="STORAGE_FAILURE",
                            commit_confirmed=(
                                work_completed and unit is not None and unit.mutated
                            ),
                        ) from exc
                    except TaskMutationConflict as exc:
                        cause = exc.__cause__
                        if isinstance(cause, ReunionCreationRequestStorageError):
                            raise cause
                        raise ReunionCreationRequestStorageError(
                            "La operación está bloqueada por otra mutación.",
                            category="RETRYABLE",
                        ) from exc
                    except DatabaseError as exc:
                        category = _database_error_category(exc)
                        outcome_unknown = bool(
                            body_failed
                            or (
                                work_completed
                                and unit is not None
                                and unit.mutated
                            )
                        )
                        if outcome_unknown:
                            raise ReunionCreationRequestStorageError(
                                "El resultado de la transacción de idempotencia es incierto.",
                                category="UNKNOWN_COMMIT_RESULT",
                                outcome_unknown=True,
                            ) from exc
                        raise ReunionCreationRequestStorageError(
                            "No se pudo completar la operación de idempotencia.",
                            category=category,
                        ) from exc
                    except Exception as exc:
                        if _is_pymysql_error(exc):
                            raise _database_storage_error(exc) from exc
                        raise
        except TaskMutationConflict as exc:
            cause = exc.__cause__
            if isinstance(cause, ReunionCreationRequestStorageError):
                raise cause
            raise ReunionCreationRequestStorageError(
                "La operación está bloqueada por otra mutación.",
                category="RETRYABLE",
            ) from exc
        except MySQLConnectionOpenError as exc:
            raise ReunionCreationRequestStorageError(
                "No se pudo abrir el almacenamiento operacional de Tareas."
            ) from exc
        except ReunionCreationRequestStorageError:
            raise
        except TaskMutationLockError as exc:
            if transaction_tracker is not None:
                raise _transaction_storage_error(
                    exc,
                    transaction_tracker,
                ) from exc
            raise ReunionCreationRequestStorageError(
                "No se pudo preparar la transacción de idempotencia."
            ) from exc
        except DatabaseError as exc:
            raise _database_storage_error(exc) from exc
        except Exception as exc:
            if _is_pymysql_error(exc):
                raise _database_storage_error(exc) from exc
            raise


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
        and getattr(context.mysql_connection, "nombre_logico", None)
        == "django_tareas"
        and context.database_name == "tareas"
    ):
        return MySQLReunionCreationRequestStorage(
            context.mysql_connection,
            context.database_name,
        )

    raise ReunionCreationRequestStorageError(
        "BASE_TAREAS no tiene un backend permitido para idempotencia."
    )


def _get_active_database(connection) -> str | None:
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT DATABASE()")
        row = cursor.fetchone()
        return str(row[0]) if row and row[0] is not None else None
    finally:
        cursor.close()


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
