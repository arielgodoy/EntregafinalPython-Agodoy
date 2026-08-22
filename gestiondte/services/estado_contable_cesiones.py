"""Persistencia batch del ultimo resultado contable conocido por empresa y cesion.

Un pago confirmado no cierra necesariamente la verificacion: un pago posterior
al otro destinatario puede convertirlo en PAGADA_AMBOS.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

from django.utils import timezone

from ..models import EstadoContableCesion
from .rpetc_contabilidad import obtener_estados_contables_cesiones


ESTADOS_CONTABILIZACION = {'CONTABILIZADA', 'NO_CONTABILIZADA', 'REVISAR', 'NO_DISPONIBLE'}
ESTADOS_PAGO = {'PAGADA', 'NO_PAGADA', 'REVISAR', 'NO_DISPONIBLE'}


def determinar_estado_pago_resumen(estado_factoring: str, estado_proveedor: str) -> str:
    """Determina un resumen de pago mutuamente excluyente con precedencia fija."""
    estados = {estado_factoring, estado_proveedor}
    if 'NO_DISPONIBLE' in estados:
        return 'NO_DISPONIBLE'
    if 'REVISAR' in estados:
        return 'REVISAR'
    factoring_pagado = estado_factoring == 'PAGADA'
    proveedor_pagado = estado_proveedor == 'PAGADA'
    if factoring_pagado and proveedor_pagado:
        return 'PAGADA_AMBOS'
    if factoring_pagado:
        return 'PAGADA_FACTORING'
    if proveedor_pagado:
        return 'PAGADA_PROVEEDOR'
    return 'PENDIENTE'


def _estado(value: Any, valid: set[str], default: str, aliases: dict[str, str] | None = None) -> str:
    value = str(value or '').strip().upper()
    value = (aliases or {}).get(value, value)
    return value if value in valid else default


def _fecha_movimiento(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    if isinstance(value, date):
        return timezone.make_aware(datetime.combine(value, datetime.min.time()))
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
        except (TypeError, ValueError):
            return None
    return None


def _pago_inequivoco(bloque: dict[str, Any]) -> tuple[datetime | None, Decimal | None]:
    """Solo extrae fecha y monto cuando el servicio legacy devuelve un movimiento."""
    movimientos = bloque.get('movimientos') or []
    if bloque.get('estado') not in {'PAGADA_FACTORING', 'PAGADA_PROVEEDOR', 'PAGADA'} or len(movimientos) != 1:
        return None, None
    movimiento = movimientos[0]
    try:
        monto = Decimal(str(movimiento.get('monto'))) if movimiento.get('monto') is not None else None
    except Exception:
        monto = None
    return _fecha_movimiento(movimiento.get('fecha')), monto


def _snapshot_values(cesion, estados: dict[str, Any], verificada_en: datetime) -> dict[str, Any]:
    contabilizacion = estados.get('contabilizacion') or {}
    factoring = estados.get('pagada_factoring') or {}
    proveedor = estados.get('pagada_proveedor') or {}
    estado_contabilizacion = _estado(contabilizacion.get('estado'), ESTADOS_CONTABILIZACION, 'NO_DISPONIBLE')
    estado_factoring = _estado(
        factoring.get('estado'), ESTADOS_PAGO, 'NO_DISPONIBLE',
        {'PAGADA_FACTORING': 'PAGADA'},
    )
    estado_proveedor = _estado(
        proveedor.get('estado'), ESTADOS_PAGO, 'NO_DISPONIBLE',
        {'PAGADA_PROVEEDOR': 'PAGADA'},
    )
    fecha_factoring, monto_factoring = _pago_inequivoco(factoring)
    fecha_proveedor, monto_proveedor = _pago_inequivoco(proveedor)
    return {
        'cesion': cesion,
        'estado_contabilizacion': estado_contabilizacion,
        'estado_factoring': estado_factoring,
        'estado_proveedor': estado_proveedor,
        'estado_pago_resumen': determinar_estado_pago_resumen(estado_factoring, estado_proveedor),
        'fecha_pago_factoring': fecha_factoring,
        'monto_pago_factoring': monto_factoring,
        'fecha_pago_proveedor': fecha_proveedor,
        'monto_pago_proveedor': monto_proveedor,
        'fecha_verificacion': verificada_en,
        'estado_verificacion': 'OK',
        'mensaje_error': None,
        'modificado': verificada_en,
    }


def _error_values(cesion, verificada_en: datetime, mensaje: str) -> dict[str, Any]:
    return {
        'cesion': cesion,
        'estado_contabilizacion': 'NO_DISPONIBLE',
        'estado_factoring': 'NO_DISPONIBLE',
        'estado_proveedor': 'NO_DISPONIBLE',
        'estado_pago_resumen': 'NO_DISPONIBLE',
        'fecha_pago_factoring': None,
        'monto_pago_factoring': None,
        'fecha_pago_proveedor': None,
        'monto_pago_proveedor': None,
        'fecha_verificacion': verificada_en,
        'estado_verificacion': 'ERROR',
        'mensaje_error': mensaje[:500],
        'modificado': verificada_en,
    }


def _persistir(empresa, cesiones: list[Any], values_by_pk: dict[Any, dict[str, Any]]) -> tuple[int, int]:
    ids = [cesion.pk for cesion in cesiones]
    existentes = {
        snapshot.cesion_id: snapshot
        for snapshot in EstadoContableCesion.objects.filter(empresa=empresa, cesion_id__in=ids)
    }
    nuevos = []
    actualizados = []
    fields = [
        'estado_contabilizacion', 'estado_factoring', 'estado_proveedor', 'estado_pago_resumen',
        'fecha_pago_factoring', 'monto_pago_factoring', 'fecha_pago_proveedor', 'monto_pago_proveedor',
        'fecha_verificacion', 'estado_verificacion', 'mensaje_error', 'modificado',
    ]
    for cesion in cesiones:
        values = values_by_pk[cesion.pk]
        snapshot = existentes.get(cesion.pk)
        if snapshot is None:
            nuevos.append(EstadoContableCesion(empresa=empresa, **values))
        else:
            for field, value in values.items():
                if field != 'cesion':
                    setattr(snapshot, field, value)
            actualizados.append(snapshot)
    if nuevos:
        EstadoContableCesion.objects.bulk_create(nuevos, batch_size=len(nuevos))
    if actualizados:
        EstadoContableCesion.objects.bulk_update(actualizados, fields, batch_size=len(actualizados))
    return len(nuevos), len(actualizados)


def actualizar_estados_contables_cesiones(empresa, cesiones: Iterable[Any], chunk_size: int = 250) -> dict[str, int]:
    """Actualiza snapshots en bloques sin destruir estados válidos ante un error técnico."""
    if chunk_size <= 0:
        raise ValueError('chunk_size debe ser positivo.')
    cesiones = list(cesiones)
    resultado = {'procesadas': 0, 'creadas': 0, 'actualizadas': 0, 'errores': 0}
    for inicio in range(0, len(cesiones), chunk_size):
        chunk = cesiones[inicio:inicio + chunk_size]
        verificada_en = timezone.now()
        try:
            legacy = obtener_estados_contables_cesiones(empresa.codigo, chunk)
            values_by_pk = {
                cesion.pk: _snapshot_values(cesion, legacy.get(cesion.pk, {}), verificada_en)
                for cesion in chunk
            }
        except Exception:
            resultado['errores'] += 1
            values_by_pk = {}
            for cesion in chunk:
                values_by_pk[cesion.pk] = _error_values(
                    cesion,
                    verificada_en,
                    'No fue posible verificar el estado contable en el sistema legacy.',
                )
        creadas, actualizadas = _persistir(empresa, chunk, values_by_pk)
        resultado['procesadas'] += len(chunk)
        resultado['creadas'] += creadas
        resultado['actualizadas'] += actualizadas
    return resultado
