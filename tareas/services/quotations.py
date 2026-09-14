from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from proveedores.models import Proveedor
from tareas.models import Cotizacion, DocumentoCotizacion, RondaCotizacion, Tarea


def get_next_round_number(*, tarea):
    if not tarea.pk:
        raise ValidationError("La tarea debe existir antes de crear una ronda.")
    ultimo_numero = (
        RondaCotizacion.objects.filter(tarea_id=tarea.pk).aggregate(
            ultimo_numero=Max("numero")
        )["ultimo_numero"]
        or 0
    )
    return ultimo_numero + 1


@transaction.atomic
def create_quotation_round(*, tarea, minimo_cotizaciones=3, fecha_apertura=None):
    if not tarea.pk:
        raise ValidationError("La tarea debe existir antes de crear una ronda.")

    tarea_bloqueada = Tarea.objects.select_for_update().get(pk=tarea.pk)
    ronda = RondaCotizacion(
        tarea=tarea_bloqueada,
        numero=get_next_round_number(tarea=tarea_bloqueada),
        minimo_cotizaciones=minimo_cotizaciones,
    )
    if fecha_apertura is not None:
        ronda.fecha_apertura = fecha_apertura
    ronda.full_clean()
    ronda.save()
    return ronda


def get_latest_quotation_round(tarea):
    return tarea.rondas_cotizacion.order_by("-numero").first()


def has_quotation_process(tarea):
    return tarea.rondas_cotizacion.exists()


def count_available_quotations(ronda):
    """Count distinct local providers with at least one vigente quotation."""
    return (
        ronda.cotizaciones.filter(vigente=True, proveedor__isnull=False)
        .values("proveedor_id")
        .distinct()
        .count()
    )


def quotation_minimum_met(ronda):
    return count_available_quotations(ronda) >= ronda.minimo_cotizaciones


@transaction.atomic
def close_quotation_round(ronda):
    if ronda.estado == RondaCotizacion.Estado.CERRADA:
        return ronda
    if not quotation_minimum_met(ronda):
        raise ValidationError(
            "QUOTATION_MINIMUM_NOT_MET: La ronda no cumple el mínimo de cotizaciones vigentes."
        )
    ronda.estado = RondaCotizacion.Estado.CERRADA
    ronda.fecha_cierre = timezone.now()
    ronda.full_clean()
    ronda.save(update_fields=["estado", "fecha_cierre"])
    return ronda


@transaction.atomic
def open_next_quotation_round(ronda_anterior):
    return create_quotation_round(
        tarea=ronda_anterior.tarea,
        minimo_cotizaciones=ronda_anterior.minimo_cotizaciones,
    )


@transaction.atomic
def create_quotation(
    *,
    ronda,
    version,
    monto,
    fecha_cotizacion,
    observaciones="",
    proveedor=None,
    vigente=True,
    estado=Cotizacion.Estado.RECIBIDA,
):
    """Create a new quotation requiring a valid local provider.

    Maximum 3 versions per provider and round; distinct-provider minimums remain
    deferred to the later quotation-minimum task.
    """
    if proveedor is None:
        raise ValidationError("PROVIDER_REQUIRED: La cotización requiere un proveedor.")
    if not isinstance(proveedor, Proveedor):
        raise ValidationError("PROVIDER_INVALID: Debe indicar un proveedor local válido.")
    if version < 1 or version > 3:
        raise ValidationError("QUOTATION_VERSION_OUT_OF_RANGE: La versión debe estar entre 1 y 3.")

    ronda_bloqueada = RondaCotizacion.objects.select_for_update().get(pk=ronda.pk)
    versiones_proveedor = Cotizacion.objects.filter(
        ronda=ronda_bloqueada,
        proveedor=proveedor,
    )
    if versiones_proveedor.filter(version=version).exists():
        raise ValidationError(
            "QUOTATION_VERSION_DUPLICATE: La versión ya existe para este proveedor y ronda."
        )
    if versiones_proveedor.count() >= 3:
        raise ValidationError(
            "QUOTATION_VERSION_LIMIT: El proveedor ya tiene tres versiones en esta ronda."
        )

    cotizacion = Cotizacion(
        ronda=ronda_bloqueada,
        version=version,
        monto=monto,
        vigente=vigente,
        estado=estado,
        fecha_cotizacion=fecha_cotizacion,
        observaciones=observaciones,
        proveedor=proveedor,
    )
    cotizacion.full_clean()
    cotizacion.save()
    return cotizacion


@transaction.atomic
def update_quotation_status(*, cotizacion, estado):
    cotizacion.estado = estado
    cotizacion.full_clean()
    cotizacion.save(update_fields=["estado"])
    return cotizacion


@transaction.atomic
def add_quotation_document(*, cotizacion, formato_archivo, usuario, archivo=None, url="", fecha=None):
    documento = DocumentoCotizacion(
        cotizacion=cotizacion,
        formato_archivo=formato_archivo,
        archivo=archivo or "",
        url=url,
        usuario=usuario,
    )
    if fecha is not None:
        documento.fecha = fecha
    documento.full_clean()
    documento.save()
    return documento
