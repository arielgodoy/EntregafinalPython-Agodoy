"""Resuelve nombres de bases legacy sin abrir conexiones.

La conexión (servidor, credenciales y engine) permanece en
``SettingsMySQLConnection``. Este módulo solo determina el nombre de la base.
"""
from __future__ import annotations

import re

from django.conf import settings


class LegacyDatabaseNameError(ValueError):
    """Indica una configuración o argumento inválido para una base legacy."""


_PREFIX_RE = re.compile(r"^[A-Za-z0-9_]+_$")
_COMPANY_CODE_RE = re.compile(r"^[0-9]{2}$")
_SUPPORTED_DOMAINS = {"gestion", "contabilidad"}


def _get_validated_prefix() -> str:
    prefix = getattr(settings, "CLIENTE_SISTEMA", None)
    if not isinstance(prefix, str) or not _PREFIX_RE.fullmatch(prefix):
        raise LegacyDatabaseNameError(
            "CLIENTE_SISTEMA debe contener solo letras, números y guiones bajos, "
            "y terminar en '_'."
        )
    return prefix


def _validate_company_code(empresa_codigo: object) -> str:
    code = str(empresa_codigo).strip() if empresa_codigo is not None else ""
    if not _COMPANY_CODE_RE.fullmatch(code):
        raise LegacyDatabaseNameError(
            "El código de empresa debe contener exactamente dos dígitos."
        )
    return code


def get_legacy_database_name(domain: str, empresa_codigo: str | None = None) -> str:
    """Devuelve el nombre de base legacy para un dominio soportado.

    ``gestion`` no usa código de empresa. ``contabilidad`` usa ``conta`` como
    base central y agrega el código solo para empresas distintas de ``00``.
    """
    if not isinstance(domain, str):
        raise LegacyDatabaseNameError("El dominio legacy es inválido.")

    normalized_domain = domain.strip().lower()
    if normalized_domain not in _SUPPORTED_DOMAINS:
        raise LegacyDatabaseNameError(
            "Dominio legacy no soportado. Use 'gestion' o 'contabilidad'."
        )

    prefix = _get_validated_prefix()
    if normalized_domain == "gestion":
        if empresa_codigo is not None:
            raise LegacyDatabaseNameError(
                "gestion no admite código de empresa en el nombre de base."
            )
        return f"{prefix}gestion"

    if empresa_codigo is None:
        return f"{prefix}conta"

    code = _validate_company_code(empresa_codigo)
    if code == "00":
        return f"{prefix}conta"
    return f"{prefix}conta{code}"
