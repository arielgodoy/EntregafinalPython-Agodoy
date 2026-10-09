"""Bootstrap idempotente del schema operacional MySQL de Tareas."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from django.apps import apps
from django.db.backends.mysql.schema import DatabaseSchemaEditor

from settings.services.mysql_connections import (
    MySQLConnectionOpenError,
    open_mysql_connection,
)

from ..models import TareaConnectionRole
from .connection_roles import get_tarea_connection, get_tarea_mysql_connection
from .reference_data import (
    BaseTareasReferenceDataError,
    ensure_mysql_delay_causes,
    inspect_mysql_delay_causes,
)


class BaseTareasSchemaInstallError(RuntimeError):
    """Error seguro al preparar la estructura operacional de Tareas."""


_FORBIDDEN_SQL = re.compile(r"\b(?:DROP|TRUNCATE|DELETE)\b", re.IGNORECASE)
_DESTRUCTIVE_ALTER = re.compile(
    r"\bALTER\s+TABLE\b.*\b(?:DROP|MODIFY|CHANGE|RENAME)\b",
    re.IGNORECASE,
)
_CREATE_TABLE = re.compile(r"^CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)", re.IGNORECASE)
_CREATE_OBJECT = re.compile(
    r"^CREATE\s+(?P<unique>UNIQUE\s+)?INDEX\s+`?(?P<name>[A-Za-z0-9_]+)`?\s+ON\s+`?(?P<table>[A-Za-z0-9_]+)`?",
    re.IGNORECASE,
)
_ADD_CONSTRAINT = re.compile(
    r"^ALTER\s+TABLE\s+`?(?P<table>[A-Za-z0-9_]+)`?\s+ADD\s+CONSTRAINT\s+`?(?P<name>[A-Za-z0-9_]+)`?",
    re.IGNORECASE,
)
_TABLE_NAME = re.compile(
    r"^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(?P<table>[A-Za-z0-9_]+)`?",
    re.IGNORECASE,
)
_CREATE_INDEX = re.compile(
    r"^CREATE\s+(?:UNIQUE\s+)?INDEX\s+`?(?P<name>[A-Za-z0-9_]+)`?\s+ON\s+`?(?P<table>[A-Za-z0-9_]+)`?",
    re.IGNORECASE,
)
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "sql" / "base_tareas_schema.sql"


EXPECTED_OPERATIONAL_MODELS = (
    "Tarea",
    "EvaluacionSimilitud",
    "UmbralSimilitudEmpresa",
    "ReunionRevision",
    "ReunionTarea",
    "ReunionParticipante",
    "Avance",
    "Hito",
    "HitoHistorial",
    "HitoEvidencia",
    "MiniTarea",
    "MiniTareaEvento",
    "DocumentoTarea",
    "DocumentoHistorial",
    "EvidenciaCierre",
    "CorrelativoEmpresa",
    "CorrelativoTodoEmpresa",
    "Todo",
    "TodoEvento",
    "TareaTransicion",
    "TareaCierre",
    "TareaAnulacionSnapshot",
    "TareaParticipante",
    "TareaLectura",
    "Comentario",
    "ComentarioAdjunto",
    "ComentarioVersion",
    "ComentarioVersionDocumento",
    "ComentarioPausaLectura",
    "EnlaceTarea",
    "EventoAccesoEnlace",
    "TareaReasignacion",
    "CausaAtraso",
    "Reprogramacion",
    "TareaRelacion",
    "RondaCotizacion",
    "Cotizacion",
    "DocumentoCotizacion",
)


def get_operational_models():
    """Return every Tareas model except the connection-role configuration."""
    configured_models = apps.get_app_config("tareas").get_models()
    models = tuple(
        model
        for model in configured_models
        if model is not TareaConnectionRole
        and model.__name__ in EXPECTED_OPERATIONAL_MODELS
    )
    if {model.__name__ for model in models} != set(EXPECTED_OPERATIONAL_MODELS):
        raise BaseTareasSchemaInstallError(
            "El inventario de modelos operacionales de Tareas no coincide con el contrato."
        )
    return models


def _is_external_foreign_key(statement: str) -> bool:
    upper = statement.upper()
    if "FOREIGN KEY" not in upper or "REFERENCES" not in upper:
        return False
    return "TAREAS_" not in upper.split("REFERENCES", 1)[1]


def _normalize_statement(statement: str) -> str:
    normalized = statement.strip()
    normalized = _CREATE_TABLE.sub("CREATE TABLE IF NOT EXISTS ", normalized)
    if _FORBIDDEN_SQL.search(normalized) or _DESTRUCTIVE_ALTER.search(normalized):
        raise BaseTareasSchemaInstallError(
            "La estructura Base Tareas contiene una operación no permitida."
        )
    return normalized


def build_base_tareas_schema_statements(connection) -> list[str]:
    """Collect MySQL DDL from current models without executing it."""
    collected: list[str] = []
    with DatabaseSchemaEditor(connection, collect_sql=True) as editor:
        for model in get_operational_models():
            editor.create_model(model)
    collected.extend(editor.collected_sql)

    statements = []
    for statement in collected:
        if _is_external_foreign_key(statement):
            continue
        normalized = _normalize_statement(statement)
        if normalized:
            statements.append(normalized)
    if not statements:
        raise BaseTareasSchemaInstallError(
            "No se pudo generar la estructura Base Tareas."
        )
    return statements


def _read_frozen_schema_statements() -> list[str]:
    try:
        content = SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo leer la estructura congelada de Base Tareas."
        ) from exc
    content = "\n".join(
        line for line in content.splitlines() if not line.lstrip().startswith("--")
    )
    statements = [item.strip() for item in content.split(";") if item.strip()]
    if not statements:
        raise BaseTareasSchemaInstallError(
            "La estructura congelada de Base Tareas está vacía."
        )
    for statement in statements:
        _normalize_statement(statement)
    return statements


def _split_sql_items(value: str) -> list[str]:
    items = []
    start = 0
    depth = 0
    quote = None
    for index, char in enumerate(value):
        if quote:
            if char == quote and (index == 0 or value[index - 1] != "\\"):
                quote = None
            continue
        if char in {"`", "'", '"'}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            items.append(value[start:index].strip())
            start = index + 1
    tail = value[start:].strip()
    if tail:
        items.append(tail)
    return items


def _normalize_schema_type(value: str | None) -> str:
    normalized = re.sub(r"\s+", " ", (value or "").strip().lower())
    normalized = re.sub(r"\s*,\s*", ",", normalized)
    normalized = re.sub(
        r"\b(tinyint|smallint|mediumint|int|integer|bigint)\(\d+\)",
        r"\1",
        normalized,
    )
    normalized = normalized.replace("integer", "int")
    normalized = normalized.replace("numeric", "decimal")
    normalized = re.sub(r"\bbool(?:ean)?\b", "tinyint", normalized)
    return normalized


def _column_names(value: str) -> tuple[str, ...]:
    return tuple(
        item.strip().strip("` ")
        for item in value.split(",")
        if item.strip()
    )


def _parse_foreign_key(statement: str) -> tuple[tuple[str, ...], str, tuple[str, ...]] | None:
    match = re.search(
        r"FOREIGN\s+KEY\s*\((?P<columns>[^)]*)\)\s+REFERENCES\s+"
        r"`?(?P<table>[A-Za-z0-9_]+)`?\s*\((?P<target>[^)]*)\)",
        statement,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return (
        _column_names(match.group("columns")),
        match.group("table"),
        _column_names(match.group("target")),
    )


def _parse_expected_schema(statements: list[str]) -> dict[str, Any]:
    schema = {
        "tables": {},
        "indexes": {},
        "foreign_keys": set(),
    }
    for statement in statements:
        table_match = _TABLE_NAME.match(statement)
        if table_match:
            table = table_match.group("table")
            opening = statement.find("(")
            closing = statement.rfind(")")
            body = statement[opening + 1:closing]
            table_info = {
                "columns": {},
                "primary": (),
                "unique": set(),
                "ordinary": set(),
            }
            for item in _split_sql_items(body):
                upper = item.upper()
                if upper.startswith("PRIMARY KEY"):
                    match = re.search(r"\(([^)]*)\)", item)
                    if match:
                        table_info["primary"] = _column_names(match.group(1))
                    continue
                if "FOREIGN KEY" in upper:
                    foreign_key = _parse_foreign_key(item)
                    if foreign_key:
                        schema["foreign_keys"].add((table, *foreign_key))
                    continue
                if upper.startswith("UNIQUE") or " UNIQUE " in f" {upper} ":
                    match = re.search(r"\(([^)]*)\)", item)
                    if match:
                        table_info["unique"].add(_column_names(match.group(1)))
                    continue
                if upper.startswith(("KEY ", "INDEX ")):
                    match = re.search(r"\(([^)]*)\)", item)
                    if match:
                        table_info["ordinary"].add(_column_names(match.group(1)))
                    continue
                if upper.startswith(("CONSTRAINT ", "CHECK ")):
                    continue
                column_match = re.match(
                    r"`?(?P<column>[A-Za-z0-9_]+)`?\s+"
                    r"(?P<type>[A-Za-z]+(?:\s+unsigned)?(?:\s*\([^)]*\))?)"
                    r"(?P<rest>.*)$",
                    item,
                    re.IGNORECASE,
                )
                if column_match:
                    rest = column_match.group("rest")
                    table_info["columns"][column_match.group("column")] = {
                        "type": _normalize_schema_type(column_match.group("type")),
                        "nullable": "NO" if re.search(r"\bNOT\s+NULL\b", rest, re.I) else "YES",
                        "auto_increment": bool(re.search(r"\bAUTO_INCREMENT\b", rest, re.I)),
                    }
            schema["tables"][table] = table_info
            continue

        index_match = _CREATE_INDEX.match(statement)
        if index_match:
            match = re.search(r"\(([^)]*)\)", statement)
            if match:
                table = index_match.group("table")
                schema["indexes"].setdefault(table, []).append(
                    {
                        "unique": bool(re.match(r"^CREATE\s+UNIQUE", statement, re.I)),
                        "columns": _column_names(match.group(1)),
                    }
                )
            continue

        constraint_match = _ADD_CONSTRAINT.match(statement)
        if constraint_match:
            foreign_key = _parse_foreign_key(statement)
            if foreign_key:
                schema["foreign_keys"].add(
                    (constraint_match.group("table"), *foreign_key)
                )

    for table, entries in schema["indexes"].items():
        schema["tables"].setdefault(
            table,
            {"columns": {}, "primary": (), "unique": set(), "ordinary": set()},
        )
        for entry in entries:
            target = (
                schema["tables"][table]["unique"]
                if entry["unique"]
                else schema["tables"][table]["ordinary"]
            )
            target.add(entry["columns"])
    return schema


def _fetch_schema_snapshot(connection, database_name: str) -> dict[str, Any]:
    statements = _read_frozen_schema_statements()
    expected = _parse_expected_schema(statements)
    tables = tuple(expected["tables"])
    placeholders = ", ".join(["%s"] * len(tables))
    params = (database_name, *tables)
    actual: dict[str, Any] = {
        "tables": {},
        "columns": {},
        "indexes": {},
        "foreign_keys": set(),
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT TABLE_NAME, TABLE_TYPE, ENGINE, TABLE_COLLATION "
            "FROM INFORMATION_SCHEMA.TABLES "
            f"WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({placeholders})",
            params,
        )
        for row in cursor.fetchall():
            actual["tables"][row[0]] = {
                "type": row[1],
                "engine": row[2],
                "collation": row[3],
            }
        cursor.execute(
            "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, EXTRA "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({placeholders}) "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION",
            params,
        )
        for table, column, column_type, nullable, extra in cursor.fetchall():
            actual["columns"].setdefault(table, {})[column] = {
                "type": _normalize_schema_type(column_type),
                "nullable": nullable,
                "auto_increment": "auto_increment" in (extra or "").lower(),
            }
        cursor.execute(
            "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME "
            "FROM INFORMATION_SCHEMA.STATISTICS "
            f"WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({placeholders}) "
            "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX",
            params,
        )
        grouped_indexes: dict[tuple[str, str], list[tuple[int, str, int]]] = {}
        for table, name, non_unique, sequence, column in cursor.fetchall():
            grouped_indexes.setdefault((table, name), []).append(
                (sequence, column, non_unique)
            )
        for (table, name), entries in grouped_indexes.items():
            ordered_entries = sorted(entries)
            columns = tuple(column for _sequence, column, _non_unique in ordered_entries)
            actual["indexes"].setdefault(table, []).append(
                {
                    "name": name,
                    "unique": name == "PRIMARY" or not bool(ordered_entries[0][2]),
                    "columns": columns,
                }
            )
        cursor.execute(
            "SELECT TABLE_NAME, CONSTRAINT_NAME, COLUMN_NAME, "
            "REFERENCED_TABLE_SCHEMA, REFERENCED_TABLE_NAME, "
            "REFERENCED_COLUMN_NAME "
            "FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE "
            f"WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({placeholders}) "
            "AND REFERENCED_TABLE_NAME IS NOT NULL "
            "ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION",
            params,
        )
        grouped_fks: dict[tuple[str, str], list[tuple[str, str, str, str]]] = {}
        for table, name, column, target_schema, target_table, target_column in cursor.fetchall():
            grouped_fks.setdefault((table, name), []).append(
                (column, target_schema, target_table, target_column)
            )
        for (table, _name), entries in grouped_fks.items():
            actual["foreign_keys"].add(
                (
                    table,
                    tuple(entry[0] for entry in entries),
                    entries[0][1],
                    entries[0][2],
                    tuple(entry[3] for entry in entries),
                )
            )
    return {"expected": expected, "actual": actual}


def _snapshot_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    expected = snapshot["expected"]
    actual = snapshot["actual"]
    return {
        "expected_tables": {
            table: {
                "columns": expected_info["columns"],
                "primary": expected_info["primary"],
                "unique": sorted(expected_info["unique"]),
                "ordinary": sorted(expected_info["ordinary"]),
            }
            for table, expected_info in sorted(expected["tables"].items())
        },
        "expected_foreign_keys": sorted(expected["foreign_keys"]),
        "actual_tables": actual["tables"],
        "actual_columns": actual["columns"],
        "actual_indexes": {
            table: sorted(
                (
                    item["name"],
                    item["unique"],
                    item["columns"],
                )
                for item in items
            )
            for table, items in actual["indexes"].items()
        },
        "actual_foreign_keys": sorted(actual["foreign_keys"]),
    }


def _schema_fingerprint(
    database_name: str,
    connection_id: int,
    snapshot: dict[str, Any],
) -> str:
    payload = {
        "role": "BASE_TAREAS",
        "connection_id": connection_id,
        "database_name": database_name,
        "schema_file": str(SCHEMA_PATH),
        "schema": _snapshot_payload(snapshot),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _compare_schema_snapshot(
    snapshot: dict[str, Any],
    database_name: str,
) -> dict[str, Any]:
    expected = snapshot["expected"]
    actual = snapshot["actual"]
    table_results = []
    for table, expected_info in expected["tables"].items():
        if table not in actual["tables"]:
            table_results.append(
                {
                    "name": table,
                    "status": "missing",
                    "classification": "PENDIENTE_CREACION",
                    "issues": [],
                    "column_differences": [],
                }
            )
            continue

        table_info = actual["tables"][table]
        issues: list[str] = []
        differences: list[dict[str, Any]] = []
        if table_info["type"] != "BASE TABLE":
            issues.append("OBJECT_TYPE_MISMATCH")
        if table_info["engine"] != "InnoDB":
            issues.append("ENGINE_MISMATCH")
        if table_info["collation"] != "utf8mb4_unicode_ci":
            issues.append("COLLATION_MISMATCH")

        actual_columns = actual["columns"].get(table, {})
        expected_columns = expected_info["columns"]
        if set(actual_columns) != set(expected_columns):
            issues.append("COLUMN_SET_MISMATCH")
        for column in sorted(set(actual_columns) & set(expected_columns)):
            expected_column = expected_columns[column]
            actual_column = actual_columns[column]
            if expected_column["type"] != actual_column["type"]:
                issues.append("COLUMN_TYPE_MISMATCH")
                differences.append(
                    {
                        "column": column,
                        "expected_type": expected_column["type"],
                        "actual_type": actual_column["type"],
                        "expected_nullability": expected_column["nullable"],
                        "actual_nullability": actual_column["nullable"],
                        "action_proposed": "Revisión manual",
                        "risk": "No se modifica automáticamente",
                    }
                )
            if expected_column["nullable"] != actual_column["nullable"]:
                issues.append("NULLABILITY_MISMATCH")
            if expected_column["auto_increment"] != actual_column["auto_increment"]:
                issues.append("AUTO_INCREMENT_MISMATCH")

        actual_indexes = actual["indexes"].get(table, [])
        actual_primary = next(
            (item["columns"] for item in actual_indexes if item["name"] == "PRIMARY"),
            (),
        )
        if actual_primary != expected_info["primary"]:
            issues.append("PRIMARY_KEY_MISMATCH")
        actual_unique = {
            item["columns"]
            for item in actual_indexes
            if item["unique"] and item["name"] != "PRIMARY"
        }
        actual_ordinary = {
            item["columns"]
            for item in actual_indexes
            if not item["unique"] and item["name"] != "PRIMARY"
        }
        if not expected_info["unique"].issubset(actual_unique):
            issues.append("UNIQUE_CONSTRAINT_MISSING")
        if expected_info["unique"] - actual_unique:
            issues.append("UNIQUE_CONSTRAINT_MISMATCH")
        if not expected_info["ordinary"].issubset(actual_ordinary):
            issues.append("INDEX_MISSING")

        expected_foreign_keys = {
            (columns, target_table, target_columns)
            for target_table_name, columns, target_table, target_columns
            in expected["foreign_keys"]
            if target_table_name == table
        }
        actual_foreign_keys = {
            (columns, target_table, target_columns)
            for source_table, columns, target_schema, target_table, target_columns
            in actual["foreign_keys"]
            if source_table == table
            and target_schema.casefold() == database_name.casefold()
        }
        if any(
            source_table == table
            and (
                target_schema.casefold() != database_name.casefold()
                or target_table not in expected["tables"]
            )
            for source_table, _columns, target_schema, target_table, _target_columns
            in actual["foreign_keys"]
        ):
            issues.append("CROSS_DATABASE_FOREIGN_KEY")
        if actual_foreign_keys != expected_foreign_keys:
            issues.append("FOREIGN_KEY_MISMATCH")

        table_results.append(
            {
                "name": table,
                "status": "conflict" if issues else "existing",
                "classification": "INCOMPATIBLE" if issues else "COMPATIBLE",
                "issues": sorted(set(issues)),
                "column_differences": differences,
            }
        )

    return {
        "tables": table_results,
        "existing": [
            item["name"] for item in table_results if item["status"] == "existing"
        ],
        "missing": [
            item["name"] for item in table_results if item["status"] == "missing"
        ],
        "conflicts": [
            item for item in table_results if item["status"] == "conflict"
        ],
    }


def preview_base_tareas_schema() -> dict[str, Any]:
    """Inspect BASE_TAREAS without executing DDL or seed operations."""
    source = get_tarea_connection("BASE_TAREAS")
    if source["type"] != "MYSQL_CONFIG":
        raise BaseTareasSchemaInstallError(
            "BASE_TAREAS utiliza Django y no requiere bootstrap MySQL."
        )
    connection_config = get_tarea_mysql_connection("BASE_TAREAS")
    database_name = source.get("database_name")
    if not isinstance(database_name, str):
        raise BaseTareasSchemaInstallError(
            "La base de BASE_TAREAS no está configurada."
        )
    try:
        with open_mysql_connection(
            connection_config,
            database_name=database_name,
        ) as connection:
            snapshot = _fetch_schema_snapshot(connection, database_name)
            result = _compare_schema_snapshot(snapshot, database_name)
            if not result["missing"] and not result["conflicts"]:
                (
                    result["reference_data_complete"],
                    result["reference_data_missing_count"],
                ) = inspect_mysql_delay_causes(connection)
            else:
                result["reference_data_complete"] = None
                result["reference_data_missing_count"] = None
    except MySQLConnectionOpenError as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo abrir la conexión de BASE_TAREAS."
        ) from exc
    except BaseTareasSchemaInstallError:
        raise
    except Exception as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo inspeccionar la estructura Base Tareas."
        ) from exc
    result.update(
        {
            "backend": "mysql",
            "database_name": database_name,
            "connection_id": int(source["connection_id"]),
            "connection_updated_at": connection_config.updated_at.isoformat(),
            "fingerprint": _schema_fingerprint(
                database_name,
                int(source["connection_id"]),
                snapshot,
            ),
        }
    )
    return result


def complete_base_tareas_reference_data(
    *,
    expected_connection_id: int,
    expected_connection_updated_at: str,
    expected_database_name: str,
    expected_fingerprint: str,
) -> int:
    """Revalidate the signed target and compatible schema before running seed DML."""
    try:
        source = get_tarea_connection("BASE_TAREAS")
        if source["type"] != "MYSQL_CONFIG":
            raise BaseTareasSchemaInstallError(
                "BASE_TAREAS utiliza Django y no requiere seed MySQL."
            )
        connection_config = get_tarea_mysql_connection("BASE_TAREAS")
        database_name = source.get("database_name")
        if (
            int(source["connection_id"]) != expected_connection_id
            or connection_config.updated_at.isoformat()
            != expected_connection_updated_at
            or database_name != expected_database_name
        ):
            raise BaseTareasSchemaInstallError(
                "La configuración de BASE_TAREAS cambió; vuelva a inspeccionar."
            )
        with open_mysql_connection(
            connection_config,
            database_name=database_name,
        ) as connection:
            snapshot = _fetch_schema_snapshot(connection, database_name)
            plan = _compare_schema_snapshot(snapshot, database_name)
            current_fingerprint = _schema_fingerprint(
                database_name,
                int(source["connection_id"]),
                snapshot,
            )
            if (
                plan["missing"]
                or plan["conflicts"]
                or current_fingerprint != expected_fingerprint
            ):
                raise BaseTareasSchemaInstallError(
                    "La estructura ya no coincide con la vista previa; "
                    "no se completaron los datos base."
                )
            reference_data_complete, _missing_count = inspect_mysql_delay_causes(
                connection
            )
            if reference_data_complete:
                return 0
            return ensure_mysql_delay_causes(connection)
    except BaseTareasSchemaInstallError:
        raise
    except BaseTareasReferenceDataError as exc:
        raise BaseTareasSchemaInstallError(str(exc)) from exc
    except MySQLConnectionOpenError as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo abrir la conexión de BASE_TAREAS."
        ) from exc
    except Exception as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudieron completar los datos base de Tareas."
        ) from exc


def _metadata_exists(cursor, statement: str, database_name: str) -> bool:
    table_match = re.search(
        r"^CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+`?([A-Za-z0-9_]+)`?",
        statement,
        re.IGNORECASE,
    )
    if table_match:
        cursor.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s LIMIT 1",
            (database_name, table_match.group(1)),
        )
        return cursor.fetchone() is not None

    index_match = _CREATE_OBJECT.match(statement)
    if index_match:
        cursor.execute(
            "SELECT 1 FROM information_schema.statistics "
            "WHERE table_schema = %s AND table_name = %s AND index_name = %s LIMIT 1",
            (database_name, index_match.group("table"), index_match.group("name")),
        )
        return cursor.fetchone() is not None

    constraint_match = _ADD_CONSTRAINT.match(statement)
    if constraint_match:
        cursor.execute(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_schema = %s AND table_name = %s "
            "AND constraint_name = %s LIMIT 1",
            (
                database_name,
                constraint_match.group("table"),
                constraint_match.group("name"),
            ),
        )
        return cursor.fetchone() is not None

    raise BaseTareasSchemaInstallError(
        "La estructura congelada contiene una sentencia no reconocida."
    )


def _statement_target(statement: str) -> str | None:
    for pattern in (_TABLE_NAME, _CREATE_INDEX, _ADD_CONSTRAINT):
        match = pattern.match(statement)
        if match:
            return match.group("table")
    return None


def install_base_tareas_schema(
    *,
    expected_fingerprint: str | None = None,
    expected_missing: tuple[str, ...] | None = None,
    expected_connection_id: int | None = None,
    expected_connection_updated_at: str | None = None,
    expected_database_name: str | None = None,
) -> int:
    """Ensure frozen structure and official causes; MySQL DDL commits separately."""
    try:
        source = get_tarea_connection("BASE_TAREAS")
        if source["type"] != "MYSQL_CONFIG":
            raise BaseTareasSchemaInstallError(
                "BASE_TAREAS utiliza Django y no requiere bootstrap MySQL."
            )
        connection_config = get_tarea_mysql_connection("BASE_TAREAS")
        database_name = source["database_name"]
        if expected_fingerprint is not None and (
            expected_connection_id != int(source["connection_id"])
            or expected_connection_updated_at
            != connection_config.updated_at.isoformat()
            or expected_database_name != database_name
        ):
            raise BaseTareasSchemaInstallError(
                "La configuración de BASE_TAREAS cambió; vuelva a inspeccionar."
            )
        with open_mysql_connection(
            connection_config,
            database_name=database_name,
        ) as connection:
            snapshot = _fetch_schema_snapshot(connection, database_name)
            plan = _compare_schema_snapshot(snapshot, database_name)
            if expected_fingerprint is not None:
                current_fingerprint = _schema_fingerprint(
                    database_name,
                    int(source["connection_id"]),
                    snapshot,
                )
                if (
                    current_fingerprint != expected_fingerprint
                    or plan["conflicts"]
                    or tuple(plan["missing"]) != tuple(expected_missing or ())
                ):
                    raise BaseTareasSchemaInstallError(
                        "La estructura cambió desde la inspección. "
                        "Vuelva a inspeccionar."
                    )
                missing_tables = set(expected_missing or ())
            else:
                if plan["conflicts"]:
                    raise BaseTareasSchemaInstallError(
                        "La estructura existente es incompatible. "
                        "Vuelva a inspeccionar."
                    )
                missing_tables = set(plan["missing"])
            statements = _read_frozen_schema_statements()
            cursor = connection.cursor()
            try:
                for statement in statements:
                    if missing_tables is not None:
                        target = _statement_target(statement)
                        if target not in missing_tables:
                            continue
                    if not _metadata_exists(cursor, statement, database_name):
                        cursor.execute(statement)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
            ensure_mysql_delay_causes(connection)
        return len(statements)
    except BaseTareasSchemaInstallError:
        raise
    except BaseTareasReferenceDataError as exc:
        raise BaseTareasSchemaInstallError(str(exc)) from exc
    except MySQLConnectionOpenError as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo abrir la conexión de BASE_TAREAS."
        ) from exc
    except Exception as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo crear la estructura Base Tareas."
        ) from exc
