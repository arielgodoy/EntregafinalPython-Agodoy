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
from .connection_roles import (
    get_tarea_connection,
    get_tarea_mysql_connection,
    resolve_operational_backend,
)
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
DELETION_LEDGER_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "sql" / "deletion_ledger_schema.sql"
)
LOGICAL_DELETION_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "sql" / "logical_deletion_schema.sql"
)
LOGICAL_RESTORATION_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "sql" / "logical_restoration_schema.sql"
)


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
EXPECTED_DELETION_LEDGER_MODELS = (
    "TareaEliminacionOperacion",
    "TareaEliminacionElemento",
    "TareaEliminacionArchivo",
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


def get_deletion_ledger_models():
    """Return only the additive deletion-ledger tables."""
    models = tuple(
        apps.get_model("tareas", model_name)
        for model_name in EXPECTED_DELETION_LEDGER_MODELS
    )
    if {model.__name__ for model in models} != set(
        EXPECTED_DELETION_LEDGER_MODELS
    ):
        raise BaseTareasSchemaInstallError(
            "El inventario del ledger de eliminación no coincide con el contrato."
        )
    return models


def get_deletion_item_models():
    """Return operational rows that may be represented in a deletion manifest."""
    models = list(get_operational_models())
    for model in tuple(models):
        for field in model._meta.local_many_to_many:
            through_model = field.remote_field.through
            if through_model._meta.auto_created and through_model not in models:
                models.append(through_model)
    return tuple(models)


def build_deletion_ledger_schema_statements(connection) -> list[str]:
    """Collect DDL for the ledger tables only, requiring InnoDB."""
    with DatabaseSchemaEditor(connection, collect_sql=True) as editor:
        for model in get_deletion_ledger_models():
            editor.create_model(model)

    expected_tables = {
        model._meta.db_table for model in get_deletion_ledger_models()
    }
    statements = []
    created_tables = set()
    for raw_statement in editor.collected_sql:
        statement = _normalize_statement(raw_statement).rstrip(";")
        table_match = _TABLE_NAME.match(statement)
        if table_match:
            table_name = table_match.group("table")
            if table_name not in expected_tables:
                raise BaseTareasSchemaInstallError(
                    "El contrato del ledger contiene DDL fuera de las tablas autorizadas."
                )
            created_tables.add(table_name)
            engine_match = re.search(
                r"\bENGINE\s*=\s*[A-Za-z0-9_]+",
                statement,
                re.IGNORECASE,
            )
            if engine_match:
                statement = (
                    statement[:engine_match.start()]
                    + "ENGINE=InnoDB"
                    + statement[engine_match.end():]
                )
            else:
                statement += " ENGINE=InnoDB"
        else:
            target = _statement_target(statement)
            if (
                target not in expected_tables
                or _is_external_foreign_key(statement)
                or not (
                    statement.upper().startswith("CREATE INDEX ")
                    or statement.upper().startswith("CREATE UNIQUE INDEX ")
                    or re.match(
                        r"^ALTER\s+TABLE\b.*\bADD\s+CONSTRAINT\b",
                        statement,
                        re.IGNORECASE,
                    )
                )
            ):
                raise BaseTareasSchemaInstallError(
                    "El contrato del ledger contiene DDL fuera de las tablas autorizadas."
                )
        statements.append(statement)

    if created_tables != expected_tables:
        raise BaseTareasSchemaInstallError(
            "No se generó el DDL completo para el ledger de eliminación."
        )
    if not statements:
        raise BaseTareasSchemaInstallError(
            "No se pudo generar la estructura del ledger de eliminación."
        )
    return statements


def _validate_deletion_ledger_statements(statements: list[str]) -> None:
    expected_tables = {
        model._meta.db_table for model in get_deletion_ledger_models()
    }
    created_tables = set()
    for statement in statements:
        normalized = _normalize_statement(statement)
        table_match = _TABLE_NAME.match(normalized)
        if table_match:
            table_name = table_match.group("table")
            if (
                table_name not in expected_tables
                or "ENGINE=INNODB" not in normalized.upper().replace(" ", "")
            ):
                raise BaseTareasSchemaInstallError(
                    "El esquema del ledger contiene una sentencia no permitida."
                )
            created_tables.add(table_name)
            continue
        target = _statement_target(normalized)
        if (
            target not in expected_tables
            or _is_external_foreign_key(normalized)
            or not (
                normalized.upper().startswith("CREATE INDEX ")
                or normalized.upper().startswith("CREATE UNIQUE INDEX ")
                or re.match(
                    r"^ALTER\s+TABLE\b.*\bADD\s+CONSTRAINT\b",
                    normalized,
                    re.IGNORECASE,
                )
            )
        ):
            raise BaseTareasSchemaInstallError(
                "El esquema del ledger contiene una sentencia no permitida."
            )
    if created_tables != expected_tables or not statements:
        raise BaseTareasSchemaInstallError(
            "El esquema del ledger no contiene exactamente sus tres tablas."
        )


def _validate_logical_deletion_statements(statements: list[str]) -> None:
    task_table = apps.get_model("tareas", "Tarea")._meta.db_table
    ledger_table = apps.get_model(
        "tareas",
        "TareaEliminacionOperacion",
    )._meta.db_table
    expected_columns = {
        task_table: {
            "eliminada",
            "eliminada_en",
            "eliminada_por_id",
            "eliminacion_operacion_id",
        },
        ledger_table: {"motivo"},
    }
    expected_constraints = {
        (task_table, "tareas_elim_metadata_consistent"),
        (ledger_table, "tareas_delop_motivo_required"),
    }
    expected_indexes = {
        (task_table, "tareas_emp_elim_idx"),
        (task_table, "tareas_delop_task_idx"),
    }
    actual_columns: set[tuple[str, str]] = set()
    actual_constraints: set[tuple[str, str]] = set()
    actual_indexes: set[tuple[str, str]] = set()
    seen_statements: set[str] = set()

    for raw_statement in statements:
        statement = _normalize_statement(raw_statement).rstrip(";")
        if statement in seen_statements:
            raise BaseTareasSchemaInstallError(
                "El contrato de evolución lógica contiene sentencias duplicadas."
            )
        seen_statements.add(statement)
        alter_match = re.match(
            r"^ALTER\s+TABLE\s+`?(?P<table>[A-Za-z0-9_]+)`?\s+"
            r"ADD\s+(?P<kind>COLUMN|CONSTRAINT)\s+`?(?P<name>[A-Za-z0-9_]+)`?",
            statement,
            re.IGNORECASE,
        )
        if alter_match:
            table = alter_match.group("table")
            kind = alter_match.group("kind").upper()
            name = alter_match.group("name")
            if kind == "COLUMN":
                if name not in expected_columns.get(table, set()):
                    raise BaseTareasSchemaInstallError(
                        "El contrato lógico incluye una columna no autorizada."
                    )
                actual_columns.add((table, name))
            elif (table, name) in expected_constraints:
                actual_constraints.add((table, name))
            else:
                raise BaseTareasSchemaInstallError(
                    "El contrato lógico incluye una restricción no autorizada."
                )
            continue

        index_match = _CREATE_OBJECT.match(statement)
        if index_match:
            table = index_match.group("table")
            name = index_match.group("name")
            if (table, name) not in expected_indexes:
                raise BaseTareasSchemaInstallError(
                    "El contrato lógico incluye un índice no autorizado."
                )
            actual_indexes.add((table, name))
            continue

        raise BaseTareasSchemaInstallError(
            "El contrato de evolución lógica solo admite adiciones declaradas."
        )

    if (
        actual_columns
        != {
            (table, column)
            for table, columns in expected_columns.items()
            for column in columns
        }
        or actual_constraints != expected_constraints
        or actual_indexes != expected_indexes
    ):
        raise BaseTareasSchemaInstallError(
            "El contrato de evolución lógica está incompleto o duplicado."
        )


def _validate_logical_restoration_statements(statements: list[str]) -> None:
    operation_table = apps.get_model(
        "tareas",
        "TareaEliminacionOperacion",
    )._meta.db_table
    expected_column = "reverses_operation_id"
    expected_constraints = {
        (operation_table, "tareas_eliminacion_o_reverses_operation_i_1b35b931_fk_tareas_el"),
        (operation_table, "tareas_delop_restore_link"),
        (operation_table, "tareas_delop_restore_motive"),
    }
    expected_indexes = {(operation_table, "tareas_delop_reverses_uniq")}
    actual_columns: set[tuple[str, str]] = set()
    actual_constraints: set[tuple[str, str]] = set()
    actual_indexes: set[tuple[str, str]] = set()
    seen_statements: set[str] = set()

    for raw_statement in statements:
        statement = _normalize_statement(raw_statement).rstrip(";")
        if statement in seen_statements:
            raise BaseTareasSchemaInstallError(
                "El contrato de restauración contiene sentencias duplicadas."
            )
        seen_statements.add(statement)
        alter_match = re.match(
            r"^ALTER\s+TABLE\s+`?(?P<table>[A-Za-z0-9_]+)`?\s+"
            r"ADD\s+(?P<kind>COLUMN|CONSTRAINT)\s+`?(?P<name>[A-Za-z0-9_]+)`?",
            statement,
            re.IGNORECASE,
        )
        if alter_match:
            table = alter_match.group("table")
            kind = alter_match.group("kind").upper()
            name = alter_match.group("name")
            if kind == "COLUMN":
                if table != operation_table or name != expected_column or not re.search(
                    r"\bVARCHAR\s*\(\s*32\s*\)\s+NULL\b",
                    statement,
                    re.IGNORECASE,
                ):
                    raise BaseTareasSchemaInstallError(
                        "El contrato de restauración incluye una columna no autorizada."
                    )
                actual_columns.add((table, name))
            else:
                if (table, name) not in expected_constraints:
                    raise BaseTareasSchemaInstallError(
                        "El contrato de restauración incluye una restricción no autorizada."
                    )
                if name.endswith("_fk_tareas_el") and (
                    not re.search(
                        r"FOREIGN\s+KEY\s*\(\s*`?reverses_operation_id`?\s*\)",
                        statement,
                        re.IGNORECASE,
                    )
                    or not re.search(
                        r"REFERENCES\s+`?tareas_eliminacion_operacion`?"
                        r"\s*\(\s*`?operation_id`?\s*\)",
                        statement,
                        re.IGNORECASE,
                    )
                    or re.search(r"\bON\s+(?:DELETE|UPDATE)\b", statement, re.IGNORECASE)
                ):
                    raise BaseTareasSchemaInstallError(
                        "La referencia de restauración debe apuntar al ledger de operaciones."
                    )
                if name == "tareas_delop_restore_link" and (
                    "LOGICALLY_RESTORED" not in statement
                    or "reverses_operation_id" not in statement
                    or "PENDING" not in statement
                    or "COMMITTED" not in statement
                ):
                    raise BaseTareasSchemaInstallError(
                        "La restricción de enlace de restauración está incompleta."
                    )
                if name == "tareas_delop_restore_motive" and (
                    "LOGICALLY_RESTORED" not in statement
                    or "reverses_operation_id" not in statement
                    or "motivo" not in statement
                ):
                    raise BaseTareasSchemaInstallError(
                        "La restricción de motivo de restauración está incompleta."
                    )
                actual_constraints.add((table, name))
            continue

        index_match = _CREATE_OBJECT.match(statement)
        if index_match:
            table = index_match.group("table")
            name = index_match.group("name")
            columns_match = re.search(r"\((?P<columns>.*)\)\s*$", statement)
            columns = (
                _split_sql_items(columns_match.group("columns"))
                if columns_match
                else []
            )
            if (
                not index_match.group("unique")
                or (table, name) not in expected_indexes
                or columns != ["`reverses_operation_id`"]
            ):
                raise BaseTareasSchemaInstallError(
                    "El contrato de restauración incluye un índice no autorizado."
                )
            actual_indexes.add((table, name))
            continue

        raise BaseTareasSchemaInstallError(
            "El contrato de restauración solo admite adiciones declaradas."
        )

    if (
        actual_columns != {(operation_table, expected_column)}
        or actual_constraints != expected_constraints
        or actual_indexes != expected_indexes
    ):
        raise BaseTareasSchemaInstallError(
            "El contrato de restauración está incompleto o duplicado."
        )


def read_logical_deletion_schema_contract() -> tuple[str, ...]:
    """Read and validate additive SQL without executing it."""
    try:
        content = LOGICAL_DELETION_SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo leer el contrato aditivo de eliminación lógica."
        ) from exc
    content = "\n".join(
        line for line in content.splitlines() if not line.lstrip().startswith("--")
    )
    statements = tuple(item.strip() for item in content.split(";") if item.strip())
    if not statements:
        raise BaseTareasSchemaInstallError(
            "El contrato aditivo de eliminación lógica está vacío."
        )
    _validate_logical_deletion_statements(list(statements))
    return statements


def read_logical_restoration_schema_contract() -> tuple[str, ...]:
    """Read and validate additive restoration-ledger SQL without executing it."""
    try:
        content = LOGICAL_RESTORATION_SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo leer el contrato aditivo del ledger de restauración."
        ) from exc
    content = "\n".join(
        line for line in content.splitlines() if not line.lstrip().startswith("--")
    )
    statements = tuple(item.strip() for item in content.split(";") if item.strip())
    if not statements:
        raise BaseTareasSchemaInstallError(
            "El contrato aditivo del ledger de restauración está vacío."
        )
    _validate_logical_restoration_statements(list(statements))
    return statements


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


def _is_json_valid_check(check_clause: str) -> str | None:
    match = re.search(
        r"\bJSON_VALID\s*\(\s*`?(?P<column>[A-Za-z0-9_]+)`?\s*\)",
        check_clause or "",
        re.IGNORECASE,
    )
    return match.group("column") if match else None


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
                "collation": None,
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
                column_match = re.match(
                    r"`?(?P<column>[A-Za-z0-9_]+)`?\s+"
                    r"(?P<type>[A-Za-z]+(?:\s+unsigned)?(?:\s*\([^)]*\))?)"
                    r"(?P<rest>.*)$",
                    item,
                    re.IGNORECASE,
                )
                if column_match:
                    rest = column_match.group("rest")
                    if re.search(r"\bPRIMARY\s+KEY\b", rest, re.IGNORECASE):
                        table_info["primary"] = (column_match.group("column"),)
                    if re.search(r"\bUNIQUE\b", rest, re.IGNORECASE):
                        table_info["unique"].add((column_match.group("column"),))
                    table_info["columns"][column_match.group("column")] = {
                        "type": _normalize_schema_type(column_match.group("type")),
                        "nullable": "NO" if re.search(r"\bNOT\s+NULL\b", rest, re.I) else "YES",
                        "auto_increment": bool(re.search(r"\bAUTO_INCREMENT\b", rest, re.I)),
                    }
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
            options = statement[closing + 1 :]
            collation_match = re.search(
                r"\bCOLLATE\s*=?\s*(?P<collation>[A-Za-z0-9_]+)",
                options,
                re.IGNORECASE,
            )
            if collation_match:
                table_info["collation"] = collation_match.group("collation")
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
        "json_valid_columns": {},
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
            f"SELECT tc.TABLE_NAME, cc.CHECK_CLAUSE "
            "FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS tc "
            "JOIN INFORMATION_SCHEMA.CHECK_CONSTRAINTS AS cc "
            "ON cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA "
            "AND cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME "
            "WHERE tc.CONSTRAINT_SCHEMA = %s "
            f"AND tc.TABLE_NAME IN ({placeholders}) "
            "AND tc.CONSTRAINT_TYPE = 'CHECK'",
            (database_name, *tables),
        )
        for table, check_clause in cursor.fetchall():
            column = _is_json_valid_check(check_clause)
            if column:
                actual["json_valid_columns"].setdefault(table, set()).add(column)
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
                "collation": expected_info.get("collation"),
            }
            for table, expected_info in sorted(expected["tables"].items())
        },
        "expected_foreign_keys": sorted(expected["foreign_keys"]),
        "actual_tables": actual["tables"],
        "actual_columns": actual["columns"],
        "actual_json_valid_columns": {
            table: sorted(columns)
            for table, columns in actual.get("json_valid_columns", {}).items()
        },
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
        expected_collation = expected_info.get("collation")
        if expected_collation and table_info["collation"] != expected_collation:
            issues.append("COLLATION_MISMATCH")

        actual_columns = actual["columns"].get(table, {})
        expected_columns = expected_info["columns"]
        if set(actual_columns) != set(expected_columns):
            issues.append("COLUMN_SET_MISMATCH")
        for column in sorted(set(actual_columns) & set(expected_columns)):
            expected_column = expected_columns[column]
            actual_column = actual_columns[column]
            if expected_column["type"] != actual_column["type"]:
                json_equivalent = (
                    expected_column["type"] == "json"
                    and actual_column["type"] == "longtext"
                    and column
                    in actual.get("json_valid_columns", {}).get(table, set())
                )
                if not json_equivalent:
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


def _deletion_ledger_schema_snapshot(
    connection,
    database_name: str,
    connection_id: int,
) -> dict[str, Any]:
    tables = tuple(
        model._meta.db_table for model in get_deletion_ledger_models()
    )
    placeholders = ", ".join("%s" for _ in tables)
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT DATABASE()")
        selected_database = cursor.fetchone()
        if not selected_database or selected_database[0] != database_name:
            raise BaseTareasSchemaInstallError(
                "La conexión abierta no apunta a la base configurada de BASE_TAREAS."
            )
        cursor.execute(
            "SELECT table_name, engine FROM information_schema.tables "
            f"WHERE table_schema = %s AND table_name IN ({placeholders})",
            (database_name, *tables),
        )
        existing = sorted(
            (str(name), str(engine or "")) for name, engine in cursor.fetchall()
        )
        cursor.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            f"WHERE table_schema = %s AND table_name IN ({placeholders})",
            (database_name, *tables),
        )
        actual_columns = {
            str(table_name): set()
            for table_name, _engine in existing
        }
        for table_name, column_name in cursor.fetchall():
            actual_columns.setdefault(str(table_name), set()).add(str(column_name))
        cursor.execute("SELECT VERSION()")
        version_row = cursor.fetchone()
        cursor.execute(
            "SELECT support FROM information_schema.engines "
            "WHERE engine = 'InnoDB' LIMIT 1"
        )
        support_row = cursor.fetchone()
    finally:
        cursor.close()
    operational_snapshot = _fetch_schema_snapshot(connection, database_name)
    operational_plan = _compare_schema_snapshot(
        operational_snapshot,
        database_name,
    )
    if operational_plan["missing"] or operational_plan["conflicts"]:
        raise BaseTareasSchemaInstallError(
            "El esquema operacional de Tareas no es compatible con el ledger."
        )
    operational_tables = tuple(
        dict.fromkeys(
            model._meta.db_table for model in get_deletion_item_models()
        )
    )
    operational_placeholders = ", ".join("%s" for _ in operational_tables)
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT table_name, engine FROM information_schema.tables "
            f"WHERE table_schema = %s AND table_name IN ({operational_placeholders})",
            (database_name, *operational_tables),
        )
        operational_engines = {
            str(name): str(engine or "") for name, engine in cursor.fetchall()
        }
    finally:
        cursor.close()
    if (
        set(operational_tables) - set(operational_engines)
        or any(engine.casefold() != "innodb" for engine in operational_engines.values())
    ):
        raise BaseTareasSchemaInstallError(
            "Todas las tablas operacionales de Tareas deben existir en InnoDB."
        )
    expected_columns = {
        model._meta.db_table: {
            field.column for field in model._meta.local_concrete_fields
        }
        for model in get_deletion_ledger_models()
    }
    missing_columns = sorted(
        (table, column)
        for table, columns in expected_columns.items()
        for column in columns - actual_columns.get(table, set())
    )
    return {
        "expected_tables": tables,
        "existing_tables": existing,
        "existing_columns": {
            table: tuple(sorted(columns))
            for table, columns in sorted(actual_columns.items())
        },
        "missing_columns": missing_columns,
        "server_version": str(version_row[0]) if version_row else "",
        "innodb_support": str(support_row[0]).upper() if support_row else "",
        "operational_fingerprint": _schema_fingerprint(
            database_name,
            connection_id,
            operational_snapshot,
        ),
    }


def _deletion_ledger_fingerprint(
    database_name: str,
    connection_id: int,
    connection_updated_at: str,
    snapshot: dict[str, Any],
) -> str:
    payload = {
        "database_name": database_name,
        "connection_id": connection_id,
        "connection_updated_at": connection_updated_at,
        "expected_tables": sorted(snapshot["expected_tables"]),
        "existing_tables": snapshot["existing_tables"],
        "existing_columns": snapshot["existing_columns"],
        "missing_columns": snapshot["missing_columns"],
        "server_version": snapshot["server_version"],
        "innodb_support": snapshot["innodb_support"],
        "operational_fingerprint": snapshot["operational_fingerprint"],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _read_deletion_ledger_statements() -> list[str]:
    try:
        content = DELETION_LEDGER_SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo leer el esquema aditivo del ledger de Tareas."
        ) from exc
    content = "\n".join(
        line for line in content.splitlines() if not line.lstrip().startswith("--")
    )
    statements = [item.strip() for item in content.split(";") if item.strip()]
    _validate_deletion_ledger_statements(statements)
    return statements


def preview_deletion_ledger_schema() -> dict[str, Any]:
    """Inspect the configured MySQL target without executing DDL."""
    context = resolve_operational_backend("BASE_TAREAS")
    if (
        context.backend_type != "MYSQL_CONFIG"
        or context.mysql_connection is None
        or not context.database_name
    ):
        raise BaseTareasSchemaInstallError(
            "El instalador aditivo requiere BASE_TAREAS en MYSQL_CONFIG."
        )
    connection_config = context.mysql_connection
    try:
        with open_mysql_connection(
            connection_config,
            database_name=context.database_name,
        ) as connection:
            snapshot = _deletion_ledger_schema_snapshot(
                connection,
                context.database_name,
                int(connection_config.pk),
            )
    except MySQLConnectionOpenError as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo abrir BASE_TAREAS para inspeccionar el ledger."
        ) from exc
    except BaseTareasSchemaInstallError:
        raise
    except Exception as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo inspeccionar el esquema aditivo del ledger."
        ) from exc

    if snapshot["innodb_support"] not in {"YES", "DEFAULT"}:
        status = "UNSUPPORTED"
    elif not snapshot["existing_tables"]:
        status = "NOT_INSTALLED"
    elif (
        {name for name, _engine in snapshot["existing_tables"]}
        == set(snapshot["expected_tables"])
        and all(
            engine.casefold() == "innodb"
            for _name, engine in snapshot["existing_tables"]
        )
    ):
        status = (
            "SCHEMA_UPDATE_REQUIRED"
            if snapshot["missing_columns"]
            else "PRESENT_REQUIRES_SCHEMA_VALIDATION"
        )
    else:
        status = "PARTIAL_OR_INCOMPATIBLE"

    updated_at = connection_config.updated_at.isoformat()
    fingerprint = _deletion_ledger_fingerprint(
        context.database_name,
        int(connection_config.pk),
        updated_at,
        snapshot,
    )
    return {
        "status": status,
        "database_name": context.database_name,
        "connection_id": int(connection_config.pk),
        "connection_updated_at": updated_at,
        "server_version": snapshot["server_version"],
        "innodb_support": snapshot["innodb_support"],
        "existing_tables": snapshot["existing_tables"],
        "existing_columns": snapshot["existing_columns"],
        "missing_columns": snapshot["missing_columns"],
        "fingerprint": fingerprint,
    }


def preview_logical_deletion_schema() -> dict[str, Any]:
    """Inspect only required logical-deletion columns on MYSQL_CONFIG."""
    contract = read_logical_deletion_schema_contract()
    context = resolve_operational_backend("BASE_TAREAS")
    if context.backend_type != "MYSQL_CONFIG":
        return {
            "status": "DJANGO_MIGRATIONS",
            "backend": context.backend_type,
            "required_columns": (
                "eliminada",
                "eliminada_en",
                "eliminada_por_id",
                "eliminacion_operacion_id",
                "motivo",
            ),
            "contract_statement_count": len(contract),
        }
    if context.mysql_connection is None or not context.database_name:
        raise BaseTareasSchemaInstallError(
            "BASE_TAREAS no tiene una conexión MYSQL_CONFIG válida."
        )

    task_table = apps.get_model("tareas", "Tarea")._meta.db_table
    ledger_table = apps.get_model(
        "tareas",
        "TareaEliminacionOperacion",
    )._meta.db_table
    expected_columns = {
        task_table: (
            "eliminada",
            "eliminada_en",
            "eliminada_por_id",
            "eliminacion_operacion_id",
        ),
        ledger_table: ("motivo",),
    }
    tables = tuple(expected_columns)
    placeholders = ", ".join("%s" for _ in tables)
    connection_config = context.mysql_connection
    try:
        with open_mysql_connection(
            connection_config,
            database_name=context.database_name,
        ) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT DATABASE()")
                selected_database = cursor.fetchone()
                if (
                    not selected_database
                    or selected_database[0] != context.database_name
                ):
                    raise BaseTareasSchemaInstallError(
                        "La conexión abierta no apunta a BASE_TAREAS."
                    )
                cursor.execute(
                    "SELECT table_name, engine FROM information_schema.tables "
                    f"WHERE table_schema = %s AND table_name IN ({placeholders})",
                    (context.database_name, *tables),
                )
                existing_tables = {
                    str(table): str(engine or "")
                    for table, engine in cursor.fetchall()
                }
                cursor.execute(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    f"WHERE table_schema = %s AND table_name IN ({placeholders})",
                    (context.database_name, *tables),
                )
                existing_columns: dict[str, set[str]] = {
                    table: set() for table in tables
                }
                for table, column in cursor.fetchall():
                    existing_columns.setdefault(str(table), set()).add(str(column))
            finally:
                cursor.close()
    except MySQLConnectionOpenError as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo abrir BASE_TAREAS para inspeccionar la evolución lógica."
        ) from exc
    except BaseTareasSchemaInstallError:
        raise
    except Exception as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo inspeccionar el esquema de eliminación lógica."
        ) from exc

    missing_tables = sorted(set(tables) - set(existing_tables))
    missing_columns = sorted(
        (table, column)
        for table, columns in expected_columns.items()
        for column in set(columns) - existing_columns.get(table, set())
    )
    incompatible_engines = sorted(
        table
        for table, engine in existing_tables.items()
        if engine.casefold() != "innodb"
    )
    if missing_tables:
        status = "TABLES_MISSING"
    elif incompatible_engines:
        status = "INCOMPATIBLE_ENGINE"
    elif missing_columns:
        status = "SCHEMA_UPDATE_REQUIRED"
    else:
        status = "CURRENT"
    return {
        "status": status,
        "database_name": context.database_name,
        "connection_id": int(connection_config.pk),
        "connection_updated_at": connection_config.updated_at.isoformat(),
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "incompatible_engines": incompatible_engines,
        "contract_statement_count": len(contract),
    }


def preview_logical_restoration_schema() -> dict[str, Any]:
    """Inspect the L5 ledger extension without executing DDL."""
    contract = read_logical_restoration_schema_contract()
    context = resolve_operational_backend("BASE_TAREAS")
    if context.backend_type == "DJANGO":
        return {
            "status": "DJANGO_MIGRATIONS",
            "backend": context.backend_type,
            "required_column": "reverses_operation_id",
            "contract_statement_count": len(contract),
        }
    if (
        context.backend_type != "MYSQL_CONFIG"
        or context.mysql_connection is None
        or not context.database_name
    ):
        raise BaseTareasSchemaInstallError(
            "BASE_TAREAS no tiene un backend compatible con el ledger de restauración."
        )
    if context.database_name != "tareas":
        raise BaseTareasSchemaInstallError(
            "El ledger de restauración solo está autorizado sobre la base tareas."
        )

    operation_table = apps.get_model(
        "tareas",
        "TareaEliminacionOperacion",
    )._meta.db_table
    column = apps.get_model(
        "tareas",
        "TareaEliminacionOperacion",
    )._meta.get_field("reverses_operation").column
    connection_config = context.mysql_connection
    try:
        with open_mysql_connection(
            connection_config,
            database_name=context.database_name,
        ) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT DATABASE()")
                selected_database = cursor.fetchone()
                if not selected_database or selected_database[0] != "tareas":
                    raise BaseTareasSchemaInstallError(
                        "La conexión no está seleccionada sobre la base autorizada tareas."
                    )
                cursor.execute("SELECT VERSION()")
                version_row = cursor.fetchone()
                cursor.execute(
                    "SELECT engine FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = %s",
                    (context.database_name, operation_table),
                )
                table_row = cursor.fetchone()
                if not table_row:
                    raise BaseTareasSchemaInstallError(
                        "Falta la tabla del ledger de eliminación en BASE_TAREAS."
                    )
                if str(table_row[0] or "").casefold() != "innodb":
                    raise BaseTareasSchemaInstallError(
                        "La tabla del ledger debe utilizar InnoDB."
                    )
                cursor.execute(
                    "SELECT data_type, character_maximum_length, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s AND column_name = %s",
                    (context.database_name, operation_table, column),
                )
                column_row = cursor.fetchone()
                cursor.execute(
                    "SELECT index_name, non_unique, column_name "
                    "FROM information_schema.statistics "
                    "WHERE table_schema = %s AND table_name = %s "
                    "ORDER BY index_name, seq_in_index",
                    (context.database_name, operation_table),
                )
                index_rows = cursor.fetchall()
                cursor.execute(
                    "SELECT kcu.referenced_table_name, kcu.referenced_column_name, "
                    "rc.delete_rule, rc.update_rule "
                    "FROM information_schema.key_column_usage AS kcu "
                    "JOIN information_schema.referential_constraints AS rc "
                    "ON rc.constraint_schema = kcu.constraint_schema "
                    "AND rc.table_name = kcu.table_name "
                    "AND rc.constraint_name = kcu.constraint_name "
                    "WHERE kcu.table_schema = %s AND kcu.table_name = %s "
                    "AND kcu.column_name = %s "
                    "AND kcu.referenced_table_name IS NOT NULL",
                    (context.database_name, operation_table, column),
                )
                foreign_key_rows = cursor.fetchall()
            finally:
                cursor.close()
    except MySQLConnectionOpenError as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo abrir BASE_TAREAS para inspeccionar el ledger de restauración."
        ) from exc
    except BaseTareasSchemaInstallError:
        raise
    except Exception as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo inspeccionar el schema del ledger de restauración."
        ) from exc

    missing = []
    if (
        not column_row
        or str(column_row[0]).casefold() not in {"char", "varchar"}
        or int(column_row[1] or 0) != 32
        or str(column_row[2]).upper() != "YES"
    ):
        missing.append("column:reverses_operation_id")
    indexes: dict[str, tuple[int, list[str]]] = {}
    for index_name, non_unique, column_name in index_rows:
        key = str(index_name)
        if key not in indexes:
            indexes[key] = (int(non_unique), [])
        indexes[key][1].append(str(column_name))
    if not any(
        non_unique == 0 and columns == [column]
        for non_unique, columns in indexes.values()
    ):
        missing.append("unique:reverses_operation_id")
    if not any(
        str(row[0]) == operation_table
        and str(row[1]) == "operation_id"
        and str(row[2]).upper() in {"RESTRICT", "NO ACTION"}
        and str(row[3]).upper() in {"RESTRICT", "NO ACTION"}
        for row in foreign_key_rows
    ):
        missing.append("foreign_key:reverses_operation_id")
    return {
        "status": "SCHEMA_UPDATE_REQUIRED" if missing else "CURRENT",
        "database_name": context.database_name,
        "connection_id": int(connection_config.pk),
        "connection_updated_at": connection_config.updated_at.isoformat(),
        "server_version": str(version_row[0]) if version_row else "",
        "table": operation_table,
        "missing": tuple(missing),
        "contract_statement_count": len(contract),
    }


def install_deletion_ledger_schema(
    *,
    expected_connection_id: int,
    expected_connection_updated_at: str,
    expected_database_name: str,
    expected_fingerprint: str,
) -> int:
    """Install only the three ledger tables after a fresh, matching preview."""
    try:
        context = resolve_operational_backend("BASE_TAREAS")
        if (
            context.backend_type != "MYSQL_CONFIG"
            or context.mysql_connection is None
            or not context.database_name
        ):
            raise BaseTareasSchemaInstallError(
                "El instalador aditivo requiere BASE_TAREAS en MYSQL_CONFIG."
            )
        connection_config = context.mysql_connection
        if (
            int(connection_config.pk) != expected_connection_id
            or connection_config.updated_at.isoformat()
            != expected_connection_updated_at
            or context.database_name != expected_database_name
        ):
            raise BaseTareasSchemaInstallError(
                "La configuración de BASE_TAREAS cambió; vuelva a inspeccionar."
            )
        with open_mysql_connection(
            connection_config,
            database_name=context.database_name,
        ) as connection:
            snapshot = _deletion_ledger_schema_snapshot(
                connection,
                context.database_name,
                int(connection_config.pk),
            )
            current_fingerprint = _deletion_ledger_fingerprint(
                context.database_name,
                int(connection_config.pk),
                connection_config.updated_at.isoformat(),
                snapshot,
            )
            if (
                current_fingerprint != expected_fingerprint
                or snapshot["existing_tables"]
                or snapshot["innodb_support"] not in {"YES", "DEFAULT"}
            ):
                raise BaseTareasSchemaInstallError(
                    "El esquema o la conexión cambió desde la inspección; "
                    "no se instaló el ledger."
                )
            statements = _read_deletion_ledger_statements()
            cursor = connection.cursor()
            try:
                for statement in statements:
                    cursor.execute(statement)
            finally:
                cursor.close()

            installed = _deletion_ledger_schema_snapshot(
                connection,
                context.database_name,
                int(connection_config.pk),
            )
            if (
                {name for name, _engine in installed["existing_tables"]}
                != set(installed["expected_tables"])
                or any(
                    engine.casefold() != "innodb"
                    for _name, engine in installed["existing_tables"]
                )
            ):
                raise BaseTareasSchemaInstallError(
                    "La instalación aditiva quedó incompleta; requiere inspección manual."
                )
        return len(statements)
    except BaseTareasSchemaInstallError:
        raise
    except MySQLConnectionOpenError as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo abrir BASE_TAREAS para instalar el ledger."
        ) from exc
    except Exception as exc:
        raise BaseTareasSchemaInstallError(
            "No se pudo instalar el esquema aditivo del ledger."
        ) from exc


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
