"""Persistencia idempotente de resultados ya parseados de API-RPETC."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.utils import timezone

from ..models import (
    CesionRPETC,
    CesionRPETCHistorial,
    TareaCesionRPETC,
    TareaRPETC,
)


class RPETCImportError(ValueError):
    """Error estructural que aborta la importación completa."""


def normalizar_rut(value: Any) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    raw = str(value).strip().replace(".", "").replace(" ", "")
    if not raw:
        return None, None
    if "-" in raw:
        rut, dv = raw.rsplit("-", 1)
    elif len(raw) > 1:
        rut, dv = raw[:-1], raw[-1]
    else:
        return raw, None
    return rut or None, dv.upper() or None


def _required_text(value: Any, field: str, row_number: int) -> str:
    result = "" if value is None else str(value).strip()
    if not result:
        raise RPETCImportError(f"Fila {row_number}: falta {field}.")
    return result


def _optional_text(value: Any) -> str | None:
    result = "" if value is None else str(value).strip()
    return result or None


def _parse_decimal(value: Any, field: str, row_number: int) -> Decimal | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise RPETCImportError(f"Fila {row_number}: {field} no es un monto valido.") from exc


def _parse_date(value: Any, field: str, row_number: int) -> date | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise RPETCImportError(f"Fila {row_number}: {field} no es una fecha valida.") from exc


def _parse_datetime(value: Any, field: str, row_number: int) -> datetime | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RPETCImportError(f"Fila {row_number}: {field} no es una fecha valida.") from exc
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _parse_sii_datetime(value: Any) -> datetime | None:
    text = _optional_text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _parse_parameters(value: Any) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    if value is None or value == "":
        return None, None
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if isinstance(value, (dict, list)):
        return value, raw
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None, raw
    return parsed if isinstance(parsed, (dict, list)) else None, raw


def _task_dates(fecha_desde: date | str, fecha_hasta: date | str) -> tuple[date, date]:
    def convert(value: date | str) -> date:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise RPETCImportError("El periodo de la tarea no es valido.") from exc
    return convert(fecha_desde), convert(fecha_hasta)


def _task_values(
    empresa,
    inicial: dict[str, Any],
    final: dict[str, Any],
    tipo_consulta: str,
    fecha_desde: date | str,
    fecha_hasta: date | str,
    formato: str,
) -> dict[str, Any]:
    id_tarea = _required_text(inicial.get("idTarea"), "idTarea", 0)
    parsed_desde, parsed_hasta = _task_dates(fecha_desde, fecha_hasta)
    parametros_value = final.get("parametros", inicial.get("parametros"))
    parametros, parametros_raw = _parse_parameters(parametros_value)
    values = {
        "empresa": empresa,
        "tipo_consulta": str(tipo_consulta).upper(),
        "rut_consultado": _required_text(inicial.get("rut"), "rut", 0),
        "dv_consultado": _required_text(inicial.get("dv"), "dv", 0).upper(),
        "fecha_desde": parsed_desde,
        "fecha_hasta": parsed_hasta,
        "formato": str(formato).upper(),
        "rut_autenticado": _optional_text(inicial.get("rutAutenticado")),
        "dv_autenticado": _optional_text(inicial.get("dvAutenticado")),
        "nombre_tarea": _optional_text(inicial.get("nombre")),
        "estado": _required_text(final.get("estado", inicial.get("estado")), "estado", 0),
        "resultado": _optional_text(final.get("resultado")),
        "hora_creado_sii": _parse_sii_datetime(inicial.get("horaCreado")),
        "hora_en_proceso_sii": _parse_sii_datetime(final.get("horaEnProceso")),
        "hora_terminado_sii": _parse_sii_datetime(final.get("horaTerminado")),
        "file_size": final.get("fileSize"),
        "cantidad_lineas": final.get("cantidadDeLineas"),
        "comprimido": final.get("comprimido"),
        "codigo_error": _optional_text(final.get("codigoError")),
        "descripcion_error": _optional_text(final.get("descripcionError")),
        "parametros": parametros,
        "parametros_raw": parametros_raw,
    }
    return id_tarea, values


def _set_if_present(target: dict[str, Any], field: str, value: Any) -> None:
    if value not in (None, ""):
        target[field] = value


def _map_cesion(row: dict[str, Any], row_number: int) -> dict[str, Any]:
    id_cesion = _required_text(row.get("ID_CESION"), "ID_CESION", row_number)
    values: dict[str, Any] = {
        "id_cesion": id_cesion,
        "estado_cesion": _required_text(row.get("ESTADO_CESION"), "ESTADO_CESION", row_number),
        "tipo_doc": _required_text(row.get("TIPO_DOC"), "TIPO_DOC", row_number),
        "nombre_doc": _optional_text(row.get("NOMBRE_DOC")),
        "folio_doc": _required_text(row.get("FOLIO_DOC"), "FOLIO_DOC", row_number),
        "fecha_emision": _parse_date(row.get("FCH_EMIS_DTE"), "FCH_EMIS_DTE", row_number),
        "monto_total": _parse_decimal(row.get("MNT_TOTAL"), "MNT_TOTAL", row_number),
        "fecha_cesion": _parse_datetime(row.get("FCH_CESION"), "FCH_CESION", row_number),
        "monto_cesion": _parse_decimal(row.get("MNT_CESION"), "MNT_CESION", row_number),
        "fecha_vencimiento": _parse_date(row.get("FCH_VENCIMIENTO"), "FCH_VENCIMIENTO", row_number),
    }
    for source, rut_field, dv_field in (
        ("VENDEDOR", "vendedor_rut", "vendedor_dv"),
        ("DEUDOR", "deudor_rut", "deudor_dv"),
        ("CEDENTE", "cedente_rut", "cedente_dv"),
        ("CESIONARIO", "cesionario_rut", "cesionario_dv"),
    ):
        rut, dv = normalizar_rut(row.get(source))
        values[rut_field] = rut
        values[dv_field] = dv
    for source, target in (
        ("MAIL_DEUDOR", "deudor_email"),
        ("MAIL_CEDENTE", "cedente_email"),
        ("MAIL_CESIONARIO", "cesionario_email"),
        ("RZ_CEDENTE", "cedente_razon_social"),
        ("RZ_CESIONARIO", "cesionario_razon_social"),
    ):
        values[target] = _optional_text(row.get(source))
    return values


def importar_resultado_rpetc(
    empresa,
    datos_tarea_inicial: dict[str, Any],
    estado_tarea_final: dict[str, Any],
    resultado_parseado: dict[str, Any],
    tipo_consulta: str,
    fecha_desde: date | str,
    fecha_hasta: date | str,
    formato: str,
) -> dict[str, Any]:
    """Importa una respuesta parseada completa en una transacción única."""
    tipo_consulta = str(tipo_consulta).upper()
    if tipo_consulta not in {"DEUDOR", "CEDENTE", "CESIONARIO"}:
        raise RPETCImportError("tipo_consulta no permitido.")
    if str(formato).upper() not in {"TXT", "XML"}:
        raise RPETCImportError("formato no permitido.")
    registros = resultado_parseado.get("registros") or []
    stats = {
        "registros_recibidos": len(registros),
        "cesiones_creadas": 0,
        "cesiones_actualizadas": 0,
        "cesiones_sin_cambios": 0,
        "vinculos_creados": 0,
        "transiciones_estado": 0,
        "errores": [],
    }
    with transaction.atomic():
        id_tarea, task_values = _task_values(
            empresa, datos_tarea_inicial, estado_tarea_final,
            tipo_consulta, fecha_desde, fecha_hasta, formato,
        )
        tarea, _ = TareaRPETC.objects.update_or_create(
            id_tarea=id_tarea,
            defaults=task_values,
        )
        for row_number, row in enumerate(registros, start=3):
            values = _map_cesion(row, row_number)
            identity = {
                key: values[key]
                for key in ("id_cesion", "deudor_rut", "deudor_dv", "tipo_doc", "folio_doc")
            }
            cesion = CesionRPETC.objects.filter(**identity).first()
            if cesion is None:
                cesion = CesionRPETC.objects.create(**values)
                stats["cesiones_creadas"] += 1
                CesionRPETCHistorial.objects.create(
                    cesion=cesion,
                    estado=cesion.estado_cesion,
                    estado_anterior=None,
                    tarea_origen=tarea,
                )
                stats["transiciones_estado"] += 1
            else:
                previous_state = cesion.estado_cesion
                changed = False
                update_values: dict[str, Any] = {}
                for field, value in values.items():
                    if value in (None, ""):
                        continue
                    if getattr(cesion, field) != value:
                        update_values[field] = value
                        changed = True
                if changed:
                    cesion.__dict__.update(update_values)
                    cesion.save(update_fields=list(update_values) + ["actualizada_en"])
                    stats["cesiones_actualizadas"] += 1
                else:
                    stats["cesiones_sin_cambios"] += 1
                if previous_state != cesion.estado_cesion:
                    CesionRPETCHistorial.objects.create(
                        cesion=cesion,
                        estado_anterior=previous_state,
                        estado=cesion.estado_cesion,
                        tarea_origen=tarea,
                    )
                    stats["transiciones_estado"] += 1
            _, created = TareaCesionRPETC.objects.get_or_create(
                tarea=tarea,
                cesion=cesion,
                defaults={
                    "rol_consulta": tipo_consulta,
                    "fila_origen": row_number,
                },
            )
            if created:
                stats["vinculos_creados"] += 1
        stats["tarea"] = tarea
    return stats
