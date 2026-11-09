"""Validation and canonical normalization for Chilean RUT values."""

from __future__ import annotations

import re
from typing import Final


class RutValidationError(ValueError):
    """Raised when a RUT value has an invalid type, structure, or character."""


_CANONICAL_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(?P<body>[0-9]{1,8})-(?P<dv>[0-9K])$")
_ALLOWED_SEPARATORS: Final[frozenset[str]] = frozenset({".", "-", " ", "\t", "\r", "\n"})


def limpiar_rut(value: str | None) -> str | None:
    """Remove permitted separators and uppercase the verification digit."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("El RUT debe ser una cadena o None.")

    cleaned: list[str] = []
    for character in value:
        if character in _ALLOWED_SEPARATORS:
            continue
        if character in "0123456789" or character in {"k", "K"}:
            cleaned.append(character.upper())
            continue
        raise RutValidationError("El RUT contiene caracteres no permitidos.")

    result = "".join(cleaned)
    return result or None


def _parse_rut(value: str | None) -> tuple[str, str] | None:
    cleaned = limpiar_rut(value)
    if cleaned is None:
        return None

    if len(cleaned) < 2:
        raise RutValidationError("El RUT debe incluir cuerpo y dígito verificador.")

    body, dv = cleaned[:-1], cleaned[-1]
    if (
        not all(character in "0123456789" for character in body)
        or not 1 <= len(body) <= 8
        or dv not in "0123456789K"
    ):
        raise RutValidationError("La estructura del RUT no es válida.")
    return body, dv


def calcular_digito_verificador(cuerpo: str) -> str:
    """Calculate the Chilean RUT verification digit using modulo 11."""

    if not isinstance(cuerpo, str):
        raise TypeError("El cuerpo del RUT debe ser una cadena.")
    if not 1 <= len(cuerpo) <= 8 or not all(character in "0123456789" for character in cuerpo):
        raise RutValidationError("El cuerpo del RUT debe tener entre 1 y 8 dígitos.")

    total = 0
    multiplier = 2
    for digit in reversed(cuerpo):
        total += int(digit) * multiplier
        multiplier = multiplier + 1 if multiplier < 7 else 2

    remainder = total % 11
    if remainder == 0:
        return "0"
    if remainder == 1:
        return "K"
    return str(11 - remainder)


def normalizar_rut(value: str | None) -> str | None:
    """Return the canonical ``cuerpo-DV`` representation, or None when absent."""

    parsed = _parse_rut(value)
    if parsed is None:
        return None

    body, dv = parsed
    expected = calcular_digito_verificador(body)
    if dv != expected:
        raise RutValidationError("El dígito verificador del RUT no es válido.")
    return f"{body}-{dv}"


def validar_rut(value: str | None) -> bool:
    """Return whether ``value`` is a structurally and mathematically valid RUT."""

    try:
        normalized = normalizar_rut(value)
    except (RutValidationError, TypeError):
        return False
    if normalized is None:
        return False
    return _CANONICAL_PATTERN.fullmatch(normalized) is not None
