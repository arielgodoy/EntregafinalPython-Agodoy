"""Public compatibility API for quotation operations."""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from proveedores.models import Proveedor
from tareas.services.quotation_storage import (
    DjangoQuotationStorage,
    execute_storage,
    resolve_quotation_storage,
)


def _pk(value):
    return getattr(value, "pk", getattr(value, "id", value))


def _task_scope(task):
    if not getattr(task, "pk", None):
        raise ValidationError("La tarea debe existir antes de crear una ronda.")
    return task.pk, getattr(task, "empresa_id", None)


def _materialize_round(storage, data):
    if data is None:
        return None
    if isinstance(storage, DjangoQuotationStorage):
        return storage.materialize_round(data.id)
    return data


def _materialize_quotation(storage, data):
    if isinstance(storage, DjangoQuotationStorage):
        return storage.materialize_quotation(data.id)
    return data


def _materialize_document(storage, data):
    if isinstance(storage, DjangoQuotationStorage):
        return storage.materialize_document(data.id)
    return data


def get_next_round_number(*, tarea):
    task_id, company_id = _task_scope(tarea)
    storage = resolve_quotation_storage()
    return execute_storage(
        storage,
        "get_next_round_number",
        task_id=task_id,
        company_id=company_id,
    )


def create_quotation_round(*, tarea, minimo_cotizaciones=3, fecha_apertura=None):
    task_id, company_id = _task_scope(tarea)
    storage = resolve_quotation_storage()
    result = execute_storage(
        storage,
        "create_round",
        task_id=task_id,
        company_id=company_id,
        minimum=minimo_cotizaciones,
        opened_at=fecha_apertura,
    )
    return _materialize_round(storage, result)


def get_latest_quotation_round(tarea):
    task_id, company_id = _task_scope(tarea)
    storage = resolve_quotation_storage()
    result = execute_storage(
        storage,
        "get_latest_round",
        task_id=task_id,
        company_id=company_id,
    )
    return _materialize_round(storage, result)


def has_quotation_process(tarea):
    task_id, company_id = _task_scope(tarea)
    storage = resolve_quotation_storage()
    return execute_storage(
        storage,
        "has_quotation_process",
        task_id=task_id,
        company_id=company_id,
    )


def count_available_quotations(ronda):
    storage = resolve_quotation_storage()
    return execute_storage(
        storage,
        "count_available_quotations",
        round_id=_pk(ronda),
    )


def quotation_minimum_met(ronda):
    storage = resolve_quotation_storage()
    return execute_storage(
        storage,
        "round_minimum_met",
        round_id=_pk(ronda),
    )


def close_quotation_round(ronda):
    storage = resolve_quotation_storage()
    result = execute_storage(
        storage,
        "close_round",
        round_id=_pk(ronda),
    )
    return _materialize_round(storage, result)


def open_next_quotation_round(ronda_anterior):
    storage = resolve_quotation_storage()
    result = execute_storage(
        storage,
        "open_next_round",
        round_id=_pk(ronda_anterior),
        company_id=None,
    )
    return _materialize_round(storage, result)


def create_quotation(
    *,
    ronda,
    version,
    monto,
    fecha_cotizacion,
    observaciones="",
    proveedor=None,
    vigente=True,
    estado="RECIBIDA",
):
    if not isinstance(proveedor, Proveedor):
        if proveedor is None:
            raise ValidationError("PROVIDER_REQUIRED: La cotización requiere un proveedor.")
        raise ValidationError("PROVIDER_INVALID: Debe indicar un proveedor local válido.")
    storage = resolve_quotation_storage()
    result = execute_storage(
        storage,
        "create_quotation",
        round_id=_pk(ronda),
        provider_id=proveedor.pk,
        version=version,
        amount=monto,
        current=vigente,
        state=estado,
        quote_date=fecha_cotizacion,
        notes=observaciones,
    )
    return _materialize_quotation(storage, result)


def update_quotation_status(*, cotizacion, estado):
    storage = resolve_quotation_storage()
    result = execute_storage(
        storage,
        "update_quotation_status",
        quotation_id=_pk(cotizacion),
        round_id=getattr(
            cotizacion,
            "ronda_id",
            getattr(cotizacion, "round_id", None),
        ),
        state=estado,
    )
    return _materialize_quotation(storage, result)


def add_quotation_document(
    *,
    cotizacion,
    formato_archivo,
    usuario,
    archivo=None,
    url="",
    fecha=None,
):
    if not isinstance(usuario, User):
        raise ValidationError("El usuario indicado no existe.")
    storage = resolve_quotation_storage()
    result = execute_storage(
        storage,
        "add_quotation_document",
        quotation_id=_pk(cotizacion),
        format=formato_archivo,
        user_id=usuario.pk,
        uploaded_file=archivo,
        url=url,
        created_at=fecha,
    )
    return _materialize_document(storage, result)
