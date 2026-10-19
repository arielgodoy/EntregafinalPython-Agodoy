"""Transactional logical deletion of a task tree."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import json
import re
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connections, transaction
from django.utils import timezone

from access_control.models import Empresa
from access_control.services.permissions import (
    get_valid_users_for_empresa,
    user_has_permission_for_empresa,
)
from auditoria.services import (
    AuditIdempotencyConflict,
    AuditIdempotencyStorageError,
)
from auditoria.services import AuditIdempotencyConflict, AuditIdempotencyStorageError

from ..models import (
    LOGICAL_DELETION_RESULT_CODE,
    Tarea,
    TareaEliminacionOperacion,
    TareaRelacion,
)
from .audit import (
    get_logical_deletion_audit_event,
    logical_deletion_audit_event_matches,
    log_logical_deletion_operation,
)
from .deletion_ledger import (
    DeletionInventoryItem,
    DeletionLedgerCommitUncertain,
    DeletionLedgerError,
    DeletionOperationInput,
    DjangoDeletionLedgerStorage,
    MySQLDeletionLedgerStorage,
    resolve_deletion_ledger_storage,
)
from .task_mutation_locks import (
    TaskMutationConflict,
    TaskMutationLockError,
    TaskMutationScopeError,
    bounded_django_lock_wait,
    bounded_mysql_lock_wait,
    is_task_mutation_conflict,
    lock_mysql_task_company,
    lock_mysql_task_rows,
    lock_orm_task_company,
    lock_orm_task_rows,
)


_BASE_COMPANY_CODE = "00"
_BASE_TAREAS_MYSQL_DATABASE = "tareas"
_TASK_ITEM_LABEL = "tareas.tarea"
_MYSQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class LogicalDeletionError(DeletionLedgerError):
    """Base error for logical task deletion."""


class LogicalDeletionInvalidRequest(LogicalDeletionError):
    pass


class LogicalDeletionAuthorizationError(LogicalDeletionError):
    pass


class LogicalDeletionAuthorizationUnavailable(LogicalDeletionError):
    pass


class LogicalDeletionCompanyError(LogicalDeletionError):
    pass


class LogicalDeletionNotFound(LogicalDeletionError):
    pass


class LogicalDeletionHierarchyError(LogicalDeletionError):
    pass


class LogicalDeletionBlocked(LogicalDeletionError):
    pass


class LogicalDeletionConflict(LogicalDeletionError):
    pass


class LogicalDeletionStorageError(LogicalDeletionError):
    pass


class LogicalDeletionCommitUncertain(LogicalDeletionError):
    def __init__(self, operation_id: UUID):
        self.operation_id = operation_id
        super().__init__(
            "El resultado del commit es incierto; consulte el operation_id "
            "antes de reintentar."
        )


class LogicalDeletionAuditPending(LogicalDeletionError):
    def __init__(self, operation_id: UUID):
        self.operation_id = operation_id
        super().__init__(
            "La eliminación lógica quedó confirmada, pero la auditoría central "
            "requiere conciliación mediante el mismo operation_id."
        )


class LogicalDeletionAuditConflict(LogicalDeletionError):
    def __init__(self, operation_id: UUID):
        self.operation_id = operation_id
        super().__init__(
            "La clave de auditoría central está asociada a un evento incompatible."
        )


@dataclass(frozen=True)
class LogicalDeletionResult:
    operation_id: UUID
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
    eliminada: bool
    eliminada_en: object
    eliminada_por_id: int | None
    eliminacion_operacion_id: UUID | None


def _positive_id(value, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LogicalDeletionInvalidRequest(
            f"{field_name} debe ser un entero positivo."
        )
    return value


def _normalize_operation_id(value) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise LogicalDeletionInvalidRequest(
            "operation_id debe ser un UUID válido."
        ) from exc


def _normalize_reason(value: str) -> str:
    if not isinstance(value, str):
        raise LogicalDeletionInvalidRequest("El motivo debe ser texto.")
    reason = value.strip()
    if not reason:
        raise LogicalDeletionInvalidRequest("El motivo es obligatorio.")
    return reason


def _active_base_company(empresa_id: int):
    try:
        companies = list(
            Empresa.objects.filter(codigo=_BASE_COMPANY_CODE).order_by("pk")[:2]
        )
    except DatabaseError as exc:
        raise LogicalDeletionAuthorizationUnavailable(
            "No se pudo validar la empresa Base 00."
        ) from exc
    if len(companies) != 1:
        raise LogicalDeletionCompanyError(
            "La empresa Base 00 no está configurada de forma única."
        )
    company = companies[0]
    if company.pk != empresa_id:
        raise LogicalDeletionCompanyError(
            "La empresa activa no corresponde a Base 00."
        )
    return company


def _authorize_actor(*, actor, company) -> None:
    if (
        actor is None
        or not getattr(actor, "is_authenticated", False)
        or not getattr(actor, "is_active", False)
        or not isinstance(getattr(actor, "pk", None), int)
        or isinstance(actor.pk, bool)
        or actor.pk < 1
    ):
        raise LogicalDeletionAuthorizationError(
            "Se requiere un usuario autenticado y activo."
        )
    try:
        is_valid_user = get_valid_users_for_empresa(
            company,
            active_only=True,
        ).filter(pk=actor.pk).exists()
        has_permission = user_has_permission_for_empresa(
            user=actor,
            empresa=company,
            vista_nombre="Tareas",
            accion="supervisor",
        )
    except DatabaseError as exc:
        raise LogicalDeletionAuthorizationUnavailable(
            "No se pudo comprobar el permiso VICMEAS requerido."
        ) from exc
    if not is_valid_user or not has_permission:
        raise LogicalDeletionAuthorizationError(
            "Se requiere permiso VICMEAS S explícito para Tareas en Base 00."
        )


def _quote_identifier(value: str) -> str:
    if not _MYSQL_IDENTIFIER.fullmatch(value):
        raise LogicalDeletionStorageError(
            "El esquema operacional contiene un identificador no válido."
        )
    return f"`{value}`"


def _mysql_table(model) -> str:
    return _quote_identifier(model._meta.db_table)


def _mysql_column(model, field_name: str) -> str:
    return _quote_identifier(model._meta.get_field(field_name).column)


def _uuid_value(value) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    if isinstance(value, bytes):
        value = value.decode("ascii")
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise LogicalDeletionStorageError(
            "El esquema operacional contiene metadata UUID no válida."
        ) from exc


class _DjangoTaskAdapter:
    def __init__(self, alias: str, empresa_id: int):
        self.alias = alias
        self.empresa_id = empresa_id
        self.connection = connections[alias]

    def lock_company(self) -> None:
        lock_orm_task_company(self.alias, self.empresa_id)

    def lock_tasks(self, task_ids: tuple[int, ...]) -> tuple[_TaskState, ...]:
        try:
            rows = lock_orm_task_rows(
                self.alias,
                self.empresa_id,
                task_ids,
                require_row_locks=self.connection.vendor != "sqlite",
                include_deleted=True,
            )
        except TaskMutationScopeError as exc:
            raise LogicalDeletionHierarchyError(
                "Una tarea del árbol no existe en la empresa activa."
            ) from exc
        return tuple(
            _TaskState(
                task_id=row.pk,
                empresa_id=row.empresa_id,
                correlativo=row.correlativo,
                eliminada=row.eliminada,
                eliminada_en=row.eliminada_en,
                eliminada_por_id=row.eliminada_por_id,
                eliminacion_operacion_id=row.eliminacion_operacion_id,
            )
            for row in rows
        )

    def children(self, parent_ids: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
        if not parent_ids:
            return ()
        query = TareaRelacion.objects.using(self.alias).filter(
            padre_id__in=parent_ids
        )
        if self.connection.features.has_select_for_update:
            query = query.select_for_update()
        return tuple(
            query.order_by("padre_id", "hija_id").values_list(
                "padre_id",
                "hija_id",
            )
        )

    def parents(self, child_ids: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
        if not child_ids:
            return ()
        query = TareaRelacion.objects.using(self.alias).filter(
            hija_id__in=child_ids
        )
        if self.connection.features.has_select_for_update:
            query = query.select_for_update()
        return tuple(
            query.order_by("hija_id", "padre_id").values_list(
                "hija_id",
                "padre_id",
            )
        )

    def has_external_origin_references(self, task_ids: tuple[int, ...]) -> bool:
        return (
            Tarea.all_objects.using(self.alias)
            .filter(tarea_origen_id__in=task_ids)
            .exclude(pk__in=task_ids)
            .exists()
        )

    def mark_tasks(
        self,
        task_ids: tuple[int, ...],
        *,
        actor_id: int,
        operation_id: UUID,
        deleted_at,
    ) -> int:
        if not task_ids:
            return 0

        quote = self.connection.ops.quote_name
        table = quote(Tarea._meta.db_table)
        pk_field = Tarea._meta.pk
        company_field = Tarea._meta.get_field("empresa")
        deleted_field = Tarea._meta.get_field("eliminada")
        deleted_at_field = Tarea._meta.get_field("eliminada_en")
        deleted_by_field = Tarea._meta.get_field("eliminada_por")
        operation_field = Tarea._meta.get_field("eliminacion_operacion_id")
        placeholders = ", ".join("%s" for _ in task_ids)
        sql = (
            f"UPDATE {table} SET "
            f"{quote(deleted_field.column)} = %s, "
            f"{quote(deleted_at_field.column)} = %s, "
            f"{quote(deleted_by_field.column)} = %s, "
            f"{quote(operation_field.column)} = %s "
            f"WHERE {quote(company_field.column)} = %s "
            f"AND {quote(pk_field.column)} IN ({placeholders}) "
            f"AND {quote(deleted_field.column)} = %s"
        )
        params = (
            deleted_field.get_db_prep_save(True, self.connection),
            deleted_at_field.get_db_prep_save(deleted_at, self.connection),
            deleted_by_field.target_field.get_db_prep_save(actor_id, self.connection),
            operation_field.get_db_prep_save(operation_id, self.connection),
            company_field.target_field.get_db_prep_save(
                self.empresa_id,
                self.connection,
            ),
            *(
                pk_field.get_db_prep_save(task_id, self.connection)
                for task_id in task_ids
            ),
            deleted_field.get_db_prep_save(False, self.connection),
        )
        # L2 is the sole authorized writer for these fields; public queryset
        # bulk-write APIs reject them.
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.rowcount

    def verified_task_ids(
        self,
        task_ids: tuple[int, ...],
        *,
        actor_id: int,
        operation_id: UUID,
    ) -> tuple[int, ...]:
        return tuple(
            Tarea.all_objects.using(self.alias)
            .filter(
                empresa_id=self.empresa_id,
                pk__in=task_ids,
                eliminada=True,
                eliminada_en__isnull=False,
                eliminada_por_id=actor_id,
                eliminacion_operacion_id=operation_id,
            )
            .order_by("pk")
            .values_list("pk", flat=True)
        )


class _MySQLTaskAdapter:
    def __init__(self, connection, empresa_id: int):
        self.connection = connection
        self.empresa_id = empresa_id
        self.task_table = _mysql_table(Tarea)
        self.task_id = _mysql_column(Tarea, "id")
        self.task_empresa = _mysql_column(Tarea, "empresa")
        self.task_correlativo = _mysql_column(Tarea, "correlativo")
        self.task_deleted = _mysql_column(Tarea, "eliminada")
        self.task_deleted_at = _mysql_column(Tarea, "eliminada_en")
        self.task_deleted_by = _mysql_column(Tarea, "eliminada_por")
        self.task_operation = _mysql_column(Tarea, "eliminacion_operacion_id")
        self.relation_table = _mysql_table(TareaRelacion)
        self.relation_parent = _mysql_column(TareaRelacion, "padre")
        self.relation_child = _mysql_column(TareaRelacion, "hija")
        self.origin_task = _mysql_column(Tarea, "tarea_origen")

    def _fetchall(self, sql: str, params=()):
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params)
            return tuple(cursor.fetchall())
        finally:
            cursor.close()

    def lock_company(self) -> None:
        lock_mysql_task_company(self.connection, self.empresa_id)

    def lock_tasks(self, task_ids: tuple[int, ...]) -> tuple[_TaskState, ...]:
        try:
            locked_ids = lock_mysql_task_rows(
                self.connection,
                self.empresa_id,
                task_ids,
                include_deleted=True,
            )
        except TaskMutationScopeError as exc:
            raise LogicalDeletionHierarchyError(
                "Una tarea del árbol no existe en la empresa activa."
            ) from exc
        if not locked_ids:
            return ()
        placeholders = ", ".join("%s" for _ in locked_ids)
        rows = self._fetchall(
            f"SELECT {self.task_id}, {self.task_empresa}, {self.task_correlativo}, "
            f"{self.task_deleted}, {self.task_deleted_at}, {self.task_deleted_by}, "
            f"{self.task_operation} FROM {self.task_table} "
            f"WHERE {self.task_id} IN ({placeholders}) "
            f"ORDER BY {self.task_id} FOR UPDATE",
            locked_ids,
        )
        return tuple(
            _TaskState(
                task_id=int(row[0]),
                empresa_id=int(row[1]),
                correlativo=str(row[2]),
                eliminada=bool(row[3]),
                eliminada_en=row[4],
                eliminada_por_id=int(row[5]) if row[5] is not None else None,
                eliminacion_operacion_id=_uuid_value(row[6]),
            )
            for row in rows
        )

    def children(self, parent_ids: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
        if not parent_ids:
            return ()
        placeholders = ", ".join("%s" for _ in parent_ids)
        rows = self._fetchall(
            f"SELECT {self.relation_parent}, {self.relation_child} "
            f"FROM {self.relation_table} "
            f"WHERE {self.relation_parent} IN ({placeholders}) "
            f"ORDER BY {self.relation_parent}, {self.relation_child} FOR UPDATE",
            parent_ids,
        )
        return tuple((int(parent_id), int(child_id)) for parent_id, child_id in rows)

    def parents(self, child_ids: tuple[int, ...]) -> tuple[tuple[int, int], ...]:
        if not child_ids:
            return ()
        placeholders = ", ".join("%s" for _ in child_ids)
        rows = self._fetchall(
            f"SELECT {self.relation_child}, {self.relation_parent} "
            f"FROM {self.relation_table} "
            f"WHERE {self.relation_child} IN ({placeholders}) "
            f"ORDER BY {self.relation_child}, {self.relation_parent} FOR UPDATE",
            child_ids,
        )
        return tuple((int(child_id), int(parent_id)) for child_id, parent_id in rows)

    def has_external_origin_references(self, task_ids: tuple[int, ...]) -> bool:
        placeholders = ", ".join("%s" for _ in task_ids)
        sql = (
            f"SELECT 1 FROM {self.task_table} "
            f"WHERE {self.origin_task} IN ({placeholders}) "
            f"AND {self.task_id} NOT IN ({placeholders}) LIMIT 1"
        )
        return bool(self._fetchall(sql, (*task_ids, *task_ids)))

    def mark_tasks(
        self,
        task_ids: tuple[int, ...],
        *,
        actor_id: int,
        operation_id: UUID,
        deleted_at,
    ) -> int:
        placeholders = ", ".join("%s" for _ in task_ids)
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                f"UPDATE {self.task_table} SET {self.task_deleted} = %s, "
                f"{self.task_deleted_at} = %s, {self.task_deleted_by} = %s, "
                f"{self.task_operation} = %s "
                f"WHERE {self.task_empresa} = %s "
                f"AND {self.task_id} IN ({placeholders}) "
                f"AND {self.task_deleted} = %s",
                (
                    True,
                    deleted_at,
                    actor_id,
                    operation_id.hex,
                    self.empresa_id,
                    *task_ids,
                    False,
                ),
            )
            return cursor.rowcount
        finally:
            cursor.close()

    def verified_task_ids(
        self,
        task_ids: tuple[int, ...],
        *,
        actor_id: int,
        operation_id: UUID,
    ) -> tuple[int, ...]:
        placeholders = ", ".join("%s" for _ in task_ids)
        rows = self._fetchall(
            f"SELECT {self.task_id} FROM {self.task_table} "
            f"WHERE {self.task_empresa} = %s "
            f"AND {self.task_id} IN ({placeholders}) "
            f"AND {self.task_deleted} = %s "
            f"AND {self.task_deleted_at} IS NOT NULL "
            f"AND {self.task_deleted_by} = %s "
            f"AND {self.task_operation} = %s "
            f"ORDER BY {self.task_id}",
            (
                self.empresa_id,
                *task_ids,
                True,
                actor_id,
                operation_id.hex,
            ),
        )
        return tuple(int(row[0]) for row in rows)


def _task_adapter(storage, unit, empresa_id: int):
    if isinstance(storage, DjangoDeletionLedgerStorage):
        connection = connections[storage.alias]
        if connection.vendor == "mysql":
            return _MySQLTaskAdapter(connection, empresa_id)
        return _DjangoTaskAdapter(storage.alias, empresa_id)
    if isinstance(storage, MySQLDeletionLedgerStorage):
        return _MySQLTaskAdapter(unit.connection, empresa_id)
    raise LogicalDeletionStorageError(
        "El storage operacional de Tareas no está soportado."
    )


@contextmanager
def _bounded_lock_wait(unit, adapter):
    if isinstance(adapter, _DjangoTaskAdapter):
        with bounded_django_lock_wait(adapter.alias):
            yield
        return
    connection = unit.connection
    with bounded_mysql_lock_wait(connection):
        alias = getattr(connection, "alias", None)
        if isinstance(alias, str) and alias:
            with transaction.atomic(using=alias):
                yield
        else:
            yield


def _collect_locked_tree(
    adapter,
    *,
    root_task_id: int,
    operation_id: UUID,
    allow_committed_marks: bool,
) -> tuple[tuple[int, ...], dict[int, _TaskState]]:
    try:
        root_rows = adapter.lock_tasks((root_task_id,))
    except LogicalDeletionHierarchyError as exc:
        raise LogicalDeletionNotFound(
            "La tarea raíz no existe en la empresa activa."
        ) from exc
    if len(root_rows) != 1:
        raise LogicalDeletionNotFound(
            "La tarea raíz no existe en la empresa activa."
        )
    states = {root_task_id: root_rows[0]}
    parent_edges = adapter.parents((root_task_id,))
    if parent_edges:
        raise LogicalDeletionHierarchyError(
            "La tarea seleccionada no es una raíz jerárquica."
        )

    discovered = {root_task_id}
    expected_parent_by_child = {}
    frontier = (root_task_id,)
    while frontier:
        edges = adapter.children(frontier)
        next_ids = []
        next_seen = set()
        for parent_id, child_id in edges:
            if parent_id not in discovered:
                raise LogicalDeletionHierarchyError(
                    "La jerarquía cambió durante su recorrido."
                )
            if child_id in discovered or child_id in next_seen:
                raise LogicalDeletionHierarchyError(
                    "La jerarquía contiene un ciclo o relaciones duplicadas."
                )
            expected_parent_by_child[child_id] = parent_id
            next_seen.add(child_id)
            next_ids.append(child_id)

        if not next_ids:
            frontier = ()
            continue
        try:
            child_rows = adapter.lock_tasks(tuple(sorted(next_seen)))
        except LogicalDeletionHierarchyError as exc:
            raise LogicalDeletionHierarchyError(
                "La jerarquía contiene una tarea inexistente o de otra empresa."
            ) from exc
        if {row.task_id for row in child_rows} != next_seen:
            raise LogicalDeletionHierarchyError(
                "No se pudo bloquear el árbol completo de tareas."
            )
        for row in child_rows:
            if row.empresa_id != adapter.empresa_id:
                raise LogicalDeletionHierarchyError(
                    "La jerarquía contiene una tarea de otra empresa."
                )
            if row.eliminada:
                if (
                    not allow_committed_marks
                    or row.eliminacion_operacion_id != operation_id
                    or row.eliminada_por_id is None
                    or row.eliminada_en is None
                ):
                    raise LogicalDeletionConflict(
                        "Una tarea del árbol ya fue eliminada por otra operación."
                    )
            elif (
                row.eliminada_en is not None
                or row.eliminada_por_id is not None
                or row.eliminacion_operacion_id is not None
            ):
                raise LogicalDeletionHierarchyError(
                    "La tarea contiene metadata de eliminación inconsistente."
                )
            states[row.task_id] = row
            discovered.add(row.task_id)
        frontier = tuple(sorted(next_seen))

    current_edges = adapter.children(tuple(sorted(discovered)))
    expected_edges = tuple(
        sorted(
            (parent_id, child_id)
            for child_id, parent_id in expected_parent_by_child.items()
        )
    )
    if tuple(sorted(current_edges)) != expected_edges:
        raise LogicalDeletionConflict(
            "La jerarquía cambió durante la operación."
        )
    current_parents = adapter.parents(tuple(sorted(discovered)))
    expected_parents = tuple(
        sorted(
            (child_id, parent_id)
            for child_id, parent_id in expected_parent_by_child.items()
        )
    )
    if tuple(sorted(current_parents)) != expected_parents:
        raise LogicalDeletionHierarchyError(
            "La jerarquía contiene enlaces de padre inconsistentes."
        )
    return tuple(sorted(discovered)), states


def _operation_matches_request(
    record,
    *,
    operation_id: UUID,
    actor_id: int,
    empresa_id: int,
    root_task_id: int,
    root_correlativo: str,
    motivo: str,
    backend_type: str,
    backend_identity: str,
    backend_config_version: str,
) -> bool:
    return (
        record.operation_id == operation_id
        and record.actor_id == actor_id
        and record.empresa_id == empresa_id
        and record.root_task_id == root_task_id
        and record.root_correlativo == root_correlativo
        and record.motivo == motivo
        and record.backend_type == backend_type
        and record.backend_identity == backend_identity
        and record.backend_config_version == backend_config_version
        and record.result_code == LOGICAL_DELETION_RESULT_CODE
        and record.status == TareaEliminacionOperacion.Estado.COMMITTED
        and record.file_cleanup_status
        == TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA
    )


def _fingerprint(
    *,
    actor_id: int,
    empresa_id: int,
    root_task_id: int,
    root_correlativo: str,
    task_ids: tuple[int, ...],
    motivo: str,
    backend_identity: str,
    backend_config_version: str,
) -> str:
    payload = {
        "actor_id": actor_id,
        "empresa_id": empresa_id,
        "root_task_id": root_task_id,
        "root_correlativo": root_correlativo,
        "task_ids": list(task_ids),
        "motivo": motivo,
        "backend_identity": backend_identity,
        "backend_config_version": backend_config_version,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _result_from_record(
    record,
    *,
    operation_id: UUID,
    task_ids: tuple[int, ...],
    backend_type: str,
    replayed: bool,
) -> LogicalDeletionResult:
    return LogicalDeletionResult(
        operation_id=operation_id,
        root_task_id=record.root_task_id,
        task_ids=task_ids,
        result_code=record.result_code,
        status=record.status,
        backend_type=backend_type,
        audit_status=record.audit_status,
        replayed=replayed,
    )


def _perform_in_transaction(
    storage,
    unit,
    *,
    actor_id: int,
    empresa_id: int,
    root_task_id: int,
    motivo: str,
    operation_id: UUID,
):
    backend_type = (
        "DJANGO"
        if isinstance(storage, DjangoDeletionLedgerStorage)
        else "MYSQL_CONFIG"
    )
    adapter = _task_adapter(storage, unit, empresa_id)
    with _bounded_lock_wait(unit, adapter):
        adapter.lock_company()
        try:
            root_rows = adapter.lock_tasks((root_task_id,))
        except LogicalDeletionHierarchyError as exc:
            raise LogicalDeletionNotFound(
                "La tarea raíz no existe en la empresa activa."
            ) from exc
        if len(root_rows) != 1:
            raise LogicalDeletionNotFound(
                "La tarea raíz no existe en la empresa activa."
            )
        root = root_rows[0]

        existing = unit.get_operation(operation_id)
        if existing is not None:
            if not _operation_matches_request(
                existing,
                operation_id=operation_id,
                actor_id=actor_id,
                empresa_id=empresa_id,
                root_task_id=root_task_id,
                root_correlativo=root.correlativo,
                motivo=motivo,
                backend_type=backend_type,
                backend_identity=storage.backend_identity,
                backend_config_version=storage.config_version,
            ):
                raise LogicalDeletionConflict(
                    "operation_id ya fue utilizado con datos diferentes."
                )
            task_ids, states = _collect_locked_tree(
                adapter,
                root_task_id=root_task_id,
                operation_id=operation_id,
                allow_committed_marks=True,
            )
            if any(
                not state.eliminada
                or state.eliminada_por_id != actor_id
                or state.eliminacion_operacion_id != operation_id
                or state.eliminada_en is None
                for state in states.values()
            ):
                raise LogicalDeletionConflict(
                    "Los metadatos confirmados no coinciden con operation_id."
                )
            manifest = unit.get_manifest(operation_id)
            expected_manifest = tuple(
                sorted(
                    DeletionInventoryItem(_TASK_ITEM_LABEL, task_id)
                    for task_id in task_ids
                )
            )
            if manifest != expected_manifest:
                raise LogicalDeletionConflict(
                    "El manifiesto persistido no coincide con la jerarquía actual."
                )
            if existing.dependency_summary.get(_TASK_ITEM_LABEL) != len(task_ids):
                raise LogicalDeletionConflict(
                    "El resumen persistido no coincide con la jerarquía actual."
                )
            if existing.audit_status not in {
                TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
                TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
                TareaEliminacionOperacion.EstadoAuditoria.ERROR,
            }:
                raise LogicalDeletionConflict(
                    "El estado de auditoría persistido no es válido."
                )
            if existing.audit_status == TareaEliminacionOperacion.EstadoAuditoria.ERROR:
                raise LogicalDeletionAuditPending(operation_id)
            result = _result_from_record(
                existing,
                operation_id=operation_id,
                task_ids=task_ids,
                backend_type=backend_type,
                replayed=True,
            )
            return result, existing, False

        previous_root_operation = unit.get_root_operation(
            empresa_id,
            root_task_id,
        )
        if previous_root_operation is not None:
            raise LogicalDeletionConflict(
                "La raíz ya tiene una operación de eliminación registrada."
            )

        task_ids, states = _collect_locked_tree(
            adapter,
            root_task_id=root_task_id,
            operation_id=operation_id,
            allow_committed_marks=False,
        )
        if any(state.eliminada for state in states.values()):
            raise LogicalDeletionConflict(
                "El árbol contiene tareas ya eliminadas."
            )
        if adapter.has_external_origin_references(task_ids):
            raise LogicalDeletionBlocked(
                "Otra tarea referencia el árbol como origen; la operación se bloqueó."
            )

        root_correlativo = states[root_task_id].correlativo
        summary = {_TASK_ITEM_LABEL: len(task_ids)}
        fingerprint = _fingerprint(
            actor_id=actor_id,
            empresa_id=empresa_id,
            root_task_id=root_task_id,
            root_correlativo=root_correlativo,
            task_ids=task_ids,
            motivo=motivo,
            backend_identity=storage.backend_identity,
            backend_config_version=storage.config_version,
        )
        operation = DeletionOperationInput(
            actor_id=actor_id,
            empresa_id=empresa_id,
            root_task_id=root_task_id,
            root_correlativo=root_correlativo,
            fingerprint=fingerprint,
            dependency_summary=summary,
            operation_id=operation_id,
            motivo=motivo,
        )
        unit.create_pending(operation)
        unit.save_manifest(
            operation_id,
            tuple(
                DeletionInventoryItem(_TASK_ITEM_LABEL, task_id)
                for task_id in task_ids
            ),
        )
        deleted_at = timezone.now()
        affected_count = adapter.mark_tasks(
            task_ids,
            actor_id=actor_id,
            operation_id=operation_id,
            deleted_at=deleted_at,
        )
        if affected_count != len(task_ids):
            raise LogicalDeletionConflict(
                "No se marcaron todas las tareas del árbol."
            )
        verified_ids = adapter.verified_task_ids(
            task_ids,
            actor_id=actor_id,
            operation_id=operation_id,
        )
        if verified_ids != task_ids:
            raise LogicalDeletionConflict(
                "La verificación posterior no confirmó todas las marcas."
            )
        committed = unit.mark_logically_deleted(operation_id)
        result = _result_from_record(
            committed,
            operation_id=operation_id,
            task_ids=task_ids,
            backend_type=backend_type,
            replayed=False,
        )
        return result, committed, True


def _record_audit_error(storage, operation_id: UUID, error_code: str) -> None:
    try:
        with storage.atomic() as unit:
            unit.record_audit_result(
                operation_id,
                confirmed=False,
                error_code=error_code,
            )
    except Exception as exc:
        raise LogicalDeletionAuditPending(operation_id) from exc


def _confirm_audit_event(storage, operation_id: UUID, event_id: int):
    try:
        with storage.atomic() as unit:
            return unit.record_audit_result(
                operation_id,
                confirmed=True,
                event_id=event_id,
            )
    except Exception as exc:
        raise LogicalDeletionAuditPending(operation_id) from exc


def _deliver_audit(
    storage,
    *,
    actor,
    empresa_id: int,
    record,
    allow_inactive_actor: bool = False,
    allow_missing_actor: bool = False,
):
    operation_id = record.operation_id
    try:
        event = log_logical_deletion_operation(
            actor=actor,
            actor_id=record.actor_id,
            allow_inactive_actor=allow_inactive_actor,
            allow_missing_actor=allow_missing_actor,
            empresa_id=empresa_id,
            task_id=record.root_task_id,
            operation_id=operation_id.hex,
            fingerprint=record.fingerprint,
            backend_type=record.backend_type,
            dependency_summary=record.dependency_summary,
        )
    except AuditIdempotencyConflict as exc:
        if allow_missing_actor:
            try:
                existing_event = get_logical_deletion_audit_event(
                    operation_id=operation_id.hex
                )
            except AuditIdempotencyStorageError as lookup_exc:
                _record_audit_error(
                    storage,
                    operation_id,
                    "AUDIT_LOOKUP_FAILED",
                )
                raise LogicalDeletionAuditPending(operation_id) from lookup_exc
            if existing_event is not None and _audit_event_matches_record(
                existing_event,
                record=record,
                empresa_id=empresa_id,
            ):
                event = existing_event
            else:
                _record_audit_error(
                    storage,
                    operation_id,
                    "AUDIT_PAYLOAD_CONFLICT",
                )
                raise LogicalDeletionAuditConflict(operation_id) from exc
        else:
            _record_audit_error(
                storage,
                operation_id,
                "AUDIT_PAYLOAD_CONFLICT",
            )
            raise LogicalDeletionAuditConflict(operation_id) from exc

    except Exception as exc:
        _record_audit_error(
            storage,
            operation_id,
            "AUDIT_DELIVERY_FAILED",
        )
        raise LogicalDeletionAuditPending(operation_id) from exc

    event_id = getattr(event, "pk", None)
    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id < 1:
        _record_audit_error(storage, operation_id, "AUDIT_DELIVERY_FAILED")
        raise LogicalDeletionAuditPending(operation_id)

    return _confirm_audit_event(storage, operation_id, event_id)


def _logical_audit_manifest(unit, operation_id: UUID, record):
    manifest = unit.get_manifest(operation_id)
    if not manifest or any(item.model_label != _TASK_ITEM_LABEL for item in manifest):
        raise LogicalDeletionConflict(
            "El manifiesto de auditoría no contiene únicamente Tareas."
        )
    task_ids = tuple(sorted(item.object_id for item in manifest))
    if (
        record.root_task_id not in task_ids
        or record.dependency_summary.get(_TASK_ITEM_LABEL) != len(task_ids)
    ):
        raise LogicalDeletionConflict(
            "El manifiesto de auditoría no coincide con la operación confirmada."
        )
    return task_ids


def _audit_event_matches_record(event, *, record, empresa_id: int) -> bool:
    return logical_deletion_audit_event_matches(
        event=event,
        actor_id=record.actor_id,
        empresa_id=empresa_id,
        task_id=record.root_task_id,
        operation_id=record.operation_id.hex,
        fingerprint=record.fingerprint,
        backend_type=record.backend_type,
        dependency_summary=record.dependency_summary,
    )


def reconcile_logical_deletion_audit(
    *,
    actor,
    empresa_id: int,
    operation_id: UUID,
) -> LogicalDeletionResult:
    """Reconcile the central audit event for an already committed logical deletion."""
    empresa_id = _positive_id(empresa_id, "empresa_id")
    operation_id = _normalize_operation_id(operation_id)
    company = _active_base_company(empresa_id)
    _authorize_actor(actor=actor, company=company)

    try:
        storage = resolve_deletion_ledger_storage()
    except (DeletionLedgerError, DatabaseError) as exc:
        raise LogicalDeletionStorageError(
            "No se pudo resolver el backend operacional de Tareas."
        ) from exc
    if (
        isinstance(storage, MySQLDeletionLedgerStorage)
        and storage.database_name != _BASE_TAREAS_MYSQL_DATABASE
    ):
        raise LogicalDeletionStorageError(
            "La eliminación lógica solo está habilitada sobre la base operacional autorizada."
        )

    try:
        with storage.atomic() as unit:
            record = unit.get_operation(operation_id)
            if record is None or record.empresa_id != empresa_id:
                raise LogicalDeletionNotFound(
                    "La operación no existe en la empresa activa."
                )
            if (
                record.status != TareaEliminacionOperacion.Estado.COMMITTED
                or record.result_code != LOGICAL_DELETION_RESULT_CODE
                or record.file_cleanup_status
                != TareaEliminacionOperacion.EstadoArchivos.NO_REQUERIDA
            ):
                raise LogicalDeletionConflict(
                    "Solo se puede reconciliar una eliminación lógica confirmada."
                )
            task_ids = _logical_audit_manifest(unit, operation_id, record)
    except LogicalDeletionError:
        raise
    except DeletionLedgerError as exc:
        raise LogicalDeletionStorageError(
            "No se pudo leer el ledger para reconciliar la auditoría."
        ) from exc
    except DatabaseError as exc:
        raise LogicalDeletionStorageError(
            "No se pudo consultar el estado de auditoría operacional."
        ) from exc

    audit_status = record.audit_status
    if audit_status not in {
        TareaEliminacionOperacion.EstadoAuditoria.PENDIENTE,
        TareaEliminacionOperacion.EstadoAuditoria.ERROR,
        TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA,
    }:
        raise LogicalDeletionAuditConflict(operation_id)

    try:
        existing_event = get_logical_deletion_audit_event(
            operation_id=operation_id.hex
        )
    except AuditIdempotencyStorageError as exc:
        if audit_status != TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA:
            _record_audit_error(
                storage,
                operation_id,
                "AUDIT_LOOKUP_FAILED",
            )
        raise LogicalDeletionAuditPending(operation_id) from exc

    if audit_status == TareaEliminacionOperacion.EstadoAuditoria.CONFIRMADA:
        if (
            existing_event is None
            or existing_event.pk != record.audit_event_id
            or not _audit_event_matches_record(
                existing_event,
                record=record,
                empresa_id=empresa_id,
            )
        ):
            raise LogicalDeletionAuditConflict(operation_id)
        return _result_from_record(
            record,
            operation_id=operation_id,
            task_ids=task_ids,
            backend_type=record.backend_type,
            replayed=True,
        )

    if existing_event is not None:
        if not _audit_event_matches_record(
            existing_event,
            record=record,
            empresa_id=empresa_id,
        ):
            _record_audit_error(
                storage,
                operation_id,
                "AUDIT_PAYLOAD_CONFLICT",
            )
            raise LogicalDeletionAuditConflict(operation_id)
        confirmed_record = _confirm_audit_event(
            storage,
            operation_id,
            existing_event.pk,
        )
        return _result_from_record(
            confirmed_record,
            operation_id=operation_id,
            task_ids=task_ids,
            backend_type=record.backend_type,
            replayed=True,
        )

    try:
        source_actor = get_user_model()._default_manager.filter(
            pk=record.actor_id
        ).first()
    except DatabaseError as exc:
        _record_audit_error(storage, operation_id, "AUDIT_ACTOR_LOOKUP_FAILED")
        raise LogicalDeletionAuditPending(operation_id) from exc
    try:
        confirmed_record = _deliver_audit(
            storage,
            actor=source_actor,
            empresa_id=empresa_id,
            record=record,
            allow_inactive_actor=True,
            allow_missing_actor=source_actor is None,
        )
    except LogicalDeletionAuditConflict:
        try:
            raced_event = get_logical_deletion_audit_event(
                operation_id=operation_id.hex
            )
        except AuditIdempotencyStorageError as exc:
            _record_audit_error(storage, operation_id, "AUDIT_LOOKUP_FAILED")
            raise LogicalDeletionAuditPending(operation_id) from exc
        if raced_event is None or not _audit_event_matches_record(
            raced_event,
            record=record,
            empresa_id=empresa_id,
        ):
            raise
        confirmed_record = _confirm_audit_event(
            storage,
            operation_id,
            raced_event.pk,
        )
    return _result_from_record(
        confirmed_record,
        operation_id=operation_id,
        task_ids=task_ids,
        backend_type=record.backend_type,
        replayed=True,
    )


def logically_delete_task_tree(
    *,
    actor,
    empresa_id: int,
    root_task_id: int,
    motivo: str,
    operation_id: UUID,
) -> LogicalDeletionResult:
    """Mark one root and its complete same-company hierarchy in one transaction."""
    empresa_id = _positive_id(empresa_id, "empresa_id")
    root_task_id = _positive_id(root_task_id, "root_task_id")
    operation_id = _normalize_operation_id(operation_id)
    motivo = _normalize_reason(motivo)
    company = _active_base_company(empresa_id)
    _authorize_actor(actor=actor, company=company)

    try:
        storage = resolve_deletion_ledger_storage()
    except (DeletionLedgerError, DatabaseError) as exc:
        raise LogicalDeletionStorageError(
            "No se pudo resolver el backend operacional de Tareas."
        ) from exc
    if (
        isinstance(storage, MySQLDeletionLedgerStorage)
        and storage.database_name != _BASE_TAREAS_MYSQL_DATABASE
    ):
        raise LogicalDeletionStorageError(
            "La eliminación lógica solo está habilitada sobre la base operacional autorizada."
        )

    try:
        with storage.atomic() as unit:
            result, record, newly_committed = _perform_in_transaction(
                storage,
                unit,
                actor_id=actor.pk,
                empresa_id=empresa_id,
                root_task_id=root_task_id,
                motivo=motivo,
                operation_id=operation_id,
            )
    except DeletionLedgerCommitUncertain as exc:
        try:
            reconciled = storage.get_operation(operation_id)
        except DeletionLedgerError as reconciliation_error:
            raise LogicalDeletionCommitUncertain(operation_id) from reconciliation_error
        if (
            reconciled is not None
            and reconciled.status == TareaEliminacionOperacion.Estado.COMMITTED
            and reconciled.result_code == LOGICAL_DELETION_RESULT_CODE
        ):
            raise LogicalDeletionAuditPending(operation_id) from exc
        raise LogicalDeletionCommitUncertain(operation_id) from exc
    except LogicalDeletionError:
        raise
    except TaskMutationConflict as exc:
        raise LogicalDeletionConflict(
            "Otra operación bloqueó el árbol; verifique operation_id antes "
            "de reintentar."
        ) from exc
    except TaskMutationLockError as exc:
        if is_task_mutation_conflict(exc):
            raise LogicalDeletionConflict(
                "Otra operación bloqueó el árbol; verifique operation_id antes "
                "de reintentar."
            ) from exc
        raise LogicalDeletionStorageError(
            "No se pudo completar el bloqueo transaccional del árbol."
        ) from exc
    except DeletionLedgerError as exc:
        if is_task_mutation_conflict(exc):
            raise LogicalDeletionConflict(
                "Otra operación bloqueó el árbol; verifique operation_id antes "
                "de reintentar."
            ) from exc
        raise LogicalDeletionStorageError(
            "No se pudo completar la transacción operacional de eliminación lógica."
        ) from exc
    except DatabaseError as exc:
        if is_task_mutation_conflict(exc):
            raise LogicalDeletionConflict(
                "Otra operación bloqueó el árbol; verifique operation_id antes "
                "de reintentar."
            ) from exc
        raise LogicalDeletionStorageError(
            "Falló la transacción operacional; verifique operation_id antes "
            "de reintentar."
        ) from exc

    if not newly_committed:
        return result
    confirmed_record = _deliver_audit(
        storage,
        actor=actor,
        empresa_id=empresa_id,
        record=record,
    )
    return replace(result, audit_status=confirmed_record.audit_status)
