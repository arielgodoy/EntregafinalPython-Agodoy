from pathlib import Path
import re

from settings.services.mysql_connections import (
    MySQLConnectionOpenError,
    open_mysql_connection,
)


class BaseDTESchemaInstallError(RuntimeError):
    pass


SCHEMA_PATH = Path(__file__).resolve().parents[1] / 'sql' / 'base_dte_schema.sql'
_FORBIDDEN_SQL = re.compile(r'\b(?:ALTER|DROP|TRUNCATE|DELETE|RENAME)\b', re.IGNORECASE)


def _read_schema_statements() -> list[str]:
    try:
        content = SCHEMA_PATH.read_text(encoding='utf-8')
    except OSError as exc:
        raise BaseDTESchemaInstallError('No se pudo leer la estructura Base DTE.') from exc

    statements = [statement.strip() for statement in content.split(';') if statement.strip()]
    if not statements:
        raise BaseDTESchemaInstallError('La estructura Base DTE está vacía.')
    for statement in statements:
        if not statement.upper().startswith('CREATE TABLE IF NOT EXISTS'):
            raise BaseDTESchemaInstallError('La estructura contiene una operación no permitida.')
        if _FORBIDDEN_SQL.search(statement):
            raise BaseDTESchemaInstallError('La estructura contiene una operación no permitida.')
    return statements


def install_base_dte_schema(connection_config) -> int:
    statements = _read_schema_statements()
    try:
        with open_mysql_connection(connection_config) as connection:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
    except (BaseDTESchemaInstallError, MySQLConnectionOpenError):
        raise
    except Exception as exc:
        raise BaseDTESchemaInstallError(
            'No se pudo crear la estructura Base DTE.'
        ) from exc
    return len(statements)