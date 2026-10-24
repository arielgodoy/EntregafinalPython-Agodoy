"""Read-only history projections for logically deleted tasks and operations."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
import json
import re
from typing import Callable, Generator, Protocol, Sequence, cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db import connections

from auditoria.services import (
    AuditIdempotencyStorageError,
    AuditoriaService,
)
from settings.services.mysql_connections import (
    MySQLConnectionOpenError,
    open_mysql_connection,
)

from ..models import (
    Comentario,
    DocumentoHistorial,
    DocumentoTarea,
    EvidenciaCierre,
    Hito,
    HitoEvidencia,
    HitoHistorial,
    LOGICAL_DELETION_RESULT_CODE,
    LOGICAL_RESTORATION_RESULT_CODE,
    MiniTarea,
    MiniTareaEvento,
    Tarea,
    TareaCierre,
    TareaEliminacionArchivo,
    TareaEliminacionElemento,
    TareaEliminacionOperacion,
    TareaParticipante,
    TareaRelacion,
    TareaTransicion,
)
from .connection_roles import (
    BackendContext,
    TareaConnectionError,
    resolve_operational_backend,
)
from .deletion_ledger import DeletionLedgerError


TASK_ITEM_LABEL = Tarea._meta.label_lower
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_PAGE_SIZE = 100
_MAX_SEARCH_LENGTH = 200
_MAX_MOTIVE_LENGTH = 200
_AUDIT_STATUSES = frozenset(value for value, _label in TareaEliminacionOperacion.EstadoAuditoria.choices)
_TASK_STATES = frozenset(value for value, _label in Tarea.Estado.choices)
_SORTS = frozenset({"deleted_desc", "deleted_asc", "correlativo", "titulo"})


class DeletedTaskHistoryError(RuntimeError):
    """Base error for read-only deleted-task history operations."""


class DeletedTaskHistoryNotFound(DeletedTaskHistoryError):
    """The historical object is absent from the active company's ledger."""


class DeletedTaskHistoryUnavailable(DeletedTaskHistoryError):
    """The configured operational history source could not be read."""


class DeletedTaskHistoryInvalidFilter(ValueError):
    """A caller supplied an invalid history filter or page parameter."""


@dataclass(frozen=True)
class DeletedTaskHistoryFilters:
    search: str = ""
    date_from: date | None = None
    date_to: date | None = None
    actor_id: int | None = None
    motive: str = ""
    task_state: str = ""
    audit_status: str = ""
    order_by: str = "deleted_desc"
    page: int = 1
    page_size: int = 25


@dataclass(frozen=True)
class DeletedTaskHistoryItem:
    operation_id: UUID
    empresa_id: int
    task_id: int
    root_task_id: int
    is_root: bool
    root_correlativo: str
    correlativo: str | None
    titulo: str | None
    estado: str | None
    deleted_at: datetime | None
    actor_id: int
    motivo: str | None
    operation_status: str
    result_code: str
    audit_status: str
    audit_event_id: int | None
    physical_status: str
    deletion_status: str = "CURRENTLY_DELETED"

    @property
    def historical_reference(self) -> str:
        if self.correlativo:
            return self.correlativo
        if self.is_root and self.root_correlativo:
            return self.root_correlativo
        return f"Tarea ID {self.task_id}"


@dataclass(frozen=True)
class DeletedTaskHistoryPage:
    items: tuple[DeletedTaskHistoryItem, ...]
    total: int
    page: int
    page_size: int
    total_pages: int


@dataclass(frozen=True)
class DeletionHistoryFile:
    storage_key: str
    file_name: str
    status: str
    attempts: int
    last_attempt_at: datetime | None
    error_code: str


@dataclass(frozen=True)
class DeletionHistoryRelation:
    parent_id: int
    child_id: int
    parent_in_manifest: bool
    child_in_manifest: bool


@dataclass(frozen=True)
class DeletionHistoryManifestItem:
    item_type: str
    object_id: int
    physical_status: str
    task: DeletedTaskHistoryItem | None


@dataclass(frozen=True)
class DeletionHistoryAudit:
    event_id: int
    created_at: datetime
    action: str
    actor_id: int | None
    object_type: str | None
    object_id: str | None
    message_key: str | None
    operation_id: str | None
    backend_type: str | None


@dataclass(frozen=True)
class DeletedTaskRestoration:
    operation_id: UUID
    actor_id: int
    motivo: str | None
    status: str
    result_code: str
    created_at: datetime
    committed_at: datetime | None
    audit_status: str
    audit_event_id: int | None
    audit_error_code: str
    manifest_matches: bool
    metadata_matches: bool


@dataclass(frozen=True)
class DeletedTaskHistoryOperation:
    operation_id: UUID
    empresa_id: int
    root_task_id: int
    root_correlativo: str
    actor_id: int
    motivo: str | None
    backend_type: str
    backend_identity: str
    status: str
    result_code: str
    audit_status: str
    audit_event_id: int | None
    audit_error_code: str
    file_cleanup_status: str
    created_at: datetime
    committed_at: datetime | None
    dependency_summary: dict[str, int] | None
    dependency_summary_valid: bool
    audit: DeletionHistoryAudit | None
    audit_consistency: str
    items: tuple[DeletionHistoryManifestItem, ...]
    files: tuple[DeletionHistoryFile, ...]
    relations: tuple[DeletionHistoryRelation, ...]
    hierarchy_status: str
    deletion_status: str = "CURRENTLY_DELETED"
    restoration: DeletedTaskRestoration | None = None


@dataclass(frozen=True)
class DeletedTaskHistoryRelatedData:
    related_status: str
    participants: tuple["DeletedHistoryRecord", ...]
    milestones: tuple["DeletedHistoryRecord", ...]
    mini_tasks: tuple["DeletedHistoryRecord", ...]
    documents: tuple["DeletedHistoryRecord", ...]
    closure_evidence: tuple["DeletedHistoryRecord", ...]
    transitions: tuple["DeletedHistoryRecord", ...]
    closures: tuple["DeletedHistoryRecord", ...]
    comments_status: str
    comments: tuple["DeletedHistoryRecord", ...]


@dataclass(frozen=True)
class DeletedTaskHistoryDetail:
    operation: DeletedTaskHistoryOperation
    task: DeletedTaskHistoryItem
    description: str | None
    prioridad: str | None
    fecha_creacion: datetime | None
    fecha_publicacion: datetime | None
    fecha_asignacion: datetime | None
    fecha_tope: date | None
    fecha_cumplimiento: datetime | None
    creada_por_id: int | None
    responsable_id: int | None
    local_id: int | None
    departamento_id: int | None
    core_information_available: bool
    related: DeletedTaskHistoryRelatedData


@dataclass(frozen=True)
class DeletedHistoryRecord:
    kind: str
    object_id: int
    label: str | None
    state: str | None
    actor_id: int | None
    occurred_at: datetime | date | None
    details: tuple[tuple[str, object], ...]


class _HistoryCursor(Protocol):
    description: Sequence[tuple[str, ...]] | None

    def execute(self, sql: str, params: object = ...) -> object: ...

    def fetchone(self) -> Sequence[object] | None: ...

    def fetchall(self) -> Sequence[Sequence[object]]: ...

    def close(self) -> None: ...


class _HistoryConnection(Protocol):
    def cursor(self) -> _HistoryCursor: ...


@contextmanager
def _history_cursor() -> Generator[
    tuple[_HistoryCursor, str, Callable[[str], str]],
    None,
    None,
]:
    try:
        context = resolve_operational_backend("BASE_TAREAS")
    except TareaConnectionError as exc:
        raise DeletedTaskHistoryUnavailable(
            "No se pudo resolver BASE_TAREAS para consultar el historial."
        ) from exc

    if context.backend_type == "DJANGO":
        alias = context.django_alias
        if not alias:
            raise DeletedTaskHistoryUnavailable(
                "BASE_TAREAS no proporcionó un alias Django válido."
            )
        connection = connections[alias]
        cursor = cast(_HistoryCursor, connection.cursor())
        try:
            if connection.vendor == "mysql":
                cursor.execute("SELECT DATABASE()")
                selected = cursor.fetchone()
                if not selected or selected[0] != connection.settings_dict.get("NAME"):
                    raise DeletedTaskHistoryUnavailable(
                        "La conexión Django no seleccionó la base de BASE_TAREAS."
                    )
            yield cursor, connection.vendor, connection.ops.quote_name
        finally:
            cursor.close()
        return

    if (
        context.backend_type != "MYSQL_CONFIG"
        or context.mysql_connection is None
        or not context.database_name
    ):
        raise DeletedTaskHistoryUnavailable(
            "El backend BASE_TAREAS no está disponible para historial."
        )

    try:
        with open_mysql_connection(
            context.mysql_connection,
            database_name=context.database_name,
        ) as connection:
            typed_connection = cast(_HistoryConnection, connection)
            cursor = typed_connection.cursor()
            try:
                cursor.execute("SELECT DATABASE()")
                selected = cursor.fetchone()
                if not selected or selected[0] != context.database_name:
                    raise DeletedTaskHistoryUnavailable(
                        "La conexión no está seleccionada sobre BASE_TAREAS."
                    )
                yield cursor, "mysql", _quote_mysql_identifier
            finally:
                cursor.close()
    except MySQLConnectionOpenError as exc:
        raise DeletedTaskHistoryUnavailable(
            "No se pudo abrir BASE_TAREAS para consultar el historial."
        ) from exc
    except DeletionLedgerError as exc:
        raise DeletedTaskHistoryUnavailable(
            "No se pudo consultar el ledger de BASE_TAREAS."
        ) from exc


def _quote_mysql_identifier(value: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise DeletedTaskHistoryUnavailable(
            "El contrato de historial contiene un identificador inválido."
        )
    return f"`{value}`"


def _column(model, field_name: str, quote) -> str:
    field = model._meta.get_field(field_name)
    column = field.column
    if not column:
        raise DeletedTaskHistoryUnavailable(
            "El contrato de historial no resuelve una columna requerida."
        )
    return quote(column)


def _required_history_int(value: object, field_name: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    raise DeletedTaskHistoryUnavailable(
        f"El campo {field_name} no contiene un entero válido."
    )


def _optional_history_int(value: object, field_name: str) -> int | None:
    return (
        None
        if value is None
        else _required_history_int(value, field_name)
    )


def _required_history_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    raise DeletedTaskHistoryUnavailable(
        f"El campo {field_name} no contiene una fecha válida."
    )


def _optional_history_datetime(value: object, field_name: str) -> datetime | None:
    return (
        None
        if value is None
        else _required_history_datetime(value, field_name)
    )


def _optional_history_date(value: object, field_name: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    raise DeletedTaskHistoryUnavailable(
        f"El campo {field_name} no contiene una fecha válida."
    )


def _table(model, quote) -> str:
    table = model._meta.db_table
    if not isinstance(table, str) or not _IDENTIFIER.fullmatch(table):
        raise DeletedTaskHistoryUnavailable(
            "El contrato de historial no resuelve una tabla válida."
        )
    return quote(table)


def _validate_positive_int(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DeletedTaskHistoryInvalidFilter(f"{field_name} debe ser un entero positivo.")


def _validated_filters(filters: DeletedTaskHistoryFilters) -> DeletedTaskHistoryFilters:
    if not isinstance(filters, DeletedTaskHistoryFilters):
        raise TypeError("filters debe ser DeletedTaskHistoryFilters.")
    _validate_positive_int(filters.page, "page")
    _validate_positive_int(filters.page_size, "page_size")
    if filters.page_size > _MAX_PAGE_SIZE:
        raise DeletedTaskHistoryInvalidFilter(
            f"page_size no puede exceder {_MAX_PAGE_SIZE}."
        )
    if filters.order_by not in _SORTS:
        raise DeletedTaskHistoryInvalidFilter("order_by no está permitido.")
    if not isinstance(filters.search, str) or len(filters.search) > _MAX_SEARCH_LENGTH:
        raise DeletedTaskHistoryInvalidFilter("search no es válido.")
    if not isinstance(filters.motive, str) or len(filters.motive) > _MAX_MOTIVE_LENGTH:
        raise DeletedTaskHistoryInvalidFilter("motive no es válido.")
    if filters.actor_id is not None:
        _validate_positive_int(filters.actor_id, "actor_id")
    if filters.audit_status and filters.audit_status not in _AUDIT_STATUSES:
        raise DeletedTaskHistoryInvalidFilter("audit_status no está permitido.")
    if filters.task_state and filters.task_state not in _TASK_STATES:
        raise DeletedTaskHistoryInvalidFilter("task_state no está permitido.")
    for name, value in (("date_from", filters.date_from), ("date_to", filters.date_to)):
        if value is not None and (
            not isinstance(value, date) or isinstance(value, datetime)
        ):
            raise DeletedTaskHistoryInvalidFilter(f"{name} debe ser una fecha.")
    if filters.date_from and filters.date_to and filters.date_from > filters.date_to:
        raise DeletedTaskHistoryInvalidFilter(
            "date_from no puede ser posterior a date_to."
        )
    return filters


def _utc_naive_local_midnight(value: date) -> datetime:
    timezone_name = getattr(settings, "SYSTEM_LOCAL_TIME_ZONE", None)
    if not timezone_name:
        raise DeletedTaskHistoryUnavailable(
            "SYSTEM_LOCAL_TIME_ZONE no está configurada para filtrar fechas."
        )
    try:
        local_zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise DeletedTaskHistoryUnavailable(
            "SYSTEM_LOCAL_TIME_ZONE no es válida."
        ) from exc
    local = datetime.combine(value, time.min, tzinfo=local_zone)
    return local.astimezone(dt_timezone.utc).replace(tzinfo=None)


def _list_query(
    *,
    empresa_id: int,
    filters: DeletedTaskHistoryFilters,
    vendor: str,
    quote,
) -> tuple[str, tuple[object, ...], str, tuple[object, ...]]:
    op_table = _table(TareaEliminacionOperacion, quote)
    item_table = _table(TareaEliminacionElemento, quote)
    task_table = _table(Tarea, quote)

    op = {
        name: _column(TareaEliminacionOperacion, name, quote)
        for name in (
            "operation_id", "empresa_id", "root_task_id", "root_correlativo",
            "actor_id", "motivo", "status", "result_code", "audit_status",
            "audit_event_id", "audit_error_code", "file_cleanup_status",
            "created_at", "committed_at", "backend_type", "backend_identity",
            "backend_config_version",
        )
    }
    restoration = {
        name: _column(TareaEliminacionOperacion, name, quote)
        for name in (
            "operation_id", "reverses_operation", "empresa_id", "root_task_id",
            "actor_id", "motivo", "status", "result_code", "audit_status",
            "audit_event_id", "audit_error_code", "file_cleanup_status",
            "created_at", "committed_at", "backend_type", "backend_identity",
            "backend_config_version",
        )
    }
    item = {
        name: _column(TareaEliminacionElemento, name, quote)
        for name in ("operacion", "tipo", "object_id")
    }
    task = {
        name: _column(Tarea, name, quote)
        for name in (
            "id", "empresa", "correlativo", "titulo", "estado", "eliminada",
            "eliminada_en", "eliminada_por", "eliminacion_operacion_id",
        )
    }
    task_valid_sql = (
        f"task.{task['id']} IS NOT NULL "
        f"AND task.{task['eliminada']} = 1 "
        f"AND task.{task['eliminada_en']} IS NOT NULL "
        f"AND task.{task['eliminada_por']} = op.{op['actor_id']} "
        f"AND task.{task['eliminacion_operacion_id']} = op.{op['operation_id']}"
    )
    deleted_at_sql = (
        f"CASE WHEN {task_valid_sql} THEN task.{task['eliminada_en']} "
        f"ELSE COALESCE(op.{op['committed_at']}, op.{op['created_at']}) END"
    )
    task_code_sql = (
        f"COALESCE(CASE WHEN {task_valid_sql} "
        f"THEN task.{task['correlativo']} ELSE NULL END, "
        f"CASE WHEN item.{item['object_id']} = op.{op['root_task_id']} "
        f"THEN op.{op['root_correlativo']} ELSE NULL END)"
    )
    task_title_sql = (
        f"CASE WHEN {task_valid_sql} "
        f"THEN task.{task['titulo']} ELSE NULL END"
    )
    from_sql = (
        f"FROM {op_table} op "
        f"JOIN {item_table} item "
        f"ON item.{item['operacion']} = op.{op['operation_id']} "
        f"LEFT JOIN {task_table} task "
        f"ON task.{task['id']} = item.{item['object_id']} "
        f"AND task.{task['empresa']} = op.{op['empresa_id']}"
        f" LEFT JOIN {op_table} restoration "
        f"ON restoration.{restoration['reverses_operation']} = op.{op['operation_id']} "
        f"AND restoration.{restoration['empresa_id']} = op.{op['empresa_id']}"
    )
    where = [
        f"op.{op['empresa_id']} = %s",
        f"op.{op['status']} = %s",
        f"op.{op['result_code']} = %s",
        f"item.{item['tipo']} = %s",
    ]
    params: list[object] = [
        empresa_id,
        TareaEliminacionOperacion.Estado.COMMITTED,
        LOGICAL_DELETION_RESULT_CODE,
        TASK_ITEM_LABEL,
    ]

    if filters.search:
        object_cast = (
            f"CAST(item.{item['object_id']} AS CHAR)"
            if vendor == "mysql"
            else f"CAST(item.{item['object_id']} AS TEXT)"
        )
        search_sql = (
            f"(LOWER(COALESCE({task_code_sql}, '')) LIKE %s "
            f"OR LOWER(COALESCE({task_title_sql}, '')) LIKE %s "
            f"OR LOWER(COALESCE(op.{op['motivo']}, '')) LIKE %s "
            f"OR {object_cast} LIKE %s)"
        )
        where.append(search_sql)
        pattern = f"%{filters.search.casefold()}%"
        params.extend((pattern, pattern, pattern, pattern))
    if filters.actor_id is not None:
        where.append(f"op.{op['actor_id']} = %s")
        params.append(filters.actor_id)
    if filters.motive:
        where.append(f"LOWER(COALESCE(op.{op['motivo']}, '')) LIKE %s")
        params.append(f"%{filters.motive.casefold()}%")
    if filters.audit_status:
        where.append(f"op.{op['audit_status']} = %s")
        params.append(filters.audit_status)
    if filters.task_state:
        where.append(f"({task_valid_sql}) AND task.{task['estado']} = %s")
        params.append(filters.task_state)
    if filters.date_from:
        where.append(f"{deleted_at_sql} >= %s")
        params.append(_utc_naive_local_midnight(filters.date_from))
    if filters.date_to:
        next_day = filters.date_to + timedelta(days=1)
        where.append(f"{deleted_at_sql} < %s")
        params.append(_utc_naive_local_midnight(next_day))

    where_sql = " WHERE " + " AND ".join(where)
    count_sql = f"SELECT COUNT(*) {from_sql}{where_sql}"
    order_by_sql = {
        "deleted_desc": f"{deleted_at_sql} DESC, op.{op['operation_id']} DESC, item.{item['object_id']} DESC",
        "deleted_asc": f"{deleted_at_sql} ASC, op.{op['operation_id']} ASC, item.{item['object_id']} ASC",
        "correlativo": f"{task_code_sql} ASC, op.{op['operation_id']} ASC, item.{item['object_id']} ASC",
        "titulo": f"LOWER(COALESCE({task_title_sql}, '')) ASC, op.{op['operation_id']} ASC, item.{item['object_id']} ASC",
    }[filters.order_by]
    select_sql = (
        "SELECT "
        f"op.{op['operation_id']} AS operation_id, "
        f"op.{op['empresa_id']} AS empresa_id, "
        f"op.{op['root_task_id']} AS root_task_id, "
        f"op.{op['root_correlativo']} AS root_correlativo, "
        f"op.{op['actor_id']} AS actor_id, "
        f"op.{op['motivo']} AS motivo, "
        f"op.{op['status']} AS operation_status, "
        f"op.{op['result_code']} AS result_code, "
        f"op.{op['audit_status']} AS audit_status, "
        f"op.{op['audit_event_id']} AS audit_event_id, "
        f"op.{op['created_at']} AS source_created_at, "
        f"op.{op['committed_at']} AS source_committed_at, "
        f"op.{op['backend_type']} AS backend_type, "
        f"op.{op['backend_identity']} AS backend_identity, "
        f"op.{op['backend_config_version']} AS backend_config_version, "
        f"restoration.{restoration['operation_id']} AS restoration_operation_id, "
        f"restoration.{restoration['reverses_operation']} AS restoration_source_operation_id, "
        f"restoration.{restoration['empresa_id']} AS restoration_empresa_id, "
        f"restoration.{restoration['root_task_id']} AS restoration_root_task_id, "
        f"restoration.{restoration['actor_id']} AS restoration_actor_id, "
        f"restoration.{restoration['motivo']} AS restoration_motivo, "
        f"restoration.{restoration['status']} AS restoration_status, "
        f"restoration.{restoration['result_code']} AS restoration_result_code, "
        f"restoration.{restoration['audit_status']} AS restoration_audit_status, "
        f"restoration.{restoration['audit_event_id']} AS restoration_audit_event_id, "
        f"restoration.{restoration['audit_error_code']} AS restoration_audit_error_code, "
        f"restoration.{restoration['file_cleanup_status']} AS restoration_file_cleanup_status, "
        f"restoration.{restoration['created_at']} AS restoration_created_at, "
        f"restoration.{restoration['committed_at']} AS restoration_committed_at, "
        f"restoration.{restoration['backend_type']} AS restoration_backend_type, "
        f"restoration.{restoration['backend_identity']} AS restoration_backend_identity, "
        f"restoration.{restoration['backend_config_version']} AS restoration_backend_config_version, "
        f"item.{item['object_id']} AS task_id, "
        f"task.{task['id']} AS physical_task_id, "
        f"task.{task['correlativo']} AS task_correlativo, "
        f"task.{task['titulo']} AS task_title, "
        f"task.{task['estado']} AS task_state, "
        f"task.{task['eliminada']} AS task_deleted, "
        f"task.{task['eliminada_en']} AS task_deleted_at, "
        f"task.{task['eliminada_por']} AS task_deleted_by_id, "
        f"task.{task['eliminacion_operacion_id']} AS task_operation_id, "
        f"{deleted_at_sql} AS deleted_at "
        f"{from_sql}{where_sql} ORDER BY {order_by_sql} LIMIT %s OFFSET %s"
    )
    data_params = tuple(params) + (
        filters.page_size,
        (filters.page - 1) * filters.page_size,
    )
    return count_sql, tuple(params), select_sql, data_params


def _dict_rows(cursor: _HistoryCursor) -> tuple[dict[str, object], ...]:
    description = cursor.description or ()
    names = tuple(column[0] for column in description)
    return tuple(dict(zip(names, row)) for row in cursor.fetchall())


def _uuid_matches(value: object, expected: UUID) -> bool:
    if value is None:
        return False
    try:
        return (value if isinstance(value, UUID) else UUID(str(value))) == expected
    except (TypeError, ValueError, AttributeError):
        return False


def _operation_timeline_is_valid(
    operation: dict[str, object],
    *,
    not_before: datetime | None = None,
) -> bool:
    created_at = operation.get("created_at")
    committed_at = operation.get("committed_at")
    if (
        not isinstance(created_at, datetime)
        or not isinstance(committed_at, datetime)
        or (not_before is not None and not isinstance(not_before, datetime))
    ):
        return False
    try:
        return committed_at >= created_at and (
            not_before is None or created_at >= not_before
        )
    except TypeError:
        return False


def _restoration_timeline_is_valid(
    source: dict[str, object],
    restoration: dict[str, object],
) -> bool:
    source_committed_at = source.get("committed_at")
    return bool(
        _operation_timeline_is_valid(source)
        and isinstance(source_committed_at, datetime)
        and _operation_timeline_is_valid(
            restoration,
            not_before=source_committed_at,
        )
    )


def _manifest_entries(
    rows: Sequence[dict[str, object]],
) -> tuple[tuple[str, int], ...]:
    return tuple(
        sorted(
            (
                str(row["item_type"]),
                _required_history_int(row["object_id"], "object_id"),
            )
            for row in rows
        )
    )


def _task_markers_match_deletion(
    task: dict[str, object] | None,
    *,
    operation_id: UUID,
    empresa_id: int,
    actor_id: int,
) -> bool:
    return bool(
        task
        and _required_history_int(task["empresa_id"], "task_empresa_id") == empresa_id
        and task["eliminada"] in (True, 1)
        and task["eliminada_en"] is not None
        and task["eliminada_por"] == actor_id
        and _uuid_matches(task["eliminacion_operacion_id"], operation_id)
    )


def _task_markers_are_clear(task: dict[str, object] | None, empresa_id: int) -> bool:
    return bool(
        task
        and _required_history_int(task["empresa_id"], "task_empresa_id") == empresa_id
        and task["eliminada"] in (False, 0)
        and task["eliminada_en"] is None
        and task["eliminada_por"] is None
        and task["eliminacion_operacion_id"] is None
    )


def _restoration_row_from_list(row: dict[str, object]) -> dict[str, object] | None:
    if row.get("restoration_operation_id") is None:
        return None
    return {
        "operation_id": row["restoration_operation_id"],
        "reverses_operation_id": row["restoration_source_operation_id"],
        "empresa_id": row["restoration_empresa_id"],
        "root_task_id": row["restoration_root_task_id"],
        "actor_id": row["restoration_actor_id"],
        "motivo": row["restoration_motivo"],
        "status": row["restoration_status"],
        "result_code": row["restoration_result_code"],
        "audit_status": row["restoration_audit_status"],
        "audit_event_id": row["restoration_audit_event_id"],
        "audit_error_code": row["restoration_audit_error_code"],
        "file_cleanup_status": row["restoration_file_cleanup_status"],
        "created_at": row["restoration_created_at"],
        "committed_at": row["restoration_committed_at"],
        "backend_type": row["restoration_backend_type"],
        "backend_identity": row["restoration_backend_identity"],
        "backend_config_version": row["restoration_backend_config_version"],
    }


def _load_current_deletion_contexts(
    cursor: _HistoryCursor,
    quote: Callable[[str], str],
    *,
    empresa_id: int,
    task_rows_by_source: dict[str, dict[int, dict[str, object]]],
) -> dict[str, dict[str, object]]:
    current_operation_ids = set()
    for source_id, task_rows in task_rows_by_source.items():
        for task_row in task_rows.values():
            raw_operation_id = task_row.get("eliminacion_operacion_id")
            if raw_operation_id is None:
                continue
            try:
                operation_id = _normal_uuid(raw_operation_id).hex
            except (TypeError, ValueError, AttributeError):
                continue
            if operation_id != source_id:
                current_operation_ids.add(operation_id)
    if not current_operation_ids:
        return {}

    operation_ids = tuple(sorted(current_operation_ids))
    placeholders = ", ".join("%s" for _ in operation_ids)
    operation = TareaEliminacionOperacion
    operation_table = _table(operation, quote)
    operation_fields = (
        ("operation_id", "operation_id"),
        ("reverses_operation", "reverses_operation_id"),
        ("empresa_id", "empresa_id"),
        ("root_task_id", "root_task_id"),
        ("root_correlativo", "root_correlativo"),
        ("actor_id", "actor_id"),
        ("motivo", "motivo"),
        ("backend_type", "backend_type"),
        ("backend_identity", "backend_identity"),
        ("backend_config_version", "backend_config_version"),
        ("status", "status"),
        ("result_code", "result_code"),
        ("audit_status", "audit_status"),
        ("file_cleanup_status", "file_cleanup_status"),
        ("created_at", "created_at"),
        ("committed_at", "committed_at"),
    )
    operation_select = ", ".join(
        f"op.{_column(operation, field_name, quote)} AS {alias}"
        for field_name, alias in operation_fields
    )
    cursor.execute(
        f"SELECT {operation_select} FROM {operation_table} op "
        f"WHERE op.{_column(operation, 'operation_id', quote)} "
        f"IN ({placeholders}) "
        f"AND op.{_column(operation, 'empresa_id', quote)} = %s",
        (*operation_ids, empresa_id),
    )
    operation_rows = {
        _normal_uuid(str(row["operation_id"])).hex: row
        for row in _dict_rows(cursor)
    }
    if not operation_rows:
        return {}

    source_ids = tuple(sorted(operation_rows))
    source_placeholders = ", ".join("%s" for _ in source_ids)
    cursor.execute(
        f"SELECT {_column(operation, 'operation_id', quote)} AS operation_id, "
        f"{_column(operation, 'reverses_operation', quote)} AS reverses_operation_id, "
        f"{_column(operation, 'empresa_id', quote)} AS empresa_id, "
        f"{_column(operation, 'root_task_id', quote)} AS root_task_id, "
        f"{_column(operation, 'root_correlativo', quote)} AS root_correlativo, "
        f"{_column(operation, 'actor_id', quote)} AS actor_id, "
        f"{_column(operation, 'motivo', quote)} AS motivo, "
        f"{_column(operation, 'backend_type', quote)} AS backend_type, "
        f"{_column(operation, 'backend_identity', quote)} AS backend_identity, "
        f"{_column(operation, 'backend_config_version', quote)} AS backend_config_version, "
        f"{_column(operation, 'status', quote)} AS status, "
        f"{_column(operation, 'result_code', quote)} AS result_code, "
        f"{_column(operation, 'file_cleanup_status', quote)} AS file_cleanup_status, "
        f"{_column(operation, 'created_at', quote)} AS created_at, "
        f"{_column(operation, 'committed_at', quote)} AS committed_at "
        f"FROM {operation_table} "
        f"WHERE {_column(operation, 'reverses_operation', quote)} "
        f"IN ({source_placeholders}) "
        f"AND {_column(operation, 'empresa_id', quote)} = %s "
        f"ORDER BY {_column(operation, 'operation_id', quote)}",
        (*source_ids, empresa_id),
    )
    restorations_by_source: dict[str, list[dict[str, object]]] = {
        source_id: [] for source_id in source_ids
    }
    restoration_rows = _dict_rows(cursor)
    restoration_ids = []
    for row in restoration_rows:
        source_id = _normal_uuid(str(row["reverses_operation_id"])).hex
        restorations_by_source.setdefault(source_id, []).append(row)
        restoration_ids.append(_normal_uuid(str(row["operation_id"])).hex)

    manifest_operation_ids = tuple(sorted(set(source_ids + tuple(restoration_ids))))
    manifest_placeholders = ", ".join(
        "%s" for _ in manifest_operation_ids
    )
    item = TareaEliminacionElemento
    cursor.execute(
        f"SELECT {_column(item, 'operacion', quote)} AS operation_id, "
        f"{_column(item, 'tipo', quote)} AS item_type, "
        f"{_column(item, 'object_id', quote)} AS object_id "
        f"FROM {_table(item, quote)} "
        f"WHERE {_column(item, 'operacion', quote)} "
        f"IN ({manifest_placeholders}) "
        f"ORDER BY {_column(item, 'operacion', quote)}, "
        f"{_column(item, 'tipo', quote)}, {_column(item, 'object_id', quote)}",
        manifest_operation_ids,
    )
    manifests: dict[str, list[dict[str, object]]] = {}
    for row in _dict_rows(cursor):
        manifest_id = _normal_uuid(str(row["operation_id"])).hex
        manifests.setdefault(manifest_id, []).append(row)

    task = Tarea
    task_id_column = _column(task, "id", quote)
    task_company_column = _column(task, "empresa", quote)
    task_deleted_column = _column(task, "eliminada", quote)
    task_deleted_at_column = _column(task, "eliminada_en", quote)
    task_deleted_by_column = _column(task, "eliminada_por", quote)
    task_operation_column = _column(task, "eliminacion_operacion_id", quote)
    cursor.execute(
        f"SELECT {task_id_column} AS task_id, "
        f"{task_company_column} AS empresa_id, "
        f"{task_deleted_column} AS eliminada, "
        f"{task_deleted_at_column} AS eliminada_en, "
        f"{task_deleted_by_column} AS eliminada_por, "
        f"{task_operation_column} AS eliminacion_operacion_id "
        f"FROM {_table(task, quote)} "
        f"WHERE {task_company_column} = %s "
        f"AND {task_operation_column} IN ({source_placeholders}) "
        f"ORDER BY {task_id_column}",
        (empresa_id, *source_ids),
    )
    marked_tasks: dict[str, dict[int, dict[str, object]]] = {
        source_id: {} for source_id in source_ids
    }
    for row in _dict_rows(cursor):
        marker_id = _normal_uuid(str(row["eliminacion_operacion_id"])).hex
        marked_tasks.setdefault(marker_id, {})[
            _required_history_int(row["task_id"], "task_id")
        ] = {
            "empresa_id": row["empresa_id"],
            "eliminada": row["eliminada"],
            "eliminada_en": row["eliminada_en"],
            "eliminada_por": row["eliminada_por"],
            "eliminacion_operacion_id": row["eliminacion_operacion_id"],
        }

    contexts = {}
    for source_id, row in operation_rows.items():
        restoration_rows_for_source = restorations_by_source.get(source_id, [])
        contexts[source_id] = {
            **row,
            "manifest_entries": tuple(manifests.get(source_id, ())),
            "restorations": tuple(
                {
                    **restoration,
                    "manifest_entries": tuple(
                        manifests.get(
                            _normal_uuid(str(restoration["operation_id"])).hex,
                            (),
                        )
                    ),
                }
                for restoration in restoration_rows_for_source
            ),
            "marked_tasks": marked_tasks.get(source_id, {}),
        }
    return contexts


def _has_valid_later_deletion(
    *,
    source: dict[str, object],
    source_entries: tuple[tuple[str, int], ...],
    task_rows: dict[int, dict[str, object]],
    restoration: DeletedTaskRestoration,
    current_operations: dict[str, dict[str, object]],
) -> bool:
    source_operation_id = _normal_uuid(str(source["operation_id"]))
    empresa_id = _required_history_int(source["empresa_id"], "empresa_id")
    root_task_id = _required_history_int(source["root_task_id"], "root_task_id")
    source_task_ids = {
        object_id
        for item_type, object_id in source_entries
        if item_type == TASK_ITEM_LABEL
    }
    marker_ids = set()
    for task_id in source_task_ids:
        task = task_rows.get(task_id)
        if (
            task is None
            or task["eliminada"] not in (True, 1)
            or task["eliminada_en"] is None
            or task["eliminada_por"] is None
        ):
            return False
        try:
            marker_ids.add(
                _normal_uuid(task["eliminacion_operacion_id"]).hex
            )
        except (TypeError, ValueError, AttributeError):
            return False

    if len(marker_ids) != 1:
        return False
    current_id = next(iter(marker_ids))
    if current_id == source_operation_id.hex:
        return False
    current = current_operations.get(current_id)
    if (
        current is None
        or _normal_uuid(str(current["operation_id"])).hex != current_id
        or current.get("reverses_operation_id") is not None
        or _required_history_int(current["empresa_id"], "current_empresa_id")
        != empresa_id
        or _required_history_int(current["root_task_id"], "current_root_task_id")
        != root_task_id
        or current["status"] != TareaEliminacionOperacion.Estado.COMMITTED
        or current["result_code"] != LOGICAL_DELETION_RESULT_CODE
        or current["file_cleanup_status"] != "NOT_REQUIRED"
        or current["backend_type"] != source["backend_type"]
        or current["backend_identity"] != source["backend_identity"]
        or current["backend_config_version"] != source["backend_config_version"]
        or not isinstance(current["motivo"], str)
        or not current["motivo"].strip()
    ):
        return False

    current_manifest = _manifest_entries(current.get("manifest_entries", ()))
    current_task_ids = {
        object_id
        for item_type, object_id in current_manifest
        if item_type == TASK_ITEM_LABEL
    }
    if (
        not current_manifest
        or len(current_task_ids) != len(current_manifest)
        or len(current_manifest) != len(set(current_manifest))
        or (TASK_ITEM_LABEL, root_task_id) not in current_manifest
        or not source_task_ids.issubset(current_task_ids)
        or set(current.get("marked_tasks", {})) != current_task_ids
    ):
        return False
    if any(
        not _task_markers_match_deletion(
            current["marked_tasks"].get(task_id),
            operation_id=UUID(current_id),
            empresa_id=empresa_id,
            actor_id=_required_history_int(
                current["actor_id"],
                "current_actor_id",
            ),
        )
        for task_id in current_task_ids
    ):
        return False

    if (
        restoration.committed_at is None
        or not _operation_timeline_is_valid(
            current,
            not_before=restoration.committed_at,
        )
    ):
        return False

    current_restorations = current.get("restorations", ())
    if len(current_restorations) > 1:
        return False
    if current_restorations:
        pending = current_restorations[0]
        if (
            not _uuid_matches(
                pending.get("reverses_operation_id"),
                UUID(current_id),
            )
            or _required_history_int(
                pending["empresa_id"],
                "current_restoration_empresa_id",
            )
            != empresa_id
            or _required_history_int(
                pending["root_task_id"],
                "current_restoration_root_task_id",
            )
            != root_task_id
            or pending["status"] != TareaEliminacionOperacion.Estado.PENDIENTE
            or (pending["result_code"] or "") != ""
            or pending["file_cleanup_status"] != "NOT_REQUIRED"
            or pending["backend_type"] != current["backend_type"]
            or pending["backend_identity"] != current["backend_identity"]
            or pending["backend_config_version"]
            != current["backend_config_version"]
            or _manifest_entries(pending.get("manifest_entries", ()))
            != current_manifest
        ):
            return False
    return True


def _project_deletion_status(
    *,
    source: dict[str, object],
    source_manifest: Sequence[dict[str, object]],
    task_rows: dict[int, dict[str, object]],
    restoration_row: dict[str, object] | None,
    restoration_manifest: Sequence[dict[str, object]] = (),
    current_operations: dict[str, dict[str, object]] | None = None,
) -> tuple[str, DeletedTaskRestoration | None]:
    source_operation_id = _normal_uuid(str(source["operation_id"]))
    empresa_id = _required_history_int(source["empresa_id"], "empresa_id")
    root_task_id = _required_history_int(source["root_task_id"], "root_task_id")
    actor_id = _required_history_int(source["actor_id"], "actor_id")
    source_entries = _manifest_entries(source_manifest)
    task_ids = tuple(
        object_id
        for item_type, object_id in source_entries
        if item_type == TASK_ITEM_LABEL
    )
    source_manifest_valid = bool(
        source_entries
        and len(task_ids) == len(source_entries)
        and len(task_ids) == len(set(task_ids))
        and (TASK_ITEM_LABEL, root_task_id) in source_entries
    )
    all_tasks_present = bool(task_ids) and all(
        task_id in task_rows for task_id in task_ids
    )
    currently_deleted = bool(
        source_manifest_valid
        and all_tasks_present
        and all(
            _task_markers_match_deletion(
                task_rows.get(task_id),
                operation_id=source_operation_id,
                empresa_id=empresa_id,
                actor_id=actor_id,
            )
            for task_id in task_ids
        )
    )
    markers_cleared = bool(
        source_manifest_valid
        and all_tasks_present
        and all(
            _task_markers_are_clear(task_rows.get(task_id), empresa_id)
            for task_id in task_ids
        )
    )

    linked_restoration = restoration_row
    if linked_restoration is not None and (
        not _uuid_matches(
            linked_restoration.get("reverses_operation_id"),
            source_operation_id,
        )
        or _required_history_int(
            linked_restoration["empresa_id"],
            "restoration_empresa_id",
        )
        != empresa_id
    ):
        linked_restoration = None

    restoration = None
    manifest_matches = False
    metadata_matches = False
    if linked_restoration is not None:
        restoration_id = _normal_uuid(
            str(linked_restoration["operation_id"])
        )
        manifest_matches = bool(
            source_manifest_valid
            and _manifest_entries(restoration_manifest) == source_entries
        )
        metadata_matches = bool(
            _required_history_int(
                linked_restoration["root_task_id"],
                "restoration_root_task_id",
            )
            == root_task_id
            and linked_restoration["backend_type"] == source["backend_type"]
            and linked_restoration["backend_identity"] == source["backend_identity"]
            and linked_restoration["backend_config_version"]
            == source["backend_config_version"]
            and linked_restoration["file_cleanup_status"] == "NOT_REQUIRED"
            and isinstance(linked_restoration["motivo"], str)
            and bool(linked_restoration["motivo"].strip())
        )
        restoration = DeletedTaskRestoration(
            operation_id=restoration_id,
            actor_id=_required_history_int(
                linked_restoration["actor_id"],
                "restoration_actor_id",
            ),
            motivo=(
                str(linked_restoration["motivo"])
                if linked_restoration["motivo"] is not None
                else None
            ),
            status=str(linked_restoration["status"]),
            result_code=str(linked_restoration["result_code"] or ""),
            created_at=_required_history_datetime(
                linked_restoration["created_at"],
                "restoration_created_at",
            ),
            committed_at=_optional_history_datetime(
                linked_restoration["committed_at"],
                "restoration_committed_at",
            ),
            audit_status=str(linked_restoration["audit_status"]),
            audit_event_id=_optional_history_int(
                linked_restoration["audit_event_id"],
                "restoration_audit_event_id",
            ),
            audit_error_code=str(linked_restoration["audit_error_code"] or ""),
            manifest_matches=manifest_matches,
            metadata_matches=metadata_matches,
        )

    if restoration is None:
        deletion_status = (
            "CURRENTLY_DELETED" if currently_deleted else "INCONSISTENT"
        )
    elif (
        restoration.status == TareaEliminacionOperacion.Estado.PENDIENTE
        and restoration.result_code == ""
    ):
        deletion_status = (
            "CURRENTLY_DELETED" if currently_deleted else "INCONSISTENT"
        )
    elif (
        restoration.status == TareaEliminacionOperacion.Estado.COMMITTED
        and restoration.result_code == LOGICAL_RESTORATION_RESULT_CODE
    ):
        restoration_chronology_valid = (
            linked_restoration is not None
            and _restoration_timeline_is_valid(source, linked_restoration)
        )
        restored_before_later_deletion = (
            metadata_matches
            and manifest_matches
            and restoration_chronology_valid
            and _has_valid_later_deletion(
                source=source,
                source_entries=source_entries,
                task_rows=task_rows,
                restoration=restoration,
                current_operations=current_operations or {},
            )
        )
        deletion_status = (
            "RESTORED"
            if metadata_matches
            and manifest_matches
            and restoration_chronology_valid
            and (markers_cleared or restored_before_later_deletion)
            else "INCONSISTENT"
        )
    else:
        deletion_status = "INCONSISTENT"
    return deletion_status, restoration


def _list_deletion_projections(
    cursor: _HistoryCursor,
    quote: Callable[[str], str],
    *,
    empresa_id: int,
    rows: Sequence[dict[str, object]],
) -> dict[str, tuple[str, DeletedTaskRestoration | None]]:
    source_rows: dict[str, dict[str, object]] = {}
    restoration_rows: dict[str, dict[str, object] | None] = {}
    for row in rows:
        source_id = _normal_uuid(str(row["operation_id"])).hex
        if source_id in source_rows:
            continue
        source_rows[source_id] = {
            "operation_id": row["operation_id"],
            "empresa_id": row["empresa_id"],
            "root_task_id": row["root_task_id"],
            "actor_id": row["actor_id"],
            "created_at": row["source_created_at"],
            "committed_at": row["source_committed_at"],
            "backend_type": row["backend_type"],
            "backend_identity": row["backend_identity"],
            "backend_config_version": row["backend_config_version"],
        }
        restoration_rows[source_id] = _restoration_row_from_list(row)

    source_ids = tuple(source_rows)
    restoration_ids = tuple(
        sorted(
            {
                _normal_uuid(str(restoration["operation_id"])).hex
                for restoration in restoration_rows.values()
                if restoration is not None
            }
        )
    )
    manifest_operation_ids = tuple(sorted(set(source_ids + restoration_ids)))
    if not manifest_operation_ids:
        return {}

    item = TareaEliminacionElemento
    item_table = _table(item, quote)
    operation_placeholders = ", ".join("%s" for _ in manifest_operation_ids)
    cursor.execute(
        f"SELECT {_column(item, 'operacion', quote)} AS operation_id, "
        f"{_column(item, 'tipo', quote)} AS item_type, "
        f"{_column(item, 'object_id', quote)} AS object_id "
        f"FROM {item_table} "
        f"WHERE {_column(item, 'operacion', quote)} IN ({operation_placeholders}) "
        f"ORDER BY {_column(item, 'operacion', quote)}, "
        f"{_column(item, 'tipo', quote)}, {_column(item, 'object_id', quote)}",
        manifest_operation_ids,
    )
    manifests: dict[str, list[dict[str, object]]] = {}
    for manifest_row in _dict_rows(cursor):
        manifest_operation_id = _normal_uuid(
            str(manifest_row["operation_id"])
        ).hex
        manifests.setdefault(manifest_operation_id, []).append(manifest_row)

    task = Tarea
    task_table = _table(task, quote)
    task_placeholders = ", ".join("%s" for _ in source_ids)
    cursor.execute(
        f"SELECT source_item.{_column(item, 'operacion', quote)} AS source_operation_id, "
        f"source_item.{_column(item, 'object_id', quote)} AS manifest_task_id, "
        f"task.{_column(task, 'id', quote)} AS physical_task_id, "
        f"task.{_column(task, 'empresa', quote)} AS empresa_id, "
        f"task.{_column(task, 'eliminada', quote)} AS eliminada, "
        f"task.{_column(task, 'eliminada_en', quote)} AS eliminada_en, "
        f"task.{_column(task, 'eliminada_por', quote)} AS eliminada_por, "
        f"task.{_column(task, 'eliminacion_operacion_id', quote)} AS eliminacion_operacion_id "
        f"FROM {item_table} source_item "
        f"LEFT JOIN {task_table} task "
        f"ON task.{_column(task, 'id', quote)} = source_item.{_column(item, 'object_id', quote)} "
        f"AND task.{_column(task, 'empresa', quote)} = %s "
        f"WHERE source_item.{_column(item, 'operacion', quote)} "
        f"IN ({task_placeholders}) "
        f"AND source_item.{_column(item, 'tipo', quote)} = %s",
        (empresa_id, *source_ids, TASK_ITEM_LABEL),
    )
    task_rows_by_source: dict[str, dict[int, dict[str, object]]] = {
        operation_id: {} for operation_id in source_ids
    }
    for task_row in _dict_rows(cursor):
        source_id = _normal_uuid(
            str(task_row["source_operation_id"])
        ).hex
        task_id = _required_history_int(
            task_row["manifest_task_id"],
            "manifest_task_id",
        )
        physical = (
            None
            if task_row["physical_task_id"] is None
            else {
                "empresa_id": task_row["empresa_id"],
                "eliminada": task_row["eliminada"],
                "eliminada_en": task_row["eliminada_en"],
                "eliminada_por": task_row["eliminada_por"],
                "eliminacion_operacion_id": task_row[
                    "eliminacion_operacion_id"
                ],
            }
        )
        if physical is not None:
            task_rows_by_source[source_id][task_id] = physical

    current_operation_contexts = _load_current_deletion_contexts(
        cursor,
        quote,
        empresa_id=empresa_id,
        task_rows_by_source=task_rows_by_source,
    )
    projections = {}
    for source_id, source_row in source_rows.items():
        restoration = restoration_rows[source_id]
        restoration_id = (
            _normal_uuid(str(restoration["operation_id"])).hex
            if restoration is not None
            else None
        )
        projections[source_id] = _project_deletion_status(
            source=source_row,
            source_manifest=manifests.get(source_id, ()),
            task_rows=task_rows_by_source[source_id],
            restoration_row=restoration,
            restoration_manifest=(
                manifests.get(restoration_id, ())
                if restoration_id is not None
                else ()
            ),
            current_operations=current_operation_contexts,
        )
    return projections


def _select_related_rows(
    cursor: _HistoryCursor,
    quote: Callable[[str], str],
    *,
    model,
    relation_field: str,
    related_ids: tuple[int, ...],
    field_names: tuple[str, ...],
    order_fields: tuple[str, ...] = ("id",),
) -> tuple[dict[str, object], ...]:
    if not related_ids:
        return ()
    selected_fields = ", ".join(
        f"{_column(model, name, quote)} AS "
        f"{quote(model._meta.get_field(name).attname)}"
        for name in field_names
    )
    placeholders = ", ".join("%s" for _ in related_ids)
    order_by = ", ".join(
        _column(model, name, quote) for name in order_fields
    )
    cursor.execute(
        f"SELECT {selected_fields} FROM {_table(model, quote)} "
        f"WHERE {_column(model, relation_field, quote)} IN ({placeholders}) "
        f"ORDER BY {order_by}",
        related_ids,
    )
    return _dict_rows(cursor)


def _related_record(
    kind: str,
    row: dict[str, object],
    *,
    label: object = None,
    state: object = None,
    actor_id: object = None,
    occurred_at: object = None,
    details: tuple[tuple[str, object], ...] = (),
) -> DeletedHistoryRecord:
    return DeletedHistoryRecord(
        kind=kind,
        object_id=_related_int(row["id"]),
        label=str(label) if label is not None else None,
        state=str(state) if state is not None else None,
        actor_id=_optional_related_int(actor_id),
        occurred_at=occurred_at if isinstance(occurred_at, (date, datetime)) else None,
        details=details,
    )


def _related_int(value: object) -> int:
    return _required_history_int(value, "related_id")


def _optional_related_int(value: object) -> int | None:
    return _optional_history_int(value, "related_id")


def _safe_file_name(value: object) -> str | None:
    if not value:
        return None
    return str(value).replace("\\", "/").rsplit("/", 1)[-1]


def _load_related_history(
    cursor: _HistoryCursor,
    quote: Callable[[str], str],
    *,
    task_id: int,
    can_read_comments: bool,
    can_read_hidden_comments: bool,
) -> DeletedTaskHistoryRelatedData:
    task_ids = (task_id,)
    participant_rows = _select_related_rows(
        cursor,
        quote,
        model=TareaParticipante,
        relation_field="tarea",
        related_ids=task_ids,
        field_names=("id", "usuario", "rol", "fecha"),
        order_fields=("fecha", "id"),
    )
    milestone_rows = _select_related_rows(
        cursor,
        quote,
        model=Hito,
        relation_field="tarea",
        related_ids=task_ids,
        field_names=(
            "id",
            "nombre",
            "responsable",
            "anulado",
            "completado",
            "completado_por",
            "fecha_completado",
            "resena_cierre",
            "cumplimiento",
            "peso",
            "fecha_creacion",
        ),
        order_fields=("fecha_creacion", "id"),
    )
    milestone_ids = tuple(_related_int(row["id"]) for row in milestone_rows)
    milestone_history_rows = _select_related_rows(
        cursor,
        quote,
        model=HitoHistorial,
        relation_field="hito",
        related_ids=milestone_ids,
        field_names=("id", "hito", "tipo_evento", "usuario", "fecha", "motivo"),
        order_fields=("fecha", "id"),
    )
    milestone_evidence_rows = _select_related_rows(
        cursor,
        quote,
        model=HitoEvidencia,
        relation_field="hito",
        related_ids=milestone_ids,
        field_names=("id", "hito", "formato_archivo", "archivo", "url", "usuario", "fecha"),
        order_fields=("fecha", "id"),
    )
    mini_task_rows = _select_related_rows(
        cursor,
        quote,
        model=MiniTarea,
        relation_field="tarea",
        related_ids=task_ids,
        field_names=("id", "descripcion", "persona", "hecho", "fecha_creacion", "fecha_completado"),
        order_fields=("fecha_creacion", "id"),
    )
    mini_task_ids = tuple(_related_int(row["id"]) for row in mini_task_rows)
    mini_task_event_rows = _select_related_rows(
        cursor,
        quote,
        model=MiniTareaEvento,
        relation_field="mini_tarea",
        related_ids=mini_task_ids,
        field_names=("id", "mini_tarea", "tipo", "actor", "fecha", "comentario"),
        order_fields=("fecha", "id"),
    )
    document_rows = _select_related_rows(
        cursor,
        quote,
        model=DocumentoTarea,
        relation_field="tarea",
        related_ids=task_ids,
        field_names=(
            "id",
            "tipo",
            "formato_archivo",
            "archivo",
            "url",
            "fecha_documento",
            "fecha_vencimiento",
            "usuario",
            "estado",
        ),
        order_fields=("fecha_documento", "id"),
    )
    document_ids = tuple(_related_int(row["id"]) for row in document_rows)
    document_history_rows = _select_related_rows(
        cursor,
        quote,
        model=DocumentoHistorial,
        relation_field="documento",
        related_ids=document_ids,
        field_names=("id", "documento", "accion", "usuario", "fecha"),
        order_fields=("fecha", "id"),
    )
    closure_evidence_rows = _select_related_rows(
        cursor,
        quote,
        model=EvidenciaCierre,
        relation_field="tarea",
        related_ids=task_ids,
        field_names=("id", "documento", "formato_archivo", "archivo", "url", "usuario", "fecha"),
        order_fields=("fecha", "id"),
    )
    transition_rows = _select_related_rows(
        cursor,
        quote,
        model=TareaTransicion,
        relation_field="tarea",
        related_ids=task_ids,
        field_names=("id", "estado_origen", "estado_destino", "accion_evento", "usuario", "timestamp", "motivo"),
        order_fields=("timestamp", "id"),
    )
    closure_rows = _select_related_rows(
        cursor,
        quote,
        model=TareaCierre,
        relation_field="tarea",
        related_ids=task_ids,
        field_names=("id", "usuario", "timestamp", "resultado", "comentario"),
        order_fields=("timestamp", "id"),
    )

    participants = tuple(
        _related_record(
            "participant",
            row,
            state=row["rol"],
            actor_id=row["usuario_id"],
            occurred_at=row["fecha"],
        )
        for row in participant_rows
    )
    milestones = tuple(
        _related_record(
            "milestone",
            row,
            label=row["nombre"],
            state=(
                "VOIDED"
                if row["anulado"]
                else "COMPLETED"
                if row["completado"]
                else "PENDING"
            ),
            actor_id=row["responsable_id"],
            occurred_at=row["fecha_creacion"],
            details=(
                ("completion", row["cumplimiento"]),
                ("weight", row["peso"]),
                ("completed_by_id", row["completado_por_id"]),
                ("completed_at", row["fecha_completado"]),
                ("closure_summary", row["resena_cierre"]),
            ),
        )
        for row in milestone_rows
    ) + tuple(
        _related_record(
            "milestone_history",
            row,
            label=row["tipo_evento"],
            actor_id=row["usuario_id"],
            occurred_at=row["fecha"],
            details=(("reason", row["motivo"]),),
        )
        for row in milestone_history_rows
    )
    mini_tasks = tuple(
        _related_record(
            "mini_task",
            row,
            label=row["descripcion"],
            state="COMPLETED" if row["hecho"] else "PENDING",
            actor_id=row["persona_id"],
            occurred_at=row["fecha_creacion"],
            details=(("completed_at", row["fecha_completado"]),),
        )
        for row in mini_task_rows
    ) + tuple(
        _related_record(
            "mini_task_event",
            row,
            label=row["comentario"],
            state=row["tipo"],
            actor_id=row["actor_id"],
            occurred_at=row["fecha"],
        )
        for row in mini_task_event_rows
    )
    documents = tuple(
        _related_record(
            "document",
            row,
            label=_safe_file_name(row["archivo"]) or (
                "EXTERNAL_LINK" if row["url"] else None
            ),
            state=row["estado"],
            actor_id=row["usuario_id"],
            occurred_at=row["fecha_documento"],
            details=(
                ("type", row["tipo"]),
                ("format", row["formato_archivo"]),
                ("has_file", bool(row["archivo"])),
                ("has_external_link", bool(row["url"])),
                ("due_date", row["fecha_vencimiento"]),
            ),
        )
        for row in document_rows
    ) + tuple(
        _related_record(
            "document_history",
            row,
            label=row["accion"],
            actor_id=row["usuario_id"],
            occurred_at=row["fecha"],
        )
        for row in document_history_rows
    )
    closure_evidence = tuple(
        _related_record(
            "milestone_evidence",
            row,
            label=_safe_file_name(row["archivo"]) or (
                "EXTERNAL_LINK" if row["url"] else None
            ),
            state=row["formato_archivo"],
            actor_id=row["usuario_id"],
            occurred_at=row["fecha"],
            details=(("has_file", bool(row["archivo"])), ("has_external_link", bool(row["url"]))),
        )
        for row in milestone_evidence_rows
    ) + tuple(
        _related_record(
            "closure_evidence",
            row,
            label=_safe_file_name(row["archivo"]) or (
                "EXTERNAL_LINK" if row["url"] else None
            ),
            state=row["formato_archivo"],
            actor_id=row["usuario_id"],
            occurred_at=row["fecha"],
            details=(
                ("document_id", row["documento_id"]),
                ("has_file", bool(row["archivo"])),
                ("has_external_link", bool(row["url"])),
            ),
        )
        for row in closure_evidence_rows
    )
    transitions = tuple(
        _related_record(
            "transition",
            row,
            label=row["accion_evento"],
            state=f"{row['estado_origen']}->{row['estado_destino']}",
            actor_id=row["usuario_id"],
            occurred_at=row["timestamp"],
            details=(("reason", row["motivo"]),),
        )
        for row in transition_rows
    )
    closures = tuple(
        _related_record(
            "closure",
            row,
            label=row["comentario"],
            state=row["resultado"],
            actor_id=row["usuario_id"],
            occurred_at=row["timestamp"],
        )
        for row in closure_rows
    )

    comments: tuple[DeletedHistoryRecord, ...] = ()
    comments_status = "ACCESS_RESTRICTED"
    if can_read_comments:
        comment_rows = _select_related_rows(
            cursor,
            quote,
            model=Comentario,
            relation_field="tarea",
            related_ids=task_ids,
            field_names=("id", "autor", "contenido", "created_at", "oculto"),
            order_fields=("created_at", "id"),
        )
        comments = tuple(
            _related_record(
                "comment" if can_read_hidden_comments or not row["oculto"] else "comment_tombstone",
                row,
                label=(
                    row["contenido"]
                    if can_read_hidden_comments or not row["oculto"]
                    else None
                ),
                state="HIDDEN" if row["oculto"] else "VISIBLE",
                actor_id=(
                    row["autor_id"]
                    if can_read_hidden_comments or not row["oculto"]
                    else None
                ),
                occurred_at=row["created_at"],
            )
            for row in comment_rows
        )
        comments_status = "AVAILABLE"

    return DeletedTaskHistoryRelatedData(
        related_status="AVAILABLE",
        participants=participants,
        milestones=milestones,
        mini_tasks=mini_tasks,
        documents=documents,
        closure_evidence=closure_evidence,
        transitions=transitions,
        closures=closures,
        comments_status=comments_status,
        comments=comments,
    )


def _normal_uuid(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError as exc:
            raise DeletedTaskHistoryNotFound(
                "La operación histórica no existe."
            ) from exc
    raise DeletedTaskHistoryNotFound("La operación histórica no existe.")


def _physical_status(row: dict[str, object], operation_id: UUID, actor_id: int) -> str:
    if row.get("physical_task_id") is None:
        return "PHYSICALLY_ABSENT"
    task_operation_id = str(row.get("task_operation_id") or "").replace("-", "")
    consistent = (
        bool(row.get("task_deleted"))
        and row.get("task_deleted_at") is not None
        and row.get("task_deleted_by_id") == actor_id
        and task_operation_id.casefold() == operation_id.hex.casefold()
    )
    return "PHYSICALLY_RETAINED" if consistent else "INCONSISTENT"


def _history_item(row: dict[str, object]) -> DeletedTaskHistoryItem:
    operation_id = _normal_uuid(str(row["operation_id"]))
    actor_id = _required_history_int(row["actor_id"], "actor_id")
    task_id = _required_history_int(row["task_id"], "task_id")
    root_task_id = _required_history_int(row["root_task_id"], "root_task_id")
    deletion_status = str(row.get("deletion_status", "INCONSISTENT"))
    physical_status = _physical_status(row, operation_id, actor_id)
    if deletion_status == "RESTORED" and row.get("physical_task_id") is not None:
        physical_status = "PHYSICALLY_RETAINED"
    snapshot_available = (
        deletion_status == "CURRENTLY_DELETED"
        and physical_status == "PHYSICALLY_RETAINED"
    )
    deleted_at_value = (
        row.get("task_deleted_at")
        if snapshot_available and row.get("task_deleted_at") is not None
        else row.get("deleted_at")
    )
    return DeletedTaskHistoryItem(
        operation_id=operation_id,
        empresa_id=_required_history_int(row["empresa_id"], "empresa_id"),
        task_id=task_id,
        root_task_id=root_task_id,
        is_root=task_id == root_task_id,
        root_correlativo=str(row["root_correlativo"] or ""),
        correlativo=(
            str(row["task_correlativo"])
            if snapshot_available and row.get("task_correlativo") is not None
            else None
        ),
        titulo=(
            str(row["task_title"])
            if snapshot_available and row.get("task_title") is not None
            else None
        ),
        estado=(
            str(row["task_state"])
            if snapshot_available and row.get("task_state") is not None
            else None
        ),
        deleted_at=_optional_history_datetime(deleted_at_value, "deleted_at"),
        actor_id=actor_id,
        motivo=str(row["motivo"]) if row.get("motivo") is not None else None,
        operation_status=str(row["operation_status"]),
        result_code=str(row["result_code"]),
        audit_status=str(row["audit_status"]),
        audit_event_id=_optional_history_int(
            row.get("audit_event_id"),
            "audit_event_id",
        ),
        physical_status=physical_status,
        deletion_status=deletion_status,
    )


def list_deleted_task_history(
    *,
    empresa_id: int,
    filters: DeletedTaskHistoryFilters | None = None,
) -> DeletedTaskHistoryPage:
    _validate_positive_int(empresa_id, "empresa_id")
    filters = _validated_filters(filters or DeletedTaskHistoryFilters())
    try:
        with _history_cursor() as (cursor, vendor, quote):
            count_sql, count_params, data_sql, data_params = _list_query(
                empresa_id=empresa_id,
                filters=filters,
                vendor=vendor,
                quote=quote,
            )
            cursor.execute(count_sql, count_params)
            count_row = cursor.fetchone()
            total = _required_history_int(
                count_row[0] if count_row else 0,
                "total",
            )
            cursor.execute(data_sql, data_params)
            rows = _dict_rows(cursor)
            projections = (
                _list_deletion_projections(
                    cursor,
                    quote,
                    empresa_id=empresa_id,
                    rows=rows,
                )
                if rows
                else {}
            )
            items = tuple(
                _history_item(
                    {
                        **row,
                        "deletion_status": projections.get(
                            _normal_uuid(str(row["operation_id"])).hex,
                            ("INCONSISTENT", None),
                        )[0],
                    }
                )
                for row in rows
            )
    except DeletedTaskHistoryError:
        raise
    except Exception as exc:
        raise DeletedTaskHistoryUnavailable(
            "No se pudo consultar el historial de tareas eliminadas."
        ) from exc
    total_pages = (total + filters.page_size - 1) // filters.page_size
    return DeletedTaskHistoryPage(
        items=items,
        total=total,
        page=filters.page,
        page_size=filters.page_size,
        total_pages=total_pages,
    )


def get_deleted_task_history_operation(
    *,
    empresa_id: int,
    operation_id: UUID | str,
) -> DeletedTaskHistoryOperation:
    _validate_positive_int(empresa_id, "empresa_id")
    operation_id = _normal_uuid(operation_id)
    op = TareaEliminacionOperacion
    item = TareaEliminacionElemento
    task = Tarea
    file_model = TareaEliminacionArchivo

    try:
        with _history_cursor() as (cursor, _vendor, quote):
            op_table = _table(op, quote)
            op_fields = (
                "operation_id", "empresa_id", "root_task_id", "root_correlativo",
                "actor_id", "motivo", "backend_type", "backend_identity",
                "backend_config_version", "status", "result_code", "audit_status",
                "audit_event_id", "audit_error_code", "file_cleanup_status",
                "created_at", "committed_at",
                "dependency_summary",
            )
            op_sql = ", ".join(
                f"op.{_column(op, name, quote)} AS {name}" for name in op_fields
            )
            cursor.execute(
                f"SELECT {op_sql} FROM {op_table} op "
                f"WHERE op.{_column(op, 'operation_id', quote)} = %s "
                f"AND op.{_column(op, 'empresa_id', quote)} = %s",
                (operation_id.hex, empresa_id),
            )
            op_rows = _dict_rows(cursor)
            if not op_rows:
                raise DeletedTaskHistoryNotFound(
                    "La operación histórica no existe en la empresa activa."
                )
            operation_row = op_rows[0]
            if (
                operation_row["status"] != TareaEliminacionOperacion.Estado.COMMITTED
                or operation_row["result_code"] != LOGICAL_DELETION_RESULT_CODE
            ):
                raise DeletedTaskHistoryNotFound(
                    "La operación histórica no existe en la empresa activa."
                )

            item_table = _table(item, quote)
            cursor.execute(
                f"SELECT {_column(item, 'tipo', quote)} AS item_type, "
                f"{_column(item, 'object_id', quote)} AS object_id "
                f"FROM {item_table} WHERE {_column(item, 'operacion', quote)} = %s "
                f"ORDER BY {_column(item, 'tipo', quote)}, {_column(item, 'object_id', quote)}",
                (operation_id.hex,),
            )
            manifest_rows = _dict_rows(cursor)

            restoration_row = None
            restoration_manifest_rows: tuple[dict[str, object], ...] = ()
            restoration_fields = (
                "operation_id", "empresa_id", "root_task_id", "actor_id",
                "motivo", "backend_type", "backend_identity",
                "backend_config_version", "status", "result_code",
                "audit_status", "audit_event_id", "audit_error_code",
                "file_cleanup_status", "created_at", "committed_at",
            )
            restoration_sql = ", ".join(
                f"restoration.{_column(op, name, quote)} AS {name}"
                for name in restoration_fields
            )
            restoration_sql += (
                f", restoration.{_column(op, 'reverses_operation', quote)} "
                "AS reverses_operation_id"
            )
            cursor.execute(
                f"SELECT {restoration_sql} FROM {op_table} restoration "
                f"WHERE restoration.{_column(op, 'reverses_operation', quote)} = %s "
                f"AND restoration.{_column(op, 'empresa_id', quote)} = %s",
                (operation_id.hex, empresa_id),
            )
            restoration_rows = _dict_rows(cursor)
            if len(restoration_rows) > 1:
                raise DeletedTaskHistoryUnavailable(
                    "El ledger contiene más de una restauración vinculada."
                )
            if restoration_rows:
                restoration_row = restoration_rows[0]
                cursor.execute(
                    f"SELECT {_column(item, 'tipo', quote)} AS item_type, "
                    f"{_column(item, 'object_id', quote)} AS object_id "
                    f"FROM {item_table} "
                    f"WHERE {_column(item, 'operacion', quote)} = %s "
                    f"ORDER BY {_column(item, 'tipo', quote)}, "
                    f"{_column(item, 'object_id', quote)}",
                    (str(restoration_row["operation_id"]),),
                )
                restoration_manifest_rows = _dict_rows(cursor)

            task_rows: dict[int, dict[str, object]] = {}
            task_ids = tuple(
                sorted(
                    {
                        _required_history_int(row["object_id"], "object_id")
                        for row in manifest_rows
                        if row["item_type"] == TASK_ITEM_LABEL
                    }
                )
            )
            if task_ids:
                placeholders = ", ".join("%s" for _ in task_ids)
                task_table = _table(task, quote)
                task_fields = (
                    "id", "empresa", "correlativo", "titulo", "descripcion",
                    "prioridad", "estado", "anulada", "eliminada", "eliminada_en",
                    "eliminada_por", "eliminacion_operacion_id", "creada_por",
                    "responsable", "fecha_creacion", "fecha_publicacion",
                    "fecha_asignacion", "fecha_tope", "fecha_cumplimiento",
                    "local", "departamento",
                )
                fields_sql = ", ".join(
                    f"task.{_column(task, name, quote)} AS {name}"
                    for name in task_fields
                )
                cursor.execute(
                    f"SELECT {fields_sql} FROM {task_table} task "
                    f"WHERE task.{_column(task, 'empresa', quote)} = %s "
                    f"AND task.{_column(task, 'id', quote)} IN ({placeholders})",
                    (empresa_id, *task_ids),
                )
                task_rows = {
                    _required_history_int(row["id"], "task_id"): row
                    for row in _dict_rows(cursor)
                }
            projection_task_rows = {
                task_id: {
                    "empresa_id": row["empresa"],
                    "eliminada": row["eliminada"],
                    "eliminada_en": row["eliminada_en"],
                    "eliminada_por": row["eliminada_por"],
                    "eliminacion_operacion_id": row[
                        "eliminacion_operacion_id"
                    ],
                }
                for task_id, row in task_rows.items()
            }
            current_operation_contexts = _load_current_deletion_contexts(
                cursor,
                quote,
                empresa_id=empresa_id,
                task_rows_by_source={operation_id.hex: projection_task_rows},
            )
            deletion_status, restoration = _project_deletion_status(
                source=operation_row,
                source_manifest=manifest_rows,
                task_rows=projection_task_rows,
                restoration_row=restoration_row,
                restoration_manifest=restoration_manifest_rows,
                current_operations=current_operation_contexts,
            )

            files: tuple[DeletionHistoryFile, ...] = ()
            file_table = _table(file_model, quote)
            cursor.execute(
                f"SELECT {_column(file_model, 'storage_key', quote)} AS storage_key, "
                f"{_column(file_model, 'file_name', quote)} AS file_name, "
                f"{_column(file_model, 'status', quote)} AS status, "
                f"{_column(file_model, 'attempts', quote)} AS attempts, "
                f"{_column(file_model, 'last_attempt_at', quote)} AS last_attempt_at, "
                f"{_column(file_model, 'error_code', quote)} AS error_code "
                f"FROM {file_table} WHERE {_column(file_model, 'operacion', quote)} = %s "
                f"ORDER BY {_column(file_model, 'storage_key', quote)}, "
                f"{_column(file_model, 'reference_hash', quote)}",
                (operation_id.hex,),
            )
            files = tuple(
                DeletionHistoryFile(
                    storage_key=str(row["storage_key"]),
                    file_name=(
                        str(row["file_name"] or "")
                        .replace("\\", "/")
                        .rsplit("/", 1)[-1]
                    ),
                    status=str(row["status"]),
                    attempts=_required_history_int(row["attempts"], "attempts"),
                    last_attempt_at=_optional_history_datetime(
                        row["last_attempt_at"],
                        "last_attempt_at",
                    ),
                    error_code=str(row["error_code"] or ""),
                )
                for row in _dict_rows(cursor)
            )

            relations: tuple[DeletionHistoryRelation, ...] = ()
            hierarchy_status = "NOT_APPLICABLE"
            if task_ids:
                relation_model = TareaRelacion
                relation_table = _table(relation_model, quote)
                placeholders = ", ".join("%s" for _ in task_ids)
                cursor.execute(
                    f"SELECT {_column(relation_model, 'padre', quote)} AS parent_id, "
                    f"{_column(relation_model, 'hija', quote)} AS child_id "
                    f"FROM {relation_table} WHERE "
                    f"{_column(relation_model, 'padre', quote)} IN ({placeholders}) "
                    f"OR {_column(relation_model, 'hija', quote)} IN ({placeholders}) "
                    f"ORDER BY {_column(relation_model, 'padre', quote)}, "
                    f"{_column(relation_model, 'hija', quote)}",
                    (*task_ids, *task_ids),
                )
                manifest_ids = set(task_ids)
                relation_rows = _dict_rows(cursor)
                relations = tuple(
                    DeletionHistoryRelation(
                        parent_id=_required_history_int(row["parent_id"], "parent_id"),
                        child_id=_required_history_int(row["child_id"], "child_id"),
                        parent_in_manifest=(
                            _required_history_int(row["parent_id"], "parent_id")
                            in manifest_ids
                        ),
                        child_in_manifest=(
                            _required_history_int(row["child_id"], "child_id")
                            in manifest_ids
                        ),
                    )
                    for row in relation_rows
                )
                hierarchy_status = (
                    "COMPLETE"
                    if len(task_ids) == 1
                    or (
                        len(relations) >= len(task_ids) - 1
                        and all(
                            edge.parent_in_manifest and edge.child_in_manifest
                            for edge in relations
                        )
                    )
                    else "HISTORICAL_RELATIONS_UNAVAILABLE"
                )
            if deletion_status != "CURRENTLY_DELETED":
                relations = ()
                hierarchy_status = "HISTORICAL_RELATIONS_UNAVAILABLE"
    except DeletedTaskHistoryError:
        raise
    except Exception as exc:
        raise DeletedTaskHistoryUnavailable(
            "No se pudo consultar el detalle del ledger histórico."
        ) from exc

    history_items = []
    for manifest_row in manifest_rows:
        object_id = _required_history_int(manifest_row["object_id"], "object_id")
        item_type = str(manifest_row["item_type"])
        if item_type != TASK_ITEM_LABEL:
            history_items.append(
                DeletionHistoryManifestItem(
                    item_type=item_type,
                    object_id=object_id,
                    physical_status="NOT_VERIFIED",
                    task=None,
                )
            )
            continue
        physical = task_rows.get(object_id)
        row = {
            "operation_id": operation_id.hex,
            "empresa_id": empresa_id,
            "root_task_id": operation_row["root_task_id"],
            "root_correlativo": operation_row["root_correlativo"],
            "actor_id": operation_row["actor_id"],
            "motivo": operation_row["motivo"],
            "operation_status": operation_row["status"],
            "result_code": operation_row["result_code"],
            "audit_status": operation_row["audit_status"],
            "audit_event_id": operation_row["audit_event_id"],
            "deletion_status": deletion_status,
            "task_id": object_id,
            "physical_task_id": physical["id"] if physical else None,
            "task_correlativo": physical["correlativo"] if physical else None,
            "task_title": physical["titulo"] if physical else None,
            "task_state": physical["estado"] if physical else None,
            "task_deleted": physical["eliminada"] if physical else None,
            "task_deleted_at": physical["eliminada_en"] if physical else None,
            "task_deleted_by_id": physical["eliminada_por"] if physical else None,
            "task_operation_id": physical["eliminacion_operacion_id"] if physical else None,
            "deleted_at": operation_row["committed_at"] or operation_row["created_at"],
        }
        if (
            physical
            and deletion_status == "CURRENTLY_DELETED"
            and _physical_status(
                row,
                operation_id,
                _required_history_int(operation_row["actor_id"], "actor_id"),
            )
            == "PHYSICALLY_RETAINED"
        ):
            row["deleted_at"] = physical["eliminada_en"]
        task_item = _history_item(row)
        history_items.append(
            DeletionHistoryManifestItem(
                item_type=item_type,
                object_id=object_id,
                physical_status=task_item.physical_status,
                task=task_item,
            )
        )

    dependency_summary = None
    dependency_summary_valid = False
    try:
        raw_summary = operation_row["dependency_summary"]
        if raw_summary is None:
            parsed_summary = {}
        elif isinstance(raw_summary, (str, bytes, bytearray)):
            parsed_summary = json.loads(raw_summary or "{}")
        else:
            parsed_summary = None
        if isinstance(parsed_summary, dict) and all(
            isinstance(key, str) and isinstance(value, int) and value >= 0
            for key, value in parsed_summary.items()
        ):
            dependency_summary = parsed_summary
            dependency_summary_valid = True
    except (TypeError, json.JSONDecodeError):
        pass

    audit = None
    audit_consistency = "EVENT_UNAVAILABLE"
    try:
        event = AuditoriaService.get_event_by_idempotency_key(
            "tareas",
            operation_id.hex,
        )
    except AuditIdempotencyStorageError:
        event = None
        audit_consistency = "CENTRAL_AUDIT_UNAVAILABLE"
    else:
        if event is None:
            audit_consistency = (
                "AUDIT_MISSING"
                if operation_row["audit_status"]
                == TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA
                else "NOT_CONFIRMED"
            )
        else:
            meta = event.meta if isinstance(event.meta, dict) else {}
            meta_operation_id = meta.get("operation_id")
            audit_consistency = (
                "CONSISTENT"
                if (
                    event.idempotency_key == operation_id.hex
                    and event.empresa_id == empresa_id
                    and event.action == "DELETE"
                    and event.object_type == "Tarea"
                    and str(event.object_id) == str(operation_row["root_task_id"])
                    and meta_operation_id == operation_id.hex
                    and (
                        operation_row["audit_event_id"] is None
                        or _required_history_int(
                            operation_row["audit_event_id"],
                            "audit_event_id",
                        )
                        == event.pk
                    )
                )
                else "INCONSISTENT"
            )
            audit = DeletionHistoryAudit(
                event_id=int(event.pk),
                created_at=event.created_at,
                action=str(event.action),
                actor_id=_optional_history_int(
                    getattr(event, "user_id", None),
                    "audit_actor_id",
                ),
                object_type=event.object_type,
                object_id=event.object_id,
                message_key=event.message_key,
                operation_id=meta_operation_id if isinstance(meta_operation_id, str) else None,
                backend_type=(
                    meta.get("backend_type")
                    if isinstance(meta.get("backend_type"), str)
                    else None
                ),
            )

    return DeletedTaskHistoryOperation(
        operation_id=operation_id,
        empresa_id=_required_history_int(operation_row["empresa_id"], "empresa_id"),
        root_task_id=_required_history_int(
            operation_row["root_task_id"],
            "root_task_id",
        ),
        root_correlativo=str(operation_row["root_correlativo"] or ""),
        actor_id=_required_history_int(operation_row["actor_id"], "actor_id"),
        motivo=(
            str(operation_row["motivo"])
            if operation_row["motivo"] is not None
            else None
        ),
        backend_type=str(operation_row["backend_type"]),
        backend_identity=str(operation_row["backend_identity"]),
        status=str(operation_row["status"]),
        result_code=str(operation_row["result_code"]),
        audit_status=str(operation_row["audit_status"]),
        audit_event_id=_optional_history_int(
            operation_row["audit_event_id"],
            "audit_event_id",
        ),
        audit_error_code=str(operation_row["audit_error_code"] or ""),
        file_cleanup_status=str(operation_row["file_cleanup_status"]),
        created_at=_required_history_datetime(
            operation_row["created_at"],
            "created_at",
        ),
        committed_at=_optional_history_datetime(
            operation_row["committed_at"],
            "committed_at",
        ),
        dependency_summary=dependency_summary,
        dependency_summary_valid=dependency_summary_valid,
        audit=audit,
        audit_consistency=audit_consistency,
        items=tuple(history_items),
        files=files,
        relations=relations,
        hierarchy_status=hierarchy_status,
        deletion_status=deletion_status,
        restoration=restoration,
    )


def _empty_related_history(status: str) -> DeletedTaskHistoryRelatedData:
    return DeletedTaskHistoryRelatedData(
        related_status=status,
        participants=(),
        milestones=(),
        mini_tasks=(),
        documents=(),
        closure_evidence=(),
        transitions=(),
        closures=(),
        comments_status="ACCESS_RESTRICTED",
        comments=(),
    )


def get_deleted_task_history_detail(
    *,
    empresa_id: int,
    operation_id: UUID | str,
    task_id: int,
    can_read_related: bool = False,
    can_read_comments: bool = False,
    can_read_hidden_comments: bool = False,
) -> DeletedTaskHistoryDetail:
    _validate_positive_int(empresa_id, "empresa_id")
    _validate_positive_int(task_id, "task_id")
    if can_read_hidden_comments and not can_read_comments:
        raise ValueError("can_read_hidden_comments requiere can_read_comments.")
    operation = get_deleted_task_history_operation(
        empresa_id=empresa_id,
        operation_id=operation_id,
    )
    manifest_item = next(
        (
            item
            for item in operation.items
            if item.item_type == TASK_ITEM_LABEL and item.object_id == task_id
        ),
        None,
    )
    if manifest_item is None or manifest_item.task is None:
        raise DeletedTaskHistoryNotFound(
            "La tarea histórica no existe en la operación de la empresa activa."
        )
    task_item = manifest_item.task
    if task_item.deletion_status == "RESTORED":
        return DeletedTaskHistoryDetail(
            operation=operation,
            task=task_item,
            description=None,
            prioridad=None,
            fecha_creacion=None,
            fecha_publicacion=None,
            fecha_asignacion=None,
            fecha_tope=None,
            fecha_cumplimiento=None,
            creada_por_id=None,
            responsable_id=None,
            local_id=None,
            departamento_id=None,
            core_information_available=False,
            related=_empty_related_history("RESTORED"),
        )
    if task_item.physical_status != "PHYSICALLY_RETAINED":
        related = _empty_related_history(
            "UNAVAILABLE_OBJECT_MISSING"
            if task_item.physical_status == "PHYSICALLY_ABSENT"
            else "INCONSISTENT"
        )
        return DeletedTaskHistoryDetail(
            operation=operation,
            task=task_item,
            description=None,
            prioridad=None,
            fecha_creacion=None,
            fecha_publicacion=None,
            fecha_asignacion=None,
            fecha_tope=None,
            fecha_cumplimiento=None,
            creada_por_id=None,
            responsable_id=None,
            local_id=None,
            departamento_id=None,
            core_information_available=False,
            related=related,
        )

    detail_fields = (
        "id", "descripcion", "prioridad", "fecha_creacion", "fecha_publicacion",
        "fecha_asignacion", "fecha_tope", "fecha_cumplimiento", "creada_por",
        "responsable", "local", "departamento",
    )
    try:
        with _history_cursor() as (cursor, _vendor, quote):
            task_table = _table(Tarea, quote)
            select_fields = ", ".join(
                f"task.{_column(Tarea, name, quote)} AS {name}"
                for name in detail_fields
            )
            cursor.execute(
                f"SELECT {select_fields} FROM {task_table} task "
                f"WHERE task.{_column(Tarea, 'id', quote)} = %s "
                f"AND task.{_column(Tarea, 'empresa', quote)} = %s "
                f"AND task.{_column(Tarea, 'eliminada', quote)} = %s "
                f"AND task.{_column(Tarea, 'eliminacion_operacion_id', quote)} = %s",
                (
                    task_id,
                    empresa_id,
                    True,
                    operation.operation_id.hex,
                ),
            )
            rows = _dict_rows(cursor)
            related = (
                _load_related_history(
                    cursor,
                    quote,
                    task_id=task_id,
                    can_read_comments=can_read_comments,
                    can_read_hidden_comments=can_read_hidden_comments,
                )
                if rows and can_read_related
                else _empty_related_history("ACCESS_RESTRICTED")
            )
    except DeletedTaskHistoryError:
        raise
    except Exception as exc:
        raise DeletedTaskHistoryUnavailable(
            "No se pudo consultar el detalle operacional conservado."
        ) from exc

    if not rows:
        return DeletedTaskHistoryDetail(
            operation=operation,
            task=task_item,
            description=None,
            prioridad=None,
            fecha_creacion=None,
            fecha_publicacion=None,
            fecha_asignacion=None,
            fecha_tope=None,
            fecha_cumplimiento=None,
            creada_por_id=None,
            responsable_id=None,
            local_id=None,
            departamento_id=None,
            core_information_available=False,
            related=_empty_related_history("INCONSISTENT"),
        )
    row = rows[0]
    return DeletedTaskHistoryDetail(
        operation=operation,
        task=task_item,
        description=str(row["descripcion"] or ""),
        prioridad=str(row["prioridad"]) if row["prioridad"] is not None else None,
        fecha_creacion=_optional_history_datetime(
            row["fecha_creacion"],
            "fecha_creacion",
        ),
        fecha_publicacion=_optional_history_datetime(
            row["fecha_publicacion"],
            "fecha_publicacion",
        ),
        fecha_asignacion=_optional_history_datetime(
            row["fecha_asignacion"],
            "fecha_asignacion",
        ),
        fecha_tope=_optional_history_date(row["fecha_tope"], "fecha_tope"),
        fecha_cumplimiento=_optional_history_datetime(
            row["fecha_cumplimiento"],
            "fecha_cumplimiento",
        ),
        creada_por_id=_optional_history_int(row["creada_por"], "creada_por"),
        responsable_id=_optional_history_int(
            row["responsable"],
            "responsable",
        ),
        local_id=_optional_history_int(row["local"], "local"),
        departamento_id=_optional_history_int(
            row["departamento"],
            "departamento",
        ),
        core_information_available=True,
        related=related,
    )
