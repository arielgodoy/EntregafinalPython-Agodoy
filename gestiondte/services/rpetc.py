"""Cliente reutilizable para recursos API-RPETC del SII."""
from __future__ import annotations

import calendar
import datetime as dt
import re
import time
from typing import Any, Callable

import requests
from django.conf import settings

from .sii_auth import SiiAuthError, obtener_access_token_sii


RPETC_BASE_URL = getattr(
    settings,
    "SII_RPETC_BASE_URL",
    "https://api.sii.cl/api/api-rpetc",
).rstrip("/")
SCOPE_TAREA = "RTC_TAR"
SCOPE_ESTADO = "RTC_PRO_EST"
SCOPE_RESULTADO = "RTC_PRO_RES"
FORMATO_PERMITIDOS = {"TXT", "XML"}
ESTADOS_TERMINALES = {"TERMINADO", "FALLO"}
ESTADOS_EN_PROCESO = {"CREADO", "EN_PROCESO"}
FECHA_API_RE = re.compile(r"^\d{8}$")


class RPETCError(Exception):
    """Error base del cliente, con status y cuerpo seguro cuando existen."""

    def __init__(self, message: str, *, status_code: int | None = None,
                 response_body: Any = None, retry_after: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
        self.retry_after = retry_after


class RPETCParameterError(RPETCError, ValueError):
    pass


class RPETCAuthenticationError(RPETCError):
    pass


class RPETCUnauthorizedError(RPETCError):
    pass


class RPETCNotFoundError(RPETCError):
    pass


class RPETCRateLimitError(RPETCError):
    pass


class RPETCServerError(RPETCError):
    pass


class RPETCUnexpectedResponseError(RPETCError):
    pass


class RPETCTaskTimeoutError(RPETCError):
    pass


class RPETCTaskFailedError(RPETCError):
    def __init__(self, message: str, *, task_state: dict[str, Any]):
        super().__init__(message, status_code=None, response_body=task_state)
        self.task_state = task_state


def _parse_api_date(value: str, field_name: str) -> dt.date:
    if not isinstance(value, str) or not FECHA_API_RE.fullmatch(value):
        raise RPETCParameterError(
            f"{field_name} debe usar el formato DDMMYYYY."
        )
    try:
        return dt.datetime.strptime(value, "%d%m%Y").date()
    except ValueError as exc:
        raise RPETCParameterError(f"{field_name} no es una fecha valida.") from exc


def _add_month(value: dt.date) -> dt.date:
    month = value.month + 1
    year = value.year
    if month == 13:
        month = 1
        year += 1
    return value.replace(day=min(value.day, calendar.monthrange(year, month)[1]),
                        month=month, year=year)


def validar_parametros_cesiones(
    desde: str,
    hasta: str,
    formato: str,
) -> str:
    """Valida el contrato local y retorna formato normalizado."""
    desde_date = _parse_api_date(desde, "desde")
    hasta_date = _parse_api_date(hasta, "hasta")
    if desde_date > hasta_date:
        raise RPETCParameterError("desde no puede ser posterior a hasta.")
    if hasta_date > _add_month(desde_date):
        raise RPETCParameterError("El rango solicitado no puede superar un mes.")
    normalized = str(formato).upper() if formato is not None else ""
    if normalized not in FORMATO_PERMITIDOS:
        raise RPETCParameterError("formato debe ser TXT o XML.")
    return normalized


def _normalize_state(value: Any) -> str:
    if not isinstance(value, str):
        raise RPETCUnexpectedResponseError("La respuesta no contiene un estado valido.")
    normalized = value.strip().upper().replace(" ", "_")
    if normalized not in ESTADOS_EN_PROCESO | ESTADOS_TERMINALES:
        raise RPETCUnexpectedResponseError(f"Estado de tarea desconocido: {value}.")
    return normalized


def _safe_response_body(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text[:2000]


def _raise_for_response(response: requests.Response) -> None:
    if response.status_code < 400:
        return
    body = _safe_response_body(response)
    message_by_status = {
        400: "Parametros rechazados por API-RPETC.",
        401: "Token API-RPETC no valido.",
        403: "Solicitud API-RPETC no autorizada.",
        404: "Recurso API-RPETC no encontrado.",
        429: "Limite de solicitudes API-RPETC alcanzado.",
        500: "Error interno de API-RPETC.",
    }
    error_type = {
        401: RPETCAuthenticationError,
        403: RPETCUnauthorizedError,
        404: RPETCNotFoundError,
        429: RPETCRateLimitError,
        500: RPETCServerError,
    }.get(response.status_code, RPETCError)
    raise error_type(
        message_by_status.get(response.status_code, "Error HTTP de API-RPETC."),
        status_code=response.status_code,
        response_body=body,
        retry_after=response.headers.get("Retry-After"),
    )


class RPETCClient:
    """Cliente sin persistencia para las operaciones confirmadas de RPETC."""

    def __init__(self, certificado_sii, *, session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.certificado_sii = certificado_sii
        self.session = session or requests.Session()
        self.sleep = sleep

    def _headers_for_scope(self, scope: str) -> dict[str, str]:
        try:
            token_data = obtener_access_token_sii(self.certificado_sii)
        except SiiAuthError as exc:
            raise RPETCAuthenticationError(
                str(exc), status_code=exc.http_status
            ) from exc
        token = token_data.get("access_token")
        if not token or token_data.get("token_type") not in (None, "Bearer"):
            raise RPETCAuthenticationError("No se obtuvo un access_token Bearer valido.")
        token_scopes = set(str(token_data.get("scope") or "").split())
        if token_scopes and scope not in token_scopes:
            raise RPETCAuthenticationError(f"El token no contiene el scope {scope}.")
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def _get_json(self, path: str, *, scope: str,
                  params: dict[str, str] | None = None) -> dict[str, Any]:
        response = self.session.get(
            f"{RPETC_BASE_URL}{path}",
            params=params,
            headers=self._headers_for_scope(scope),
            timeout=30,
        )
        _raise_for_response(response)
        body = _safe_response_body(response)
        if not isinstance(body, dict):
            raise RPETCUnexpectedResponseError(
                "API-RPETC no devolvio un objeto JSON.",
                status_code=response.status_code,
                response_body=body,
            )
        return body

    def crear_tarea_cesiones_deudor(
        self,
        rut_deudor: str,
        dv_deudor: str,
        desde: str,
        hasta: str,
        formato: str,
        *,
        rut_cedente: str | None = None,
        dv_cedente: str | None = None,
        rut_cesionario: str | None = None,
        dv_cesionario: str | None = None,
    ) -> dict[str, Any]:
        normalized_format = validar_parametros_cesiones(desde, hasta, formato)
        params = {"desde": desde, "hasta": hasta, "formato": normalized_format}
        optional_pairs = (
            ("rutCedente", rut_cedente, "dvCedente", dv_cedente),
            ("rutCesionario", rut_cesionario, "dvCesionario", dv_cesionario),
        )
        for rut_name, rut_value, dv_name, dv_value in optional_pairs:
            if (rut_value is None) != (dv_value is None):
                raise RPETCParameterError(f"{rut_name} y {dv_name} deben venir juntos.")
            if rut_value is not None:
                params[rut_name] = str(rut_value)
                params[dv_name] = str(dv_value)
        return self._get_json(
            f"/recurso/v1/tarea/{rut_deudor}-{dv_deudor}/cesiones.deudor",
            scope=SCOPE_TAREA,
            params=params,
        )

    def consultar_estado_tarea(self, rut_autenticado: str, dv_autenticado: str,
                               id_tarea: str) -> dict[str, Any]:
        return self._get_json(
            f"/recurso/v1/estado/{rut_autenticado}-{dv_autenticado}/{id_tarea}",
            scope=SCOPE_ESTADO,
        )

    def esperar_tarea(self, rut_autenticado: str, dv_autenticado: str,
                      id_tarea: str, *, intervalo: float = 3,
                      max_intentos: int = 20) -> dict[str, Any]:
        if intervalo < 0 or max_intentos < 1:
            raise RPETCParameterError("intervalo y max_intentos deben ser validos.")
        for intento in range(1, max_intentos + 1):
            estado = self.consultar_estado_tarea(
                rut_autenticado, dv_autenticado, id_tarea
            )
            normalized = _normalize_state(estado.get("estado"))
            if normalized == "TERMINADO":
                return estado
            if normalized == "FALLO":
                raise RPETCTaskFailedError(
                    estado.get("descripcionError") or "La tarea RPETC fallo.",
                    task_state=estado,
                )
            if intento < max_intentos:
                self.sleep(intervalo)
        raise RPETCTaskTimeoutError(
            "La tarea RPETC no termino dentro del maximo de intentos."
        )

    def descargar_resultado_tarea(self, rut_autenticado: str, dv_autenticado: str,
                                  id_tarea: str) -> dict[str, Any]:
        response = self.session.get(
            f"{RPETC_BASE_URL}/recurso/v1/resultado/"
            f"{rut_autenticado}-{dv_autenticado}/{id_tarea}",
            headers=self._headers_for_scope(SCOPE_RESULTADO),
            timeout=60,
        )
        _raise_for_response(response)
        return {
            "bytes": response.content,
            "status_code": response.status_code,
            "content_type": response.headers.get("Content-Type"),
            "content_disposition": response.headers.get("Content-Disposition"),
        }

    def obtener_cesiones_deudor(self, rut_deudor: str, dv_deudor: str,
                                desde: str, hasta: str, formato: str,
                                *, intervalo: float = 3,
                                max_intentos: int = 20,
                                **filtros: str | None) -> dict[str, Any]:
        inicial = self.crear_tarea_cesiones_deudor(
            rut_deudor, dv_deudor, desde, hasta, formato, **filtros
        )
        id_tarea = inicial.get("idTarea")
        rut_autenticado = inicial.get("rutAutenticado")
        dv_autenticado = inicial.get("dvAutenticado")
        if not id_tarea or rut_autenticado is None or dv_autenticado is None:
            raise RPETCUnexpectedResponseError(
                "La respuesta inicial no contiene identificadores de tarea completos.",
                response_body=inicial,
            )
        estado = self.esperar_tarea(
            str(rut_autenticado), str(dv_autenticado), str(id_tarea),
            intervalo=intervalo, max_intentos=max_intentos,
        )
        resultado = self.descargar_resultado_tarea(
            str(rut_autenticado), str(dv_autenticado), str(id_tarea)
        )
        return {"tarea_inicial": inicial, "estado_final": estado, "resultado": resultado}


def crear_tarea_cesiones_deudor(cliente: RPETCClient, *args, **kwargs):
    return cliente.crear_tarea_cesiones_deudor(*args, **kwargs)


def consultar_estado_tarea(cliente: RPETCClient, *args, **kwargs):
    return cliente.consultar_estado_tarea(*args, **kwargs)


def esperar_tarea(cliente: RPETCClient, *args, **kwargs):
    return cliente.esperar_tarea(*args, **kwargs)


def descargar_resultado_tarea(cliente: RPETCClient, *args, **kwargs):
    return cliente.descargar_resultado_tarea(*args, **kwargs)


def obtener_cesiones_deudor(cliente: RPETCClient, *args, **kwargs):
    return cliente.obtener_cesiones_deudor(*args, **kwargs)
