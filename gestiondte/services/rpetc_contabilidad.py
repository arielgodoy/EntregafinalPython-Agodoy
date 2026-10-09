"""Lecturas y registro contable legacy para cesiones RPETC."""
from __future__ import annotations

import re
import logging
from datetime import date, datetime, time
from decimal import Decimal
from contextlib import contextmanager, nullcontext
from types import TracebackType
from typing import Any, ContextManager, Generator, Iterable, Protocol, Sequence, cast

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils import timezone
from settings.models import SettingsMySQLConnection
from settings.services.mysql_connections import open_mysql_connection

from .connection_roles import (
    GestionDTEConnectionError,
    get_gestiondte_connection,
    get_gestiondte_mysql_connection,
)
from ..utils.sql_identifiers import validate_mysql_identifier


logger = logging.getLogger(__name__)

TIPO_DTE_LEGACY = {"33": "FC"}
CUENTA_CONTABLE_CESIONES = "23100026"
_FOLIO_TOKEN_RE = re.compile(r"\d+")
_SCHEMA_RE = re.compile(r"^[0-9]{2}$")
_SELECT_FIELDS = (
    "rutctacte, tipodocumento, numerodocumento, monto, dh, fecha, "
    "fechadocumento, fechavencimiento, glosacontable, creadopor, "
    "fechacreacion, horacreacion, tipo, codigocuenta"
)


class _AccountingCursor(Protocol):
    description: Sequence[Sequence[Any]]

    def execute(self, query: str, params: Sequence[Any] | None = None) -> Any: ...

    def fetchone(self) -> Sequence[Any] | None: ...

    def fetchall(self) -> Sequence[Sequence[Any]]: ...

    def __enter__(self) -> _AccountingCursor: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class _AccountingConnection(Protocol):
    def cursor(self) -> ContextManager[_AccountingCursor]: ...

    def commit(self) -> None: ...


class ContabilidadLegacyError(RuntimeError):
    """Error controlado de acceso al ERP legacy."""


EVENTO_CESION = "CED"
LEGACY_RCV_SCHEMA = "eltit_conta"
LEGACY_RCV_TABLE = f"`{LEGACY_RCV_SCHEMA}`.`facturasdecompras_eventos_rcv`"


def _validar_codigo_empresa(codigo: Any) -> str:
    codigo = str(codigo or "").strip()
    if not _SCHEMA_RE.fullmatch(codigo):
        raise ContabilidadLegacyError("Código de empresa inválido para consulta legacy.")
    return codigo


def _accounting_schema(empresa=None) -> str:
    try:
        role_config = (
            get_gestiondte_connection("servercontabilidad", empresa=empresa)
            if empresa is not None
            else get_gestiondte_connection("servercontabilidad")
        )
    except (GestionDTEConnectionError, ObjectDoesNotExist) as exc:
        raise ContabilidadLegacyError(
            "No existe configuración de schema legacy contable activa."
        ) from exc
    try:
        return validate_mysql_identifier(
            role_config.get("database_name"),
            label="esquema de contabilidad",
        )
    except ValueError as exc:
        raise ContabilidadLegacyError(
            "El rol servercontabilidad no tiene un schema contable válido."
        ) from exc


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


def _normalizar_tipo_sii(tipo_doc: Any) -> str:
    tipo = str(tipo_doc or "").strip()
    if not tipo or not tipo.isdigit() or len(tipo) > 3:
        raise ContabilidadLegacyError("Tipo de documento SII inválido para evento contable.")
    return tipo


def _normalizar_numero_doc(folio: Any) -> str:
    numero = str(folio or "").strip()
    if not numero or len(numero) > 10 or not numero.isdigit():
        raise ContabilidadLegacyError("Folio inválido para evento contable.")
    return numero


def _fecha_hora_evento(fecha_cesion: Any) -> tuple[date, time]:
    if not isinstance(fecha_cesion, datetime):
        raise ContabilidadLegacyError("La cesión no tiene fecha y hora válidas.")
    if timezone.is_naive(fecha_cesion):
        fecha_cesion = timezone.make_aware(fecha_cesion, timezone.get_current_timezone())
    fecha_local = timezone.localtime(fecha_cesion)
    return fecha_local.date(), fecha_local.time().replace(microsecond=0)


def _glosa_cesion(cesion: Any) -> str:
    cesionario = getattr(cesion, "cesionario_razon_social", None)
    if not cesionario:
        cesionario = normalizar_rut_legacy(
            getattr(cesion, "cesionario_rut", None),
            getattr(cesion, "cesionario_dv", None),
        ) or ""
    return f"DTE Cedido - {cesionario}"[:100]


def _evento_cesion_values(empresa_codigo: Any, cesion: Any) -> tuple[dict[str, Any], tuple[Any, ...]]:
    codigo = _validar_codigo_empresa(empresa_codigo)
    rut_proveedor = normalizar_rut_legacy(
        getattr(cesion, "cedente_rut", None),
        getattr(cesion, "cedente_dv", None),
    )
    if not rut_proveedor:
        raise ContabilidadLegacyError("La cesión no tiene RUT proveedor válido.")
    fecha_evento, hora_evento = _fecha_hora_evento(getattr(cesion, "fecha_cesion", None))
    values = {
        "rut_proveedor": rut_proveedor,
        "tipo_doc": _normalizar_tipo_sii(getattr(cesion, "tipo_doc", None)),
        "numero_doc": _normalizar_numero_doc(getattr(cesion, "folio_doc", None)),
        "tipo_evento": EVENTO_CESION,
        "fecha_evento": fecha_evento,
        "hora_evento": hora_evento,
        "glosa_evento": _glosa_cesion(cesion),
        "empresa_verificacion": codigo,
    }
    identity = (
        values["empresa_verificacion"],
        values["rut_proveedor"],
        values["tipo_doc"],
        values["numero_doc"],
        values["tipo_evento"],
    )
    return values, identity


def registrar_cesiones_contabilidad(
    empresa_codigo: Any,
    cesiones: Iterable[Any],
    *,
    empresa=None,
) -> dict[str, int]:
    """Registra eventos CED sin duplicar cesiones previamente registradas."""
    cesiones = list(cesiones)
    result = {
        "eventos_creados": 0,
        "eventos_actualizados": 0,
        "eventos_sin_cambios": 0,
        "errores_contables": 0,
    }
    if not cesiones:
        return result
    if empresa is not None and str(empresa_codigo) != str(empresa.codigo):
        raise ContabilidadLegacyError(
            "El código de empresa no coincide con la empresa activa."
        )
    config = _mysql_connection_config(empresa)
    try:
        with _open_accounting_connection(config, database_name=LEGACY_RCV_SCHEMA) as connection:
            transaction_context = (
                transaction.atomic(using=connection.alias)
                if isinstance(connection, BaseDatabaseWrapper)
                else nullcontext()
            )
            with transaction_context:
                with connection.cursor() as cursor:
                    for cesion in cesiones:
                        try:
                            values, identity = _evento_cesion_values(empresa_codigo, cesion)
                            cursor.execute(
                                "SELECT fecha_evento, hora_evento, glosa_evento "
                                f"FROM {LEGACY_RCV_TABLE} "
                                "WHERE empresa_verificacion=%s AND rut_proveedor=%s "
                                "AND tipo_doc=%s AND numero_doc=%s AND tipo_evento=%s LIMIT 1",
                                identity,
                            )
                            existing = cursor.fetchone()
                            if existing is None:
                                cursor.execute(
                                    f"INSERT INTO {LEGACY_RCV_TABLE} "
                                    "(rut_proveedor, tipo_doc, numero_doc, tipo_evento, fecha_evento, "
                                    "hora_evento, glosa_evento, empresa_verificacion) "
                                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                                    (
                                        values["rut_proveedor"], values["tipo_doc"], values["numero_doc"],
                                        values["tipo_evento"], values["fecha_evento"], values["hora_evento"],
                                        values["glosa_evento"], values["empresa_verificacion"],
                                    ),
                                )
                                result["eventos_creados"] += 1
                            elif tuple(existing) == (
                                values["fecha_evento"], values["hora_evento"], values["glosa_evento"],
                            ):
                                result["eventos_sin_cambios"] += 1
                            else:
                                cursor.execute(
                                    f"UPDATE {LEGACY_RCV_TABLE} SET fecha_evento=%s, hora_evento=%s, "
                                    "glosa_evento=%s WHERE empresa_verificacion=%s AND rut_proveedor=%s "
                                    "AND tipo_doc=%s AND numero_doc=%s AND tipo_evento=%s",
                                    (
                                        values["fecha_evento"], values["hora_evento"], values["glosa_evento"],
                                        *identity,
                                    ),
                                )
                                result["eventos_actualizados"] += 1
                        except ContabilidadLegacyError:
                            result["errores_contables"] += 1
                if not isinstance(connection, BaseDatabaseWrapper):
                    connection.commit()
    except Exception as exc:
        raise ContabilidadLegacyError("No fue posible registrar eventos contables RPETC.") from exc
    return result


def _mysql_connection_config(empresa=None) -> SettingsMySQLConnection:
    try:
        return (
            get_gestiondte_mysql_connection("servercontabilidad", empresa=empresa)
            if empresa is not None
            else get_gestiondte_mysql_connection("servercontabilidad")
        )
    except (GestionDTEConnectionError, ObjectDoesNotExist) as exc:
        raise ContabilidadLegacyError(
            "No existe conexión legacy contable activa."
        ) from exc


@contextmanager
def _open_accounting_connection(
    config: SettingsMySQLConnection,
    database_name: str | None = None,
) -> Generator[BaseDatabaseWrapper | _AccountingConnection, None, None]:
    connection_context = (
        open_mysql_connection(config)
        if database_name is None
        else open_mysql_connection(config, database_name=database_name)
    )
    with connection_context as connection:
        yield cast(BaseDatabaseWrapper | _AccountingConnection, connection)


def _movimiento_dicts(cursor) -> list[dict[str, Any]]:
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _query_movimientos(
    empresa_codigo: str,
    keys: set[tuple[str, str, str, str, str]],
    *,
    empresa=None,
) -> list[dict[str, Any]]:
    if not keys:
        return []
    config = _mysql_connection_config(empresa)
    schema = _accounting_schema(empresa)
    table = f"`{schema}`.`movimientoscontables`"
    clauses = []
    params: list[str] = []
    for rutctacte, tipo, folio, dh, codigocuenta in sorted(keys):
        clauses.append("(rutctacte=%s AND tipodocumento=%s AND numerodocumento=%s AND dh=%s AND codigocuenta=%s)")
        params.extend((rutctacte, tipo, folio, dh, codigocuenta))
    sql = f"SELECT {_SELECT_FIELDS} FROM {table} WHERE " + " OR ".join(clauses)
    try:
        with _open_accounting_connection(config) as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return _movimiento_dicts(cursor)
    except Exception as exc:
        raise ContabilidadLegacyError("No fue posible consultar el ERP legacy.") from exc


def _query_factoring_glosa_candidates(
    empresa_codigo: str,
    candidates: set[tuple[str, Decimal]],
    *,
    empresa=None,
) -> list[dict[str, Any]]:
    if not candidates:
        return []
    config = _mysql_connection_config(empresa)
    schema = _accounting_schema(empresa)
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
    try:
        with _open_accounting_connection(config) as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return _movimiento_dicts(cursor)
    except Exception as exc:
        raise ContabilidadLegacyError("No fue posible consultar candidatos de factoring.") from exc


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
    elif found_state == "D" and paid_state:
        result["estado"] = f"{paid_state}_DIFERENCIA"
        result["diferencia_monto"] = legacy_amount - expected if expected is not None else None
    else:
        result["estado"] = "REVISAR"
    return result


def obtener_estados_contables_cesiones(
    empresa_codigo: str,
    cesiones: Iterable[Any],
    *,
    empresa=None,
) -> dict[Any, dict[str, Any]]:
    """Resuelve estados de todas las cesiones con una consulta OR batch."""
    _validar_codigo_empresa(empresa_codigo)
    if empresa is not None and str(empresa_codigo) != str(empresa.codigo):
        raise ContabilidadLegacyError(
            "El código de empresa no coincide con la empresa activa."
        )
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
    for movement in _query_movimientos(empresa_codigo, keys, empresa=empresa):
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
                if role in {"contabilizacion", "pagada_proveedor"}:
                    expected = cesion.monto_total
                else:
                    expected = cesion.monto_cesion
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
        fallback_movements = _query_factoring_glosa_candidates(
            empresa_codigo,
            fallback_candidates,
            empresa=empresa,
        )
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


def obtener_detalle_contable_cesion(
    empresa_codigo: str,
    cesion,
    *,
    empresa=None,
) -> dict[str, Any]:
    """Obtiene ambos bloques de movimientos para una cesión concreta."""
    states = obtener_estados_contables_cesiones(
        empresa_codigo,
        [cesion],
        empresa=empresa,
    )
    return states[cesion.pk]
