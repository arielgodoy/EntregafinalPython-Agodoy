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
    formato_archivo,
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
        "formato_archivo": formato_archivo,
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
        "formato_archivo",
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
def configure_closure_evidence(*, tarea, usuario, requiere_evidencia_cierre):
    _validate_user_in_task_company(tarea, usuario)
    tarea.requiere_evidencia_cierre = bool(requiere_evidencia_cierre)
    tarea.save(update_fields=["requiere_evidencia_cierre"])
    return tarea


@transaction.atomic
def register_closure_evidence(
    *, tarea, usuario, formato_archivo, archivo=None, url="", documento=None
):
    _validate_user_in_task_company(tarea, usuario)
    if documento is not None and documento.tarea_id != tarea.pk:
        raise ValidationError("El documento no pertenece a la tarea.")
    if documento is not None and not archivo and not url:
        archivo = documento.archivo or None
        url = documento.url
    evidencia = EvidenciaCierre(
        tarea=tarea,
        documento=documento,
        formato_archivo=formato_archivo,
        archivo=archivo or "",
        url=url or "",
        usuario=usuario,
    )
    evidencia.full_clean()
    evidencia.save()
    return evidencia