"""Database-backed locks shared by task mutations and permanent deletion."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Mapping
from typing import Iterator

from django.core.exceptions import ValidationError
from django.db import connections, transaction

from ..models import CorrelativoEmpresa, Tarea


TASK_LOCK_WAIT_SECONDS = 5


class TaskMutationLockError(RuntimeError):
    """Base error for the task mutation lock protocol."""


class TaskMutationLockUnsupported(TaskMutationLockError):
    """The operational backend cannot provide the requested row locks."""


class TaskMutationScopeError(TaskMutationLockError):
    """Requested task rows are absent or belong to another company."""


class TaskMutationConflict(ValidationError):
    """A concurrent mutation prevented the operation from being completed."""


def _normalize_task_ids(task_ids):
    if task_ids is None:
        return None
    ids = tuple(sorted(set(task_ids)))
    if any(
        isinstance(task_id, bool)
        or not isinstance(task_id, int)
        or task_id < 1
        for task_id in ids
    ):
        raise ValueError("task_ids debe contener identificadores positivos.")
    return ids


def _normalize_task_groups(task_groups):
    items = task_groups.items() if isinstance(task_groups, Mapping) else task_groups
    normalized = []
    seen = set()
    for empresa_id, task_ids in items:
        if (
            isinstance(empresa_id, bool)
            or not isinstance(empresa_id, int)
            or empresa_id < 1
        ):
            raise ValueError("empresa_id debe ser un entero positivo.")
        ids = _normalize_task_ids(task_ids)
        if not ids:
            continue
        if seen.intersection(ids):
            raise ValueError("task_ids no puede repetirse entre empresas.")
        seen.update(ids)
        normalized.append((empresa_id, ids))
    return tuple(sorted(normalized, key=lambda item: (item[0], item[1])))


def lock_orm_task_rows(
    alias: str,
    empresa_id: int,
    task_ids=None,
    *,
    require_row_locks: bool = False,
) -> tuple[Tarea, ...]:
    """Lock task rows in primary-key order inside the caller's transaction."""
    connection = connections[alias]
    if not connection.features.supports_transactions:
        raise TaskMutationLockUnsupported(
            "BASE_TAREAS no soporta transacciones."
        )
    if not connection.in_atomic_block:
        raise TaskMutationLockError(
            "Los locks de tareas requieren una transacción operacional activa."
        )
    supports_row_locks = connection.features.has_select_for_update
    if require_row_locks and not supports_row_locks:
        raise TaskMutationLockUnsupported(
            "El backend no ofrece SELECT FOR UPDATE para la operación requerida."
        )

    normalized_ids = _normalize_task_ids(task_ids)
    lock_orm_task_company(alias, empresa_id)
    if normalized_ids == ():
        return ()
    queryset = Tarea.objects.using(alias).filter(empresa_id=empresa_id)
    if normalized_ids is not None:
        queryset = queryset.filter(pk__in=normalized_ids)
    if supports_row_locks:
        queryset = queryset.select_for_update()
    rows = tuple(queryset.order_by("pk"))
    if normalized_ids is not None and {
        row.pk for row in rows
    } != set(normalized_ids):
        raise TaskMutationScopeError(
            "Una o más tareas no existen en la empresa operacional indicada."
        )
    return rows


def lock_mysql_task_rows(connection, empresa_id: int, task_ids=None) -> tuple[int, ...]:
    """Lock MySQL task rows in deterministic order on the supplied connection."""
    alias = getattr(connection, "alias", None)
    if isinstance(alias, str) and alias and not connections[alias].in_atomic_block:
        raise TaskMutationLockError(
            "Los locks de tareas requieren una transacción operacional activa."
        )
    lock_mysql_task_company(connection, empresa_id)
    normalized_ids = _normalize_task_ids(task_ids)
    if normalized_ids == ():
        return ()
    table = f"`{Tarea._meta.db_table}`"
    id_column = f"`{Tarea._meta.pk.column}`"
    company_column = f"`{Tarea._meta.get_field('empresa').column}`"
    sql = (
        f"SELECT {id_column} FROM {table} "
        f"WHERE {company_column} = %s"
    )
    params = [empresa_id]
    if normalized_ids is not None:
        placeholders = ", ".join("%s" for _ in normalized_ids)
        sql += f" AND {id_column} IN ({placeholders})"
        params.extend(normalized_ids)
    sql += f" ORDER BY {id_column} FOR UPDATE"
    cursor = connection.cursor()
    try:
        cursor.execute(sql, tuple(params))
        locked_ids = tuple(row[0] for row in cursor.fetchall())
    finally:
        cursor.close()
    if normalized_ids is not None and set(locked_ids) != set(normalized_ids):
        raise TaskMutationScopeError(
            "Una o más tareas no existen en la empresa operacional indicada."
        )
    return locked_ids


def lock_orm_task_company(alias: str, empresa_id: int) -> CorrelativoEmpresa:
    """Lock the company's persistent coordination row before locking task rows."""
    connection = connections[alias]
    if not connection.features.supports_transactions:
        raise TaskMutationLockUnsupported(
            "BASE_TAREAS no soporta transacciones."
        )
    if not connection.in_atomic_block:
        raise TaskMutationLockError(
            "El lock de empresa requiere una transacción operacional activa."
        )
    manager = CorrelativoEmpresa.objects.using(alias)
    manager.get_or_create(
        empresa_id=empresa_id,
        defaults={"siguiente_numero": 1},
    )
    try:
        return manager.select_for_update().get(empresa_id=empresa_id)
    except CorrelativoEmpresa.DoesNotExist as exc:
        raise TaskMutationLockError(
            "No se pudo obtener el lock de coordinación de la empresa."
        ) from exc


def lock_mysql_task_company(connection, empresa_id: int) -> None:
    """Create-if-absent and lock the same company row used by task numbering."""
    table = f"`{CorrelativoEmpresa._meta.db_table}`"
    company_column = (
        f"`{CorrelativoEmpresa._meta.get_field('empresa').column}`"
    )
    sequence_column = (
        f"`{CorrelativoEmpresa._meta.get_field('siguiente_numero').column}`"
    )
    cursor = connection.cursor()
    try:
        try:
            cursor.execute(
                f"INSERT INTO {table} ({company_column}, {sequence_column}) "
                f"VALUES (%s, %s)",
                (empresa_id, 1),
            )
        except Exception as exc:
            if not _is_duplicate_key_error(exc):
                raise
            cursor.execute(
                f"SELECT {company_column} FROM {table} "
                f"WHERE {company_column} = %s FOR UPDATE",
                (empresa_id,),
            )
            if cursor.fetchone() is None:
                raise TaskMutationLockError(
                    "No se pudo obtener el lock de coordinación de la empresa."
                )
    finally:
        cursor.close()


def _is_duplicate_key_error(error: BaseException) -> bool:
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "errno", None) == 1062:
            return True
        args = getattr(current, "args", ())
        if args and args[0] == 1062:
            return True
        current = current.__cause__ or current.__context__
    return False


def lock_orm_task_groups(
    alias: str,
    task_groups,
    *,
    require_row_locks: bool = False,
) -> tuple[Tarea, ...]:
    rows = []
    for empresa_id, task_ids in _normalize_task_groups(task_groups):
        rows.extend(
            lock_orm_task_rows(
                alias,
                empresa_id,
                task_ids,
                require_row_locks=require_row_locks,
            )
        )
    return tuple(rows)


def lock_mysql_task_groups(connection, task_groups) -> tuple[tuple[int, int], ...]:
    locked = []
    for empresa_id, task_ids in _normalize_task_groups(task_groups):
        locked.extend(
            (empresa_id, task_id)
            for task_id in lock_mysql_task_rows(
                connection,
                empresa_id,
                task_ids,
            )
        )
    return tuple(locked)


@contextmanager
def bounded_mysql_lock_wait(connection) -> Iterator[None]:
    """Apply a short session-local InnoDB wait timeout on the same connection."""
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT @@SESSION.innodb_lock_wait_timeout")
        row = cursor.fetchone()
        if row is None:
            raise TaskMutationLockUnsupported(
                "No se pudo leer el timeout de bloqueo InnoDB."
            )
        previous_timeout = int(row[0])
        cursor.execute(
            f"SET SESSION innodb_lock_wait_timeout = {TASK_LOCK_WAIT_SECONDS}"
        )
    finally:
        cursor.close()

    try:
        try:
            yield
        except Exception as exc:
            if is_task_mutation_conflict(exc):
                raise TaskMutationConflict(
                    "La tarea está siendo modificada por otra operación; "
                    "vuelva a intentarlo."
                ) from exc
            raise
    finally:
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"SET SESSION innodb_lock_wait_timeout = {previous_timeout}"
            )
        except Exception as exc:
            raise TaskMutationLockError(
                "No se pudo restaurar el timeout de bloqueo de la conexión."
            ) from exc
        finally:
            cursor.close()


@contextmanager
def bounded_django_lock_wait(alias: str) -> Iterator[None]:
    """Bound row-lock waits where supported; SQLite deliberately has no claim."""
    connection = connections[alias]
    if connection.vendor == "mysql":
        with bounded_mysql_lock_wait(connection):
            yield
        return
    if connection.vendor == "postgresql":
        if not connection.in_atomic_block:
            raise TaskMutationLockError(
                "El timeout de PostgreSQL requiere una transacción activa."
            )
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"SET LOCAL lock_timeout = '{TASK_LOCK_WAIT_SECONDS}s'"
            )
        finally:
            cursor.close()
    try:
        yield
    except Exception as exc:
        if is_task_mutation_conflict(exc):
            raise TaskMutationConflict(
                "La tarea está siendo modificada por otra operación; "
                "vuelva a intentarlo."
            ) from exc
        raise


@contextmanager
def mysql_mutation_transaction(connection) -> Iterator[None]:
    """Use the already-open operational connection for one mutation transaction."""
    alias = getattr(connection, "alias", None)
    if isinstance(alias, str) and alias:
        with transaction.atomic(using=alias):
            yield
        return
    try:
        connection.begin()
    except Exception as exc:
        raise TaskMutationLockError(
            "No se pudo iniciar la transacción de mutación."
        ) from exc
    try:
        yield
    except BaseException:
        try:
            connection.rollback()
        except Exception as exc:
            raise TaskMutationLockError(
                "No se pudo revertir la transacción de mutación."
            ) from exc
        raise
    try:
        connection.commit()
    except Exception as exc:
        raise TaskMutationLockError(
            "No se pudo confirmar la transacción de mutación."
        ) from exc


def is_task_mutation_conflict(error: BaseException) -> bool:
    """Recognize lock waits, deadlocks and duplicate-edge races by driver code."""
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = (
            getattr(current, "sqlstate", None)
            or getattr(current, "pgcode", None)
            or getattr(current, "errno", None)
        )
        known_codes = (5, 6, 1062, 1205, 1213, "40001", "40P01", "55P03")
        if code in known_codes:
            return True
        args = getattr(current, "args", ())
        if args and args[0] in known_codes:
            return True
        if "database is locked" in str(current).casefold():
            return True
        current = current.__cause__ or current.__context__
    return False
