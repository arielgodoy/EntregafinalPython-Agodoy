"""Private, fail-closed engine for administrative deletion of a task tree."""

from __future__ import annotations

from collections import defaultdict
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import logging
import re
from typing import Generator, TypedDict
from uuid import UUID, uuid4

from access_control.models import Empresa
from access_control.services.permissions import (
    get_valid_users_for_empresa,
    user_has_permission_for_empresa,
)
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.files.storage import default_storage
from django.db import connections
from django.db import models
from django.db.models import Q
from settings.services.mysql_connections import open_mysql_connection

from ..models import Tarea, TareaRelacion
from .base_tareas_schema import get_deletion_item_models
from .connection_roles import (
    BackendContext,
    TareaConnectionError,
    resolve_operational_backend,
)
from .deletion_ledger import (
    DeletionFileReference,
    DeletionInventoryItem,
    DeletionLedgerCommitUncertain,
    DeletionLedgerConflict,
    DeletionLedgerError,
    DeletionLedgerSchemaError,
    DeletionLedgerStateError,
    DeletionOperationRecord,
    DeletionOperationInput,
    DjangoDeletionLedgerStorage,
    DjangoDeletionLedgerUnitOfWork,
    MySQLDeletionLedgerStorage,
    MySQLDeletionLedgerUnitOfWork,
)
from .deletion_preview import (
    DeletionPreviewNotFound,
    DeletionPreviewSchemaIncomplete,
    _DjangoReader,
    _Inventory,
    _MySQLReader,
    _batches,
    _collect_hierarchy,
    _inventory_dependencies,
)
from .task_mutation_locks import (
    TaskMutationLockUnsupported,
    TaskMutationScopeError,
    bounded_django_lock_wait,
    bounded_mysql_lock_wait,
    lock_mysql_task_company,
    lock_mysql_task_rows,
    lock_orm_task_company,
    lock_orm_task_rows,
)

logger = logging.getLogger(__name__)

_CONFIRMATION_SALT = "tareas.permanent-deletion.v1"
_CONFIRMATION_MAX_AGE_SECONDS = 300
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SQL_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PRESERVED_MODEL_NAMES = frozenset(
    {
        "CausaAtraso",
        "CorrelativoEmpresa",
        "CorrelativoTodoEmpresa",
        "Todo",
        "UmbralSimilitudEmpresa",
    }
)
_SAFE_DELETE_RULES = frozenset({"RESTRICT", "NO ACTION"})


class _ConfirmationPayload(TypedDict):
    actor_id: int
    empresa_id: int
    root_task_id: int
    root_correlativo: str
    backend_type: str
    backend_identity: str
    backend_config_version: str
    fingerprint: str
    operation_id: UUID


class PermanentDeletionError(DeletionLedgerError):
    """Base error for the private permanent-deletion workflow."""


class PermanentDeletionAuthorizationError(PermanentDeletionError):
    """The actor or confirmation context does not satisfy the contract."""


class PermanentDeletionBlocked(PermanentDeletionError):
    """A safety blocker prevents confirmation or execution."""

    def __init__(self, blockers: tuple[str, ...] | list[str]):
        self.blockers = tuple(sorted(set(blockers)))
        super().__init__("La eliminación administrativa está bloqueada.")


class PermanentDeletionFingerprintMismatch(PermanentDeletionError):
    """The locked inventory differs from the confirmed inventory."""


class PermanentDeletionCommitUnresolved(PermanentDeletionError):
    """The operation outcome could not be reconciled without retrying."""


class PermanentDeletionAuditPending(PermanentDeletionError):
    """The operational commit succeeded but audit delivery needs reconciliation."""


@dataclass(frozen=True)
class PermanentDeletionInventory:
    root_task: dict[str, object]
    task_ids: tuple[int, ...]
    items: tuple[DeletionInventoryItem, ...]
    files: tuple[DeletionFileReference, ...]
    file_classifications: tuple[tuple[str, str, str], ...]
    dependency_edges: tuple[tuple[str, int, str, str, int], ...]
    references: tuple[tuple[str, int, str, str, int, str], ...]
    counts: tuple[tuple[str, int], ...]
    blockers: tuple[str, ...]
    deletion_order: tuple[DeletionInventoryItem, ...]
    orm_constraints: tuple[tuple[str, ...], ...]
    physical_constraints: tuple[tuple[str, ...], ...]
    backend_type: str
    backend_identity: str
    backend_config_version: str
    fingerprint: str


@dataclass(frozen=True)
class PermanentDeletionResult:
    operation_id: UUID
    root_task_id: int
    empresa_id: int
    status: str
    audit_status: str
    audit_event_id: int | None
    file_cleanup_status: str
    backend_type: str
    fingerprint: str


@dataclass(frozen=True)
class _Backend:
    context: BackendContext
    storage: DjangoDeletionLedgerStorage | MySQLDeletionLedgerStorage
    backend_type: str
    backend_identity: str
    config_version: str


def _positive_id(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} debe ser un entero positivo.")
    return value


def _related_model(field) -> type[models.Model]:
    remote_field = field.remote_field
    if remote_field is None or isinstance(remote_field.model, str):
        raise DeletionLedgerSchemaError(
            "El inventario contiene una relación Django no resuelta."
        )
    return remote_field.model


def _target_column(field) -> str:
    target_field = field.target_field
    if target_field is None:
        raise DeletionLedgerSchemaError(
            "El inventario contiene una FK sin columna destino."
        )
    return target_field.column


def _field_column(model, field_name: str) -> str:
    column = model._meta.get_field(field_name).column
    if column is None:
        raise DeletionLedgerSchemaError(
            "El inventario contiene una columna física no resuelta."
        )
    return column


def _primary_key_column(model) -> str:
    column = model._meta.pk.column
    if column is None:
        raise DeletionLedgerSchemaError(
            "El inventario contiene una PK física no resuelta."
        )
    return column


def _resolve_backend() -> _Backend:
    try:
        context = resolve_operational_backend("BASE_TAREAS")
    except TareaConnectionError as exc:
        raise PermanentDeletionError(
            "No se pudo resolver el backend operacional BASE_TAREAS."
        ) from exc

    if context.backend_type == "DJANGO":
        alias = context.django_alias
        if not alias:
            raise PermanentDeletionError(
                "BASE_TAREAS no proporcionó un alias Django válido."
            )
        connection = connections[alias]
        config = connection.settings_dict
        signature = "|".join(
            str(config.get(key) or "")
            for key in ("ENGINE", "NAME", "HOST", "PORT")
        )
        config_version = sha256(signature.encode("utf-8")).hexdigest()
        storage = DjangoDeletionLedgerStorage(alias, config_version)
        return _Backend(
            context=context,
            storage=storage,
            backend_type="DJANGO",
            backend_identity=storage.backend_identity,
            config_version=config_version,
        )

    if (
        context.backend_type == "MYSQL_CONFIG"
        and context.mysql_connection is not None
        and context.database_name
    ):
        storage = MySQLDeletionLedgerStorage(
            context.mysql_connection,
            context.database_name,
        )
        return _Backend(
            context=context,
            storage=storage,
            backend_type="MYSQL_CONFIG",
            backend_identity=storage.backend_identity,
            config_version=storage.config_version,
        )

    raise PermanentDeletionBackendError(
        "BASE_TAREAS no utiliza un backend operacional soportado."
    )


class PermanentDeletionBackendError(PermanentDeletionError):
    """The backend cannot provide the physical guarantees required."""


@contextmanager
def _reader_for_backend(
    backend: _Backend,
    operational_connection=None,
) -> Generator[_DjangoReader | _MySQLReader, None, None]:
    context = backend.context
    if backend.backend_type == "DJANGO":
        alias = context.django_alias
        if not alias:
            raise PermanentDeletionBackendError(
                "BASE_TAREAS no tiene un alias Django válido."
            )
        yield _DjangoReader(alias)
        return

    if context.mysql_connection is None or not context.database_name:
        raise PermanentDeletionBackendError(
            "BASE_TAREAS no tiene una conexión MYSQL_CONFIG válida."
        )
    if operational_connection is None:
        with open_mysql_connection(
            context.mysql_connection,
            database_name=context.database_name,
        ) as connection:
            reader = _MySQLReader(connection, context.database_name)
            try:
                yield reader
            finally:
                reader.close()
        return

    reader = _MySQLReader(operational_connection, context.database_name)
    try:
        yield reader
    finally:
        reader.close()


def _require_reader_schema(reader: _DjangoReader | _MySQLReader) -> None:
    if reader.missing_tables:
        raise DeletionPreviewSchemaIncomplete(reader.missing_tables)


def _deletion_models():
    all_models = tuple(get_deletion_item_models())
    deletable = tuple(
        model
        for model in all_models
        if model.__name__ not in _PRESERVED_MODEL_NAMES
    )
    if Tarea not in deletable:
        raise DeletionLedgerSchemaError(
            "El inventario de eliminación no incluye el modelo Tarea."
        )
    return all_models, deletable


def _orm_fk_contract(all_models: tuple[type, ...]) -> tuple[tuple[str, ...], ...]:
    model_set = set(all_models)
    constraints = set()
    for model in all_models:
        for field in _foreign_key_fields(model):
            target_model = _related_model(field)
            if target_model not in model_set:
                continue
            on_delete = getattr(field.remote_field, "on_delete", None)
            action = getattr(on_delete, "__name__", None)
            if not isinstance(action, str) or not action:
                raise DeletionLedgerSchemaError(
                    "No se pudo identificar on_delete en una FK operacional."
                )
            constraints.add(
                (
                    model._meta.db_table,
                    _field_column(model, field.name),
                    target_model._meta.db_table,
                    _target_column(field),
                    action,
                )
            )
    return tuple(sorted(constraints))


def _foreign_key_fields(model):
    return tuple(
        field
        for field in model._meta.concrete_fields
        if field.is_relation
        and (field.many_to_one or field.one_to_one)
        and field.remote_field is not None
    )


def _collect_manifest_ids(
    reader: _DjangoReader | _MySQLReader,
    task_ids: tuple[int, ...],
    deletable_models: tuple[type, ...],
) -> dict[type, set[int]]:
    deletable_set = set(deletable_models)
    item_ids = {model: set() for model in deletable_models}
    item_ids[Tarea].update(task_ids)

    for _ in range(len(deletable_models) + 1):
        changed = False
        for model in deletable_models:
            if model is Tarea:
                continue
            for field in _foreign_key_fields(model):
                target_model = _related_model(field)
                if target_model not in deletable_set:
                    continue
                target_ids = item_ids[target_model]
                if not target_ids:
                    continue
                related = reader.related_ids(
                    model,
                    field.name,
                    sorted(target_ids),
                )
                new_ids = set(related) - item_ids[model]
                if new_ids:
                    item_ids[model].update(new_ids)
                    changed = True
        if not changed:
            return item_ids

    raise PermanentDeletionBlocked(
        ["El inventario de dependencias no alcanzó un punto fijo."]
    )


def _foreign_key_rows(
    reader: _DjangoReader | _MySQLReader,
    model,
    object_ids: tuple[int, ...],
):
    if not object_ids:
        return ()
    fields = _foreign_key_fields(model)
    if not fields:
        return ()

    rows = []
    if isinstance(reader, _DjangoReader):
        for batch in _batches(object_ids):
            selected = (model._meta.pk.attname,) + tuple(
                field.attname for field in fields
            )
            query = (
                model.objects.using(reader.alias)
                .filter(pk__in=batch)
                .order_by("pk")
                .values_list(*selected)
            )
            for row in query:
                object_id = row[0]
                for index, field in enumerate(fields, start=1):
                    related_id = row[index]
                    if related_id is not None:
                        rows.append(
                            (
                                object_id,
                                field.name,
                                _related_model(field)._meta.label_lower,
                                related_id,
                            )
                        )
        return tuple(rows)

    quote = reader._quote
    table = quote(model._meta.db_table)
    pk_column = quote(_primary_key_column(model))
    selected_columns = [quote(field.column) for field in fields]
    selected_sql = ", ".join((pk_column, *selected_columns))
    for batch in _batches(object_ids):
        placeholders = ", ".join("%s" for _ in batch)
        reader.cursor.execute(
            f"SELECT {selected_sql} FROM {table} "
            f"WHERE {pk_column} IN ({placeholders}) ORDER BY {pk_column}",
            tuple(batch),
        )
        for row in reader.cursor.fetchall():
            object_id = row[0]
            for index, field in enumerate(fields, start=1):
                related_id = row[index]
                if related_id is not None:
                    rows.append(
                        (
                            object_id,
                            field.name,
                            _related_model(field)._meta.label_lower,
                            related_id,
                        )
                    )
    return tuple(rows)


def _incoming_origin_references(
    reader: _DjangoReader | _MySQLReader,
    task_ids: tuple[int, ...],
) -> tuple[tuple[int, int], ...]:
    if isinstance(reader, _DjangoReader):
        return tuple(
            Tarea.objects.using(reader.alias)
            .filter(tarea_origen_id__in=task_ids)
            .exclude(pk__in=task_ids)
            .order_by("pk")
            .values_list("pk", "tarea_origen_id")
        )

    table = reader._quote(Tarea._meta.db_table)
    pk_column = reader._quote(_primary_key_column(Tarea))
    origin_column = reader._quote(_field_column(Tarea, "tarea_origen"))
    excluded = set(task_ids)
    references = set()
    for batch in _batches(task_ids):
        placeholders = ", ".join("%s" for _ in batch)
        reader.cursor.execute(
            f"SELECT {pk_column}, {origin_column} FROM {table} "
            f"WHERE {origin_column} IN ({placeholders}) ORDER BY {pk_column}",
            tuple(batch),
        )
        references.update(
            (source_id, origin_id)
            for source_id, origin_id in reader.cursor.fetchall()
            if source_id not in excluded
        )
    return tuple(sorted(references))


def _storage_key(field) -> str:
    if field.storage is default_storage:
        return "default"
    return "unknown"


def _collect_files(
    reader: _DjangoReader | _MySQLReader,
    item_ids: dict[type, set[int]],
    deletable_models: tuple[type, ...],
) -> tuple[tuple[DeletionFileReference, ...], tuple[str, ...]]:
    deletable_set = set(deletable_models)
    references = set()
    blockers = set()

    for model in deletable_models:
        model_ids = item_ids[model]
        if not model_ids:
            continue
        file_fields = tuple(
            field
            for field in model._meta.concrete_fields
            if isinstance(field, models.FileField)
        )
        for file_field in file_fields:
            owner_fields = tuple(
                field
                for field in _foreign_key_fields(model)
                if _related_model(field) in deletable_set
            )
            if len(owner_fields) != 1:
                blockers.add(
                    "La pertenencia de una referencia de archivo no se puede determinar."
                )
                continue
            owner_field = owner_fields[0]
            rows = reader.file_rows(
                model,
                owner_field.name,
                sorted(item_ids[_related_model(owner_field)]),
            )
            storage_key = _storage_key(file_field)
            if storage_key == "unknown":
                blockers.add(
                    "El backend de almacenamiento del archivo no está reconocido."
                )
            for object_id, file_name in rows:
                if object_id not in item_ids[model]:
                    blockers.add(
                        "Una referencia de archivo no pertenece al manifiesto."
                    )
                    continue
                if file_name:
                    references.add(
                        DeletionFileReference(
                            storage_key=storage_key,
                            file_name=str(file_name),
                        )
                    )

    if references:
        blockers.add(
            "La exclusividad de los archivos físicos no se puede demostrar."
        )
    return tuple(sorted(references)), tuple(sorted(blockers))


def _mysql_fk_snapshot(
    connection,
    database_name: str,
    all_models: tuple[type, ...],
    item_ids: dict[type, set[int]],
) -> tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]:
    table_models = {model._meta.db_table: model for model in all_models}
    table_names = tuple(sorted(table_models))
    placeholders = ", ".join("%s" for _ in table_names)
    sql = (
        "SELECT k.TABLE_SCHEMA, k.TABLE_NAME, k.COLUMN_NAME, "
        "k.REFERENCED_TABLE_SCHEMA, k.REFERENCED_TABLE_NAME, "
        "k.REFERENCED_COLUMN_NAME, r.DELETE_RULE "
        "FROM information_schema.KEY_COLUMN_USAGE AS k "
        "LEFT JOIN information_schema.REFERENTIAL_CONSTRAINTS AS r "
        "ON r.CONSTRAINT_SCHEMA = k.CONSTRAINT_SCHEMA "
        "AND r.TABLE_NAME = k.TABLE_NAME "
        "AND r.CONSTRAINT_NAME = k.CONSTRAINT_NAME "
        "WHERE k.REFERENCED_TABLE_NAME IS NOT NULL AND ("
        f"(k.TABLE_SCHEMA = %s AND k.TABLE_NAME IN ({placeholders})) OR "
        f"(k.REFERENCED_TABLE_SCHEMA = %s "
        f"AND k.REFERENCED_TABLE_NAME IN ({placeholders})))"
    )
    cursor = connection.cursor()
    blockers = set()
    constraints = set()
    try:
        cursor.execute(
            sql,
            (database_name, *table_names, database_name, *table_names),
        )
        rows = tuple(cursor.fetchall())
        expected = set()
        for model in all_models:
            for field in _foreign_key_fields(model):
                target_model = _related_model(field)
                if target_model in table_models.values():
                    expected.add(
                        (
                            model._meta.db_table,
                            field.column,
                            target_model._meta.db_table,
                            _target_column(field),
                        )
                    )

        actual_internal = set()
        for (
            child_schema,
            child_table,
            child_column,
            parent_schema,
            parent_table,
            parent_column,
            delete_rule,
        ) in rows:
            normalized = (
                str(child_schema),
                str(child_table),
                str(child_column),
                str(parent_schema),
                str(parent_table),
                str(parent_column),
                str(delete_rule or "").upper(),
            )
            constraints.add(normalized)
            if (
                child_schema == database_name
                and child_table in table_models
                and parent_schema == database_name
                and parent_table in table_models
            ):
                key = (
                    str(child_table),
                    str(child_column),
                    str(parent_table),
                    str(parent_column),
                )
                actual_internal.add(key)
                if str(delete_rule or "").upper() not in _SAFE_DELETE_RULES:
                    blockers.add(
                        "Una FK física interna no aplica RESTRICT/NO ACTION."
                    )
                continue

            if (
                parent_schema == database_name
                and parent_table in table_models
                and not (
                    child_schema == database_name
                    and child_table in table_models
                )
            ):
                target_model = table_models[parent_table]
                target_ids = tuple(sorted(item_ids.get(target_model, ())))
                if not target_ids:
                    continue
                schema_name = str(child_schema)
                source_table = str(child_table)
                source_column = str(child_column)
                if not all(
                    _SQL_IDENTIFIER_PATTERN.fullmatch(value)
                    for value in (schema_name, source_table, source_column)
                ):
                    blockers.add(
                        "Una referencia física externa no se puede verificar."
                    )
                    continue
                external_count = 0
                for batch in _batches(target_ids):
                    count_cursor = connection.cursor()
                    try:
                        id_placeholders = ", ".join("%s" for _ in batch)
                        count_cursor.execute(
                            f"SELECT COUNT(*) FROM `{schema_name}`.`{source_table}` "
                            f"WHERE `{source_column}` IN ({id_placeholders})",
                            tuple(batch),
                        )
                        count_row = count_cursor.fetchone()
                    finally:
                        count_cursor.close()
                    if count_row is None:
                        blockers.add(
                            "No se pudo verificar una FK física externa."
                        )
                        break
                    external_count += int(count_row[0])
                if external_count > 0:
                    blockers.add(
                        "Una tabla externa contiene referencias físicas al inventario."
                    )

        missing = expected - actual_internal
        extra = actual_internal - expected
        if missing:
            blockers.add(
                "El esquema físico no contiene todas las FK operacionales esperadas."
            )
        if extra:
            blockers.add(
                "El esquema físico contiene FK internas ajenas al modelo vigente."
            )
    finally:
        cursor.close()

    return tuple(sorted(constraints)), tuple(sorted(blockers))


def _physical_fk_snapshot(
    reader: _DjangoReader | _MySQLReader,
    backend: _Backend,
    all_models: tuple[type, ...],
    item_ids: dict[type, set[int]],
) -> tuple[tuple[tuple[str, ...], ...], tuple[str, ...]]:
    if isinstance(reader, _DjangoReader):
        connection = connections[reader.alias]
        if connection.vendor != "mysql":
            return (
                (("UNVERIFIED", connection.vendor),),
                ("El backend no permite verificar las reglas FK físicas MariaDB.",),
            )
        database_name = connection.settings_dict.get("NAME")
    else:
        connection = reader.connection
        database_name = reader.database_name

    if not isinstance(database_name, str) or not database_name:
        return (
            (("UNVERIFIED", backend.backend_type),),
            ("No se pudo identificar la base para verificar las FK físicas.",),
        )
    return _mysql_fk_snapshot(
        connection,
        database_name,
        all_models,
        item_ids,
    )


def _topological_deletion_order(
    items: tuple[DeletionInventoryItem, ...],
    dependency_edges: tuple[tuple[str, int, str, str, int], ...],
) -> tuple[tuple[DeletionInventoryItem, ...], bool]:
    nodes = {(item.model_label, item.object_id) for item in items}
    parents_by_child: dict[tuple[str, int], set[tuple[str, int]]] = defaultdict(set)
    indegree = {node: 0 for node in nodes}
    for source_label, source_id, _, target_label, target_id in dependency_edges:
        source = (source_label, source_id)
        target = (target_label, target_id)
        if source in nodes and target in nodes and target not in parents_by_child[source]:
            parents_by_child[source].add(target)
            indegree[target] += 1

    ready = sorted(node for node, degree in indegree.items() if degree == 0)
    ordered = []
    while ready:
        node = ready.pop(0)
        ordered.append(node)
        for parent in sorted(parents_by_child[node]):
            indegree[parent] -= 1
            if indegree[parent] == 0:
                ready.append(parent)
                ready.sort()

    cyclic = len(ordered) != len(nodes)
    if cyclic:
        return (), True
    return (
        tuple(
            DeletionInventoryItem(model_label=label, object_id=object_id)
            for label, object_id in ordered
        ),
        False,
    )


def _reference_classification(
    model,
    field_name,
    target_model,
    target_is_in_manifest,
):
    if target_is_in_manifest:
        return "ELIMINABLE"
    if model is Tarea and field_name == "tarea_origen":
        return "PRESERVAR"
    if (
        target_model.__name__ in _PRESERVED_MODEL_NAMES
        or target_model._meta.app_label != "tareas"
    ):
        return "PRESERVAR"
    return "BLOQUEADO"


def _build_internal_inventory(
    reader: _DjangoReader | _MySQLReader,
    backend: _Backend,
    task_id: int,
    empresa_id: int,
) -> PermanentDeletionInventory:
    _require_reader_schema(reader)
    root_task = reader.task(task_id, empresa_id)
    task_ids_list, hierarchy_blockers = _collect_hierarchy(
        reader,
        task_id,
        empresa_id,
    )
    inventory = _Inventory(task_ids_list)
    inventory.blockers.extend(hierarchy_blockers)
    inventory.counts["Tareas descendientes"] = max(0, len(task_ids_list) - 1)
    _inventory_dependencies(reader, inventory)

    all_models, deletable_models = _deletion_models()
    orm_constraints = _orm_fk_contract(all_models)
    deletable_set = set(deletable_models)
    item_ids = _collect_manifest_ids(
        reader,
        tuple(task_ids_list),
        deletable_models,
    )

    item_values = tuple(
        sorted(
            DeletionInventoryItem(model._meta.label_lower, object_id)
            for model in deletable_models
            for object_id in item_ids[model]
        )
    )
    items_by_model = {
        model: set(item_ids[model])
        for model in deletable_models
    }
    model_by_label = {
        model._meta.label_lower: model
        for model in deletable_models
    }

    dependency_edges = set()
    references = set()
    blockers = set(inventory.blockers)
    for item in item_values:
        model = model_by_label[item.model_label]
        for object_id, field_name, target_label, target_id in _foreign_key_rows(
            reader,
            model,
            (item.object_id,),
        ):
            field = model._meta.get_field(field_name)
            target_model = _related_model(field)
            target_in_manifest = (
                target_model in deletable_set
                and target_id in items_by_model[target_model]
            )
            classification = _reference_classification(
                model,
                field_name,
                target_model,
                target_in_manifest,
            )
            if model.__name__ == "TodoEvento" and field_name == "todo":
                classification = "BLOQUEADO"
                blockers.add(
                    "Un evento de un TO-DO preservado no se puede eliminar de forma exclusiva."
                )
            references.add(
                (
                    model._meta.label_lower,
                    object_id,
                    field_name,
                    target_label,
                    int(target_id),
                    classification,
                )
            )
            if target_in_manifest:
                dependency_edges.add(
                    (
                        model._meta.label_lower,
                        object_id,
                        field_name,
                        target_label,
                        int(target_id),
                    )
                )
            elif target_model in deletable_set and not (
                model is Tarea and field_name == "tarea_origen"
            ):
                blockers.add(
                    "Un registro candidato referencia un objeto fuera del árbol."
                )

    incoming_origins = _incoming_origin_references(
        reader,
        tuple(task_ids_list),
    )
    for external_task_id, origin_task_id in incoming_origins:
        references.add(
            (
                Tarea._meta.label_lower,
                int(external_task_id),
                "tarea_origen",
                Tarea._meta.label_lower,
                int(origin_task_id),
                "BLOQUEADO",
            )
        )
        blockers.add(
            "Una tarea externa referencia una tarea del árbol como origen."
        )

    file_references, file_blockers = _collect_files(
        reader,
        item_ids,
        deletable_models,
    )
    file_classifications = tuple(
        (item.storage_key, item.file_name, "BLOQUEADO")
        for item in file_references
    )
    blockers.update(file_blockers)

    physical_constraints, physical_blockers = _physical_fk_snapshot(
        reader,
        backend,
        all_models,
        item_ids,
    )
    blockers.update(physical_blockers)

    # No public Tareas interface can enumerate every logical reference from other apps.
    references.add(
        (
            "",
            0,
            "external_application_references",
            "unverified",
            0,
            "NO_VERIFICADO",
        )
    )
    blockers.add(
        "Las referencias lógicas desde otras aplicaciones no se pueden verificar."
    )

    dependency_edges_tuple = tuple(sorted(dependency_edges))
    references_tuple = tuple(sorted(references))
    deletion_order, has_cycle = _topological_deletion_order(
        item_values,
        dependency_edges_tuple,
    )
    if has_cycle:
        blockers.add("El grafo de dependencias contiene un ciclo.")

    exact_counts = tuple(
        sorted(
            (
                model._meta.label_lower,
                len(item_ids[model]),
            )
            for model in deletable_models
            if item_ids[model]
        )
    )
    canonical = {
        "contract": "tareas.permanent-deletion.v1",
        "empresa_id": empresa_id,
        "root": {
            "task_id": task_id,
            "correlativo": root_task["correlativo"],
        },
        "task_ids": sorted(task_ids_list),
        "items": [
            [item.model_label, item.object_id]
            for item in item_values
        ],
        "files": [
            [item.storage_key, item.file_name]
            for item in file_references
        ],
        "file_classifications": [
            list(item) for item in file_classifications
        ],
        "dependencies": [list(edge) for edge in dependency_edges_tuple],
        "references": [list(reference) for reference in references_tuple],
        "orm_constraints": [list(item) for item in orm_constraints],
        "counts": [list(count) for count in exact_counts],
        "blockers": sorted(blockers),
        "physical_constraints": [
            list(constraint)
            for constraint in physical_constraints
        ],
        "backend": {
            "type": backend.backend_type,
            "identity": backend.backend_identity,
            "config_version": backend.config_version,
        },
    }
    fingerprint = sha256(
        json.dumps(
            canonical,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return PermanentDeletionInventory(
        root_task=root_task,
        task_ids=tuple(sorted(task_ids_list)),
        items=item_values,
        files=file_references,
        file_classifications=file_classifications,
        dependency_edges=dependency_edges_tuple,
        references=references_tuple,
        counts=exact_counts,
        blockers=tuple(sorted(blockers)),
        deletion_order=deletion_order,
        orm_constraints=orm_constraints,
        physical_constraints=physical_constraints,
        backend_type=backend.backend_type,
        backend_identity=backend.backend_identity,
        backend_config_version=backend.config_version,
        fingerprint=fingerprint,
    )


def build_deletion_inventory(
    *,
    actor,
    empresa_id: int,
    task_id: int,
) -> PermanentDeletionInventory:
    """Build a sensitive internal inventory only after explicit supervisor checks."""
    actor = _authorized_actor_company(actor, empresa_id)
    task_id = _positive_id(task_id, "task_id")
    backend = _resolve_backend()
    try:
        with _reader_for_backend(backend) as reader:
            return _build_internal_inventory(
                reader,
                backend,
                task_id,
                empresa_id,
            )
    except (DeletionPreviewNotFound, DeletionPreviewSchemaIncomplete):
        raise
    except PermanentDeletionError:
        raise
    except Exception as exc:
        raise PermanentDeletionError(
            "No se pudo construir el inventario interno de eliminación."
        ) from exc


def _authorized_actor_company(
    actor: AbstractBaseUser,
    empresa_id: int,
) -> AbstractBaseUser:
    User = get_user_model()
    if not isinstance(actor, User) or not getattr(actor, "is_authenticated", False):
        raise PermanentDeletionAuthorizationError(
            "Se requiere un usuario autenticado."
        )
    empresa_id = _positive_id(empresa_id, "empresa_id")
    if not getattr(actor, "is_active", False):
        raise PermanentDeletionAuthorizationError(
            "El usuario debe estar activo."
        )

    persisted_actor = (
        User.objects.using("default")
        .filter(pk=actor.pk, is_active=True)
        .first()
    )
    empresa = (
        Empresa.objects.using("default")
        .filter(pk=empresa_id, codigo="00")
        .first()
    )
    if persisted_actor is None or empresa is None:
        raise PermanentDeletionAuthorizationError(
            "El usuario o la Empresa Base 00 no están disponibles."
        )
    if not get_valid_users_for_empresa(empresa, active_only=True).filter(
        pk=persisted_actor.pk
    ).exists():
        raise PermanentDeletionAuthorizationError(
            "El usuario no pertenece a la Empresa Base 00."
        )
    if not user_has_permission_for_empresa(
        user=persisted_actor,
        empresa=empresa,
        vista_nombre="Tareas",
        accion="supervisor",
    ):
        raise PermanentDeletionAuthorizationError(
            "Se requiere permiso VICMEAS supervisor S en Tareas/Base 00."
        )
    return persisted_actor


def issue_permanent_deletion_confirmation(
    *,
    actor,
    empresa_id: int,
    task_id: int,
    expected_fingerprint: str,
    confirmation_phrase: str,
) -> str:
    """Issue a short-lived, signed confirmation only for a clear inventory."""
    actor = _authorized_actor_company(actor, empresa_id)
    if (
        not isinstance(expected_fingerprint, str)
        or not _FINGERPRINT_PATTERN.fullmatch(expected_fingerprint)
    ):
        raise PermanentDeletionFingerprintMismatch(
            "El fingerprint de confirmación no es válido."
        )

    inventory = build_deletion_inventory(
        actor=actor,
        empresa_id=empresa_id,
        task_id=task_id,
    )
    if not hmac.compare_digest(inventory.fingerprint, expected_fingerprint):
        raise PermanentDeletionFingerprintMismatch(
            "El inventario cambió desde la previsualización."
        )
    if inventory.blockers:
        raise PermanentDeletionBlocked(inventory.blockers)

    expected_phrase = f"ELIMINAR {inventory.root_task['correlativo']}"
    if not isinstance(confirmation_phrase, str) or not hmac.compare_digest(
        confirmation_phrase.strip(),
        expected_phrase,
    ):
        raise PermanentDeletionAuthorizationError(
            "La confirmación informada no coincide con la tarea."
        )

    root_correlativo = inventory.root_task.get("correlativo")
    if not isinstance(root_correlativo, str):
        raise DeletionLedgerSchemaError(
            "El inventario no contiene el correlativo de la raíz."
        )
    payload = {
        "actor_id": _positive_id(actor.pk, "actor_id"),
        "empresa_id": empresa_id,
        "root_task_id": _positive_id(task_id, "task_id"),
        "root_correlativo": root_correlativo,
        "backend_type": inventory.backend_type,
        "backend_identity": inventory.backend_identity,
        "backend_config_version": inventory.backend_config_version,
        "fingerprint": inventory.fingerprint,
        "operation_id": uuid4().hex,
    }
    return signing.dumps(
        payload,
        salt=_CONFIRMATION_SALT,
        compress=True,
    )


def _load_confirmation(token: str) -> _ConfirmationPayload:
    if not isinstance(token, str) or not token or len(token) > 4096:
        raise PermanentDeletionAuthorizationError(
            "La confirmación no es válida."
        )
    try:
        payload = signing.loads(
            token,
            salt=_CONFIRMATION_SALT,
            max_age=_CONFIRMATION_MAX_AGE_SECONDS,
        )
    except signing.SignatureExpired as exc:
        raise PermanentDeletionAuthorizationError(
            "La confirmación expiró."
        ) from exc
    except signing.BadSignature as exc:
        raise PermanentDeletionAuthorizationError(
            "La confirmación no es válida."
        ) from exc
    required = {
        "actor_id",
        "empresa_id",
        "root_task_id",
        "root_correlativo",
        "backend_type",
        "backend_identity",
        "backend_config_version",
        "fingerprint",
        "operation_id",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise PermanentDeletionAuthorizationError(
            "El contenido de confirmación no es válido."
        )
    try:
        actor_id = _positive_id(payload["actor_id"], "actor_id")
        empresa_id = _positive_id(payload["empresa_id"], "empresa_id")
        root_task_id = _positive_id(payload["root_task_id"], "root_task_id")
        raw_operation_id = payload["operation_id"]
        if not isinstance(raw_operation_id, str):
            raise ValueError("operation_id no es texto.")
        operation_id = UUID(hex=raw_operation_id)
    except (TypeError, ValueError, AttributeError) as exc:
        raise PermanentDeletionAuthorizationError(
            "La identidad de confirmación no es válida."
        ) from exc
    root_correlativo = payload["root_correlativo"]
    backend_type = payload["backend_type"]
    backend_identity = payload["backend_identity"]
    backend_config_version = payload["backend_config_version"]
    fingerprint = payload["fingerprint"]
    if (
        not isinstance(fingerprint, str)
        or not _FINGERPRINT_PATTERN.fullmatch(fingerprint)
        or not isinstance(root_correlativo, str)
        or not isinstance(backend_type, str)
        or backend_type not in {"DJANGO", "MYSQL_CONFIG"}
        or not isinstance(backend_identity, str)
        or not backend_identity
        or not isinstance(backend_config_version, str)
    ):
        raise PermanentDeletionAuthorizationError(
            "Los metadatos de confirmación no son válidos."
        )
    return {
        "actor_id": actor_id,
        "empresa_id": empresa_id,
        "root_task_id": root_task_id,
        "root_correlativo": root_correlativo,
        "backend_type": backend_type,
        "backend_identity": backend_identity,
        "backend_config_version": backend_config_version,
        "fingerprint": fingerprint,
        "operation_id": operation_id,
    }


def _validate_existing_operation(
    record: DeletionOperationRecord,
    payload: _ConfirmationPayload,
    backend: _Backend,
) -> None:
    expected = (
        payload["actor_id"],
        payload["empresa_id"],
        payload["root_task_id"],
        payload["root_correlativo"],
        payload["fingerprint"],
        backend.backend_type,
        backend.backend_identity,
        backend.config_version,
    )
    actual = (
        record.actor_id,
        record.empresa_id,
        record.root_task_id,
        record.root_correlativo,
        record.fingerprint,
        record.backend_type,
        record.backend_identity,
        record.backend_config_version,
    )
    if actual != expected:
        raise DeletionLedgerConflict(
            "operation_id ya existe con datos diferentes."
        )


def _lock_hierarchy_rows(
    reader: _DjangoReader | _MySQLReader,
    task_ids: tuple[int, ...],
) -> None:
    if isinstance(reader, _DjangoReader):
        tuple(
            TareaRelacion.objects.using(reader.alias)
            .filter(Q(padre_id__in=task_ids) | Q(hija_id__in=task_ids))
            .select_for_update()
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        return

    table = reader._quote(TareaRelacion._meta.db_table)
    pk_column = reader._quote(_primary_key_column(TareaRelacion))
    parent_column = reader._quote(_field_column(TareaRelacion, "padre"))
    child_column = reader._quote(_field_column(TareaRelacion, "hija"))
    for batch in _batches(task_ids):
        placeholders = ", ".join("%s" for _ in batch)
        reader.cursor.execute(
            f"SELECT {pk_column} FROM {table} WHERE "
            f"{parent_column} IN ({placeholders}) OR "
            f"{child_column} IN ({placeholders}) "
            f"ORDER BY {pk_column} FOR UPDATE",
            (*batch, *batch),
        )
        reader.cursor.fetchall()


def _lock_manifest_rows(
    reader: _DjangoReader | _MySQLReader,
    inventory: PermanentDeletionInventory,
) -> None:
    model_map = {
        model._meta.label_lower: model
        for model in get_deletion_item_models()
    }
    grouped: dict[str, set[int]] = defaultdict(set)
    for item in inventory.items:
        grouped[item.model_label].add(item.object_id)

    for model_label in sorted(grouped):
        model = model_map.get(model_label)
        if model is None:
            raise DeletionLedgerSchemaError(
                "El manifiesto incluye un modelo no permitido."
            )
        if model in {Tarea, TareaRelacion}:
            continue
        expected_ids = grouped[model_label]
        locked_ids = set()
        if isinstance(reader, _DjangoReader):
            query = (
                model.objects.using(reader.alias)
                .filter(pk__in=expected_ids)
                .select_for_update()
                .order_by("pk")
                .values_list("pk", flat=True)
            )
            locked_ids.update(query)
        else:
            table = reader._quote(model._meta.db_table)
            pk_column = reader._quote(_primary_key_column(model))
            for batch in _batches(tuple(sorted(expected_ids))):
                placeholders = ", ".join("%s" for _ in batch)
                reader.cursor.execute(
                    f"SELECT {pk_column} FROM {table} "
                    f"WHERE {pk_column} IN ({placeholders}) "
                    f"ORDER BY {pk_column} FOR UPDATE",
                    tuple(batch),
                )
                locked_ids.update(row[0] for row in reader.cursor.fetchall())
        if locked_ids != expected_ids:
            raise TaskMutationScopeError(
                "Un registro del inventario cambió antes de obtener sus locks."
            )


def _delete_manifest_item(
    reader: _DjangoReader | _MySQLReader,
    item: DeletionInventoryItem,
    allowed_items: set[DeletionInventoryItem],
) -> None:
    if item not in allowed_items:
        raise DeletionLedgerStateError(
            "Se rechazó una eliminación fuera del manifiesto aprobado."
        )
    model_map = {
        model._meta.label_lower: model
        for model in get_deletion_item_models()
    }
    model = model_map.get(item.model_label)
    if model is None or model.__name__ in _PRESERVED_MODEL_NAMES:
        raise DeletionLedgerSchemaError(
            "El manifiesto incluye un modelo que debe conservarse."
        )

    if isinstance(reader, _DjangoReader):
        connection = connections[reader.alias]
        quote = connection.ops.quote_name
    else:
        connection = reader.connection
        quote = reader._quote
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"DELETE FROM {quote(model._meta.db_table)} "
            f"WHERE {quote(_primary_key_column(model))} = %s",
            (item.object_id,),
        )
        if cursor.rowcount != 1:
            raise TaskMutationScopeError(
                "Un registro del manifiesto no se pudo eliminar exactamente una vez."
            )
    finally:
        cursor.close()


def _result_from_record(
    record: DeletionOperationRecord,
    backend_type: str,
) -> PermanentDeletionResult:
    return PermanentDeletionResult(
        operation_id=record.operation_id,
        root_task_id=record.root_task_id,
        empresa_id=record.empresa_id,
        status=record.status,
        audit_status=record.audit_status,
        audit_event_id=record.audit_event_id,
        file_cleanup_status=record.file_cleanup_status,
        backend_type=backend_type,
        fingerprint=record.fingerprint,
    )


def _deliver_audit_once(
    *,
    backend: _Backend,
    operation_id: UUID,
    actor: AbstractBaseUser,
    record: DeletionOperationRecord,
) -> PermanentDeletionResult:
    from .audit import log_permanent_deletion_operation

    try:
        event = log_permanent_deletion_operation(
            actor=actor,
            empresa_id=record.empresa_id,
            task_id=record.root_task_id,
            operation_id=operation_id.hex,
            fingerprint=record.fingerprint,
            backend_type=backend.backend_type,
            dependency_summary=record.dependency_summary,
        )
    except Exception as exc:
        event = None
        error_type = type(exc).__name__
    else:
        error_type = "AUDIT_RESULT_UNCONFIRMED"

    if event is None:
        try:
            with backend.storage.atomic() as unit:
                updated = unit.record_audit_result(
                    operation_id,
                    confirmed=False,
                    error_code="AUDIT_UNCERTAIN",
                )
        except Exception as exc:
            logger.error(
                "Permanent task deletion audit reconciliation failed "
                "operation_id=%s error_type=%s",
                operation_id.hex,
                type(exc).__name__,
            )
            raise PermanentDeletionAuditPending(
                "La eliminación se confirmó, pero la auditoría requiere reconciliación."
            ) from exc
        logger.error(
            "Permanent task deletion audit was not confirmed "
            "operation_id=%s error_type=%s",
            operation_id.hex,
            error_type,
        )
        raise PermanentDeletionAuditPending(
            "La eliminación se confirmó, pero la auditoría requiere reconciliación."
        )

    try:
        with backend.storage.atomic() as unit:
            updated = unit.record_audit_result(
                operation_id,
                confirmed=True,
                event_id=event.pk,
            )
    except Exception as exc:
        logger.error(
            "Permanent task deletion audit was written but its ledger result "
            "is unresolved operation_id=%s error_type=%s",
            operation_id.hex,
            type(exc).__name__,
        )
        raise PermanentDeletionAuditPending(
            "La auditoría pudo persistirse, pero su ledger requiere reconciliación."
        ) from exc
    return _result_from_record(updated, backend.backend_type)


def execute_permanent_deletion(
    *,
    confirmation_token: str,
) -> PermanentDeletionResult:
    """Execute one confirmed inventory; this service is not connected to HTTP."""
    payload = _load_confirmation(confirmation_token)
    actor = _authorized_actor_company(
        _load_actor(payload["actor_id"]),
        payload["empresa_id"],
    )
    backend = _resolve_backend()
    if (
        payload["backend_type"] != backend.backend_type
        or payload["backend_identity"] != backend.backend_identity
        or payload["backend_config_version"] != backend.config_version
    ):
        raise PermanentDeletionFingerprintMismatch(
            "El backend operacional cambió desde la confirmación."
        )

    _require_physical_row_locks(backend)
    operation_id = payload["operation_id"]
    committed_record: DeletionOperationRecord | None = None
    audit_eligible = False
    try:
        with backend.storage.atomic() as unit:
            if backend.backend_type == "DJANGO":
                if not isinstance(unit, DjangoDeletionLedgerUnitOfWork):
                    raise PermanentDeletionBackendError(
                        "La unidad transaccional Django no coincide con el backend."
                    )
                alias = unit.alias
                with bounded_django_lock_wait(alias):
                    lock_orm_task_company(alias, payload["empresa_id"])
                    committed_record, audit_eligible = _execute_locked(
                        reader_context=_reader_for_backend(backend),
                        backend=backend,
                        unit=unit,
                        payload=payload,
                    )
            else:
                if not isinstance(unit, MySQLDeletionLedgerUnitOfWork):
                    raise PermanentDeletionBackendError(
                        "La unidad transaccional MySQL no coincide con el backend."
                    )
                connection = unit.connection
                with bounded_mysql_lock_wait(connection):
                    lock_mysql_task_company(connection, payload["empresa_id"])
                    committed_record, audit_eligible = _execute_locked(
                        reader_context=_reader_for_backend(
                            backend,
                            operational_connection=connection,
                        ),
                        backend=backend,
                        unit=unit,
                        payload=payload,
                    )
    except DeletionLedgerCommitUncertain as exc:
        try:
            record = backend.storage.get_operation(operation_id)
        except Exception as reconcile_error:
            raise PermanentDeletionCommitUnresolved(
                "El resultado del commit es incierto y no se pudo reconciliar por UUID."
            ) from reconcile_error
        if record is None:
            raise PermanentDeletionCommitUnresolved(
                "No se repetirá la eliminación tras un commit incierto sin evidencia concluyente."
            ) from exc
        _validate_existing_operation(record, payload, backend)
        if record.status != "COMMITTED":
            raise PermanentDeletionCommitUnresolved(
                "El ledger no confirma el commit; no se repetirá la eliminación."
            ) from exc
        committed_record = record
        audit_eligible = True

    if committed_record is None:
        raise PermanentDeletionError(
            "El executor terminó sin un resultado de ledger."
        )
    if committed_record.status == "COMMITTED":
        if not audit_eligible:
            return _result_from_record(committed_record, backend.backend_type)
        return _deliver_audit_once(
            backend=backend,
            operation_id=operation_id,
            actor=actor,
            record=committed_record,
        )
    return _result_from_record(committed_record, backend.backend_type)


def reconcile_permanent_deletion_operation(
    *,
    actor,
    empresa_id: int,
    root_task_id: int,
    operation_id: UUID,
    fingerprint: str,
) -> PermanentDeletionResult:
    """Read the durable ledger state without retrying deletion, audit, or files."""
    actor = _authorized_actor_company(actor, empresa_id)
    root_task_id = _positive_id(root_task_id, "root_task_id")
    if not isinstance(operation_id, UUID):
        try:
            operation_id = UUID(str(operation_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise PermanentDeletionAuthorizationError(
                "operation_id no es un UUID válido."
            ) from exc
    if (
        not isinstance(fingerprint, str)
        or not _FINGERPRINT_PATTERN.fullmatch(fingerprint)
    ):
        raise PermanentDeletionFingerprintMismatch(
            "El fingerprint de reconciliación no es válido."
        )

    backend = _resolve_backend()
    try:
        with backend.storage.atomic() as unit:
            record = unit.get_operation(operation_id)
            if record is None:
                raise PermanentDeletionCommitUnresolved(
                    "El UUID no aparece en el ledger; no se autoriza un reintento automático."
                )
            if (
                record.actor_id != actor.pk
                or record.empresa_id != empresa_id
                or record.root_task_id != root_task_id
                or record.fingerprint != fingerprint
                or record.backend_type != backend.backend_type
                or record.backend_identity != backend.backend_identity
                or record.backend_config_version != backend.config_version
            ):
                raise DeletionLedgerConflict(
                    "El UUID no coincide con la identidad de la operación consultada."
                )
            if record.status != "COMMITTED":
                raise PermanentDeletionCommitUnresolved(
                    "El ledger no confirma el commit; no se repetirá la eliminación."
                )
            unit.verify_committed_inventory(operation_id)
    except PermanentDeletionError:
        raise
    except Exception as exc:
        raise PermanentDeletionCommitUnresolved(
            "No se pudo reconciliar la operación de forma segura."
        ) from exc
    return _result_from_record(record, backend.backend_type)


def _load_actor(actor_id: int) -> AbstractBaseUser:
    User = get_user_model()
    try:
        return User.objects.using("default").get(pk=actor_id, is_active=True)
    except User.DoesNotExist as exc:
        raise PermanentDeletionAuthorizationError(
            "El actor de confirmación no está activo."
        ) from exc


def _require_physical_row_locks(backend: _Backend) -> None:
    if backend.backend_type == "MYSQL_CONFIG":
        return
    alias = backend.context.django_alias
    if not alias:
        raise PermanentDeletionBackendError(
            "BASE_TAREAS no tiene un alias Django para validar locks."
        )
    connection = connections[alias]
    if (
        connection.vendor != "mysql"
        or not connection.features.supports_transactions
        or not connection.features.has_select_for_update
    ):
        raise TaskMutationLockUnsupported(
            "El backend Django no ofrece los locks físicos requeridos."
        )


def _execute_locked(
    *,
    reader_context: AbstractContextManager[_DjangoReader | _MySQLReader],
    backend: _Backend,
    unit: DjangoDeletionLedgerUnitOfWork | MySQLDeletionLedgerUnitOfWork,
    payload: _ConfirmationPayload,
) -> tuple[DeletionOperationRecord, bool]:
    with reader_context as reader:
        _require_reader_schema(reader)
        operation_id = payload["operation_id"]
        existing = unit.get_operation(operation_id)
        if existing is not None:
            _validate_existing_operation(existing, payload, backend)
            if existing.status == "COMMITTED":
                return existing, False
            raise DeletionLedgerStateError(
                "La operación ya tiene un estado PENDING; requiere reconciliación."
            )

        root_operation = unit.get_root_operation(
            payload["empresa_id"],
            payload["root_task_id"],
        )
        if root_operation is not None:
            raise DeletionLedgerConflict(
                "Ya existe una operación de eliminación para la raíz."
            )

        reader.task(payload["root_task_id"], payload["empresa_id"])
        initial_task_ids, hierarchy_blockers = _collect_hierarchy(
            reader,
            payload["root_task_id"],
            payload["empresa_id"],
        )
        if hierarchy_blockers:
            raise PermanentDeletionBlocked(hierarchy_blockers)

        if isinstance(reader, _DjangoReader):
            locked_tasks = lock_orm_task_rows(
                reader.alias,
                payload["empresa_id"],
                tuple(sorted(initial_task_ids)),
                require_row_locks=True,
            )
            locked_task_ids = tuple(task.pk for task in locked_tasks)
        else:
            locked_task_ids = lock_mysql_task_rows(
                reader.connection,
                payload["empresa_id"],
                tuple(sorted(initial_task_ids)),
            )
        if locked_task_ids != tuple(sorted(initial_task_ids)):
            raise TaskMutationScopeError(
                "No se pudieron bloquear todas las tareas del árbol."
            )

        _lock_hierarchy_rows(reader, tuple(sorted(initial_task_ids)))
        inventory = _build_internal_inventory(
            reader,
            backend,
            payload["root_task_id"],
            payload["empresa_id"],
        )
        if inventory.task_ids != tuple(sorted(initial_task_ids)):
            raise PermanentDeletionFingerprintMismatch(
                "La jerarquía cambió mientras se adquirían locks."
            )
        if inventory.blockers:
            raise PermanentDeletionBlocked(inventory.blockers)
        if not hmac.compare_digest(
            inventory.fingerprint,
            payload["fingerprint"],
        ):
            raise PermanentDeletionFingerprintMismatch(
                "El inventario bloqueado difiere de la confirmación."
            )
        if not inventory.deletion_order or len(inventory.deletion_order) != len(
            inventory.items
        ):
            raise PermanentDeletionBlocked(
                ["No existe un orden de eliminación completo y acíclico."]
            )

        _lock_manifest_rows(reader, inventory)
        locked_inventory = _build_internal_inventory(
            reader,
            backend,
            payload["root_task_id"],
            payload["empresa_id"],
        )
        if locked_inventory.blockers:
            raise PermanentDeletionBlocked(locked_inventory.blockers)
        if not hmac.compare_digest(
            locked_inventory.fingerprint,
            payload["fingerprint"],
        ):
            raise PermanentDeletionFingerprintMismatch(
                "El inventario cambió durante la revalidación bajo locks."
            )

        dependency_summary = dict(locked_inventory.counts)
        operation = DeletionOperationInput(
            actor_id=payload["actor_id"],
            empresa_id=payload["empresa_id"],
            root_task_id=payload["root_task_id"],
            root_correlativo=payload["root_correlativo"],
            fingerprint=locked_inventory.fingerprint,
            dependency_summary=dependency_summary,
            operation_id=operation_id,
        )
        pending = unit.create_pending(operation)
        if pending.status == "COMMITTED":
            return pending, False
        unit.save_manifest(
            operation_id,
            locked_inventory.items,
            locked_inventory.files,
        )

        allowed_items = set(locked_inventory.items)
        if len(locked_inventory.deletion_order) != len(allowed_items):
            raise PermanentDeletionBlocked(["El orden no coincide con el manifiesto."])
        for item in locked_inventory.deletion_order:
            _delete_manifest_item(reader, item, allowed_items)

        return unit.mark_committed(operation_id), True
