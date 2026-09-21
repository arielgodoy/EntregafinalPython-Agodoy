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
