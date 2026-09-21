from contextlib import contextmanager
import re
from typing import Dict, Iterator, Optional
from uuid import uuid4

from django.conf import settings
from django.db import connections
from django.http import HttpRequest

from access_control.models import Empresa
from ..models import SettingsMySQLConnection


class EmpresaActivaRequeridaError(Exception):
    pass


class MySQLConnectionConfigNotFoundError(Exception):
    pass


class MySQLConnectionConfigInactiveError(Exception):
    pass


class MySQLConnectionOpenError(Exception):
    pass


def _normalize_nombre_logico(nombre_logico: str) -> str:
    if nombre_logico is None:
        return ""
    return nombre_logico.lower().strip()


_DATABASE_NAME_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')


def _resolve_database_name(connection_config: SettingsMySQLConnection, database_name: Optional[str]) -> str:
    if database_name is None:
        return connection_config.db_name
    if not isinstance(database_name, str) or not _DATABASE_NAME_PATTERN.fullmatch(database_name):
        raise MySQLConnectionOpenError('El nombre de base de datos no es válido.')
    return database_name


def get_mysql_connection_config(empresa_id: int, nombre_logico: str) -> Dict[str, Optional[object]]:
    nombre = _normalize_nombre_logico(nombre_logico)
    if not nombre:
        raise MySQLConnectionConfigNotFoundError("nombre_logico inválido")

    try:
        cfg = SettingsMySQLConnection.objects.get(empresa_id=empresa_id, nombre_logico=nombre)
    except SettingsMySQLConnection.DoesNotExist:
        raise MySQLConnectionConfigNotFoundError("No se encontró configuración para la empresa y nombre solicitado")

    if not cfg.is_active:
        raise MySQLConnectionConfigInactiveError("La configuración existe pero está inactiva")

    return {
        "empresa_id": cfg.empresa_id,
        "nombre_logico": cfg.nombre_logico,
        "host": cfg.host,
        "port": cfg.port,
        "user": cfg.user,
        "password": cfg.password,
        "db_name": cfg.db_name,
        "is_active": cfg.is_active,
    }


def get_mysql_connection_config_for_request(request: HttpRequest, nombre_logico: str) -> Dict[str, Optional[object]]:
    empresa_id = None
    if hasattr(request, "session"):
        empresa_id = request.session.get("empresa_id")

    if not empresa_id:
        raise EmpresaActivaRequeridaError("Empresa activa requerida en sesión")

    return get_mysql_connection_config(empresa_id, nombre_logico)


@contextmanager
def open_mysql_connection(
    connection_config: SettingsMySQLConnection,
    database_name: Optional[str] = None,
) -> Iterator[object]:
    """Open one concrete MySQL configuration and close it on exit."""
    if not isinstance(connection_config, SettingsMySQLConnection):
        raise TypeError("connection_config debe ser SettingsMySQLConnection")

    effective_database = _resolve_database_name(connection_config, database_name)

    engine = SettingsMySQLConnection.normalize_engine(connection_config.engine)
    if engine == SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL:
        try:
            import pymysql
        except Exception as exc:
            raise MySQLConnectionOpenError("No se pudo cargar el driver MySQL.") from exc

        connection = None
        try:
            charset = (connection_config.charset or "utf8").strip() or "utf8"
            try:
                connection = pymysql.connect(
                    host=connection_config.host,
                    port=int(connection_config.port or 3306),
                    user=connection_config.user,
                    password=connection_config.password,
                    database=effective_database,
                    charset=charset,
                    connect_timeout=5,
                    read_timeout=10,
                    write_timeout=10,
                )
            except Exception as exc:
                raise MySQLConnectionOpenError(
                    f"No se pudo abrir la conexión MySQL {connection_config.nombre_logico!r}."
                ) from exc
            yield connection
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
        return

    if engine == SettingsMySQLConnection.ENGINE_API_REMOTA:
        raise MySQLConnectionOpenError("El tipo de conexión remota no está implementado.")

    if engine != SettingsMySQLConnection.ENGINE_DJANGO_MYSQL:
        raise MySQLConnectionOpenError("El tipo de conexión MySQL no está soportado.")

    alias = f"mysql_runtime_{uuid4().hex}"
    base_config = getattr(settings, "DATABASES", {}).get("default", {}).copy()
    base_config.update(
        {
            "ENGINE": SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
            "NAME": effective_database,
            "USER": connection_config.user,
            "PASSWORD": connection_config.password,
            "HOST": connection_config.host,
            "PORT": str(connection_config.port or ""),
            "OPTIONS": {"charset": "utf8mb4"},
            "CONN_MAX_AGE": 0,
            "ATOMIC_REQUESTS": False,
        }
    )
    connections.databases[alias] = base_config
    try:
        try:
            connection = connections[alias]
            connection.ensure_connection()
        except Exception as exc:
            raise MySQLConnectionOpenError(
                f"No se pudo abrir la conexión MySQL {connection_config.nombre_logico!r}."
            ) from exc
        yield connection
    finally:
        try:
            connections[alias].close()
        except Exception:
            pass
        connections.databases.pop(alias, None)
