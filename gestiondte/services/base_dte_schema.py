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


def install_base_dte_schema(connection_config, database_name=None) -> int:
    statements = _read_schema_statements()
    try:
        if database_name is None:
            connection_context = open_mysql_connection(connection_config)
        else:
            connection_context = open_mysql_connection(
                connection_config,
                database_name=database_name,
            )
        with connection_context as connection:
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
    except BaseDTESchemaInstallError:
        raise
    except MySQLConnectionOpenError as exc:
        effective_database = (
            connection_config.db_name if database_name is None else database_name
        )
        raise BaseDTESchemaInstallError(
            f'No se pudo abrir la base de datos {effective_database!r}.'
        ) from exc
    except Exception as exc:
        raise BaseDTESchemaInstallError(
            'No se pudo crear la estructura Base DTE.'
        ) from exc
    return len(statements)