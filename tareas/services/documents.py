"""Document and closure-evidence services for T038."""

from django.core.exceptions import ValidationError
from django.db import transaction

from tareas.models import DocumentoHistorial, DocumentoTarea, EvidenciaCierre
from tareas.services.assignment import _validate_user_in_task_company


def _history_data(documento, usuario, accion):
    return {
        "documento": documento,
        "accion": accion,
        "usuario": usuario,
    }


@transaction.atomic
def create_document(
    *,
    tarea,
    tipo,
    usuario,
    archivo=None,
    url="",
    fecha_documento=None,
    fecha_vencimiento=None,
    estado="",
):
    _validate_user_in_task_company(tarea, usuario)
    datos = {
        "tarea": tarea,
        "tipo": tipo,
        "usuario": usuario,
        "archivo": archivo or "",
        "url": url or "",
        "fecha_vencimiento": fecha_vencimiento,
        "estado": estado,
    }
    if fecha_documento is not None:
        datos["fecha_documento"] = fecha_documento
    documento = DocumentoTarea(**datos)
    documento.full_clean()
    documento.save()
    DocumentoHistorial.objects.create(**_history_data(documento, usuario, "CREADO"))
    return documento


@transaction.atomic
def update_document(documento, usuario, **changes):
    _validate_user_in_task_company(documento.tarea, usuario)
    campos = {
        "tipo",
        "archivo",
        "url",
        "fecha_documento",
        "fecha_vencimiento",
        "estado",
    }
    desconocidos = set(changes) - campos
    if desconocidos:
        raise ValidationError("El documento contiene campos no editables.")

    for campo, valor in changes.items():
        setattr(documento, campo, valor or "" if campo in {"archivo", "url"} else valor)
    documento.full_clean()
    documento.save()
    DocumentoHistorial.objects.create(**_history_data(documento, usuario, "ACTUALIZADO"))
    return documento


@transaction.atomic
def configure_closure_evidence(*, tarea, usuario, requerida):
    _validate_user_in_task_company(tarea, usuario)
    evidencia, _created = EvidenciaCierre.objects.update_or_create(
        tarea=tarea,
        defaults={"requerida": bool(requerida), "usuario": usuario},
    )
    return evidencia


@transaction.atomic
def register_closure_evidence(*, tarea, documento, usuario):
    _validate_user_in_task_company(tarea, usuario)
    if documento.tarea_id != tarea.pk:
        raise ValidationError("El documento no pertenece a la tarea.")
    evidencia, _created = EvidenciaCierre.objects.update_or_create(
        tarea=tarea,
        defaults={
            "documento": documento,
            "requerida": True,
            "usuario": usuario,
        },
    )
    return evidencia