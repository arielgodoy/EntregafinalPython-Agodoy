from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import UniqueConstraint

from settings.models import SettingsMySQLConnection
from settings.services.mysql_connections import (
    MySQLConnectionOpenError,
    open_mysql_connection,
)

from ..models import (
    CertificadoSII,
    CesionRPETC,
    CesionRPETCHistorial,
    EstadoContableCesion,
    GestionDTEConnectionRole,
    LecturaAutomaticaConfig,
    LecturaAutomaticaEjecucion,
    RevisionCesionComentario,
    RevisionCesionRPETC,
    TareaCesionRPETC,
    TareaRPETC,
)


class BaseDTESchemaInstallError(RuntimeError):
    pass


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "sql" / "base_dte_schema.sql"
SCHEMA_MODELS = (
    CertificadoSII,
    TareaRPETC,
    CesionRPETC,
    CesionRPETCHistorial,
    TareaCesionRPETC,
    LecturaAutomaticaConfig,
    LecturaAutomaticaEjecucion,
    RevisionCesionRPETC,
    RevisionCesionComentario,
    EstadoContableCesion,
)
MODEL_BY_TABLE = {model._meta.db_table: model for model in SCHEMA_MODELS}
TABLE_NAMES = tuple(MODEL_BY_TABLE)
_CREATE_TABLE = re.compile(
    r"^CREATE\s+TABLE\s+`(?P<table>[A-Za-z0-9_]+)`\s*\(",
    re.IGNORECASE,
)
_FORBIDDEN_SQL = re.compile(
    r"\b(?:ALTER|DROP|TRUNCATE|DELETE|RENAME|INSERT|UPDATE)\b",
    re.IGNORECASE,
)


def _read_schema_statements() -> dict[str, str]:
    try:
        content = SCHEMA_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise BaseDTESchemaInstallError(
            "No se pudo leer la estructura Base DTE."
        ) from exc

    statements: dict[str, str] = {}
    for raw_statement in content.split(";"):
        statement = raw_statement.strip()
        if not statement:
            continue
        match = _CREATE_TABLE.match(statement)
        if match is None or _FORBIDDEN_SQL.search(statement):
            raise BaseDTESchemaInstallError(
                "La estructura contiene una operación no permitida."
            )
        table = match.group("table")
        if table not in MODEL_BY_TABLE or table in statements:
            raise BaseDTESchemaInstallError(
                "La estructura contiene una tabla no permitida o duplicada."
            )
        referenced_tables = re.findall(
            r"\bREFERENCES\s+`([A-Za-z0-9_]+)`",
            statement,
            re.IGNORECASE,
        )
        if any(target not in MODEL_BY_TABLE for target in referenced_tables):
            raise BaseDTESchemaInstallError(
                "La estructura contiene una referencia física fuera de GestionDTE."
            )
        statements[table] = statement

    if set(statements) != set(TABLE_NAMES):
        raise BaseDTESchemaInstallError(
            "La estructura Base DTE no contiene las diez tablas esperadas."
        )
    return statements


def _schema_statement_for_connection(
    table: str,
    statement: str,
    connection: BaseDatabaseWrapper,
) -> str:
    if table != LecturaAutomaticaEjecucion._meta.db_table:
        return statement

    uuid_field = LecturaAutomaticaEjecucion._meta.get_field("lote_id")
    expected_type = _normalize_type(uuid_field.db_type(connection), connection.vendor)
    declaration = "`lote_id` CHAR(32) NOT NULL"
    if statement.count(declaration) != 1:
        raise BaseDTESchemaInstallError(
            "La declaración SQL de lote_id no coincide con la estructura validada."
        )
    if expected_type == "char(32)":
        return statement
    if expected_type == "uuid":
        return statement.replace(declaration, "`lote_id` UUID NOT NULL", 1)
    raise BaseDTESchemaInstallError(
        "El backend configurado no ofrece un tipo UUID compatible."
    )


def _fetch_dicts(cursor: Any, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    cursor.execute(sql, params)
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _server_version_tuple(version: str, is_mariadb: bool) -> tuple[int, int, int] | None:
    version_text = version.casefold()
    if is_mariadb:
        version_text = version_text.split("mariadb", 1)[0]
    matches = re.findall(r"(\d+)\.(\d+)\.(\d+)", version_text)
    if not matches:
        return None
    values = matches[-1] if is_mariadb else matches[0]
    return int(values[0]), int(values[1]), int(values[2])


def _supports_enforced_check_constraints(
    version: str,
    is_mariadb: bool,
) -> bool:
    parsed_version = _server_version_tuple(version, is_mariadb)
    if parsed_version is None:
        return False
    minimum_version = (10, 2, 1) if is_mariadb else (8, 0, 16)
    return parsed_version >= minimum_version


def _inspect_schema(connection: BaseDatabaseWrapper, database_name: str) -> dict[str, Any]:
    if connection.vendor != "mysql":
        raise BaseDTESchemaInstallError(
            "La inspección operacional requiere el backend MySQL configurado."
        )
    placeholders = ", ".join(["%s"] * len(TABLE_NAMES))
    params = (database_name, *TABLE_NAMES)
    server_version = ""
    is_mariadb = False
    check_constraints_enforced = False
    checks: list[dict[str, str]] = []
    with connection.cursor() as cursor:
        cursor.execute("SELECT VERSION()")
        version_row = cursor.fetchone()
        server_version = str(version_row[0]) if version_row else ""
        is_mariadb = "mariadb" in server_version.casefold()
        supports_checks = _supports_enforced_check_constraints(
            server_version,
            is_mariadb,
        )
        if supports_checks and is_mariadb:
            cursor.execute("SELECT @@SESSION.check_constraint_checks")
            check_constraints_enforced = bool(cursor.fetchone()[0])
        elif supports_checks:
            check_constraints_enforced = True

        tables = _fetch_dicts(
            cursor,
            "SELECT TABLE_NAME, TABLE_TYPE, ENGINE, TABLE_COLLATION "
            "FROM INFORMATION_SCHEMA.TABLES "
            f"WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({placeholders}) "
            "ORDER BY TABLE_NAME",
            params,
        )
        columns = _fetch_dicts(
            cursor,
            "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, EXTRA "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({placeholders}) "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION",
            params,
        )
        indexes = _fetch_dicts(
            cursor,
            "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME "
            "FROM INFORMATION_SCHEMA.STATISTICS "
            f"WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({placeholders}) "
            "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX",
            params,
        )
        foreign_keys = _fetch_dicts(
            cursor,
            "SELECT TABLE_NAME, CONSTRAINT_NAME, COLUMN_NAME, "
            "REFERENCED_TABLE_SCHEMA, REFERENCED_TABLE_NAME, "
            "REFERENCED_COLUMN_NAME, ORDINAL_POSITION "
            "FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE "
            f"WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({placeholders}) "
            "AND REFERENCED_TABLE_NAME IS NOT NULL "
            "ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION",
            params,
        )
        if supports_checks:
            checks = _fetch_dicts(
                cursor,
                "SELECT tc.TABLE_NAME, tc.CONSTRAINT_NAME, cc.CHECK_CLAUSE "
                "FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc "
                "JOIN INFORMATION_SCHEMA.CHECK_CONSTRAINTS cc "
                "ON cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA "
                "AND cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME "
                f"WHERE tc.TABLE_SCHEMA = %s AND tc.TABLE_NAME IN ({placeholders}) "
                "AND tc.CONSTRAINT_TYPE = 'CHECK' "
                "ORDER BY tc.TABLE_NAME, tc.CONSTRAINT_NAME",
                params,
            )

    result: dict[str, Any] = {
        "tables": {},
        "columns": {},
        "indexes": {},
        "foreign_keys": {},
        "checks": {},
        "server_version": server_version,
        "is_mariadb": is_mariadb,
        "check_constraints_enforced": check_constraints_enforced,
    }
    for row in tables:
        result["tables"][row["TABLE_NAME"]] = {
            key: row[key]
            for key in ("TABLE_TYPE", "ENGINE", "TABLE_COLLATION")
        }
    for row in columns:
        result["columns"].setdefault(row["TABLE_NAME"], []).append(
            {
                key: row[key]
                for key in (
                    "COLUMN_NAME",
                    "COLUMN_TYPE",
                    "IS_NULLABLE",
                    "EXTRA",
                )
            }
        )

    index_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in indexes:
        index_groups.setdefault(
            (row["TABLE_NAME"], row["INDEX_NAME"]), []
        ).append(row)
    for (table, name), rows in index_groups.items():
        result["indexes"].setdefault(table, []).append(
            {
                "name": name,
                "unique": not bool(rows[0]["NON_UNIQUE"]),
                "columns": tuple(row["COLUMN_NAME"] for row in rows),
            }
        )

    fk_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in foreign_keys:
        fk_groups.setdefault(
            (row["TABLE_NAME"], row["CONSTRAINT_NAME"]), []
        ).append(row)
    for (table, name), rows in fk_groups.items():
        result["foreign_keys"].setdefault(table, []).append(
            {
                "name": name,
                "columns": tuple(row["COLUMN_NAME"] for row in rows),
                "target_schema": rows[0]["REFERENCED_TABLE_SCHEMA"],
                "target_table": rows[0]["REFERENCED_TABLE_NAME"],
                "target_columns": tuple(
                    row["REFERENCED_COLUMN_NAME"] for row in rows
                ),
            }
        )
    for row in checks:
        result["checks"].setdefault(row["TABLE_NAME"], []).append(
            {
                "name": row["CONSTRAINT_NAME"],
                "clause": row["CHECK_CLAUSE"],
            }
        )
    return result


def _normalize_type(db_type: str | None, vendor: str = "mysql") -> str:
    value = re.sub(r"\s+", " ", (db_type or "").strip().lower())
    if vendor == "mysql":
        value = re.sub(r"\s+auto_increment$", "", value)
        value = re.sub(r"\s*,\s*", ",", value)
        value = re.sub(
            r"\b(tinyint|smallint|mediumint|int|integer|bigint)\(\d+\)",
            r"\1",
            value,
        )
        value = re.sub(r"\binteger\b", "int", value)
        value = re.sub(r"\bnumeric\b", "decimal", value)
        if value in {"bool", "boolean"}:
            return "tinyint"
    elif vendor == "sqlite":
        value = re.sub(r"\binteger\b", "int", value)
    return value


def _sqlite_type_affinity(db_type: str) -> str:
    value = db_type.casefold()
    if "int" in value:
        return "integer"
    if any(token in value for token in ("char", "clob", "text")):
        return "text"
    if "blob" in value or not value:
        return "blob"
    if any(token in value for token in ("real", "floa", "doub")):
        return "real"
    return "numeric"


def _has_json_valid_check(
    actual: dict[str, Any],
    table: str,
    column: str,
) -> bool:
    column_name = column.casefold()
    expected_clauses = {
        f"json_valid{column_name}",
        f"json_valid{column_name}or{column_name}isnull",
        f"{column_name}isnullorjson_valid{column_name}",
    }
    for check in actual.get("checks", {}).get(table, []):
        clause = re.sub(
            r'[`"\[\]\s()]',
            "",
            str(check.get("clause") or "").casefold(),
        )
        if clause in expected_clauses:
            return True
    return False


def _json_validation_is_proven(
    field,
    table: str,
    actual_type: str,
    actual: dict[str, Any],
    connection: BaseDatabaseWrapper,
) -> bool:
    if field.get_internal_type() != "JSONField":
        return False
    vendor = connection.vendor
    if vendor == "mysql":
        if _normalize_type(
            actual_type,
            vendor,
        ) == "json":
            return True
        is_mariadb = bool(actual.get("is_mariadb"))
        if not actual.get("check_constraints_enforced"):
            return False
        return (
            _supports_enforced_check_constraints(
                actual.get("server_version", ""),
                is_mariadb,
            )
            and _has_json_valid_check(actual, table, field.column)
        )
    if vendor == "sqlite":
        return bool(actual.get("check_constraints_enforced")) and _has_json_valid_check(
            actual,
            table,
            field.column,
        )
    return False


def _column_type_is_compatible(
    field,
    expected_type: str,
    actual_type: str,
    vendor: str = "mysql",
    json_validation_proven: bool = False,
) -> bool:
    expected = _normalize_type(expected_type, vendor)
    actual = _normalize_type(actual_type, vendor)
    if field.get_internal_type() == "JSONField":
        if vendor == "mysql":
            if expected == actual == "json":
                return True
            return (
                expected == "json"
                and actual in {"longtext", "text"}
                and json_validation_proven
            )
        if vendor == "sqlite":
            return (
                expected == actual == "text"
                and json_validation_proven
            )
        return False
    if expected == actual:
        return True
    if vendor == "sqlite":
        return _sqlite_type_affinity(expected) == _sqlite_type_affinity(actual)
    remote = getattr(getattr(field, "remote_field", None), "model", None)
    return (
        vendor == "mysql"
        and remote is not None
        and remote._meta.label_lower == "auth.user"
        and expected == "int"
        and actual == "bigint"
    )


def _column_difference_plan(
    field,
    expected_type: str,
    actual_type: str,
    expected_nullability: str,
    actual_nullability: str,
    json_validation_proven: bool,
    vendor: str,
) -> dict[str, Any]:
    type_compatible = _column_type_is_compatible(
        field,
        expected_type,
        actual_type,
        vendor=vendor,
        json_validation_proven=json_validation_proven,
    )
    if type_compatible and expected_nullability == actual_nullability:
        return {}
    if expected_nullability != actual_nullability:
        classification = "INCOMPATIBLE"
        action = "No realizar cambios automáticos; revisar la nulabilidad."
        risk = "La nulabilidad distinta puede cambiar validaciones y persistencia."
    elif (
        vendor == "mysql"
        and _normalize_type(expected_type, vendor) == "longblob"
        and _normalize_type(actual_type, vendor) in {"blob", "mediumblob"}
    ):
        classification = "REQUIERE_AMPLIACIÓN_SEGURA"
        action = f"Plan: ampliar capacidad {actual_type.upper()} → LONGBLOB."
        risk = (
            "La operación puede requerir bloqueo o tabla temporal; exige respaldo "
            "verificable, revisión de índices y restricciones, y autorización humana."
        )
    elif (
        field.get_internal_type() == "JSONField"
        and vendor in {"mysql", "sqlite"}
        and not json_validation_proven
    ):
        classification = "NO_VERIFICADO"
        action = "Verificar validación JSON física; mantener bloqueada la reconciliación."
        risk = "No se demostró la semántica de lectura, escritura y validación JSON."
    else:
        classification = "INCOMPATIBLE"
        action = "Sin corrección automática; requiere análisis específico."
        risk = "La diferencia puede alterar capacidad, signo o semántica del campo."
    return {
        "classification": classification,
        "action_proposed": action,
        "risk": risk,
        "requires_confirmation": True,
    }


def _column_compatibility_differences(
    model,
    actual: dict[str, Any],
    connection: BaseDatabaseWrapper,
) -> list[dict[str, Any]]:
    table = model._meta.db_table
    vendor = connection.vendor
    expected_columns = {
        field.column: field for field in model._meta.local_concrete_fields
    }
    actual_columns = {
        row["COLUMN_NAME"]: row for row in actual["columns"].get(table, [])
    }
    differences = []
    for name in set(actual_columns) & set(expected_columns):
        field = expected_columns[name]
        column = actual_columns[name]
        expected_type = field.db_type(connection)
        actual_type = column["COLUMN_TYPE"]
        expected_nullability = "YES" if field.null else "NO"
        actual_nullability = column["IS_NULLABLE"]
        json_validation_proven = _json_validation_is_proven(
            field,
            table,
            actual_type,
            actual,
            connection,
        )
        type_compatible = _column_type_is_compatible(
            field,
            expected_type,
            actual_type,
            vendor=vendor,
            json_validation_proven=json_validation_proven,
        )
        nullability_compatible = expected_nullability == actual_nullability
        if type_compatible and nullability_compatible:
            continue
        difference = {
            "column": name,
            "expected_type": expected_type,
            "actual_type": actual_type,
            "expected_nullability": expected_nullability,
            "actual_nullability": actual_nullability,
            "type_compatible": type_compatible,
            "nullability_compatible": nullability_compatible,
        }
        difference.update(
            _column_difference_plan(
                field,
                expected_type,
                actual_type,
                expected_nullability,
                actual_nullability,
                json_validation_proven,
                vendor,
            )
        )
        differences.append(difference)
    return sorted(differences, key=lambda item: item["column"])


def _expected_indexes(model) -> tuple[set[tuple[str, ...]], set[tuple[str, ...]]]:
    unique: set[tuple[str, ...]] = set()
    ordinary: set[tuple[str, ...]] = set()

    for field in model._meta.local_concrete_fields:
        if field.primary_key:
            continue
        columns = (field.column,)
        if field.unique:
            unique.add(columns)
        elif field.db_index:
            ordinary.add(columns)

    for constraint in model._meta.constraints:
        fields = getattr(constraint, "fields", ())
        if fields and isinstance(constraint, UniqueConstraint):
            unique.add(
                tuple(model._meta.get_field(name).column for name in fields)
            )
    for fields in model._meta.unique_together:
        unique.add(tuple(model._meta.get_field(name).column for name in fields))
    for index in model._meta.indexes:
        fields = getattr(index, "fields", ())
        if fields:
            ordinary.add(
                tuple(
                    model._meta.get_field(name.lstrip("-")).column
                    for name in fields
                )
            )

    ordinary.difference_update(unique)
    return unique, ordinary


def _expected_internal_foreign_keys(
    model,
) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    internal = set()
    for field in model._meta.local_concrete_fields:
        remote = getattr(getattr(field, "remote_field", None), "model", None)
        if remote in SCHEMA_MODELS:
            internal.add(
                (
                    (field.column,),
                    remote._meta.db_table,
                    (field.target_field.column,),
                )
            )
    return internal


def _table_compatibility_issues(
    model,
    actual: dict[str, Any],
    database_name: str,
    connection: BaseDatabaseWrapper,
) -> list[str]:
    table = model._meta.db_table
    table_info = actual["tables"][table]
    issues: list[str] = []

    if table_info["TABLE_TYPE"] != "BASE TABLE":
        return ["OBJECT_TYPE_MISMATCH"]
    if connection.vendor == "mysql":
        if table_info["ENGINE"] != "InnoDB":
            issues.append("ENGINE_MISMATCH")
        if table_info["TABLE_COLLATION"] != "utf8mb4_unicode_ci":
            issues.append("COLLATION_MISMATCH")
    elif connection.vendor != "sqlite":
        issues.append("UNSUPPORTED_DATABASE_BACKEND")

    actual_columns = {
        row["COLUMN_NAME"]: row for row in actual["columns"].get(table, [])
    }
    expected_columns = {
        field.column: field for field in model._meta.local_concrete_fields
    }
    if set(actual_columns) != set(expected_columns):
        issues.append("COLUMN_SET_MISMATCH")
    column_differences = _column_compatibility_differences(
        model,
        actual,
        connection,
    )
    for difference in column_differences:
        if not difference["type_compatible"]:
            issues.append("COLUMN_TYPE_MISMATCH")
        if not difference["nullability_compatible"]:
            issues.append("NULLABILITY_MISMATCH")
    for name in set(actual_columns) & set(expected_columns):
        field = expected_columns[name]
        column = actual_columns[name]
        should_auto_increment = field.get_internal_type() in {
            "AutoField",
            "BigAutoField",
            "SmallAutoField",
        }
        has_auto_increment = "auto_increment" in (column["EXTRA"] or "").lower()
        if should_auto_increment != has_auto_increment:
            issues.append("AUTO_INCREMENT_MISMATCH")

    table_indexes = actual["indexes"].get(table, [])
    primary = next(
        (index for index in table_indexes if index["name"] == "PRIMARY"),
        None,
    )
    expected_primary = tuple(
        field.column
        for field in model._meta.local_concrete_fields
        if field.primary_key
    )
    if primary is None or primary["columns"] != expected_primary:
        issues.append("PRIMARY_KEY_MISMATCH")

    expected_unique, expected_ordinary = _expected_indexes(model)
    actual_unique = {
        index["columns"]
        for index in table_indexes
        if index["unique"] and index["name"] != "PRIMARY"
    }
    actual_any = [index["columns"] for index in table_indexes]
    if not expected_unique.issubset(actual_unique):
        issues.append("UNIQUE_CONSTRAINT_MISSING")
    if actual_unique - expected_unique:
        issues.append("UNEXPECTED_UNIQUE_CONSTRAINT")
    if any(
        not any(index[: len(expected)] == expected for index in actual_any)
        for expected in expected_ordinary
    ):
        issues.append("INDEX_MISSING")

    actual_foreign_keys = actual["foreign_keys"].get(table, [])
    actual_fk_set = {
        (
            foreign_key["columns"],
            foreign_key["target_table"],
            foreign_key["target_columns"],
        )
        for foreign_key in actual_foreign_keys
        if (foreign_key["target_schema"] or "").casefold()
        == database_name.casefold()
    }
    if any(
        (foreign_key["target_schema"] or "").casefold()
        != database_name.casefold()
        or foreign_key["target_table"] not in MODEL_BY_TABLE
        for foreign_key in actual_foreign_keys
    ):
        issues.append("CROSS_DATABASE_FOREIGN_KEY")
    if actual_fk_set != _expected_internal_foreign_keys(model):
        issues.append("INTERNAL_FOREIGN_KEY_MISMATCH")
    return sorted(set(issues))


def _table_classification(
    issues: list[str],
    column_differences: list[dict[str, Any]],
) -> str:
    if not issues:
        return "COMPATIBLE"
    if any(
        difference["classification"] == "INCOMPATIBLE"
        for difference in column_differences
    ) or any(
        issue
        not in {
            "COLUMN_TYPE_MISMATCH",
            "NULLABILITY_MISMATCH",
        }
        for issue in issues
    ):
        return "INCOMPATIBLE"
    if any(
        difference["classification"] == "NO_VERIFICADO"
        for difference in column_differences
    ):
        return "NO_VERIFICADO"
    if any(
        difference["classification"] == "REQUIERE_AMPLIACIÓN_SEGURA"
        for difference in column_differences
    ):
        return "REQUIERE_AMPLIACIÓN_SEGURA"
    return "INCOMPATIBLE"


def _build_preview(
    actual: dict[str, Any],
    database_name: str,
    connection: BaseDatabaseWrapper,
) -> dict[str, Any]:
    table_results = []
    for model in SCHEMA_MODELS:
        table = model._meta.db_table
        if table not in actual["tables"]:
            table_results.append(
                {
                    "name": table,
                    "status": "missing",
                    "classification": "PENDIENTE_CREACIÓN",
                    "issues": [],
                    "column_differences": [],
                }
            )
            continue
        column_differences = _column_compatibility_differences(
            model,
            actual,
            connection,
        )
        issues = _table_compatibility_issues(
            model,
            actual,
            database_name,
            connection,
        )
        table_results.append(
            {
                "name": table,
                "status": "conflict" if issues else "existing",
                "classification": _table_classification(
                    issues,
                    column_differences,
                ),
                "issues": issues,
                "column_differences": column_differences,
            }
        )

    fingerprint = hashlib.sha256(
        json.dumps(
            {"database_name": database_name, "snapshot": actual},
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "backend": connection.vendor,
        "database_name": database_name,
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
        "fingerprint": fingerprint,
    }


def _validate_connection(connection, database_name: str) -> BaseDatabaseWrapper:
    if (
        not isinstance(connection, BaseDatabaseWrapper)
        or connection.vendor != "mysql"
        or not connection.alias.startswith("mysql_runtime_")
    ):
        raise BaseDTESchemaInstallError(
            "La conexión Base DTE no abrió un alias MySQL operacional aislado."
        )
    with connection.cursor() as cursor:
        cursor.execute("SELECT DATABASE()")
        row = cursor.fetchone()
    if not row or row[0] != database_name:
        raise BaseDTESchemaInstallError(
            "La conexión abierta no corresponde a la base Base DTE configurada."
        )
    return connection


def _open_base_dte(connection_config, database_name: str):
    if not isinstance(connection_config, SettingsMySQLConnection):
        raise BaseDTESchemaInstallError("La configuración Base DTE no es válida.")
    if not connection_config.is_active:
        raise BaseDTESchemaInstallError(
            "La conexión configurada para Base DTE está inactiva."
        )
    if (
        SettingsMySQLConnection.normalize_engine(connection_config.engine)
        != SettingsMySQLConnection.ENGINE_DJANGO_MYSQL
    ):
        raise BaseDTESchemaInstallError(
            "La creación controlada requiere el backend Django MySQL configurado."
        )
    if (
        not isinstance(database_name, str)
        or not GestionDTEConnectionRole.DATABASE_NAME_PATTERN.fullmatch(database_name)
    ):
        raise BaseDTESchemaInstallError(
            "La base de datos del rol Base DTE no está configurada o no es válida."
        )
    return open_mysql_connection(connection_config, database_name=database_name)


def _schema_operation(
    connection_config: SettingsMySQLConnection,
    database_name: str,
    operation,
):
    try:
        with _open_base_dte(connection_config, database_name) as opened:
            connection = _validate_connection(opened, database_name)
            actual = _inspect_schema(connection, database_name)
            return operation(connection, actual)
    except BaseDTESchemaInstallError:
        raise
    except MySQLConnectionOpenError as exc:
        raise BaseDTESchemaInstallError(
            "No se pudo abrir la conexión Base DTE configurada."
        ) from exc
    except Exception as exc:
        raise BaseDTESchemaInstallError(
            f"No se pudo procesar la estructura Base DTE ({type(exc).__name__})."
        ) from exc


def preview_base_dte_schema(
    connection_config: SettingsMySQLConnection,
    database_name: str,
) -> dict[str, Any]:
    _read_schema_statements()
    return _schema_operation(
        connection_config,
        database_name,
        lambda connection, actual: _build_preview(
            actual,
            database_name,
            connection,
        ),
    )


def install_base_dte_schema(
    connection_config: SettingsMySQLConnection,
    database_name: str,
    expected_fingerprint: str,
) -> dict[str, Any]:
    statements = _read_schema_statements()
    if not expected_fingerprint:
        raise BaseDTESchemaInstallError(
            "La creación requiere una inspección y confirmación previas."
        )

    def create_missing(connection, actual):
        plan = _build_preview(actual, database_name, connection)
        if plan["fingerprint"] != expected_fingerprint:
            raise BaseDTESchemaInstallError(
                "La estructura cambió desde la vista previa; vuelva a inspeccionarla."
            )
        if plan["conflicts"]:
            return {
                "created": [],
                "existing": plan["existing"],
                "omitted": plan["missing"],
                "conflicts": plan["conflicts"],
                "error_table": None,
                "error_type": None,
                "pending": [],
            }

        created: list[str] = []
        pending = list(plan["missing"])
        for table in tuple(pending):
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        _schema_statement_for_connection(
                            table,
                            statements[table],
                            connection,
                        )
                    )
            except Exception as exc:
                return {
                    "created": created,
                    "existing": plan["existing"],
                    "omitted": [],
                    "conflicts": [],
                    "error_table": table,
                    "error_type": type(exc).__name__,
                    "pending": pending[pending.index(table):],
                }

            pending.remove(table)
            created.append(table)
            try:
                current = _inspect_schema(connection, database_name)
                current_plan = _build_preview(current, database_name, connection)
                if current_plan["conflicts"]:
                    return {
                        "created": created,
                        "existing": plan["existing"],
                        "omitted": [],
                        "conflicts": current_plan["conflicts"],
                        "error_table": table,
                        "error_type": "POST_CREATE_SCHEMA_MISMATCH",
                        "pending": pending,
                    }
                table_status = next(
                    item for item in current_plan["tables"]
                    if item["name"] == table
                )
            except Exception as exc:
                return {
                    "created": created,
                    "existing": plan["existing"],
                    "omitted": [],
                    "conflicts": [],
                    "error_table": table,
                    "error_type": type(exc).__name__,
                    "pending": pending,
                }
            if table_status["status"] != "existing":
                return {
                    "created": created,
                    "existing": plan["existing"],
                    "omitted": [],
                    "conflicts": [table_status],
                    "error_table": table,
                    "error_type": "POST_CREATE_SCHEMA_MISMATCH",
                    "pending": pending,
                }

        return {
            "created": created,
            "existing": plan["existing"],
            "omitted": [],
            "conflicts": [],
            "error_table": None,
            "error_type": None,
            "pending": [],
        }

    return _schema_operation(
        connection_config,
        database_name,
        create_missing,
    )
