"""Safe MySQL bootstrap for the operational Evaluaciones table."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Iterator

from django.db.backends.mysql.base import DatabaseWrapper
from django.db.backends.mysql.schema import DatabaseSchemaEditor

from settings.services.mysql_connections import (
    MySQLConnectionOpenError,
    open_mysql_connection,
)

from ..models import EvaluacionConnectionRole, Persona
from .connection_roles import (
    EvaluacionesConnectionError,
    resolve_operational_backend,
)


logger = logging.getLogger(__name__)


class BaseEvaluacionesSchemaInstallError(RuntimeError):
    """Controlled error for the Base Evaluaciones schema installer."""


ROLE = EvaluacionConnectionRole.ROLE_BASE_EVALUACIONES
TABLE_NAME = Persona._meta.db_table
EXPECTED_ENGINE = "InnoDB"
EXPECTED_CHARSET = "utf8mb4"
EXPECTED_COLLATION = "utf8mb4_unicode_ci"
MIN_MYSQL_VERSION = (8, 0, 16)
MIN_MARIADB_VERSION = (10, 5, 0)
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "sql" / "base_evaluaciones_schema.sql"

_CREATE_TABLE = re.compile(
    r"^CREATE\s+TABLE\s+`(?P<table>[A-Za-z0-9_]+)`\s*"
    r"\((?P<body>.*)\)\s+ENGINE=InnoDB\s+"
    r"DEFAULT\s+CHARACTER\s+SET=utf8mb4\s+"
    r"COLLATE=utf8mb4_unicode_ci$",
    re.IGNORECASE | re.DOTALL,
)
_COLUMN = re.compile(
    r"^`(?P<name>[A-Za-z0-9_]+)`\s+"
    r"(?P<type>[A-Za-z]+(?:\s+UNSIGNED)?(?:\s*\([^)]*\))?)"
    r"(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_CHECK = re.compile(r"\bCHECK\s*\((?P<expression>.*)\)\s*$", re.IGNORECASE | re.DOTALL)
_FORBIDDEN_SQL = re.compile(
    r"\b(?:ALTER|DROP|TRUNCATE|INSERT|UPDATE|DELETE|REPLACE|CREATE\s+DATABASE)\b",
    re.IGNORECASE,
)


def _split_sql_items(value: str) -> list[str]:
    items: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    for index, char in enumerate(value):
        if quote:
            if char == quote and (index == 0 or value[index - 1] != "\\"):
                quote = None
        elif char in {"`", "'", '"'}:
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


def _normalize_sql(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip()).rstrip(";")
    normalized = re.sub(r"\(\s+", "(", normalized)
    return re.sub(r"\s+\)", ")", normalized)


def _normalize_type(value: str | None) -> str:
    normalized = re.sub(r"\s+", " ", (value or "").strip().lower())
    normalized = re.sub(r"\s*,\s*", ",", normalized)
    normalized = re.sub(
        r"\b(tinyint|smallint|mediumint|int|integer|bigint)\(\d+\)",
        r"\1",
        normalized,
    )
    normalized = normalized.replace("integer", "int")
    normalized = re.sub(r"\bbool(?:ean)?\b", "tinyint", normalized)
    return normalized


def _normalize_check(value: str) -> str:
    return re.sub(r"[\s`()]+", "", value).replace("`", "").lower()


def _expected_schema(statement: str) -> dict[str, Any]:
    match = _CREATE_TABLE.match(statement)
    if match is None or match.group("table") != TABLE_NAME:
        raise BaseEvaluacionesSchemaInstallError(
            "El SQL de Base Evaluaciones no coincide con el contrato."
        )

    expected: dict[str, Any] = {
        "table": TABLE_NAME,
        "columns": {},
        "primary": (),
        "unique": set(),
        "ordinary": set(),
        "checks": set(),
        "engine": EXPECTED_ENGINE,
        "charset": EXPECTED_CHARSET,
        "collation": EXPECTED_COLLATION,
    }
    for item in _split_sql_items(match.group("body")):
        if item.upper().startswith(("CONSTRAINT ", "CHECK ")):
            check = _CHECK.search(item)
            if check:
                expected["checks"].add(_normalize_check(check.group("expression")))
            continue

        column = _COLUMN.match(item)
        if column is None:
            raise BaseEvaluacionesSchemaInstallError(
                "El SQL de Base Evaluaciones contiene una definición no reconocida."
            )
        name = column.group("name")
        rest = column.group("rest")
        expected["columns"][name] = {
            "type": _normalize_type(column.group("type")),
            "nullable": "NO" if re.search(r"\bNOT\s+NULL\b", rest, re.I) else "YES",
            "auto_increment": bool(re.search(r"\bAUTO_INCREMENT\b", rest, re.I)),
        }
        if re.search(r"\bPRIMARY\s+KEY\b", rest, re.I):
            expected["primary"] = (name,)
        if re.search(r"\bUNIQUE\b", rest, re.I):
            expected["unique"].add((name,))
        for check in _CHECK.finditer(rest):
            expected["checks"].add(_normalize_check(check.group("expression")))

    if not expected["columns"] or not expected["primary"]:
        raise BaseEvaluacionesSchemaInstallError(
            "El SQL de Base Evaluaciones no define una tabla operacional válida."
        )
    return expected


def _read_frozen_statement() -> str:
    try:
        content = SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise BaseEvaluacionesSchemaInstallError(
            "No se pudo leer el SQL congelado de Base Evaluaciones."
        ) from exc

    content = "\n".join(
        line for line in content.splitlines() if not line.lstrip().startswith("--")
    )
    statements = [item.strip() for item in content.split(";") if item.strip()]
    if len(statements) != 1 or _FORBIDDEN_SQL.search(content):
        raise BaseEvaluacionesSchemaInstallError(
            "El SQL de Base Evaluaciones contiene operaciones no permitidas."
        )
    statement = _normalize_sql(statements[0])
    _expected_schema(statement)
    return statement


def _schema_editor_connection(server_version: str) -> DatabaseWrapper:
    """Create a disconnected MySQL schema-editor context for the validated version."""
    config = {
        "ENGINE": "django.db.backends.mysql",
        "NAME": "evaluaciones_schema_generation",
        "USER": "",
        "PASSWORD": "",
        "HOST": "",
        "PORT": "",
        "OPTIONS": {},
        "TIME_ZONE": None,
        "CONN_MAX_AGE": 0,
        "ATOMIC_REQUESTS": False,
        "AUTOCOMMIT": True,
        "CONN_HEALTH_CHECKS": False,
        "TEST": {
            "CHARSET": None,
            "COLLATION": None,
            "NAME": None,
            "MIGRATE": True,
        },
    }
    connection = DatabaseWrapper(config, "evaluaciones_schema_generation")
    connection.__dict__["mysql_server_data"] = {
        "version": server_version,
        "sql_mode": "",
        "default_storage_engine": EXPECTED_ENGINE,
        "sql_auto_is_null": False,
        "lower_case_table_names": False,
        "has_zoneinfo_database": True,
    }
    return connection


def build_base_evaluaciones_schema_statements(server_version: str) -> list[str]:
    """Collect MySQL DDL from Persona without opening a database connection."""
    _parse_mysql_version(server_version)
    connection = _schema_editor_connection(server_version)
    generated: list[str] = []
    try:
        with DatabaseSchemaEditor(connection, collect_sql=True) as editor:
            editor.create_model(Persona)
            generated.extend(editor.collected_sql)
    except Exception as exc:
        raise BaseEvaluacionesSchemaInstallError(
            "No se pudo derivar el esquema MySQL del modelo Persona."
        ) from exc

    if len(generated) != 1:
        raise BaseEvaluacionesSchemaInstallError(
            "El modelo Persona generó objetos SQL fuera del alcance aprobado."
        )
    statement = _normalize_sql(generated[0])
    if _FORBIDDEN_SQL.search(statement):
        raise BaseEvaluacionesSchemaInstallError(
            "El modelo Persona generó una operación SQL no permitida."
        )
    if not statement.endswith(")"):
        raise BaseEvaluacionesSchemaInstallError(
            "El DDL generado para Persona no tiene una forma reconocida."
        )
    statement = (
        f"{statement} ENGINE={EXPECTED_ENGINE} "
        f"DEFAULT CHARACTER SET={EXPECTED_CHARSET} "
        f"COLLATE={EXPECTED_COLLATION}"
    )
    if statement != _read_frozen_statement():
        raise BaseEvaluacionesSchemaInstallError(
            "El SQL congelado no coincide con el modelo Persona vigente."
        )
    _expected_schema(statement)
    return [statement]


def _validate_server_product(version: str, version_comment: str) -> str:
    version_is_mariadb = "mariadb" in version.lower()
    comment_is_mariadb = "mariadb" in version_comment.lower()
    comment_is_mysql = "mysql" in version_comment.lower() and not comment_is_mariadb
    if version_is_mariadb and comment_is_mariadb:
        return "mariadb"
    if not version_is_mariadb and comment_is_mysql:
        return "mysql"
    raise BaseEvaluacionesSchemaInstallError(
        "El destino no se identificó como MySQL Oracle o MariaDB compatible."
    )


def _parse_mysql_version(version: str) -> tuple[int, int, int]:
    is_mariadb = "mariadb" in version.lower()
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        raise BaseEvaluacionesSchemaInstallError(
            "No se pudo validar la versión del servidor MySQL/MariaDB."
        )
    parsed = tuple(int(part) for part in match.groups())
    minimum_version = MIN_MARIADB_VERSION if is_mariadb else MIN_MYSQL_VERSION
    if parsed < minimum_version:
        if is_mariadb:
            raise BaseEvaluacionesSchemaInstallError(
                "El instalador requiere MariaDB 10.5 o superior."
            )
        raise BaseEvaluacionesSchemaInstallError(
            "El instalador requiere MySQL 8.0.16 o superior."
        )
    return parsed


def _resolve_target() -> dict[str, Any]:
    try:
        context = resolve_operational_backend(ROLE)
    except EvaluacionesConnectionError as exc:
        raise BaseEvaluacionesSchemaInstallError(
            "No se pudo resolver BASE_EVALUACIONES."
        ) from exc

    if context.backend_type != EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG:
        raise BaseEvaluacionesSchemaInstallError(
            "El instalador solo está disponible para BASE_EVALUACIONES MYSQL_CONFIG."
        )
    connection_config = context.mysql_connection
    database_name = context.database_name
    if connection_config is None or not database_name:
        raise BaseEvaluacionesSchemaInstallError(
            "BASE_EVALUACIONES no tiene un destino MySQL válido."
        )
    return {
        "connection_config": connection_config,
        "connection_id": connection_config.pk,
        "connection_updated_at": connection_config.updated_at.isoformat(),
        "database_name": database_name,
    }


@contextmanager
def _open_target_connection(target: dict[str, Any]) -> Iterator[Any]:
    with ExitStack() as stack:
        try:
            connection = stack.enter_context(
                open_mysql_connection(
                    target["connection_config"],
                    database_name=target["database_name"],
                )
            )
        except MySQLConnectionOpenError:
            raise
        except Exception as exc:
            raise BaseEvaluacionesSchemaInstallError(
                "No se pudo abrir la conexión de BASE_EVALUACIONES."
            ) from exc
        yield connection


def _log_schema_diagnostic(stage: str, error: Exception) -> None:
    cause = error
    while cause.__cause__ is not None:
        cause = cause.__cause__
    args = getattr(cause, "args", ())
    mysql_error_code = args[0] if args and type(args[0]) is int else None
    logger.debug(
        "Base Evaluaciones schema %s failed: cause_type=%s mysql_error_code=%s",
        stage,
        type(cause).__name__,
        mysql_error_code,
    )


def _collect_snapshot(connection, database_name: str) -> dict[str, Any]:
    statement = _read_frozen_statement()
    expected = _expected_schema(statement)
    with connection.cursor() as cursor:
        cursor.execute("SELECT VERSION(), @@version_comment, DATABASE()")
        server_row = cursor.fetchone()
        if not server_row:
            raise BaseEvaluacionesSchemaInstallError(
                "No se pudo identificar el servidor MySQL de destino."
            )
        version = str(server_row[0] or "")
        version_comment = str(server_row[1] or "")
        server_product = _validate_server_product(version, version_comment)
        _parse_mysql_version(version)
        active_database = str(server_row[2] or "")
        if active_database.casefold() != database_name.casefold():
            raise BaseEvaluacionesSchemaInstallError(
                "La conexión no abrió la base efectiva de BASE_EVALUACIONES."
            )

        cursor.execute(
            "SELECT TABLE_NAME, TABLE_TYPE, ENGINE, TABLE_COLLATION "
            "FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
            (database_name, TABLE_NAME),
        )
        tables = {
            row[0]: {
                "type": row[1],
                "engine": row[2],
                "collation": row[3],
            }
            for row in cursor.fetchall()
        }

        cursor.execute(
            "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, EXTRA "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
            "ORDER BY ORDINAL_POSITION",
            (database_name, TABLE_NAME),
        )
        columns = {
            row[0]: {
                "type": _normalize_type(row[1]),
                "nullable": row[2],
                "auto_increment": "auto_increment" in str(row[3] or "").lower(),
            }
            for row in cursor.fetchall()
        }

        cursor.execute(
            "SELECT INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME "
            "FROM INFORMATION_SCHEMA.STATISTICS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
            "ORDER BY INDEX_NAME, SEQ_IN_INDEX",
            (database_name, TABLE_NAME),
        )
        grouped_indexes: dict[tuple[str, bool], list[tuple[int, str]]] = {}
        for name, non_unique, sequence, column in cursor.fetchall():
            grouped_indexes.setdefault((name, not bool(non_unique)), []).append(
                (int(sequence), str(column or ""))
            )
        indexes = [
            {
                "name": name,
                "unique": unique,
                "columns": tuple(column for _seq, column in sorted(items)),
            }
            for (name, unique), items in grouped_indexes.items()
        ]

        check_metadata_columns = "tc.CONSTRAINT_TYPE, cc.CHECK_CLAUSE"
        if server_product == "mysql":
            check_metadata_columns += ", cc.ENFORCED"
        cursor.execute(
            f"SELECT {check_metadata_columns} "
            "FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc "
            "LEFT JOIN INFORMATION_SCHEMA.CHECK_CONSTRAINTS cc "
            "ON cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA "
            "AND cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME "
            "WHERE tc.CONSTRAINT_SCHEMA = %s AND tc.TABLE_NAME = %s "
            "AND tc.CONSTRAINT_TYPE = 'CHECK'",
            (database_name, TABLE_NAME),
        )
        checks = set()
        unenforced_checks = set()
        for row in cursor.fetchall():
            _constraint_type, clause = row[:2]
            if clause is None:
                continue
            normalized = _normalize_check(clause)
            if server_product == "mariadb":
                # The supported MariaDB baseline enforces checks but has no ENFORCED column.
                checks.add(normalized)
            elif str(row[2]).upper() == "YES":
                checks.add(normalized)
            else:
                unenforced_checks.add(normalized)

    return {
        "expected": expected,
        "actual": {
            "tables": tables,
            "columns": columns,
            "indexes": indexes,
            "checks": checks,
            "unenforced_checks": unenforced_checks,
        },
        "server_version": version,
    }


def _compare_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    expected = snapshot["expected"]
    actual = snapshot["actual"]
    table = actual["tables"].get(TABLE_NAME)
    if table is None:
        return {
            "tables": [{
                "name": TABLE_NAME,
                "classification": "PENDIENTE_CREACION",
                "issues": [],
            }],
            "existing": [],
            "missing": [TABLE_NAME],
            "conflicts": [],
        }

    issues: list[str] = []
    if table["type"] != "BASE TABLE":
        issues.append("OBJECT_TYPE_MISMATCH")
    if str(table["engine"] or "").casefold() != EXPECTED_ENGINE.casefold():
        issues.append("ENGINE_MISMATCH")
    if str(table["collation"] or "").casefold() != EXPECTED_COLLATION.casefold():
        issues.append("COLLATION_MISMATCH")

    actual_columns = actual["columns"]
    expected_columns = expected["columns"]
    if set(actual_columns) != set(expected_columns):
        issues.append("COLUMN_SET_MISMATCH")
    for name in set(actual_columns) & set(expected_columns):
        if actual_columns[name]["type"] != expected_columns[name]["type"]:
            issues.append("COLUMN_TYPE_MISMATCH")
        if actual_columns[name]["nullable"] != expected_columns[name]["nullable"]:
            issues.append("NULLABILITY_MISMATCH")
        if actual_columns[name]["auto_increment"] != expected_columns[name]["auto_increment"]:
            issues.append("AUTO_INCREMENT_MISMATCH")

    actual_primary = tuple(
        index["columns"] for index in actual["indexes"] if index["name"] == "PRIMARY"
    )
    if actual_primary != (expected["primary"],):
        issues.append("PRIMARY_KEY_MISMATCH")

    actual_unique = {
        index["columns"]
        for index in actual["indexes"]
        if index["unique"] and index["name"] != "PRIMARY"
    }
    actual_ordinary = {
        index["columns"] for index in actual["indexes"] if not index["unique"]
    }
    if actual_unique != expected["unique"]:
        issues.append("UNIQUE_INDEX_MISMATCH")
    if actual_ordinary != expected["ordinary"]:
        issues.append("INDEX_MISMATCH")
    if actual["checks"] != expected["checks"]:
        issues.append("CHECK_CONSTRAINT_MISMATCH")
    if actual["unenforced_checks"]:
        issues.append("CHECK_CONSTRAINT_NOT_ENFORCED")

    classification = "INCOMPATIBLE" if issues else "COMPATIBLE"
    result = {
        "name": TABLE_NAME,
        "classification": classification,
        "issues": sorted(set(issues)),
    }
    return {
        "tables": [result],
        "existing": [TABLE_NAME] if not issues else [],
        "missing": [],
        "conflicts": [result] if issues else [],
    }


def _fingerprint(target: dict[str, Any], snapshot: dict[str, Any]) -> str:
    expected = snapshot["expected"]
    actual = snapshot["actual"]
    payload = {
        "role": ROLE,
        "connection_id": target["connection_id"],
        "connection_updated_at": target["connection_updated_at"],
        "database_name": target["database_name"],
        "schema": {
            "tables": actual["tables"],
            "columns": actual["columns"],
            "indexes": sorted(actual["indexes"], key=lambda item: item["name"]),
            "checks": sorted(actual["checks"]),
            "unenforced_checks": sorted(actual["unenforced_checks"]),
            "expected": {
                "table": expected["table"],
                "columns": expected["columns"],
                "primary": list(expected["primary"]),
                "unique": sorted(
                    [list(columns) for columns in expected["unique"]]
                ),
                "ordinary": sorted(
                    [list(columns) for columns in expected["ordinary"]]
                ),
                "checks": sorted(expected["checks"]),
                "engine": expected["engine"],
                "charset": expected["charset"],
                "collation": expected["collation"],
            },
            "server_version": snapshot["server_version"],
        },
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _inspect_target(
    target: dict[str, Any],
) -> tuple[dict[str, Any], str, str]:
    try:
        with _open_target_connection(target) as connection:
            snapshot = _collect_snapshot(connection, target["database_name"])
            statements = build_base_evaluaciones_schema_statements(
                snapshot["server_version"]
            )
            result = _compare_snapshot(snapshot)
    except BaseEvaluacionesSchemaInstallError as exc:
        _log_schema_diagnostic("preview", exc)
        raise
    except (EvaluacionesConnectionError, MySQLConnectionOpenError) as exc:
        _log_schema_diagnostic("connection_open", exc)
        raise BaseEvaluacionesSchemaInstallError(
            "No se pudo abrir la conexión de BASE_EVALUACIONES."
        ) from exc
    except Exception as exc:
        _log_schema_diagnostic("preview", exc)
        raise BaseEvaluacionesSchemaInstallError(
            "No se pudo inspeccionar la estructura Base Evaluaciones."
        ) from exc

    if len(statements) != 1:
        raise BaseEvaluacionesSchemaInstallError(
            "El instalador recibió un plan SQL fuera del alcance aprobado."
        )
    return result, snapshot["server_version"], _fingerprint(target, snapshot)


def preview_base_evaluaciones_schema() -> dict[str, Any]:
    """Read-only inspection of the effective BASE_EVALUACIONES destination."""
    target = _resolve_target()
    result, server_version, fingerprint = _inspect_target(target)
    return {
        **result,
        "backend": "mysql",
        "database_name": target["database_name"],
        "connection_id": target["connection_id"],
        "connection_updated_at": target["connection_updated_at"],
        "server_version": server_version,
        "fingerprint": fingerprint,
    }


def install_base_evaluaciones_schema(
    *,
    expected_fingerprint: str,
    expected_missing: tuple[str, ...],
    expected_connection_id: int,
    expected_connection_updated_at: str,
    expected_database_name: str,
) -> int:
    """Revalidate the signed preview before creating the single missing table."""
    target = _resolve_target()
    if (
        expected_connection_id != target["connection_id"]
        or expected_connection_updated_at != target["connection_updated_at"]
        or expected_database_name != target["database_name"]
    ):
        raise BaseEvaluacionesSchemaInstallError(
            "La configuración de BASE_EVALUACIONES cambió; vuelva a inspeccionar."
        )
    if tuple(expected_missing) != (TABLE_NAME,):
        raise BaseEvaluacionesSchemaInstallError(
            "La confirmación no autoriza objetos faltantes válidos."
        )

    try:
        with _open_target_connection(target) as connection:
            snapshot = _collect_snapshot(connection, target["database_name"])
            statements = build_base_evaluaciones_schema_statements(
                snapshot["server_version"]
            )
            plan = _compare_snapshot(snapshot)
            current_fingerprint = _fingerprint(target, snapshot)
            if (
                current_fingerprint != expected_fingerprint
                or plan["conflicts"]
                or tuple(plan["missing"]) != (TABLE_NAME,)
            ):
                raise BaseEvaluacionesSchemaInstallError(
                    "La estructura o el destino cambió desde la vista previa; "
                    "vuelva a inspeccionar."
                )

            if len(statements) != 1 or TABLE_NAME not in statements[0]:
                raise BaseEvaluacionesSchemaInstallError(
                    "El plan SQL excede el objeto autorizado."
                )
            cursor = connection.cursor()
            try:
                cursor.execute(statements[0])
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
    except BaseEvaluacionesSchemaInstallError:
        raise
    except (EvaluacionesConnectionError, MySQLConnectionOpenError) as exc:
        raise BaseEvaluacionesSchemaInstallError(
            "No se pudo abrir la conexión de BASE_EVALUACIONES."
        ) from exc
    except Exception as exc:
        raise BaseEvaluacionesSchemaInstallError(
            "No se pudo crear la estructura Base Evaluaciones."
        ) from exc
    return 1
