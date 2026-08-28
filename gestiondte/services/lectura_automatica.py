"""Orquestación común para lecturas manuales y automáticas de cesiones RPETC."""
from __future__ import annotations

import logging
import uuid
import calendar
from datetime import date, datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from ..models import (
    CertificadoSII,
    LecturaAutomaticaConfig,
    LecturaAutomaticaEjecucion,
)
from ..utils.maestro import get_maestroempresa_by_codigo
from .rpetc_importer import normalizar_rut

logger = logging.getLogger(__name__)


class LecturaAutomaticaError(RuntimeError):
    """Error seguro de precondiciones de una lectura RPETC."""


MESES_RPETC = (
    'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
)


def rango_mensual_rpetc(fecha_sistema: date, mes: int) -> tuple[date, date]:
    if mes < 1 or mes > 12:
        raise LecturaAutomaticaError("El mes RPETC no es válido.")
    if mes > fecha_sistema.month:
        raise LecturaAutomaticaError("No se puede sincronizar un mes posterior a la fecha de sistema.")
    desde = date(fecha_sistema.year, mes, 1)
    hasta = date(fecha_sistema.year, mes, calendar.monthrange(fecha_sistema.year, mes)[1])
    if mes == fecha_sistema.month:
        hasta = fecha_sistema
    return desde, hasta


def periodos_mensuales_rpetc(fecha_sistema: date) -> list[dict[str, Any]]:
    periodos = []
    for mes, nombre in enumerate(MESES_RPETC, start=1):
        if mes <= fecha_sistema.month:
            desde, hasta = rango_mensual_rpetc(fecha_sistema, mes)
        else:
            desde = hasta = None
        periodos.append({
            'mes': mes,
            'nombre': nombre,
            'fecha_desde': desde,
            'fecha_hasta': hasta,
            'habilitado': mes <= fecha_sistema.month,
        })
    return periodos


def validar_rango_lectura(fecha_desde: date, fecha_hasta: date, hoy: date | None = None) -> None:
    hoy = hoy or timezone.localdate()
    if fecha_desde > fecha_hasta:
        raise LecturaAutomaticaError("La fecha desde no puede ser posterior a la fecha hasta.")
    if fecha_hasta > hoy:
        raise LecturaAutomaticaError("La fecha hasta no puede ser futura.")
    if (fecha_hasta - fecha_desde).days + 1 > 30:
        raise LecturaAutomaticaError("El rango no puede superar 30 días.")


def rango_automatico(hoy: date | None = None) -> tuple[date, date]:
    hasta = hoy or timezone.localdate()
    desde = hasta.replace(day=1)
    if (hasta - desde).days + 1 > 30:
        desde = hasta - timedelta(days=29)
    return desde, hasta


def _certificado_elegible(certificado: CertificadoSII, ahora: datetime | None = None) -> bool:
    ahora = ahora or timezone.now()
    if not (
        certificado.activo
        and certificado.archivo
        and certificado.archivo.name
        and certificado.valido_hasta
        and certificado.valido_hasta >= ahora
    ):
        return False
    try:
        return certificado.archivo.storage.exists(certificado.archivo.name)
    except Exception:
        return False


def empresas_elegibles() -> list[tuple[Any, CertificadoSII]]:
    """Devuelve una empresa por código con certificado activo y vigente."""
    from access_control.models import Empresa

    ahora = timezone.now()
    certificados = CertificadoSII.objects.filter(
        activo=True,
        valido_hasta__isnull=False,
        valido_hasta__gte=ahora,
    ).exclude(archivo="").order_by("empresa_codigo", "-valido_hasta", "-pk")
    elegibles = {}
    for certificado in certificados:
        if certificado.empresa_codigo in elegibles or not _certificado_elegible(certificado, ahora):
            continue
        empresa = Empresa.objects.filter(codigo=certificado.empresa_codigo).first()
        if empresa:
            elegibles[empresa.codigo] = (empresa, certificado)
    return list(elegibles.values())


def sincronizar_empresa_rpetc(
    empresa,
    fecha_desde: date,
    fecha_hasta: date,
    *,
    certificado: CertificadoSII | None = None,
    maestro: dict[str, Any] | None = None,
    intervalo: float = 3,
    max_intentos: int = 20,
) -> dict[str, Any]:
    """Ejecuta una lectura DEUDOR reutilizando cliente, parser e importador."""
    maestro = maestro or get_maestroempresa_by_codigo(empresa.codigo)
    rut_empresa, dv_empresa = normalizar_rut((maestro or {}).get("rut"))
    certificado = certificado or CertificadoSII.objects.filter(
        empresa_codigo=empresa.codigo,
        activo=True,
    ).order_by("-valido_hasta", "-pk").first()
    if not maestro or not rut_empresa or not dv_empresa:
        raise LecturaAutomaticaError("No fue posible resolver el RUT de la empresa.")
    if not certificado or not certificado.activo or not certificado.archivo or not certificado.archivo.name:
        raise LecturaAutomaticaError("No existe un certificado SII vigente para la empresa.")

    from .rpetc import RPETCClient
    from .rpetc_importer import importar_resultado_rpetc
    from .rpetc_parser import parsear_txt_rpetc

    resultado = RPETCClient(certificado).obtener_cesiones_deudor(
        rut_deudor=rut_empresa,
        dv_deudor=dv_empresa,
        desde=fecha_desde.strftime("%d%m%Y"),
        hasta=fecha_hasta.strftime("%d%m%Y"),
        formato="TXT",
        intervalo=intervalo,
        max_intentos=max_intentos,
    )
    estado = resultado["estado_final"]
    if estado.get("estado") != "TERMINADO" or estado.get("codigoError") not in (0, "0", None):
        raise LecturaAutomaticaError("La tarea RPETC no terminó correctamente.")
    parseado = parsear_txt_rpetc(resultado["resultado"]["bytes"])
    if (
        parseado["consulta"].get("TIPO_CONSULTA") != "DEUDOR"
        or not parseado.get("columnas")
        or "ID_CESION" not in parseado["columnas"]
    ):
        raise LecturaAutomaticaError("El resultado RPETC no contiene una consulta DEUDOR válida.")
    stats = importar_resultado_rpetc(
        empresa,
        resultado["tarea_inicial"],
        estado,
        parseado,
        "DEUDOR",
        fecha_desde,
        fecha_hasta,
        "TXT",
    )
    return {"resultado": resultado, "stats": stats, "tarea": stats.get("tarea")}


def _mensaje_error_seguro(exc: Exception) -> str:
    return "No fue posible completar la lectura automática para esta empresa."


def ejecutar_lote(
    fecha_desde: date,
    fecha_hasta: date,
    *,
    tipo_ejecucion: str,
    ahora: datetime | None = None,
) -> dict[str, Any]:
    """Procesa empresas elegibles secuencialmente bajo un lock de base de datos."""
    validar_rango_lectura(fecha_desde, fecha_hasta, (ahora or timezone.now()).date())
    ahora = ahora or timezone.now()
    lote_id = uuid.uuid4()
    with transaction.atomic():
        config, _ = LecturaAutomaticaConfig.objects.get_or_create(pk=1)
        config = LecturaAutomaticaConfig.objects.select_for_update().get(pk=1)
        if LecturaAutomaticaEjecucion.objects.filter(
            estado__in=("PENDIENTE", "EN_PROCESO"),
        ).exists():
            return {"bloqueado": True, "lote_id": None, "ejecuciones": []}
        elegibles = empresas_elegibles()
        ejecuciones = [
            LecturaAutomaticaEjecucion.objects.create(
                lote_id=lote_id,
                empresa=empresa,
                tipo_ejecucion=tipo_ejecucion,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta,
                estado="PENDIENTE",
            )
            for empresa, _certificado in elegibles
        ]
    for ejecucion, (_empresa, certificado) in zip(ejecuciones, elegibles):
        ejecucion.estado = "EN_PROCESO"
        ejecucion.fecha_inicio = timezone.now()
        ejecucion.progreso = 0
        ejecucion.save(update_fields=["estado", "fecha_inicio", "progreso", "ultima_actualizacion"])
        try:
            resultado = sincronizar_empresa_rpetc(
                ejecucion.empresa,
                fecha_desde,
                fecha_hasta,
                certificado=certificado,
            )
            stats = resultado["stats"]
            total = stats.get("registros_recibidos")
            ejecucion.estado = "ACTUALIZADO"
            ejecucion.progreso = 100
            ejecucion.total_documentos = total
            ejecucion.documentos_procesados = total or 0
            ejecucion.tarea_rpetc = resultado.get("tarea")
            ejecucion.mensaje_error = None
        except Exception as exc:
            logger.exception("Error en lectura automática de cesiones para empresa %s", ejecucion.empresa.codigo)
            ejecucion.estado = "ERROR"
            ejecucion.mensaje_error = _mensaje_error_seguro(exc)
        ejecucion.fecha_termino = timezone.now()
        ejecucion.save(update_fields=[
            "estado", "progreso", "total_documentos", "documentos_procesados",
            "tarea_rpetc", "mensaje_error", "fecha_termino", "ultima_actualizacion",
        ])
    if tipo_ejecucion == "AUTOMATICA":
        config = LecturaAutomaticaConfig.objects.get(pk=1)
        config.ultima_ejecucion = ahora
        config.proxima_ejecucion = ahora + timedelta(minutes=config.intervalo_minutos)
        config.save(update_fields=["ultima_ejecucion", "proxima_ejecucion", "modificado"])
    return {"bloqueado": False, "lote_id": lote_id, "ejecuciones": ejecuciones}


def estado_lote(lote_id=None):
    qs = LecturaAutomaticaEjecucion.objects.select_related("empresa").order_by("empresa__codigo")
    if lote_id:
        qs = qs.filter(lote_id=lote_id)
    return qs
