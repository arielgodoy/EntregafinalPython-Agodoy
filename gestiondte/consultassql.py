import re


_DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


def build_maestroempresa_by_codigo_query(schema_name, codigo):
    if not isinstance(schema_name, str) or not _DATABASE_NAME_PATTERN.fullmatch(schema_name):
        raise ValueError("El esquema de contabilidad no es válido.")
    return (
        f"SELECT codigoempresa, nombre, rut, rutenviasii "
        f"FROM `{schema_name}`.maestroempresas "
        "WHERE codigoempresa = %s LIMIT 1",
        (codigo,),
    )


CERTIFICATE_COLUMNS = (
    "id, empresa_codigo, archivo, password_encrypted, activo, titular, "
    "emisor_certificado, numero_serie, rut_titular, valido_desde, valido_hasta, "
    "created_by_id, updated_by_id, created_by_username, updated_by_username, "
    "created_at, updated_at"
)


def build_certificado_list_query(empresa_codigo, pk=None):
    if pk is None:
        return (
            f"SELECT {CERTIFICATE_COLUMNS} FROM gestiondte_certificadosii "
            "WHERE empresa_codigo = %s ORDER BY created_at DESC",
            (empresa_codigo,),
        )
    return (
        f"SELECT {CERTIFICATE_COLUMNS} FROM gestiondte_certificadosii "
        "WHERE id = %s AND empresa_codigo = %s LIMIT 1",
        (pk, empresa_codigo),
    )


def build_certificado_insert_query(values):
    fields = tuple(values)
    placeholders = ", ".join("%s" for _ in fields)
    return (
        f"INSERT INTO gestiondte_certificadosii ({', '.join(fields)}) "
        f"VALUES ({placeholders})",
        tuple(values[field] for field in fields),
    )


def build_certificado_update_query(pk, empresa_codigo, values):
    assignments = ", ".join(f"{field} = %s" for field in values)
    return (
        f"UPDATE gestiondte_certificadosii SET {assignments} "
        "WHERE id = %s AND empresa_codigo = %s",
        tuple(values.values()) + (pk, empresa_codigo),
    )


def build_certificado_delete_query(pk, empresa_codigo):
    return (
        "DELETE FROM gestiondte_certificadosii WHERE id = %s AND empresa_codigo = %s",
        (pk, empresa_codigo),
    )
