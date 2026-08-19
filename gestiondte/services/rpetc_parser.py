"""Parser conservador del TXT de resultados API-RPETC."""
from __future__ import annotations

import csv
import io
from typing import Any


class RPETCParseError(ValueError):
    pass


def _decode(content: bytes) -> str:
    for encoding in ("utf-8", "cp1252", "latin1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise RPETCParseError("No se pudo decodificar el resultado TXT.")


def _metadata(line: str) -> dict[str, str]:
    fields = next(csv.reader([line], delimiter=";"), [])
    if not fields or fields[0] != "DATOS_CONSULTA":
        raise RPETCParseError("Falta la linea DATOS_CONSULTA.")
    result: dict[str, str] = {}
    for field in fields[1:]:
        key, separator, value = field.partition("=")
        if separator:
            result[key] = value
    return result


def parsear_txt_rpetc(content: bytes) -> dict[str, Any]:
    """Retorna metadata, columnas y registros sin convertir valores."""
    if not isinstance(content, bytes):
        raise RPETCParseError("El resultado RPETC debe recibirse como bytes.")
    lines = _decode(content).splitlines()
    if len(lines) < 2:
        raise RPETCParseError("El resultado TXT no contiene encabezados.")
    consulta = _metadata(lines[0])
    reader = csv.reader(io.StringIO(lines[1]), delimiter=";")
    columnas = next(reader, [])
    if not columnas or any(not column for column in columnas):
        raise RPETCParseError("El encabezado TXT es invalido.")
    registros: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines[2:], start=3):
        if not line.strip():
            continue
        values = next(csv.reader([line], delimiter=";"), [])
        if len(values) < len(columnas):
            raise RPETCParseError(
                f"La linea {line_number} tiene menos columnas que el encabezado."
            )
        record = dict(zip(columnas, values[:len(columnas)]))
        if len(values) > len(columnas):
            record["__extra__"] = values[len(columnas):]
        registros.append(record)
    return {
        "consulta": consulta,
        "columnas": columnas,
        "registros": registros,
        "cantidad_registros": len(registros),
    }
