"""Internal preview and transactional service for logical task restoration."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import re
from typing import Generator
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connections
from django.db.models import Q

from access_control.models import Empresa
from auditoria.services import (
    AuditIdempotencyConflict,
    AuditIdempotencyError,
    AuditIdempotencyStorageError,
    AuditoriaService,
)

from ..models import (
    LOGICAL_DELETION_RESULT_CODE,
    LOGICAL_RESTORATION_RESULT_CODE,
    DocumentoTarea,
    Tarea,
    TareaEliminacionArchivo,
    TareaEliminacionOperacion,
    TareaRelacion,
)
from .deletion_ledger import (
    DeletionInventoryItem,
    DeletionLedgerBackendError,
    DeletionLedgerCommitUncertain,
    DeletionLedgerConflict,
    DeletionLedgerError,
    DeletionLedgerSchemaError,
    DeletionLedgerStateError,
    DeletionOperationRecord,
    DjangoDeletionLedgerStorage,
    MySQLDeletionLedgerStorage,
    RestorationOperationInput,
    _assert_restoration_source,
    _normalize_restoration_manifest,
    resolve_deletion_ledger_storage,
)
from .logical_deletion import (
    LogicalDeletionAuthorizationError,
    LogicalDeletionAuthorizationUnavailable,
    LogicalDeletionCompanyError,
    LogicalDeletionInvalidRequest,
    _active_base_company,
    _authorize_actor,
)
from .task_mutation_locks import (
    TaskMutationConflict,
    TaskMutationLockError,
    TaskMutationScopeError,
    bounded_django_lock_wait,
    bounded_mysql_lock_wait,
    lock_mysql_task_company,
    lock_mysql_task_rows,
    lock_orm_task_company,
    lock_orm_task_rows,
)


_BASE_TAREAS_DATABASE = "tareas"
_TASK_ITEM_LABEL = "tareas.tarea"
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_MYSQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
class LogicalRestorationError(DeletionLedgerError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        operation_id: UUID | None = None,
    ):
        self.code = code
        self.operation_id = operation_id
        super().__init__(message)


@dataclass(frozen=True)
class LogicalRestorationIssue:
    code: str
    message: str


@dataclass(frozen=True)
class LogicalRestorationTask:
    task_id: int
    physically_present: bool
    correlativo: str | None
    titulo: str | None
    estado: str | None
    fecha_tope: date | None
    responsable_id: int | None
    eliminada: bool | None
    eliminada_en: datetime | None
    eliminada_por_id: int | None
    eliminacion_operacion_id: UUID | None


@dataclass(frozen=True)
class LogicalRestorationDocument:
    document_id: int
    task_id: int
    tipo: str
    formato_archivo: str
    estado: str
    has_file: bool
    has_url: bool


@dataclass(frozen=True)
class LogicalRestorationPreview:
    deletion_operation_id: UUID
    root_task_id: int
    root_correlativo: str
    empresa_id: int
    empresa_codigo: str
    empresa_descripcion: str
    deletion_actor_id: int
    deletion_created_at: datetime
    deletion_committed_at: datetime | None
    deletion_motivo: str
    source_audit_status: str
    manifest: tuple[DeletionInventoryItem, ...]
    task_ids: tuple[int, ...]
    tasks: tuple[LogicalRestorationTask, ...]
    hierarchy: tuple[tuple[int, int], ...]
    documents: tuple[LogicalRestorationDocument, ...]
    external_origin_reference_count: int
    restoration_operation_id: UUID | None
    warnings: tuple[LogicalRestorationIssue, ...]
    blockers: tuple[LogicalRestorationIssue, ...]
    backend_type: str
    backend_identity: str
    backend_config_version: str
    fingerprint: str

    @property
    def can_restore(self) -> bool:
        return not self.blockers


@dataclass(frozen=True)
class LogicalRestorationResult:
    operation_id: UUID
    reverses_operation_id: UUID
    root_task_id: int
    task_ids: tuple[int, ...]
    result_code: str
    status: str
    backend_type: str
    audit_status: str
    replayed: bool


@dataclass(frozen=True)
class _TaskState:
    task_id: int
    empresa_id: int
    correlativo: str
    titulo: str
    estado: str
    prioridad: str
    fecha_creacion: datetime
    fecha_publicacion: datetime | None
    fecha_asignacion: datetime | None
    fecha_tope: date | None
    fecha_cumplimiento: datetime | None
    responsable_id: int | None
    eliminada: bool
    eliminada_en: datetime | None
    eliminada_por_id: int | None
    eliminacion_operacion_id: UUID | None


@dataclass(frozen=True)
class _DocumentState:
    document_id: int
    task_id: int
    tipo: str
    formato_archivo: str
    estado: str
    has_file: bool
    has_url: bool
    reference_fingerprint: str


def _positive_id(value, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LogicalRestorationError(
            "RESTORATION_INVALID_REQUEST",
            f"{field_name} debe ser un entero positivo.",
        )
    return value


def _operation_uuid(value, field_name: str) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise LogicalRestorationError(
            "RESTORATION_INVALID_REQUEST",
            f"{field_name} debe ser un UUID válido.",
        ) from exc


def _reason(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LogicalRestorationError(
            "RESTORATION_INVALID_REQUEST",
            "El motivo de restauración es obligatorio.",
        )
    return value.strip()


def _expected_fingerprint(value: str) -> str:
    if not isinstance(value, str) or not _FINGERPRINT.fullmatch(value):
        raise LogicalRestorationError(
            "RESTORATION_INVALID_REQUEST",
            "El fingerprint de previsualización no es válido.",
        )
    return value


def _authorize(actor, empresa_id: int):
    try:
        company = _active_base_company(empresa_id)
        _authorize_actor(actor=actor, company=company)
    except LogicalDeletionInvalidRequest as exc:
        raise LogicalRestorationError(
            "RESTORATION_INVALID_REQUEST",
            "La empresa activa no es válida.",
        ) from exc
    except LogicalDeletionAuthorizationUnavailable as exc:
        raise LogicalRestorationError(
            "RESTORATION_BACKEND_UNAVAILABLE",
            "No se pudo validar la autorización VICMEAS.",
        ) from exc
    except (LogicalDeletionAuthorizationError, LogicalDeletionCompanyError) as exc:
        raise LogicalRestorationError(
            "RESTORATION_UNAUTHORIZED",
            "Se requiere permiso VICMEAS S explícito para Tareas en Base 00.",
        ) from exc
    return company


def _resolve_storage():
    try:
        storage = resolve_deletion_ledger_storage()
    except (DeletionLedgerError, DatabaseError) as exc:
        raise LogicalRestorationError(
            "RESTORATION_BACKEND_UNAVAILABLE",
            "No se pudo resolver el backend operacional BASE_TAREAS.",
        ) from exc
    if isinstance(storage, MySQLDeletionLedgerStorage):
        if storage.database_name != _BASE_TAREAS_DATABASE:
            raise LogicalRestorationError(
                "RESTORATION_BACKEND_UNAVAILABLE",
                "La restauración lógica solo está habilitada sobre la base tareas.",
            )
    elif not isinstance(storage, DjangoDeletionLedgerStorage):
        raise LogicalRestorationError(
            "RESTORATION_BACKEND_UNAVAILABLE",
            "El backend operacional de Tareas no está soportado.",
        )
    return storage


def _mysql_identifier(value: str) -> str:
    if not _MYSQL_IDENTIFIER.fullmatch(value):
        raise LogicalRestorationError(
            "RESTORATION_BACKEND_UNAVAILABLE",
            "El esquema operacional contiene un identificador no válido.",
        )
    return f"`{value}`"


def _mysql_table(model) -> str:
    return _mysql_identifier(model._meta.db_table)


def _mysql_column(model, field_name: str) -> str:
    return _mysql_identifier(model._meta.get_field(field_name).column)


def _uuid_value(value) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    if isinstance(value, bytes):
        value = value.decode("ascii")
    return UUID(str(value))


def _task_state_from_model(row) -> _TaskState:
    return _TaskState(
        task_id=row.pk,
        empresa_id=row.empresa_id,
        correlativo=row.correlativo,
        titulo=row.titulo,
        estado=row.estado,
        prioridad=row.prioridad,
        fecha_creacion=row.fecha_creacion,
        fecha_publicacion=row.fecha_publicacion,
        fecha_asignacion=row.fecha_asignacion,
        fecha_tope=row.fecha_tope,
        fecha_cumplimiento=row.fecha_cumplimiento,
        responsable_id=row.responsable_id,
        eliminada=row.eliminada,
        eliminada_en=row.eliminada_en,
        eliminada_por_id=row.eliminada_por_id,
        eliminacion_operacion_id=_uuid_value(row.eliminacion_operacion_id),
    )


def _task_state_from_row(row) -> _TaskState:
    return _TaskState(
        task_id=int(row[0]),
        empresa_id=int(row[1]),
        correlativo=str(row[2]),
        titulo=str(row[3]),
        estado=str(row[4]),
        prioridad=str(row[5]),
        fecha_creacion=row[6],
        fecha_publicacion=row[7],
        fecha_asignacion=row[8],
        fecha_tope=row[9],
        fecha_cumplimiento=row[10],
        responsable_id=int(row[11]) if row[11] is not None else None,
        eliminada=bool(row[12]),
        eliminada_en=row[13],
        eliminada_por_id=int(row[14]) if row[14] is not None else None,
        eliminacion_operacion_id=_uuid_value(row[15]),
    )


def _file_reference_fingerprint(file_name: object, url: object) -> str:
    file_value = file_name.decode("utf-8") if isinstance(file_name, bytes) else str(file_name or "")
    url_value = url.decode("utf-8") if isinstance(url, bytes) else str(url or "")
    return hashlib.sha256(
        f"{file_value}\0{url_value}".encode("utf-8")
    ).hexdigest()


def _required_field(model, field_name: str):
    field = model._meta.get_field(field_name)
    if field is None:
        raise LogicalRestorationError(
            "RESTORATION_BACKEND_UNAVAILABLE",
            "El esquema operacional no contiene un campo requerido.",
        )
    return field


class _DjangoRestorationAdapter:
    def __init__(self, alias: str, empresa_id: int):
        self.alias = alias
        self.empresa_id = empresa_id
        self.connection = connections[alias]

    def lock_company(self) -> None:
        lock_orm_task_company(self.alias, self.empresa_id)

    def tasks(
        self,
        task_ids: tuple[int, ...],
        *,
        lock: bool,
    ) -> tuple[_TaskState, ...]:
        if not task_ids:
            return ()
        if lock:
            rows = lock_orm_task_rows(
                self.alias,
                self.empresa_id,
                task_ids,
                require_row_locks=self.connection.vendor != "sqlite",
                include_deleted=True,
            )
        else:
            rows = Tarea.all_objects.using(self.alias).filter(
                empresa_id=self.empresa_id,
                pk__in=task_ids,
            ).order_by("pk")
        return tuple(_task_state_from_model(row) for row in rows)

    def hierarchy_edges(
        self,
        task_ids: tuple[int, ...],
        *,
        lock: bool,
    ) -> tuple[tuple[int, int], ...]:
        if not task_ids:
            return ()
        query = TareaRelacion.objects.using(self.alias).filter(
            Q(padre_id__in=task_ids) | Q(hija_id__in=task_ids)
        )
        if lock and self.connection.features.has_select_for_update:
            query = query.select_for_update()
        return tuple(
            (int(parent_id), int(child_id))
            for parent_id, child_id in query.order_by(
                "padre_id",
                "hija_id",
            ).values_list("padre_id", "hija_id")
        )

    def documents(
        self,
        task_ids: tuple[int, ...],
        *,
        lock: bool,
    ) -> tuple[_DocumentState, ...]:
        if not task_ids:
            return ()
        query = DocumentoTarea.objects.using(self.alias).filter(
            tarea_id__in=task_ids,
            tarea__empresa_id=self.empresa_id,
        )
        if lock and self.connection.features.has_select_for_update:
            query = query.select_for_update()
        rows = query.order_by("tarea_id", "pk").values_list(
            "pk",
            "tarea_id",
            "tipo",
            "formato_archivo",
            "estado",
            "archivo",
            "url",
        )
        return tuple(
            _DocumentState(
                document_id=int(row[0]),
                task_id=int(row[1]),
                tipo=str(row[2]),
                formato_archivo=str(row[3]),
                estado=str(row[4]),
                has_file=bool(row[5]),
                has_url=bool(row[6]),
                reference_fingerprint=_file_reference_fingerprint(row[5], row[6]),
            )
            for row in rows
        )

    def external_origin_reference_count(self, task_ids: tuple[int, ...]) -> int:
        if not task_ids:
            return 0
        return Tarea.all_objects.using(self.alias).filter(
            empresa_id=self.empresa_id,
            tarea_origen_id__in=task_ids
        ).exclude(pk__in=task_ids).count()

    def has_file_cleanup(self, operation_id: UUID) -> bool:
        return TareaEliminacionArchivo.objects.using(self.alias).filter(
            operacion_id=operation_id.hex
        ).exists()

    def clear_deletion_markers(
        self,
        task_ids: tuple[int, ...],
        operation_id: UUID,
    ) -> int:
        if not task_ids:
            return 0
        quote = self.connection.ops.quote_name
        table = quote(Tarea._meta.db_table)
        pk_field = _required_field(Tarea, "id")
        company_field = _required_field(Tarea, "empresa")
        deleted_field = _required_field(Tarea, "eliminada")
        deleted_at_field = _required_field(Tarea, "eliminada_en")
        deleted_by_field = _required_field(Tarea, "eliminada_por")
        operation_field = _required_field(Tarea, "eliminacion_operacion_id")
        placeholders = ", ".join("%s" for _ in task_ids)
        sql = (
            f"UPDATE {table} SET "
            f"{quote(deleted_field.column)} = %s, "
            f"{quote(deleted_at_field.column)} = %s, "
            f"{quote(deleted_by_field.column)} = %s, "
            f"{quote(operation_field.column)} = %s "
            f"WHERE {quote(company_field.column)} = %s "
            f"AND {quote(pk_field.column)} IN ({placeholders}) "
            f"AND {quote(deleted_field.column)} = %s "
            f"AND {quote(deleted_at_field.column)} IS NOT NULL "
            f"AND {quote(deleted_by_field.column)} IS NOT NULL "
            f"AND {quote(operation_field.column)} = %s"
        )
        params = (
            deleted_field.get_db_prep_save(False, self.connection),
            deleted_at_field.get_db_prep_save(None, self.connection),
            deleted_by_field.get_db_prep_save(None, self.connection),
            operation_field.get_db_prep_save(None, self.connection),
            company_field.get_db_prep_save(
                self.empresa_id,
                self.connection,
            ),
            *(
                pk_field.get_db_prep_save(task_id, self.connection)
                for task_id in task_ids
            ),
            deleted_field.get_db_prep_save(True, self.connection),
            operation_field.get_db_prep_save(operation_id, self.connection),
        )
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.rowcount


class _MySQLRestorationAdapter:
    def __init__(self, connection, empresa_id: int):
        self.connection = connection
        self.empresa_id = empresa_id
        self.task_table = _mysql_table(Tarea)
        self.task_columns = tuple(
            _mysql_column(Tarea, name)
            for name in (
                "id",
                "empresa",
                "correlativo",
                "titulo",
                "estado",
                "prioridad",
                "fecha_creacion",
                "fecha_publicacion",
                "fecha_asignacion",
                "fecha_tope",
                "fecha_cumplimiento",
                "responsable",
                "eliminada",
                "eliminada_en",
                "eliminada_por",
                "eliminacion_operacion_id",
            )
        )
        self.task_id = _mysql_column(Tarea, "id")
        self.task_empresa = _mysql_column(Tarea, "empresa")
        self.task_deleted = _mysql_column(Tarea, "eliminada")
        self.task_deleted_at = _mysql_column(Tarea, "eliminada_en")
        self.task_deleted_by = _mysql_column(Tarea, "eliminada_por")
        self.task_operation = _mysql_column(Tarea, "eliminacion_operacion_id")
        self.relation_table = _mysql_table(TareaRelacion)
        self.relation_parent = _mysql_column(TareaRelacion, "padre")
        self.relation_child = _mysql_column(TareaRelacion, "hija")
        self.document_table = _mysql_table(DocumentoTarea)
        self.document_id = _mysql_column(DocumentoTarea, "id")
        self.document_task = _mysql_column(DocumentoTarea, "tarea")
        self.document_type = _mysql_column(DocumentoTarea, "tipo")
        self.document_format = _mysql_column(DocumentoTarea, "formato_archivo")
        self.document_status = _mysql_column(DocumentoTarea, "estado")
        self.document_file = _mysql_column(DocumentoTarea, "archivo")
        self.document_url = _mysql_column(DocumentoTarea, "url")
        self.origin_task = _mysql_column(Tarea, "tarea_origen")
        self.file_table = _mysql_table(TareaEliminacionArchivo)

    def _fetchall(self, sql: str, params=()):
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params)
            return tuple(cursor.fetchall())
        finally:
            cursor.close()

    def lock_company(self) -> None:
        lock_mysql_task_company(self.connection, self.empresa_id)

    def tasks(
        self,
        task_ids: tuple[int, ...],
        *,
        lock: bool,
    ) -> tuple[_TaskState, ...]:
        if not task_ids:
            return ()
        if lock:
            lock_mysql_task_rows(
                self.connection,
                self.empresa_id,
                task_ids,
                include_deleted=True,
            )
        placeholders = ", ".join("%s" for _ in task_ids)
        sql = (
            f"SELECT {', '.join(self.task_columns)} FROM {self.task_table} "
            f"WHERE {self.task_empresa} = %s "
            f"AND {self.task_id} IN ({placeholders}) "
            f"ORDER BY {self.task_id}"
        )
        if lock:
            sql += " FOR UPDATE"
        rows = self._fetchall(sql, (self.empresa_id, *task_ids))
        return tuple(_task_state_from_row(row) for row in rows)

    def hierarchy_edges(
        self,
        task_ids: tuple[int, ...],
        *,
        lock: bool,
    ) -> tuple[tuple[int, int], ...]:
        if not task_ids:
            return ()
        placeholders = ", ".join("%s" for _ in task_ids)
        sql = (
            f"SELECT {self.relation_parent}, {self.relation_child} "
            f"FROM {self.relation_table} "
            f"WHERE {self.relation_parent} IN ({placeholders}) "
            f"OR {self.relation_child} IN ({placeholders}) "
            f"ORDER BY {self.relation_parent}, {self.relation_child}"
        )
        if lock:
            sql += " FOR UPDATE"
        return tuple(
            (int(parent_id), int(child_id))
            for parent_id, child_id in self._fetchall(
                sql,
                (*task_ids, *task_ids),
            )
        )

    def documents(
        self,
        task_ids: tuple[int, ...],
        *,
        lock: bool,
    ) -> tuple[_DocumentState, ...]:
        if not task_ids:
            return ()
        placeholders = ", ".join("%s" for _ in task_ids)
        sql = (
            f"SELECT d.{self.document_id}, d.{self.document_task}, "
            f"d.{self.document_type}, d.{self.document_format}, "
            f"d.{self.document_status}, d.{self.document_file}, d.{self.document_url} "
            f"FROM {self.document_table} AS d "
            f"JOIN {self.task_table} AS t "
            f"ON t.{self.task_id} = d.{self.document_task} "
            f"WHERE t.{self.task_empresa} = %s "
            f"AND d.{self.document_task} IN ({placeholders}) "
            f"ORDER BY d.{self.document_task}, d.{self.document_id}"
        )
        if lock:
            sql += " FOR UPDATE"
        rows = self._fetchall(sql, (self.empresa_id, *task_ids))
        return tuple(
            _DocumentState(
                document_id=int(row[0]),
                task_id=int(row[1]),
                tipo=str(row[2]),
                formato_archivo=str(row[3]),
                estado=str(row[4]),
                has_file=bool(row[5]),
                has_url=bool(row[6]),
                reference_fingerprint=_file_reference_fingerprint(row[5], row[6]),
            )
            for row in rows
        )

    def external_origin_reference_count(self, task_ids: tuple[int, ...]) -> int:
        if not task_ids:
            return 0
        placeholders = ", ".join("%s" for _ in task_ids)
        rows = self._fetchall(
            f"SELECT COUNT(*) FROM {self.task_table} "
            f"WHERE {self.task_empresa} = %s "
            f"AND {self.origin_task} IN ({placeholders}) "
            f"AND {self.task_id} NOT IN ({placeholders})",
            (self.empresa_id, *task_ids, *task_ids),
        )
        return int(rows[0][0]) if rows else 0

    def has_file_cleanup(self, operation_id: UUID) -> bool:
        rows = self._fetchall(
            f"SELECT 1 FROM {self.file_table} "
            "WHERE `operacion_id` = %s LIMIT 1",
            (operation_id.hex,),
        )
        return bool(rows)

    def clear_deletion_markers(
        self,
        task_ids: tuple[int, ...],
        operation_id: UUID,
    ) -> int:
        if not task_ids:
            return 0
        placeholders = ", ".join("%s" for _ in task_ids)
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                f"UPDATE {self.task_table} SET "
                f"{self.task_deleted} = %s, "
                f"{self.task_deleted_at} = NULL, "
                f"{self.task_deleted_by} = NULL, "
                f"{self.task_operation} = NULL "
                f"WHERE {self.task_empresa} = %s "
                f"AND {self.task_id} IN ({placeholders}) "
                f"AND {self.task_deleted} = %s "
                f"AND {self.task_deleted_at} IS NOT NULL "
                f"AND {self.task_deleted_by} IS NOT NULL "
                f"AND {self.task_operation} = %s",
                (
                    False,
                    self.empresa_id,
                    *task_ids,
                    True,
                    operation_id.hex,
                ),
            )
            return cursor.rowcount
        finally:
            cursor.close()


def _task_adapter(storage, unit, empresa_id: int):
    if isinstance(storage, DjangoDeletionLedgerStorage):
        connection = connections[storage.alias]
        if connection.vendor == "mysql":
            return _MySQLRestorationAdapter(connection, empresa_id)
        return _DjangoRestorationAdapter(storage.alias, empresa_id)
    if isinstance(storage, MySQLDeletionLedgerStorage):
        return _MySQLRestorationAdapter(unit.connection, empresa_id)
    raise LogicalRestorationError(
        "RESTORATION_BACKEND_UNAVAILABLE",
        "El backend operacional de Tareas no está soportado.",
    )


@contextmanager
def _bounded_lock_wait(storage, unit) -> Generator[None, None, None]:
    if isinstance(storage, DjangoDeletionLedgerStorage):
        with bounded_django_lock_wait(storage.alias):
            yield
        return
    if isinstance(storage, MySQLDeletionLedgerStorage):
        with bounded_mysql_lock_wait(unit.connection):
            yield
        return
    raise LogicalRestorationError(
        "RESTORATION_BACKEND_UNAVAILABLE",
        "El backend operacional de Tareas no está soportado.",
    )


@contextmanager
def _translate_task_mutation_errors() -> Generator[None, None, None]:
    try:
        yield
    except TaskMutationScopeError as exc:
        raise LogicalRestorationError(
            "RESTORATION_TASK_MISSING",
            "Una o más tareas del manifiesto no existen o cambiaron de empresa.",
        ) from exc
    except TaskMutationConflict as exc:
        raise LogicalRestorationError(
            "RESTORATION_STATE_CONFLICT",
            "Otra mutación bloqueó el manifiesto; vuelva a generar la previsualización.",
        ) from exc
    except TaskMutationLockError as exc:
        raise LogicalRestorationError(
            "RESTORATION_BACKEND_UNAVAILABLE",
            "No se pudo adquirir el bloqueo transaccional requerido.",
        ) from exc


def _manifest_problem(
    source: DeletionOperationRecord,
    manifest: tuple[DeletionInventoryItem, ...],
) -> bool:
    task_items = tuple(item for item in manifest if item.model_label == _TASK_ITEM_LABEL)
    task_ids = tuple(item.object_id for item in task_items)
    return bool(
        not manifest
        or len(task_items) != len(manifest)
        or len(task_ids) != len(set(task_ids))
        or any(task_id < 1 for task_id in task_ids)
        or DeletionInventoryItem(_TASK_ITEM_LABEL, source.root_task_id)
        not in task_items
        or source.dependency_summary.get(_TASK_ITEM_LABEL) != len(task_ids)
    )


def _hierarchy_is_valid(
    root_task_id: int,
    task_ids: tuple[int, ...],
    edges: tuple[tuple[int, int], ...],
) -> bool:
    task_set = set(task_ids)
    if not task_set or root_task_id not in task_set:
        return False
    if any(
        parent_id not in task_set
        or child_id not in task_set
        or parent_id == child_id
        for parent_id, child_id in edges
    ):
        return False
    if len(edges) != len(set(edges)) or len(edges) != len(task_set) - 1:
        return False

    parents_by_child: dict[int, int] = {}
    children_by_parent: dict[int, list[int]] = {}
    for parent_id, child_id in edges:
        if child_id in parents_by_child:
            return False
        parents_by_child[child_id] = parent_id
        children_by_parent.setdefault(parent_id, []).append(child_id)
    if root_task_id in parents_by_child or any(
        task_id != root_task_id and task_id not in parents_by_child
        for task_id in task_set
    ):
        return False

    visited = set()
    frontier = [root_task_id]
    while frontier:
        current = frontier.pop()
        if current in visited:
            return False
        visited.add(current)
        frontier.extend(children_by_parent.get(current, ()))
    return visited == task_set


def _issue(code: str, message: str) -> LogicalRestorationIssue:
    return LogicalRestorationIssue(code=code, message=message)


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return value.hex
    raise TypeError(f"Unsupported fingerprint value: {type(value).__name__}")


def _preview_fingerprint(
    *,
    actor_id: int,
    company: Empresa,
    source: DeletionOperationRecord,
    manifest: tuple[DeletionInventoryItem, ...],
    tasks: tuple[_TaskState, ...],
    edges: tuple[tuple[int, int], ...],
    documents: tuple[_DocumentState, ...],
    external_origin_reference_count: int,
    has_file_cleanup: bool,
) -> str:
    payload = {
        "actor_id": actor_id,
        "company": {"id": company.pk, "codigo": company.codigo},
        "source": {
            "operation_id": source.operation_id,
            "actor_id": source.actor_id,
            "empresa_id": source.empresa_id,
            "root_task_id": source.root_task_id,
            "root_correlativo": source.root_correlativo,
            "fingerprint": source.fingerprint,
            "status": source.status,
            "result_code": source.result_code,
            "audit_status": source.audit_status,
            "file_cleanup_status": source.file_cleanup_status,
            "created_at": source.created_at,
            "committed_at": source.committed_at,
            "motivo": source.motivo,
            "backend_type": source.backend_type,
            "backend_identity": source.backend_identity,
            "backend_config_version": source.backend_config_version,
            "dependency_summary": source.dependency_summary,
        },
        "manifest": [
            {"model_label": item.model_label, "object_id": item.object_id}
            for item in manifest
        ],
        "tasks": [
            {
                "task_id": item.task_id,
                "empresa_id": item.empresa_id,
                "correlativo": item.correlativo,
                "titulo": item.titulo,
                "estado": item.estado,
                "prioridad": item.prioridad,
                "fecha_creacion": item.fecha_creacion,
                "fecha_publicacion": item.fecha_publicacion,
                "fecha_asignacion": item.fecha_asignacion,
                "fecha_tope": item.fecha_tope,
                "fecha_cumplimiento": item.fecha_cumplimiento,
                "responsable_id": item.responsable_id,
                "eliminada": item.eliminada,
                "eliminada_en": item.eliminada_en,
                "eliminada_por_id": item.eliminada_por_id,
                "eliminacion_operacion_id": item.eliminacion_operacion_id,
            }
            for item in tasks
        ],
        "hierarchy": edges,
        "documents": [
            {
                "document_id": item.document_id,
                "task_id": item.task_id,
                "tipo": item.tipo,
                "formato_archivo": item.formato_archivo,
                "estado": item.estado,
                "has_file": item.has_file,
                "has_url": item.has_url,
                "reference_fingerprint": item.reference_fingerprint,
            }
            for item in documents
        ],
        "external_origin_reference_count": external_origin_reference_count,
        "has_file_cleanup": has_file_cleanup,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_value,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _compose_preview(
    *,
    actor_id: int,
    company: Empresa,
    source: DeletionOperationRecord,
    manifest: tuple[DeletionInventoryItem, ...],
    existing_restoration: DeletionOperationRecord | None,
    allowed_pending_operation_id: UUID | None,
    tasks: tuple[_TaskState, ...],
    edges: tuple[tuple[int, int], ...],
    documents: tuple[_DocumentState, ...],
    external_origin_reference_count: int,
    has_file_cleanup: bool,
) -> LogicalRestorationPreview:
    task_items = tuple(item for item in manifest if item.model_label == _TASK_ITEM_LABEL)
    task_ids = tuple(sorted({item.object_id for item in task_items}))
    task_map = {item.task_id: item for item in tasks}
    task_summaries = tuple(
        LogicalRestorationTask(
            task_id=task_id,
            physically_present=task_id in task_map,
            correlativo=task_map[task_id].correlativo if task_id in task_map else None,
            titulo=task_map[task_id].titulo if task_id in task_map else None,
            estado=task_map[task_id].estado if task_id in task_map else None,
            fecha_tope=task_map[task_id].fecha_tope if task_id in task_map else None,
            responsable_id=(
                task_map[task_id].responsable_id if task_id in task_map else None
            ),
            eliminada=task_map[task_id].eliminada if task_id in task_map else None,
            eliminada_en=(
                task_map[task_id].eliminada_en if task_id in task_map else None
            ),
            eliminada_por_id=(
                task_map[task_id].eliminada_por_id if task_id in task_map else None
            ),
            eliminacion_operacion_id=(
                task_map[task_id].eliminacion_operacion_id
                if task_id in task_map
                else None
            ),
        )
        for task_id in task_ids
    )
    task_set = set(task_ids)
    internal_edges = tuple(
        sorted(
            (parent_id, child_id)
            for parent_id, child_id in edges
            if parent_id in task_set and child_id in task_set
        )
    )
    public_documents = tuple(
        LogicalRestorationDocument(
            document_id=item.document_id,
            task_id=item.task_id,
            tipo=item.tipo,
            formato_archivo=item.formato_archivo,
            estado=item.estado,
            has_file=item.has_file,
            has_url=item.has_url,
        )
        for item in documents
    )

    blockers: list[LogicalRestorationIssue] = []
    warnings: list[LogicalRestorationIssue] = []
    if _manifest_problem(source, manifest):
        blockers.append(
            _issue(
                "RESTORATION_MANIFEST_INCOMPLETE",
                "El manifiesto no contiene exactamente las tareas de la eliminación original.",
            )
        )
    if existing_restoration is not None:
        if existing_restoration.status == TareaEliminacionOperacion.Estado.COMMITTED:
            blockers.append(
                _issue(
                    "RESTORATION_ALREADY_COMPLETED",
                    "La eliminación original ya tiene una restauración confirmada.",
                )
            )
        elif existing_restoration.operation_id != allowed_pending_operation_id:
            blockers.append(
                _issue(
                    "RESTORATION_STATE_CONFLICT",
                    "Existe una restauración pendiente que requiere el mismo UUID para reintentar.",
                )
            )

    missing_ids = tuple(task_id for task_id in task_ids if task_id not in task_map)
    if missing_ids:
        blockers.append(
            _issue(
                "RESTORATION_TASK_MISSING",
                "Falta al menos una fila del manifiesto en la empresa operativa.",
            )
        )
    if any(
        not task.eliminada
        or task.eliminada_en is None
        or task.eliminada_por_id is None
        or task.eliminacion_operacion_id != source.operation_id
        or (
            task.task_id == source.root_task_id
            and task.correlativo != source.root_correlativo
        )
        for task in tasks
    ):
        blockers.append(
            _issue(
                "RESTORATION_STATE_CONFLICT",
                "Las marcas o identidad de una tarea no coinciden con la eliminación original.",
            )
        )
    if not _hierarchy_is_valid(source.root_task_id, task_ids, edges):
        blockers.append(
            _issue(
                "RESTORATION_HIERARCHY_CONFLICT",
                "La jerarquía retenida no forma un árbol íntegro dentro del manifiesto.",
            )
        )
    if has_file_cleanup:
        blockers.append(
            _issue(
                "RESTORATION_NOT_ELIGIBLE",
                "La operación de origen contiene una limpieza física de archivos incompatible.",
            )
        )
    if (
        source.audit_status
        != TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA
    ):
        warnings.append(
            _issue(
                "SOURCE_AUDIT_UNCONFIRMED",
                "La auditoría de la eliminación original se concilia por separado.",
            )
        )
    if external_origin_reference_count:
        warnings.append(
            _issue(
                "EXTERNAL_ORIGIN_REFERENCES",
                f"Hay {external_origin_reference_count} referencias de origen desde tareas externas al manifiesto.",
            )
        )
    file_count = sum(1 for item in documents if item.has_file)
    if file_count:
        warnings.append(
            _issue(
                "FILES_NOT_VERIFIED",
                f"Hay {file_count} referencias a archivos; su disponibilidad física no fue comprobada ni será modificada.",
            )
        )

    fingerprint = _preview_fingerprint(
        actor_id=actor_id,
        company=company,
        source=source,
        manifest=manifest,
        tasks=tasks,
        edges=edges,
        documents=documents,
        external_origin_reference_count=external_origin_reference_count,
        has_file_cleanup=has_file_cleanup,
    )
    return LogicalRestorationPreview(
        deletion_operation_id=source.operation_id,
        root_task_id=source.root_task_id,
        root_correlativo=source.root_correlativo,
        empresa_id=source.empresa_id,
        empresa_codigo=company.codigo,
        empresa_descripcion=company.descripcion or "",
        deletion_actor_id=source.actor_id,
        deletion_created_at=source.created_at,
        deletion_committed_at=source.committed_at,
        deletion_motivo=source.motivo or "",
        source_audit_status=source.audit_status,
        manifest=manifest,
        task_ids=task_ids,
        tasks=task_summaries,
        hierarchy=internal_edges,
        documents=public_documents,
        external_origin_reference_count=external_origin_reference_count,
        restoration_operation_id=(
            existing_restoration.operation_id
            if existing_restoration is not None
            else None
        ),
        warnings=tuple(warnings),
        blockers=tuple(blockers),
        backend_type=source.backend_type,
        backend_identity=source.backend_identity,
        backend_config_version=source.backend_config_version,
        fingerprint=fingerprint,
    )


def _validate_source(source: DeletionOperationRecord, empresa_id: int, storage) -> None:
    backend_type = (
        "DJANGO"
        if isinstance(storage, DjangoDeletionLedgerStorage)
        else "MYSQL_CONFIG"
    )
    if (
        source.empresa_id != empresa_id
        or source.reverses_operation_id is not None
        or source.status != TareaEliminacionOperacion.Estado.COMMITTED
        or source.result_code != LOGICAL_DELETION_RESULT_CODE
        or source.file_cleanup_status
        != TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA
        or not source.motivo
        or not source.motivo.strip()
        or source.backend_type != backend_type
        or source.backend_identity != storage.backend_identity
        or source.backend_config_version != storage.config_version
    ):
        raise LogicalRestorationError(
            "RESTORATION_NOT_ELIGIBLE",
            "La operación de origen no es una eliminación lógica vigente en BASE_TAREAS.",
        )


def _read_preview(
    *,
    actor,
    company: Empresa,
    empresa_id: int,
    deletion_operation_id: UUID,
    storage,
    allowed_pending_operation_id: UUID | None = None,
) -> LogicalRestorationPreview:
    try:
        with storage.atomic() as unit:
            source = unit.get_restoration_source_operation(deletion_operation_id)
            if source is None or source.empresa_id != empresa_id:
                raise LogicalRestorationError(
                    "RESTORATION_NOT_FOUND",
                    "La operación no existe en la empresa activa.",
                )
            _validate_source(source, empresa_id, storage)
            manifest = unit.get_manifest(deletion_operation_id)
            try:
                existing_restoration = unit.get_restoration_for_source(
                    deletion_operation_id
                )
            except DeletionLedgerStateError:
                existing_restoration = None
                invalid_existing_restoration = True
            else:
                invalid_existing_restoration = False
            adapter = _task_adapter(storage, unit, empresa_id)
            task_ids = tuple(
                sorted(
                    {
                        item.object_id
                        for item in manifest
                        if item.model_label == _TASK_ITEM_LABEL
                    }
                )
            )
            tasks = adapter.tasks(task_ids, lock=False)
            verified_task_ids = tuple(sorted(task.task_id for task in tasks))
            if verified_task_ids == task_ids:
                edges = adapter.hierarchy_edges(task_ids, lock=False)
                documents = adapter.documents(task_ids, lock=False)
                external_count = adapter.external_origin_reference_count(task_ids)
            else:
                edges = ()
                documents = ()
                external_count = 0
            has_file_cleanup = adapter.has_file_cleanup(deletion_operation_id)
            preview = _compose_preview(
                actor_id=actor.pk,
                company=company,
                source=source,
                manifest=manifest,
                existing_restoration=existing_restoration,
                allowed_pending_operation_id=allowed_pending_operation_id,
                tasks=tasks,
                edges=edges,
                documents=documents,
                external_origin_reference_count=external_count,
                has_file_cleanup=has_file_cleanup,
            )
            if invalid_existing_restoration:
                preview = LogicalRestorationPreview(
                    **{
                        **preview.__dict__,
                        "blockers": (
                            *preview.blockers,
                            _issue(
                                "RESTORATION_STATE_CONFLICT",
                                "El ledger contiene una restauración existente con estado inválido.",
                            ),
                        ),
                    }
                )
            return preview
    except LogicalRestorationError:
        raise
    except (DeletionLedgerError, DatabaseError) as exc:
        raise LogicalRestorationError(
            "RESTORATION_BACKEND_UNAVAILABLE",
            "No se pudo leer el ledger o el esquema operacional de Tareas.",
        ) from exc


def build_logical_restoration_preview(
    *,
    actor,
    empresa_id: int,
    deletion_operation_id: UUID,
) -> LogicalRestorationPreview:
    empresa_id = _positive_id(empresa_id, "empresa_id")
    deletion_operation_id = _operation_uuid(
        deletion_operation_id,
        "deletion_operation_id",
    )
    company = _authorize(actor, empresa_id)
    storage = _resolve_storage()
    return _read_preview(
        actor=actor,
        company=company,
        empresa_id=empresa_id,
        deletion_operation_id=deletion_operation_id,
        storage=storage,
    )


def _restoration_input(
    *,
    actor,
    empresa_id: int,
    source: DeletionOperationRecord,
    restoration_operation_id: UUID,
    motivo: str,
    fingerprint: str,
    manifest: tuple[DeletionInventoryItem, ...],
) -> RestorationOperationInput:
    return RestorationOperationInput(
        actor_id=actor.pk,
        empresa_id=empresa_id,
        reverses_operation_id=source.operation_id,
        fingerprint=fingerprint,
        manifest=manifest,
        operation_id=restoration_operation_id,
        motivo=motivo,
    )


def _assert_restoration_request(
    record: DeletionOperationRecord,
    *,
    actor_id: int,
    empresa_id: int,
    source_operation_id: UUID,
    operation_id: UUID,
    motivo: str,
    fingerprint: str,
    storage,
) -> None:
    if (
        record.operation_id != operation_id
        or record.reverses_operation_id != source_operation_id
        or record.actor_id != actor_id
        or record.empresa_id != empresa_id
        or record.motivo != motivo
        or record.fingerprint != fingerprint
        or record.backend_identity != storage.backend_identity
        or record.backend_config_version != storage.config_version
        or record.backend_type
        != ("DJANGO" if isinstance(storage, DjangoDeletionLedgerStorage) else "MYSQL_CONFIG")
    ):
        raise LogicalRestorationError(
            "RESTORATION_OPERATION_ID_CONFLICT",
            "El UUID de restauración ya está asociado a otra solicitud.",
            operation_id=operation_id,
        )


def _validate_source_and_manifests(
    unit,
    *,
    source_operation_id: UUID,
    restoration: DeletionOperationRecord,
    empresa_id: int,
    storage,
) -> tuple[DeletionOperationRecord, tuple[DeletionInventoryItem, ...]]:
    source = unit.get_restoration_source_operation(source_operation_id)
    if source is None or source.empresa_id != empresa_id:
        raise LogicalRestorationError(
            "RESTORATION_NOT_FOUND",
            "La operación no existe en la empresa activa.",
        )
    _validate_source(source, empresa_id, storage)
    source_manifest = unit.get_manifest(source_operation_id)
    restoration_manifest = unit.get_manifest(restoration.operation_id)
    if _manifest_problem(source, source_manifest):
        raise LogicalRestorationError(
            "RESTORATION_MANIFEST_INCOMPLETE",
            "El manifiesto original no es íntegro.",
            operation_id=restoration.operation_id,
        )
    if restoration_manifest != source_manifest:
        raise LogicalRestorationError(
            "RESTORATION_MANIFEST_INCOMPLETE",
            "El manifiesto de restauración no coincide con la eliminación original.",
            operation_id=restoration.operation_id,
        )
    return source, source_manifest


def _result(
    record: DeletionOperationRecord,
    *,
    task_ids: tuple[int, ...],
    replayed: bool,
) -> LogicalRestorationResult:
    if (
        record.reverses_operation_id is None
        or record.status != TareaEliminacionOperacion.Estado.COMMITTED
        or record.result_code != LOGICAL_RESTORATION_RESULT_CODE
    ):
        raise LogicalRestorationError(
            "RESTORATION_STATE_CONFLICT",
            "La operación de restauración no está confirmada correctamente.",
            operation_id=record.operation_id,
        )
    return LogicalRestorationResult(
        operation_id=record.operation_id,
        reverses_operation_id=record.reverses_operation_id,
        root_task_id=record.root_task_id,
        task_ids=task_ids,
        result_code=record.result_code,
        status=record.status,
        backend_type=record.backend_type,
        audit_status=record.audit_status,
        replayed=replayed,
    )


def _audit_meta(
    record: DeletionOperationRecord,
    task_ids: tuple[int, ...],
) -> dict[str, object]:
    if record.reverses_operation_id is None:
        raise LogicalRestorationError(
            "RESTORATION_STATE_CONFLICT",
            "La operación no referencia una eliminación lógica.",
            operation_id=record.operation_id,
        )
    return {
        "operation": "logical_restore_tree",
        "operation_id": record.operation_id.hex,
        "source_operation_id": record.reverses_operation_id.hex,
        "actor_id": record.actor_id,
        "empresa_id": record.empresa_id,
        "root_task_id": record.root_task_id,
        "restored_task_ids": list(task_ids),
        "fingerprint": record.fingerprint,
        "backend_type": record.backend_type,
    }


def _audit_payload_matches(
    event,
    *,
    record: DeletionOperationRecord,
    task_ids: tuple[int, ...],
) -> bool:
    payload_hash = getattr(event, "idempotency_payload_hash", None)
    return (
        event.idempotency_key == record.operation_id.hex
        and isinstance(payload_hash, str)
        and len(payload_hash) == 64
        and all(char in "0123456789abcdef" for char in payload_hash.lower())
        and event.user_id in (None, record.actor_id)
        and event.empresa_id == record.empresa_id
        and event.action == "UPDATE"
        and event.object_type == "Tarea"
        and event.object_id == str(record.root_task_id)
        and event.ip_address is None
        and event.user_agent == ""
        and event.method == "INTERNAL"
        and event.path == "internal/logical-task-restoration"
        and event.querystring == ""
        and event.status_code is None
        and event.duration_ms is None
        and event.vista_nombre == "Tareas"
        and event.message_key is None
        and event.meta == _audit_meta(record, task_ids)
        and event.before is None
        and event.after is None
    )


def _record_audit_error(storage, operation_id: UUID, error_code: str) -> None:
    try:
        with storage.atomic() as unit:
            unit.record_audit_result(
                operation_id,
                confirmed=False,
                error_code=error_code,
            )
    except (DeletionLedgerError, DatabaseError) as exc:
        raise LogicalRestorationError(
            "RESTORATION_AUDIT_PENDING",
            "La restauración está confirmada, pero la auditoría requiere conciliación.",
            operation_id=operation_id,
        ) from exc


def _confirm_audit(storage, operation_id: UUID, event_id: int):
    try:
        with storage.atomic() as unit:
            unit.record_audit_result(
                operation_id,
                confirmed=True,
                event_id=event_id,
            )
            record = unit.get_restoration_operation(operation_id)
            if record is None:
                raise DeletionLedgerStateError(
                    "No se pudo recuperar la operación de restauración."
                )
            return record
    except (DeletionLedgerError, DatabaseError) as exc:
        raise LogicalRestorationError(
            "RESTORATION_AUDIT_PENDING",
            "La restauración está confirmada, pero la auditoría requiere conciliación.",
            operation_id=operation_id,
        ) from exc


def _deliver_audit(
    storage,
    *,
    record: DeletionOperationRecord,
    task_ids: tuple[int, ...],
    replayed: bool,
) -> LogicalRestorationResult:
    operation_id = record.operation_id
    if record.audit_status not in {
        TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
        TareaEliminacionOperacion.EstadoAuditoria.ERROR,
        TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
    }:
        raise LogicalRestorationError(
            "RESTORATION_AUDIT_CONFLICT",
            "El estado de auditoría de la restauración no es válido.",
            operation_id=operation_id,
        )
    try:
        audit_actor = get_user_model().objects.filter(pk=record.actor_id).first()
        audit_result = AuditoriaService.log_event_idempotent(
            app_label="tareas",
            idempotency_key=operation_id,
            action="UPDATE",
            user=audit_actor,
            empresa_id=record.empresa_id,
            object_type="Tarea",
            object_id=str(record.root_task_id),
            ip_address=None,
            user_agent="",
            method="INTERNAL",
            path="internal/logical-task-restoration",
            querystring="",
            status_code=None,
            duration_ms=None,
            vista_nombre="Tareas",
            message_key=None,
            meta=_audit_meta(record, task_ids),
        )
        event = audit_result.event
    except AuditIdempotencyConflict as exc:
        try:
            existing_event = AuditoriaService.get_event_by_idempotency_key(
                "tareas",
                operation_id,
            )
        except AuditIdempotencyStorageError as lookup_error:
            _record_audit_error(storage, operation_id, "AUDIT_LOOKUP_FAILED")
            raise LogicalRestorationError(
                "RESTORATION_AUDIT_PENDING",
                "La restauración está confirmada, pero la auditoría requiere conciliación.",
                operation_id=operation_id,
            ) from lookup_error
        if existing_event is None or not _audit_payload_matches(
            existing_event,
            record=record,
            task_ids=task_ids,
        ):
            _record_audit_error(storage, operation_id, "AUDIT_PAYLOAD_CONFLICT")
            raise LogicalRestorationError(
                "RESTORATION_AUDIT_CONFLICT",
                "La clave idempotente de auditoría está asociada a otro evento.",
                operation_id=operation_id,
            ) from exc
        event = existing_event
    except (AuditIdempotencyError, DatabaseError) as exc:
        _record_audit_error(storage, operation_id, "AUDIT_DELIVERY_FAILED")
        raise LogicalRestorationError(
            "RESTORATION_AUDIT_PENDING",
            "La restauración está confirmada, pero la auditoría requiere conciliación.",
            operation_id=operation_id,
        ) from exc

    event_id = getattr(event, "pk", None)
    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id < 1:
        _record_audit_error(storage, operation_id, "AUDIT_DELIVERY_FAILED")
        raise LogicalRestorationError(
            "RESTORATION_AUDIT_PENDING",
            "La restauración está confirmada, pero la auditoría requiere conciliación.",
            operation_id=operation_id,
        )
    confirmed = _confirm_audit(storage, operation_id, event_id)
    return _result(confirmed, task_ids=task_ids, replayed=replayed)


def _map_preview_blocker(preview: LogicalRestorationPreview) -> None:
    if not preview.blockers:
        return
    blocker = preview.blockers[0]
    raise LogicalRestorationError(blocker.code, blocker.message)


def _existing_restore_details(
    unit,
    *,
    restoration: DeletionOperationRecord,
    source_operation_id: UUID,
    empresa_id: int,
    storage,
) -> tuple[tuple[int, ...], bool]:
    source, manifest = _validate_source_and_manifests(
        unit,
        source_operation_id=source_operation_id,
        restoration=restoration,
        empresa_id=empresa_id,
        storage=storage,
    )
    _assert_restoration_source(
        RestorationOperationInput(
            actor_id=restoration.actor_id,
            empresa_id=restoration.empresa_id,
            reverses_operation_id=source_operation_id,
            fingerprint=restoration.fingerprint,
            manifest=manifest,
            operation_id=restoration.operation_id,
            motivo=restoration.motivo or "",
        ),
        source,
        backend_type=restoration.backend_type,
        backend_identity=storage.backend_identity,
        config_version=storage.config_version,
    )
    _normalize_restoration_manifest(
        unit.get_manifest(restoration.operation_id),
        root_task_id=source.root_task_id,
        source_manifest=manifest,
    )
    task_ids = tuple(sorted(item.object_id for item in manifest))
    return task_ids, (
        restoration.status == TareaEliminacionOperacion.Estado.COMMITTED
        and restoration.result_code == LOGICAL_RESTORATION_RESULT_CODE
    )


def restore_logical_task_tree(
    *,
    actor,
    empresa_id: int,
    deletion_operation_id: UUID,
    restoration_operation_id: UUID,
    motivo: str,
    expected_fingerprint: str,
) -> LogicalRestorationResult:
    empresa_id = _positive_id(empresa_id, "empresa_id")
    deletion_operation_id = _operation_uuid(
        deletion_operation_id,
        "deletion_operation_id",
    )
    restoration_operation_id = _operation_uuid(
        restoration_operation_id,
        "restoration_operation_id",
    )
    motivo = _reason(motivo)
    expected_fingerprint = _expected_fingerprint(expected_fingerprint)
    company = _authorize(actor, empresa_id)
    storage = _resolve_storage()

    existing_restoration = None
    replay_record = None
    task_ids: tuple[int, ...] = ()
    try:
        with storage.atomic() as unit:
            existing_restoration = unit.get_restoration_operation(
                restoration_operation_id
            )
            if existing_restoration is None:
                existing_operation = unit.get_operation(restoration_operation_id)
                if existing_operation is not None:
                    raise LogicalRestorationError(
                        "RESTORATION_OPERATION_ID_CONFLICT",
                        "El UUID ya pertenece a otra operación del ledger.",
                        operation_id=restoration_operation_id,
                    )
            else:
                _assert_restoration_request(
                    existing_restoration,
                    actor_id=actor.pk,
                    empresa_id=empresa_id,
                    source_operation_id=deletion_operation_id,
                    operation_id=restoration_operation_id,
                    motivo=motivo,
                    fingerprint=expected_fingerprint,
                    storage=storage,
                )
                if existing_restoration.status == TareaEliminacionOperacion.Estado.COMMITTED:
                    task_ids, committed = _existing_restore_details(
                        unit,
                        restoration=existing_restoration,
                        source_operation_id=deletion_operation_id,
                        empresa_id=empresa_id,
                        storage=storage,
                    )
                    if not committed:
                        raise LogicalRestorationError(
                            "RESTORATION_STATE_CONFLICT",
                            "La operación de restauración no está confirmada correctamente.",
                            operation_id=restoration_operation_id,
                        )
                    replay_record = existing_restoration
                else:
                    replay_record = None
                    task_ids = ()
    except LogicalRestorationError:
        raise
    except (DeletionLedgerError, DatabaseError) as exc:
        raise LogicalRestorationError(
            "RESTORATION_BACKEND_UNAVAILABLE",
            "No se pudo consultar el estado de la operación de restauración.",
            operation_id=restoration_operation_id,
        ) from exc

    if existing_restoration is not None and existing_restoration.status == (
        TareaEliminacionOperacion.Estado.COMMITTED
    ):
        if replay_record is None:
            raise LogicalRestorationError(
                "RESTORATION_STATE_CONFLICT",
                "No se pudo recuperar la operación de restauración.",
                operation_id=restoration_operation_id,
            )
        return _deliver_audit(
            storage,
            record=replay_record,
            task_ids=task_ids,
            replayed=True,
        )

    preview = _read_preview(
        actor=actor,
        company=company,
        empresa_id=empresa_id,
        deletion_operation_id=deletion_operation_id,
        storage=storage,
        allowed_pending_operation_id=(
            restoration_operation_id
            if existing_restoration is not None
            else None
        ),
    )
    if preview.fingerprint != expected_fingerprint:
        raise LogicalRestorationError(
            "RESTORATION_PREVIEW_STALE",
            "El alcance o los datos cambiaron desde la previsualización.",
        )
    _map_preview_blocker(preview)

    record = None
    restored_task_ids: tuple[int, ...] = ()
    replayed = False
    try:
        with storage.atomic() as unit, _translate_task_mutation_errors():
            source_before_lock = unit.get_restoration_source_operation(
                deletion_operation_id
            )
            if source_before_lock is None or source_before_lock.empresa_id != empresa_id:
                raise LogicalRestorationError(
                    "RESTORATION_NOT_FOUND",
                    "La operación no existe en la empresa activa.",
                )
            _validate_source(source_before_lock, empresa_id, storage)
            manifest_before_lock = unit.get_manifest(deletion_operation_id)
            if manifest_before_lock != preview.manifest:
                raise LogicalRestorationError(
                    "RESTORATION_PREVIEW_STALE",
                    "El manifiesto cambió desde la previsualización.",
                )

            adapter = _task_adapter(storage, unit, empresa_id)
            with _bounded_lock_wait(storage, unit):
                adapter.lock_company()
                task_ids = preview.task_ids
                tasks = adapter.tasks(task_ids, lock=True)
                edges = adapter.hierarchy_edges(task_ids, lock=True)
                documents = adapter.documents(task_ids, lock=True)
                external_count = adapter.external_origin_reference_count(task_ids)
                has_file_cleanup = adapter.has_file_cleanup(deletion_operation_id)

                source = unit.get_restoration_source_operation(
                    deletion_operation_id,
                    lock=True,
                )
                manifest = unit.get_manifest(deletion_operation_id, lock=True)
                if source is None or source.empresa_id != empresa_id:
                    raise LogicalRestorationError(
                        "RESTORATION_NOT_FOUND",
                        "La operación no existe en la empresa activa.",
                    )
                _validate_source(source, empresa_id, storage)
                if manifest != preview.manifest:
                    raise LogicalRestorationError(
                        "RESTORATION_PREVIEW_STALE",
                        "El manifiesto cambió desde la previsualización.",
                    )

                existing_for_source = unit.get_restoration_for_source(
                    deletion_operation_id,
                    lock=True,
                )
                if existing_for_source is not None and (
                    existing_for_source.operation_id != restoration_operation_id
                ):
                    code = (
                        "RESTORATION_ALREADY_COMPLETED"
                        if existing_for_source.status
                        == TareaEliminacionOperacion.Estado.COMMITTED
                        else "RESTORATION_STATE_CONFLICT"
                    )
                    raise LogicalRestorationError(
                        code,
                        "La eliminación original ya tiene otra operación de restauración.",
                        operation_id=existing_for_source.operation_id,
                    )
                if existing_for_source is not None:
                    _assert_restoration_request(
                        existing_for_source,
                        actor_id=actor.pk,
                        empresa_id=empresa_id,
                        source_operation_id=deletion_operation_id,
                        operation_id=restoration_operation_id,
                        motivo=motivo,
                        fingerprint=expected_fingerprint,
                        storage=storage,
                    )
                if existing_for_source is not None and (
                    existing_for_source.status
                    == TareaEliminacionOperacion.Estado.COMMITTED
                ):
                    task_ids, committed = _existing_restore_details(
                        unit,
                        restoration=existing_for_source,
                        source_operation_id=deletion_operation_id,
                        empresa_id=empresa_id,
                        storage=storage,
                    )
                    if not committed:
                        raise LogicalRestorationError(
                            "RESTORATION_STATE_CONFLICT",
                            "La operación de restauración no está confirmada correctamente.",
                            operation_id=restoration_operation_id,
                        )
                    record = existing_for_source
                    restored_task_ids = task_ids
                    replayed = True
                else:
                    current_preview = _compose_preview(
                        actor_id=actor.pk,
                        company=company,
                        source=source,
                        manifest=manifest,
                        existing_restoration=existing_for_source,
                        allowed_pending_operation_id=(
                            restoration_operation_id
                            if existing_for_source is not None
                            else None
                        ),
                        tasks=tasks,
                        edges=edges,
                        documents=documents,
                        external_origin_reference_count=external_count,
                        has_file_cleanup=has_file_cleanup,
                    )
                    if current_preview.fingerprint != expected_fingerprint:
                        raise LogicalRestorationError(
                            "RESTORATION_PREVIEW_STALE",
                            "El alcance o los datos cambiaron desde la previsualización.",
                        )
                    _map_preview_blocker(current_preview)
                    operation_input = _restoration_input(
                        actor=actor,
                        empresa_id=empresa_id,
                        source=source,
                        restoration_operation_id=restoration_operation_id,
                        motivo=motivo,
                        fingerprint=expected_fingerprint,
                        manifest=manifest,
                    )
                    record = unit.create_restoration_pending(operation_input)
                    restored_task_ids = tuple(
                        sorted(item.object_id for item in manifest)
                    )
                    affected_count = adapter.clear_deletion_markers(
                        restored_task_ids,
                        deletion_operation_id,
                    )
                    if affected_count != len(restored_task_ids):
                        raise LogicalRestorationError(
                            "RESTORATION_STATE_CONFLICT",
                            "No se pudieron limpiar exactamente todas las marcas del manifiesto.",
                            operation_id=restoration_operation_id,
                        )
                    verified_tasks = adapter.tasks(
                        restored_task_ids,
                        lock=True,
                    )
                    if len(verified_tasks) != len(restored_task_ids) or any(
                        task.eliminada
                        or task.eliminada_en is not None
                        or task.eliminada_por_id is not None
                        or task.eliminacion_operacion_id is not None
                        for task in verified_tasks
                    ):
                        raise LogicalRestorationError(
                            "RESTORATION_STATE_CONFLICT",
                            "La verificación posterior no confirmó la restauración exacta.",
                            operation_id=restoration_operation_id,
                        )
                    record = unit.mark_logically_restored(restoration_operation_id)
    except LogicalRestorationError:
        raise
    except DeletionLedgerCommitUncertain as exc:
        try:
            committed = storage.get_restoration_operation(
                restoration_operation_id
            )
        except (DeletionLedgerError, DatabaseError) as lookup_error:
            raise LogicalRestorationError(
                "RESTORATION_COMMIT_UNCERTAIN",
                "No se pudo resolver el resultado del commit; consulte el mismo UUID.",
                operation_id=restoration_operation_id,
            ) from lookup_error
        if (
            committed is not None
            and committed.status == TareaEliminacionOperacion.Estado.COMMITTED
            and committed.result_code == LOGICAL_RESTORATION_RESULT_CODE
        ):
            _assert_restoration_request(
                committed,
                actor_id=actor.pk,
                empresa_id=empresa_id,
                source_operation_id=deletion_operation_id,
                operation_id=restoration_operation_id,
                motivo=motivo,
                fingerprint=expected_fingerprint,
                storage=storage,
            )
            with storage.atomic() as unit:
                restored_task_ids, _ = _existing_restore_details(
                    unit,
                    restoration=committed,
                    source_operation_id=deletion_operation_id,
                    empresa_id=empresa_id,
                    storage=storage,
                )
            return _deliver_audit(
                storage,
                record=committed,
                task_ids=restored_task_ids,
                replayed=True,
            )
        raise LogicalRestorationError(
            "RESTORATION_COMMIT_UNCERTAIN",
            "No se pudo resolver el resultado del commit; consulte el mismo UUID.",
            operation_id=restoration_operation_id,
        ) from exc
    except TaskMutationScopeError as exc:
        raise LogicalRestorationError(
            "RESTORATION_TASK_MISSING",
            "Una o más tareas del manifiesto no existen o cambiaron de empresa.",
        ) from exc
    except TaskMutationConflict as exc:
        raise LogicalRestorationError(
            "RESTORATION_STATE_CONFLICT",
            "Otra mutación bloqueó el manifiesto; vuelva a generar la previsualización.",
        ) from exc
    except TaskMutationLockError as exc:
        raise LogicalRestorationError(
            "RESTORATION_BACKEND_UNAVAILABLE",
            "No se pudo adquirir el bloqueo transaccional requerido.",
        ) from exc
    except DeletionLedgerConflict as exc:
        raise LogicalRestorationError(
            "RESTORATION_OPERATION_ID_CONFLICT",
            "La operación de restauración ya existe con datos diferentes.",
            operation_id=restoration_operation_id,
        ) from exc
    except DeletionLedgerStateError as exc:
        raise LogicalRestorationError(
            "RESTORATION_STATE_CONFLICT",
            "El ledger o las marcas de eliminación no permiten restaurar.",
            operation_id=restoration_operation_id,
        ) from exc
    except (DeletionLedgerSchemaError, DeletionLedgerBackendError, DatabaseError) as exc:
        raise LogicalRestorationError(
            "RESTORATION_BACKEND_UNAVAILABLE",
            "No se pudo completar la transacción en BASE_TAREAS.",
            operation_id=restoration_operation_id,
        ) from exc
    except DeletionLedgerError as exc:
        raise LogicalRestorationError(
            "RESTORATION_BACKEND_UNAVAILABLE",
            "Falló la transacción operacional de restauración.",
            operation_id=restoration_operation_id,
        ) from exc

    if record is None:
        raise LogicalRestorationError(
            "RESTORATION_STATE_CONFLICT",
            "No se obtuvo una operación de restauración confirmada.",
            operation_id=restoration_operation_id,
        )
    committed_record = record
    return _deliver_audit(
        storage,
        record=committed_record,
        task_ids=restored_task_ids,
        replayed=replayed,
    )


def reconcile_logical_restoration_audit(
    *,
    actor,
    empresa_id: int,
    restoration_operation_id: UUID,
) -> LogicalRestorationResult:
    empresa_id = _positive_id(empresa_id, "empresa_id")
    restoration_operation_id = _operation_uuid(
        restoration_operation_id,
        "restoration_operation_id",
    )
    _authorize(actor, empresa_id)
    storage = _resolve_storage()
    try:
        with storage.atomic() as unit:
            record = unit.get_restoration_operation(restoration_operation_id)
            if record is None or record.empresa_id != empresa_id:
                raise LogicalRestorationError(
                    "RESTORATION_NOT_FOUND",
                    "La operación de restauración no existe en la empresa activa.",
                )
            if (
                record.status != TareaEliminacionOperacion.Estado.COMMITTED
                or record.result_code != LOGICAL_RESTORATION_RESULT_CODE
                or record.reverses_operation_id is None
                or record.file_cleanup_status
                != TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA
            ):
                raise LogicalRestorationError(
                    "RESTORATION_STATE_CONFLICT",
                    "Solo se puede conciliar una restauración lógica confirmada.",
                    operation_id=restoration_operation_id,
                )
            source, task_ids = _validate_source_and_manifests(
                unit,
                source_operation_id=record.reverses_operation_id,
                restoration=record,
                empresa_id=empresa_id,
                storage=storage,
            )
            _assert_restoration_source(
                RestorationOperationInput(
                    actor_id=record.actor_id,
                    empresa_id=record.empresa_id,
                    reverses_operation_id=source.operation_id,
                    fingerprint=record.fingerprint,
                    manifest=task_ids,
                    operation_id=record.operation_id,
                    motivo=record.motivo or "",
                ),
                source,
                backend_type=record.backend_type,
                backend_identity=storage.backend_identity,
                config_version=storage.config_version,
            )
    except LogicalRestorationError:
        raise
    except (DeletionLedgerError, DatabaseError) as exc:
        raise LogicalRestorationError(
            "RESTORATION_BACKEND_UNAVAILABLE",
            "No se pudo consultar el ledger para conciliar la auditoría.",
            operation_id=restoration_operation_id,
        ) from exc

    return _deliver_audit(
        storage,
        record=record,
        task_ids=tuple(sorted(item.object_id for item in task_ids)),
        replayed=True,
    )
