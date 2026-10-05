"""Bootstrap idempotente del schema operacional MySQL de Tareas."""

from __future__ import annotations

import re
from pathlib import Path

from django.apps import apps
from django.db.backends.mysql.schema import DatabaseSchemaEditor

from settings.services.mysql_connections import (
    MySQLConnectionOpenError,
    open_mysql_connection,
)

from ..models import TareaConnectionRole
from .connection_roles import get_tarea_connection, get_tarea_mysql_connection
from .reference_data import BaseTareasReferenceDataError, ensure_mysql_delay_causes


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


def install_base_tareas_schema() -> int:
    """Ensure frozen structure and official causes; MySQL DDL commits separately."""
    try:
        source = get_tarea_connection("BASE_TAREAS")
        if source["type"] != "MYSQL_CONFIG":
            raise BaseTareasSchemaInstallError(
                "BASE_TAREAS utiliza Django y no requiere bootstrap MySQL."
            )
        connection_config = get_tarea_mysql_connection("BASE_TAREAS")
        database_name = source["database_name"]
        with open_mysql_connection(
            connection_config,
            database_name=database_name,
        ) as connection:
            statements = _read_frozen_schema_statements()
            cursor = connection.cursor()
            try:
                for statement in statements:
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
