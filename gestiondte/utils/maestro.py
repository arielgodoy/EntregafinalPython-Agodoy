from django.db import connections

from settings.services.mysql_connections import open_mysql_connection

from ..consultassql import build_maestroempresa_by_codigo_query
from ..services.connection_roles import (
    GestionDTECompanyMismatchError,
    get_gestiondte_connection,
    get_gestiondte_mysql_connection,
)


def _row_to_dict(row):
    if not row:
        return None
    return {
        "codigo": row[0],
        "nombre": row[1],
        "rut": row[2],
        "rutenviasii": row[3],
    }


def get_maestroempresa_by_codigo(codigo, *, empresa=None):
    """Read one company from the global accounting database via servercontabilidad."""
    if codigo is None:
        return None

    codigo_str = str(codigo).strip()
    if empresa is not None and codigo_str != str(empresa.codigo):
        raise GestionDTECompanyMismatchError(
            "El código de empresa no coincide con la empresa activa."
        )
    candidates = [codigo_str]
    stripped = codigo_str.lstrip("0")
    if stripped and stripped != codigo_str:
        candidates.append(stripped)

    role_config = (
        get_gestiondte_connection("servercontabilidad", empresa=empresa)
        if empresa is not None
        else get_gestiondte_connection("servercontabilidad")
    )
    schema_name = role_config.get("database_name")
    if not schema_name:
        raise ValueError("El rol servercontabilidad no tiene database_name configurado.")

    if role_config["type"] == "DJANGO":
        connection = connections[role_config["alias"]]
        with connection.cursor() as cursor:
            for candidate in candidates:
                query, params = build_maestroempresa_by_codigo_query(schema_name, candidate)
                cursor.execute(query, params)
                result = _row_to_dict(cursor.fetchone())
                if result:
                    return result
        return None

    if role_config["type"] != "MYSQL_CONFIG":
        return None

    connection_config = (
        get_gestiondte_mysql_connection("servercontabilidad", empresa=empresa)
        if empresa is not None
        else get_gestiondte_mysql_connection("servercontabilidad")
    )
    with open_mysql_connection(connection_config, database_name=schema_name) as connection:
        cursor = connection.cursor()
        try:
            for candidate in candidates:
                query, params = build_maestroempresa_by_codigo_query(schema_name, candidate)
                cursor.execute(query, params)
                result = _row_to_dict(cursor.fetchone())
                if result:
                    return result
            return None
        finally:
            cursor.close()
