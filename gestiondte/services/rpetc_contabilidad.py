"""Lecturas batch de estados contables para cesiones RPETC."""
from __future__ import annotations

import re
import logging
from decimal import Decimal
from typing import Any, Iterable

from settings.models import SettingsMySQLConnection


logger = logging.getLogger(__name__)

try:
    import pymysql
except ImportError:  # pragma: no cover - el entorno productivo debe incluirlo
    pymysql = None


TIPO_DTE_LEGACY = {"33": "FC"}
CUENTA_CONTABLE_CESIONES = "23100026"
_SCHEMA_RE = re.compile(r"^[0-9]{2}$")
_FOLIO_TOKEN_RE = re.compile(r"\d+")
_SELECT_FIELDS = (
    "rutctacte, tipodocumento, numerodocumento, monto, dh, fecha, "
    "fechadocumento, fechavencimiento, glosacontable, creadopor, "
    "fechacreacion, horacreacion, tipo, codigocuenta"
)


class ContabilidadLegacyError(RuntimeError):
    """Error controlado de lectura del ERP legacy."""


def _validar_codigo_empresa(codigo: Any) -> str:
    codigo = str(codigo or "").strip()
    if not _SCHEMA_RE.fullmatch(codigo):
        raise ContabilidadLegacyError("Código de empresa inválido para consulta legacy.")
    return codigo


def _schema_empresa(codigo: Any) -> str:
    return f"eltit_conta{_validar_codigo_empresa(codigo)}"


def normalizar_rut_legacy(rut: Any, dv: Any) -> str | None:
    if rut is None or dv is None:
        return None
    cuerpo = re.sub(r"[.\-\s]", "", str(rut).strip())
    verificador = str(dv).strip().upper()
    if not cuerpo.isdigit() or len(verificador) != 1 or not re.fullmatch(r"[0-9K]", verificador):
        return None
    return f"{cuerpo}{verificador}".zfill(10)


def normalizar_folio_legacy(folio: Any, tipo_legacy: str) -> str | None:
    if folio is None:
        return None
    value = str(folio).strip()
    if not value:
        return None
    if tipo_legacy in {"FC", "DB"}:
        return value.zfill(10)
    return None


def _config_legacy() -> SettingsMySQLConnection:
    config = SettingsMySQLConnection.objects.filter(
        is_active=True,
        engine=SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL,
        db_name="eltit_conta",
    ).order_by("pk").first()
    if not config:
        raise ContabilidadLegacyError("No existe conexión legacy contable activa.")
    if pymysql is None:
        raise ContabilidadLegacyError("La librería de conexión legacy no está disponible.")
    return config


def _movimiento_dicts(cursor) -> list[dict[str, Any]]:
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _query_movimientos(empresa_codigo: str, keys: set[tuple[str, str, str, str, str]]) -> list[dict[str, Any]]:
    if not keys:
        return []
    config = _config_legacy()
    schema = _schema_empresa(empresa_codigo)
    table = f"`{schema}`.`movimientoscontables`"
    clauses = []
    params: list[str] = []
    for rutctacte, tipo, folio, dh, codigocuenta in sorted(keys):
        clauses.append("(rutctacte=%s AND tipodocumento=%s AND numerodocumento=%s AND dh=%s AND codigocuenta=%s)")
        params.extend((rutctacte, tipo, folio, dh, codigocuenta))
    sql = f"SELECT {_SELECT_FIELDS} FROM {table} WHERE " + " OR ".join(clauses)
    connection = None
    try:
        connection = pymysql.connect(
            host=config.host,
            port=int(config.port or 3306),
            user=config.user,
            password=config.password,
            database=config.db_name,
            charset=(config.charset or "latin1"),
            connect_timeout=5,
            read_timeout=15,
            write_timeout=10,
        )
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return _movimiento_dicts(cursor)
    except Exception as exc:
        raise ContabilidadLegacyError("No fue posible consultar el ERP legacy.") from exc
    finally:
        if connection is not None:
            connection.close()


def _query_factoring_glosa_candidates(
    empresa_codigo: str,
    candidates: set[tuple[str, Decimal]],
) -> list[dict[str, Any]]:
    if not candidates:
        return []
    config = _config_legacy()
    schema = _schema_empresa(empresa_codigo)
    table = f"`{schema}`.`movimientoscontables`"
    clauses = []
    params: list[Any] = []
    for rutctacte, monto in sorted(candidates):
        clauses.append("(rutctacte=%s AND monto=%s)")
        params.extend((rutctacte, monto))
    sql = (
        f"SELECT {_SELECT_FIELDS} FROM {table} "
        "WHERE codigocuenta=%s AND dh=%s AND tipo=%s AND tipodocumento=%s "
        "AND (" + " OR ".join(clauses) + ")"
    )
    params = [CUENTA_CONTABLE_CESIONES, "D", "DB", "DB", *params]
    connection = None
    try:
        connection = pymysql.connect(
            host=config.host,
            port=int(config.port or 3306),
            user=config.user,
            password=config.password,
            database=config.db_name,
            charset=(config.charset or "latin1"),
            connect_timeout=5,
            read_timeout=15,
            write_timeout=10,
        )
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return _movimiento_dicts(cursor)
    except Exception as exc:
        raise ContabilidadLegacyError("No fue posible consultar candidatos de factoring.") from exc
    finally:
        if connection is not None:
            connection.close()


def _folio_en_glosa(folio: Any, glosa: Any) -> bool:
    folio_normalizado = str(folio or "").strip().lstrip("0") or "0"
    tokens = _FOLIO_TOKEN_RE.findall(str(glosa or ""))
    return any((token.lstrip("0") or "0") == folio_normalizado for token in tokens)


def _key_for(cesion, role: str, tipo_legacy: str | None = None) -> tuple[str, str, str, str, str] | None:
    tipo = TIPO_DTE_LEGACY.get(str(cesion.tipo_doc))
    if not tipo:
        return None
    tipo = tipo_legacy or tipo
    if role in {"contabilizacion", "pagada_proveedor"}:
        rut = normalizar_rut_legacy(cesion.cedente_rut, cesion.cedente_dv)
        dh = "H" if role == "contabilizacion" else "D"
    else:
        rut = normalizar_rut_legacy(cesion.cesionario_rut, cesion.cesionario_dv)
        dh = "D"
    folio = normalizar_folio_legacy(cesion.folio_doc, tipo)
    return (rut, tipo, folio, dh, CUENTA_CONTABLE_CESIONES) if rut and folio else None


def _keys_for(cesion, role: str) -> list[tuple[str, str, str, str, str]]:
    tipo = TIPO_DTE_LEGACY.get(str(cesion.tipo_doc))
    if not tipo:
        return []
    tipos = ("FC", "DB") if role == "pagada_factoring" else (tipo,)
    return [key for key in (_key_for(cesion, role, candidate) for candidate in tipos) if key]


def _classify(
    movements: list[dict[str, Any]],
    expected: Decimal | None,
    found_state: str,
    paid_state: str,
    excluded_tipo: str | None = None,
) -> dict[str, Any]:
    if excluded_tipo:
        movements = [
            movement for movement in movements
            if str(movement.get("tipo") or "").strip().upper() != excluded_tipo
        ]
    result = {
        "estado": "NO_CONTABILIZADA" if found_state == "H" else "NO_PAGADA",
        "cantidad_movimientos": len(movements),
        "monto_coincide": False,
        "monto_rpetc": expected,
        "monto_legacy": None,
        "movimientos": movements,
    }
    if len(movements) != 1:
        if len(movements) > 1:
            result["estado"] = "REVISAR"
        return result
    try:
        legacy_amount = Decimal(str(movements[0].get("monto")))
    except Exception:
        result["estado"] = "REVISAR"
        return result
    result["monto_legacy"] = legacy_amount
    result["monto_coincide"] = expected is not None and legacy_amount == expected
    if result["monto_coincide"]:
        result["estado"] = "CONTABILIZADA" if found_state == "H" else paid_state
    else:
        result["estado"] = "REVISAR"
    return result


def obtener_estados_contables_cesiones(empresa_codigo: str, cesiones: Iterable[Any]) -> dict[Any, dict[str, Any]]:
    """Resuelve estados de todas las cesiones con una consulta OR batch."""
    _validar_codigo_empresa(empresa_codigo)
    cesiones = list(cesiones)
    result: dict[Any, dict[str, Any]] = {}
    keys: set[tuple[str, str, str, str, str]] = set()
    key_by_cesion: dict[Any, dict[str, list[tuple[str, str, str, str, str]]]] = {}
    for cesion in cesiones:
        key_by_cesion[cesion.pk] = {
            "contabilizacion": _keys_for(cesion, "contabilizacion"),
            "pagada_factoring": _keys_for(cesion, "pagada_factoring"),
            "pagada_proveedor": _keys_for(cesion, "pagada_proveedor"),
        }
        keys.update(key for candidates in key_by_cesion[cesion.pk].values() for key in candidates)
        result[cesion.pk] = {
            "contabilizacion": {"estado": "TIPO_NO_SOPORTADO" if not key_by_cesion[cesion.pk]["contabilizacion"] else None, "cantidad_movimientos": 0, "movimientos": []},
            "pagada_factoring": {"estado": "TIPO_NO_SOPORTADO" if not key_by_cesion[cesion.pk]["pagada_factoring"] else None, "cantidad_movimientos": 0, "movimientos": []},
            "pagada_proveedor": {"estado": "TIPO_NO_SOPORTADO" if not key_by_cesion[cesion.pk]["pagada_proveedor"] else None, "cantidad_movimientos": 0, "movimientos": []},
        }
    indexed = {}
    for movement in _query_movimientos(empresa_codigo, keys):
        key = (
            movement["rutctacte"],
            movement["tipodocumento"],
            movement["numerodocumento"],
            movement["dh"],
            movement["codigocuenta"],
        )
        indexed.setdefault(key, []).append(movement)
    for cesion in cesiones:
        for role, state, paid_state, excluded_tipo in (
            ("contabilizacion", "H", "PAGADA", None),
            ("pagada_factoring", "D", "PAGADA_FACTORING", None),
            ("pagada_proveedor", "D", "PAGADA_PROVEEDOR", "CT"),
        ):
            keys_for_role = key_by_cesion[cesion.pk][role]
            if keys_for_role:
                expected = cesion.monto_total if role == "contabilizacion" else cesion.monto_cesion
                movements = [
                    movement
                    for candidate_key in keys_for_role
                    for movement in indexed.get(candidate_key, [])
                ]
                result[cesion.pk][role] = _classify(
                    movements,
                    expected,
                    state,
                    paid_state,
                    excluded_tipo,
                )
        result[cesion.pk]["pago"] = dict(result[cesion.pk]["pagada_factoring"])
        if result[cesion.pk]["pago"]["estado"] == "PAGADA_FACTORING":
            result[cesion.pk]["pago"]["estado"] = "PAGADA"

    unresolved = [
        cesion for cesion in cesiones
        if result[cesion.pk]["pagada_factoring"].get("estado") != "PAGADA_FACTORING"
        and key_by_cesion[cesion.pk]["pagada_factoring"]
        and cesion.monto_cesion is not None
    ]
    fallback_candidates = {
        (
            normalizar_rut_legacy(cesion.cesionario_rut, cesion.cesionario_dv),
            Decimal(str(cesion.monto_cesion)),
        )
        for cesion in unresolved
        if normalizar_rut_legacy(cesion.cesionario_rut, cesion.cesionario_dv)
    }
    logger.debug("rpetc factoring fallback iniciado: pending=%d", len(unresolved))
    logger.debug("rpetc factoring fallback claves candidatas: count=%d", len(fallback_candidates))
    try:
        fallback_movements = _query_factoring_glosa_candidates(empresa_codigo, fallback_candidates)
        logger.debug("rpetc factoring fallback candidatos SQL: count=%d", len(fallback_movements))
        fallback_by_cesion: dict[Any, list[dict[str, Any]]] = {cesion.pk: [] for cesion in unresolved}
        for movement in fallback_movements:
            logger.debug(
                "rpetc factoring fallback candidato: rut=%s monto=%s tipo=%s tipodocumento=%s numero=%s glosa=%r",
                movement.get("rutctacte"), movement.get("monto"), movement.get("tipo"),
                movement.get("tipodocumento"), movement.get("numerodocumento"), movement.get("glosacontable"),
            )
            for cesion in unresolved:
                rut_cesionario = normalizar_rut_legacy(cesion.cesionario_rut, cesion.cesionario_dv)
                tokens = _FOLIO_TOKEN_RE.findall(str(movement.get("glosacontable") or ""))
                token_match = _folio_en_glosa(cesion.folio_doc, movement.get("glosacontable"))
                logger.debug(
                    "rpetc factoring fallback folio: pk=%s folio_normalized=%s tokens=%s match=%s",
                    cesion.pk, str(cesion.folio_doc).strip().lstrip("0") or "0", tokens, token_match,
                )
                if (
                    rut_cesionario == movement["rutctacte"]
                    and str(movement.get("codigocuenta") or "") == CUENTA_CONTABLE_CESIONES
                    and str(movement.get("dh") or "").upper() == "D"
                    and str(movement.get("tipo") or "").upper() == "DB"
                    and str(movement.get("tipodocumento") or "").upper() == "DB"
                    and cesion.monto_cesion is not None
                    and Decimal(str(cesion.monto_cesion)) == Decimal(str(movement.get("monto")))
                    and token_match
                ):
                    fallback_by_cesion[cesion.pk].append(movement)
                    logger.debug("rpetc factoring fallback coincidencia: pk=%s final=PAGADA_FACTORING", cesion.pk)
        for cesion in unresolved:
            movements = fallback_by_cesion[cesion.pk]
            if movements:
                result[cesion.pk]["pagada_factoring"] = _classify(
                    movements,
                    cesion.monto_cesion,
                    "D",
                    "PAGADA_FACTORING",
                )
            result[cesion.pk]["pago"] = dict(result[cesion.pk]["pagada_factoring"])
            if result[cesion.pk]["pago"]["estado"] == "PAGADA_FACTORING":
                result[cesion.pk]["pago"]["estado"] = "PAGADA"
            logger.debug(
                "rpetc factoring fallback final: pk=%s estado=%s",
                cesion.pk, result[cesion.pk]["pagada_factoring"].get("estado"),
            )
    except Exception:
        logger.warning(
            "rpetc factoring fallback error: pending=%d; estados exactos conservados",
            len(unresolved),
            exc_info=True,
        )
        for cesion in unresolved:
            result[cesion.pk]["pagada_factoring"] = {
                "estado": "NO_DISPONIBLE",
                "cantidad_movimientos": 0,
                "monto_coincide": False,
                "monto_rpetc": cesion.monto_cesion,
                "monto_legacy": None,
                "movimientos": [],
            }
            result[cesion.pk]["pago"] = dict(result[cesion.pk]["pagada_factoring"])
    return result


def obtener_detalle_contable_cesion(empresa_codigo: str, cesion) -> dict[str, Any]:
    """Obtiene ambos bloques de movimientos para una cesión concreta."""
    states = obtener_estados_contables_cesiones(empresa_codigo, [cesion])
    return states[cesion.pk]
