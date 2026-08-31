"""Read-only preflight checks for a future database migration."""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from django.apps import apps
from django.db import connections, models

from .comparison import compare_databases


DETAIL_LIMIT = 20
TECHNICAL_APP_LABELS = frozenset({"admin", "auth", "contenttypes", "sessions"})


class PreflightCheckStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    NOT_CHECKED = "NOT_CHECKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass
class PreflightCheck:
    key: str
    label: str
    status: PreflightCheckStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class PreflightResult:
    source_alias: str
    target_alias: str
    comparison: dict[str, Any]
    checks: list[PreflightCheck] = field(default_factory=list)

    @property
    def blocking_errors(self) -> list[PreflightCheck]:
        return [check for check in self.checks if check.status is PreflightCheckStatus.BLOCKED]

    @property
    def warnings(self) -> list[PreflightCheck]:
        return [check for check in self.checks if check.status is PreflightCheckStatus.WARNING]

    @property
    def status(self) -> str:
        if self.blocking_errors:
            return "BLOCKED"
        if self.warnings:
            return "WARNING"
        return "READY"

    @property
    def summary(self) -> dict[str, int]:
        return {
            "warning_count": len(self.warnings),
            "blocking_count": len(self.blocking_errors),
            "check_count": len(self.checks),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_alias": self.source_alias,
            "target_alias": self.target_alias,
            "comparison": self.comparison,
            "checks": [check.to_dict() for check in self.checks],
            "warnings": [check.to_dict() for check in self.warnings],
            "blocking_errors": [check.to_dict() for check in self.blocking_errors],
            "status": self.status,
            "summary": self.summary,
        }


def _check(key, label, status, message, **details):
    return PreflightCheck(key, label, status, message, details)


def _managed_models():
    return [
        model
        for model in apps.get_models(include_auto_created=True)
        if model._meta.managed and not model._meta.proxy
    ]


def _application_models(models_to_check):
    return [
        model for model in models_to_check
        if model._meta.app_label not in TECHNICAL_APP_LABELS
    ]


def _table_columns(connection, table):
    with connection.cursor() as cursor:
        return {
            column.name: column
            for column in connection.introspection.get_table_description(cursor, table)
        }


def _column_is_primary_key(column):
    return bool(getattr(column, "primary_key", False))


def _limit(values):
    values = list(values)
    return values[:DETAIL_LIMIT], len(values) > DETAIL_LIMIT


def _schema_check(source_alias, target_alias, models_to_check):
    source_connection = connections[source_alias]
    target_connection = connections[target_alias]
    missing = []
    incompatible = []
    for model in models_to_check:
        table = model._meta.db_table
        source_columns = _table_columns(source_connection, table)
        target_columns = _table_columns(target_connection, table)
        for field in model._meta.local_fields:
            column = field.column
            source_column = source_columns.get(column)
            target_column = target_columns.get(column)
            if source_column is None or target_column is None:
                missing.append({"table": table, "column": column, "side": "source" if source_column is None else "target"})
                continue
            if _column_is_primary_key(source_column) != _column_is_primary_key(target_column):
                incompatible.append({"table": table, "column": column, "reason": "primary_key"})
            if not field.null and bool(getattr(target_column, "null_ok", False)):
                incompatible.append({"table": table, "column": column, "reason": "target_allows_null"})
            source_size = getattr(source_column, "internal_size", None)
            target_size = getattr(target_column, "internal_size", None)
            if source_size and target_size and target_size < source_size:
                incompatible.append({"table": table, "column": column, "reason": "target_length_smaller"})
    if missing or incompatible:
        details = {"missing": _limit(missing)[0], "incompatible": _limit(incompatible)[0]}
        return _check("schema", "Schema", PreflightCheckStatus.BLOCKED, "Managed schema is incompatible.", **details)
    return _check("schema", "Schema", PreflightCheckStatus.PASS, "Managed columns are compatible.")


def _foreign_key_check(target_alias, models_to_check):
    connection = connections[target_alias]
    missing = []
    for model in models_to_check:
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, model._meta.db_table)
        relations = {
            (tuple(data.get("columns") or ()), data.get("foreign_key"))
            for data in constraints.values()
            if data.get("foreign_key")
        }
        for field in model._meta.local_fields:
            if not isinstance(field, models.ForeignKey):
                continue
            expected = ((field.column,), (field.target_field.model._meta.db_table, field.target_field.column))
            if expected not in relations:
                missing.append({"table": model._meta.db_table, "column": field.column, "target_table": expected[1][0]})
    if missing:
        items, truncated = _limit(missing)
        return _check("foreign_keys", "Foreign keys", PreflightCheckStatus.BLOCKED, "Required foreign keys are missing in the target.", missing=items, truncated=truncated)
    return _check("foreign_keys", "Foreign keys", PreflightCheckStatus.PASS, "Required foreign keys are present.")


def _unique_check(target_alias, models_to_check):
    connection = connections[target_alias]
    missing = []
    for model in models_to_check:
        expected = {(field.column,) for field in model._meta.local_fields if field.unique}
        expected.update(
            tuple(model._meta.get_field(field_name).column for field_name in constraint.fields)
            for constraint in model._meta.constraints
            if isinstance(constraint, models.UniqueConstraint) and constraint.fields
        )
        if not expected:
            continue
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, model._meta.db_table)
        actual = {tuple(data.get("columns") or ()) for data in constraints.values() if data.get("unique")}
        for columns in expected - actual:
            missing.append({"table": model._meta.db_table, "columns": columns})
    if missing:
        items, truncated = _limit(missing)
        return _check("unique_constraints", "Unique constraints", PreflightCheckStatus.BLOCKED, "Required unique constraints are missing in the target.", missing=items, truncated=truncated)
    return _check("unique_constraints", "Unique constraints", PreflightCheckStatus.PASS, "Required unique constraints are present.")


def _count_query(connection, sql):
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchone()[0] or 0


def _data_integrity_checks(source_alias, target_alias, models_to_check, comparison):
    source_connection = connections[source_alias]
    application_models = _application_models(models_to_check)
    target_has_data = [
        {"table": model._meta.db_table, "count": comparison["table_counts"].get(model._meta.db_table, {}).get("target", 0)}
        for model in application_models
        if comparison["table_counts"].get(model._meta.db_table, {}).get("target", 0) > 0
    ]
    checks = []
    if target_has_data:
        items, truncated = _limit(target_has_data)
        checks.append(_check("destination_data", "Destination data", PreflightCheckStatus.WARNING, "The target already contains application data.", tables=items, truncated=truncated))
    else:
        checks.append(_check("destination_data", "Destination data", PreflightCheckStatus.PASS, "The target has no application data."))

    high_pk = []
    for model in application_models:
        values = comparison["pk_max_values"].get(model._meta.db_table, {})
        source_max, target_max = values.get("source"), values.get("target")
        if source_max is not None and target_max is not None and target_max > source_max:
            high_pk.append({"table": model._meta.db_table, "source_max_pk": source_max, "target_max_pk": target_max})
    if high_pk:
        items, truncated = _limit(high_pk)
        checks.append(_check("pk_max", "Maximum PK values", PreflightCheckStatus.WARNING, "Target PK values exceed source values.", tables=items, truncated=truncated))
    else:
        checks.append(_check("pk_max", "Maximum PK values", PreflightCheckStatus.PASS, "Target PK values do not exceed source values."))

    orphan_details = []
    null_details = []
    length_details = []
    for model in models_to_check:
        table = source_connection.ops.quote_name(model._meta.db_table)
        for field in model._meta.local_fields:
            column = source_connection.ops.quote_name(field.column)
            if isinstance(field, models.ForeignKey):
                target_table = source_connection.ops.quote_name(field.target_field.model._meta.db_table)
                target_column = source_connection.ops.quote_name(field.target_field.column)
                orphan_count = _count_query(source_connection, f"SELECT COUNT(*) FROM {table} src LEFT JOIN {target_table} ref ON src.{column} = ref.{target_column} WHERE src.{column} IS NOT NULL AND ref.{target_column} IS NULL")
                if orphan_count:
                    orphan_details.append({"table": model._meta.db_table, "fk_column": field.column, "target_table": field.target_field.model._meta.db_table, "orphan_count": orphan_count})
            if not field.null and not field.primary_key:
                null_count = _count_query(source_connection, f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL")
                if null_count:
                    null_details.append({"table": model._meta.db_table, "column": field.column, "invalid_null_count": null_count})
            if isinstance(field, models.CharField) and field.max_length:
                max_found = _count_query(source_connection, f"SELECT MAX(LENGTH({column})) FROM {table}")
                if max_found > field.max_length:
                    length_details.append({"table": model._meta.db_table, "column": field.column, "max_allowed": field.max_length, "max_found": max_found})
    for key, label, details, message in (
        ("orphans", "Referential integrity", orphan_details, "Source contains orphan foreign keys."),
        ("required_nulls", "Required nulls", null_details, "Source contains invalid null values."),
        ("text_length", "Text length", length_details, "Source text exceeds the model limit."),
    ):
        if details:
            items, truncated = _limit(details)
            checks.append(_check(key, label, PreflightCheckStatus.BLOCKED, message, items=items, truncated=truncated))
        else:
            checks.append(_check(key, label, PreflightCheckStatus.PASS, "No incompatibilities detected."))
    return checks


def _destination_check(target_alias):
    connection = connections[target_alias]
    details = {"vendor": connection.vendor, "transactions_supported": connection.features.supports_transactions}
    if not connection.features.supports_transactions:
        return _check("destination", "Destination capabilities", PreflightCheckStatus.BLOCKED, "Target does not support transactions.", **details)
    if connection.vendor == "mysql":
        charset = (connection.settings_dict.get("OPTIONS") or {}).get("charset")
        if charset and charset.lower() != "utf8mb4":
            return _check("destination", "Destination capabilities", PreflightCheckStatus.WARNING, "Target charset is not utf8mb4.", **details)
    return _check("destination", "Destination capabilities", PreflightCheckStatus.PASS, "Target connection supports transactions.", **details)


def _autoincrement_check(models_to_check, comparison):
    tables = []
    for model in models_to_check:
        if isinstance(model._meta.pk, models.AutoField):
            values = comparison["pk_max_values"].get(model._meta.db_table, {})
            tables.append({"table": model._meta.db_table, "pk_column": model._meta.pk.column, "source_max_pk": values.get("source"), "target_max_pk": values.get("target"), "target_autoincrement_detected": None})
    return _check("autoincrement", "Autoincrement strategy", PreflightCheckStatus.NOT_CHECKED, "Portable autoincrement detection is not available.", tables=tables[:DETAIL_LIMIT], truncated=len(tables) > DETAIL_LIMIT)


def run_preflight(source_alias: str, target_alias: str) -> PreflightResult:
    """Run read-only readiness checks for a future data migration."""
    comparison = compare_databases(source_alias, target_alias).to_dict()
    result = PreflightResult(source_alias, target_alias, comparison)
    classification_status = PreflightCheckStatus.PASS if comparison["source_classification"] == "SYSTEM" and comparison["target_classification"] == "SYSTEM" else PreflightCheckStatus.BLOCKED
    result.checks.append(_check("classification", "Classification", classification_status, "Aliases are classified as SYSTEM." if classification_status is PreflightCheckStatus.PASS else "Only SYSTEM aliases are allowed.", source=comparison["source_classification"], target=comparison["target_classification"]))
    if comparison["status"] == "BLOCKED":
        result.checks.append(_check("comparison", "Basic comparison", PreflightCheckStatus.BLOCKED, "Basic comparison is blocked; dependent checks were not run.", errors=comparison["blocking_errors"][:DETAIL_LIMIT]))
        return result

    for key, label, valid, details in (
        ("migrations", "Migrations", comparison["migration_sets_equal"], {"only_source": comparison["migrations_only_source"][:DETAIL_LIMIT], "only_target": comparison["migrations_only_target"][:DETAIL_LIMIT]}),
        ("managed_tables", "Managed tables", not comparison["missing_in_source"] and not comparison["missing_in_target"], {"missing_in_source": comparison["missing_in_source"][:DETAIL_LIMIT], "missing_in_target": comparison["missing_in_target"][:DETAIL_LIMIT]}),
        ("managed_false", "External managed=False tables", not comparison["managed_false_tables_present"], {"tables": comparison["managed_false_tables_present"][:DETAIL_LIMIT]}),
    ):
        result.checks.append(_check(key, label, PreflightCheckStatus.PASS if valid else PreflightCheckStatus.BLOCKED, "Check passed." if valid else "Check failed.", **details))

    models_to_check = _managed_models()
    result.checks.extend([
        _schema_check(source_alias, target_alias, models_to_check),
        _foreign_key_check(target_alias, models_to_check),
        _unique_check(target_alias, models_to_check),
        _destination_check(target_alias),
        _autoincrement_check(models_to_check, comparison),
    ])
    result.checks.extend(_data_integrity_checks(source_alias, target_alias, models_to_check, comparison))
    decimal_models = [model._meta.db_table for model in models_to_check if any(isinstance(field, models.DecimalField) for field in model._meta.local_fields)]
    result.checks.append(_check("decimal", "Decimal compatibility", PreflightCheckStatus.NOT_CHECKED, "Portable decimal range validation is not implemented.", tables=decimal_models[:DETAIL_LIMIT]))
    json_models = [model._meta.db_table for model in models_to_check if any(isinstance(field, models.JSONField) for field in model._meta.local_fields)]
    result.checks.append(_check("json", "JSON compatibility", PreflightCheckStatus.NOT_CHECKED if json_models else PreflightCheckStatus.NOT_APPLICABLE, "JSON values are not inspected." if json_models else "No JSON fields apply.", tables=json_models[:DETAIL_LIMIT]))
    return result
