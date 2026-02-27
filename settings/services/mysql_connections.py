from typing import Optional, Dict

from django.http import HttpRequest

from access_control.models import Empresa
from ..models import SettingsMySQLConnection


class EmpresaActivaRequeridaError(Exception):
    pass


class MySQLConnectionConfigNotFoundError(Exception):
    pass


class MySQLConnectionConfigInactiveError(Exception):
    pass


def _normalize_nombre_logico(nombre_logico: str) -> str:
    if nombre_logico is None:
        return ""
    return nombre_logico.lower().strip()


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
