"""Read-only comparison of two configured Django database aliases."""

from dataclasses import asdict, dataclass, field
from typing import Any

from django.apps import apps
from django.db import connections, models

from common.database_classification import (
    DatabaseClassification,
    get_database_classification,
)


@dataclass(frozen=True)
class DatabaseSnapshot:
    alias: str
    vendor: str
    migrations: frozenset[tuple[str, str]]
    tables: frozenset[str]
    table_counts: dict[str, int]
    pk_max_values: dict[str, Any]


@dataclass
class DatabaseComparisonResult:
    source_alias: str
    target_alias: str
    source_classification: str
    target_classification: str
    source_vendor: str | None = None
    target_vendor: str | None = None
    migration_sets_equal: bool = False
    source_migration_count: int = 0
    target_migration_count: int = 0
    migrations_only_source: list[tuple[str, str]] = field(default_factory=list)
    migrations_only_target: list[tuple[str, str]] = field(default_factory=list)
    managed_tables_expected: list[str] = field(default_factory=list)
    source_tables: list[str] = field(default_factory=list)
    target_tables: list[str] = field(default_factory=list)
    missing_in_source: list[str] = field(default_factory=list)
    missing_in_target: list[str] = field(default_factory=list)
    table_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    pk_max_values: dict[str, dict[str, Any]] = field(default_factory=dict)
    managed_false_tables_present: list[str] = field(default_factory=list)
    blocking_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = 'BLOCKED'

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _managed_models():
    return [
        model
        for model in apps.get_models(include_auto_created=True)
        if model._meta.managed and not model._meta.proxy
    ]


def _unmanaged_tables():
    return {
        model._meta.db_table
        for model in apps.get_models(include_auto_created=True)
        if not model._meta.managed and not model._meta.proxy
    }


def _read_snapshot(alias: str, managed_models: list[type[models.Model]]) -> DatabaseSnapshot:
    connection = connections[alias]
    table_names = frozenset(connection.introspection.table_names())
    if 'django_migrations' not in table_names:
        raise RuntimeError(f'{alias}: missing django_migrations table')

    migrations = frozenset()
    table_counts: dict[str, int] = {}
    pk_max_values: dict[str, Any] = {}
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT app, name FROM {connection.ops.quote_name("django_migrations")} '
            'ORDER BY app, name'
        )
        migrations = frozenset((row[0], row[1]) for row in cursor.fetchall())
        for model in managed_models:
            table = model._meta.db_table
            if table not in table_names:
                continue
            quoted_table = connection.ops.quote_name(table)
            cursor.execute(f'SELECT COUNT(*) FROM {quoted_table}')
            table_counts[table] = cursor.fetchone()[0]
            if isinstance(model._meta.pk, models.IntegerField):
                cursor.execute(
                    f'SELECT MAX({connection.ops.quote_name(model._meta.pk.column)}) '
                    f'FROM {quoted_table}'
                )
                pk_max_values[table] = cursor.fetchone()[0]

    return DatabaseSnapshot(
        alias=alias,
        vendor=connection.vendor,
        migrations=migrations,
        tables=table_names,
        table_counts=table_counts,
        pk_max_values=pk_max_values,
    )


def compare_databases(source_alias: str, target_alias: str) -> DatabaseComparisonResult:
    """Compare schema metadata and counts without writing either database."""
    source_classification = get_database_classification(source_alias)
    target_classification = get_database_classification(target_alias)
    result = DatabaseComparisonResult(
        source_alias=source_alias,
        target_alias=target_alias,
        source_classification=source_classification.value,
        target_classification=target_classification.value,
    )
    if source_classification is DatabaseClassification.UNKNOWN:
        result.blocking_errors.append('source alias has UNKNOWN classification')
    if target_classification is not DatabaseClassification.SYSTEM:
        result.blocking_errors.append('target alias is not classified as SYSTEM')
    if result.blocking_errors:
        return result

    managed_models = _managed_models()
    result.managed_tables_expected = sorted({model._meta.db_table for model in managed_models})
    try:
        source = _read_snapshot(source_alias, managed_models)
        target = _read_snapshot(target_alias, managed_models)
    except Exception as exc:
        result.blocking_errors.append(str(exc))
        return result

    result.source_vendor = source.vendor
    result.target_vendor = target.vendor
    result.source_tables = sorted(source.tables)
    result.target_tables = sorted(target.tables)
    result.source_migration_count = len(source.migrations)
    result.target_migration_count = len(target.migrations)
    result.migration_sets_equal = source.migrations == target.migrations
    result.migrations_only_source = sorted(source.migrations - target.migrations)
    result.migrations_only_target = sorted(target.migrations - source.migrations)
    result.missing_in_source = sorted(set(result.managed_tables_expected) - source.tables)
    result.missing_in_target = sorted(set(result.managed_tables_expected) - target.tables)

    for table in sorted(set(source.table_counts) & set(target.table_counts)):
        result.table_counts[table] = {
            'source': source.table_counts[table],
            'target': target.table_counts[table],
            'difference': target.table_counts[table] - source.table_counts[table],
        }
    for table in sorted(set(source.pk_max_values) | set(target.pk_max_values)):
        result.pk_max_values[table] = {
            'source': source.pk_max_values.get(table),
            'target': target.pk_max_values.get(table),
        }

    result.managed_false_tables_present = sorted(_unmanaged_tables() & target.tables)
    if not result.migration_sets_equal:
        result.blocking_errors.append('migration sets are different')
    if result.missing_in_source:
        result.blocking_errors.append('managed tables are missing in source')
    if result.missing_in_target:
        result.blocking_errors.append('managed tables are missing in target')
    if result.managed_false_tables_present:
        result.blocking_errors.append('managed=False tables are present in target')
    if any(item['difference'] for item in result.table_counts.values()):
        result.warnings.append('table row counts differ')
    result.status = 'COMPATIBLE' if not result.blocking_errors else 'BLOCKED'
    return result
