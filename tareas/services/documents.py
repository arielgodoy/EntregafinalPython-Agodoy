"""Document and closure-evidence services for T038."""

from django.core.exceptions import ValidationError
from django.db import transaction

from tareas.models import (
    DocumentoHistorial,
    DocumentoTarea,
    EvidenciaCierre,
    TareaParticipante,
    Tarea,
)
from tareas.services.assignment import _validate_user_in_task_company
from tareas.services.image_processing import optimize_uploaded_image
from tareas.services.notifications import emit_task_event, task_recipients
from tareas.services.document_storage import (
    DocumentCreateCommand,
    DocumentUpdateCommand,
    EvidenceCreateCommand,
    DjangoDocumentStorage,
    resolve_document_storage,
)


def _history_data(documento, usuario, accion):
    return {
        "documento": documento,
        "accion": accion,
        "usuario": usuario,
    }


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
    emit_notification=True,
):
    storage = resolve_document_storage()
    result = storage.create_document(DocumentCreateCommand(
        tarea_id=tarea.pk, empresa_id=tarea.empresa_id, usuario_id=usuario.pk,
        tipo=tipo, formato_archivo=formato_archivo, archivo=archivo, url=url,
        fecha_documento=fecha_documento, fecha_vencimiento=fecha_vencimiento,
        estado=estado,
    ))
    if emit_notification and isinstance(storage, DjangoDocumentStorage) and isinstance(tarea, Tarea):
        emit_task_event(
            tarea=tarea,
            event="documento_agregado",
            recipients=task_recipients(
                tarea,
                actor=usuario,
                include_creator=True,
                include_responsible=True,
                participant_roles=list(TareaParticipante.Rol),
            ),
            title="Documento agregado a la tarea",
            body="Se agregó un documento a la tarea.",
            actor=usuario,
        )
    return result


def update_document(documento, usuario, **changes):
    storage = resolve_document_storage()
    result = storage.update_document(DocumentUpdateCommand(
        documento_id=documento.pk,
        tarea_id=documento.tarea_id,
        empresa_id=documento.tarea.empresa_id,
        usuario_id=usuario.pk,
        changes=changes,
    ))
    return result


def configure_closure_evidence(*, tarea, usuario, requiere_evidencia_cierre):
    storage = resolve_document_storage()
    storage.configure_evidence(
        task_id=tarea.pk,
        empresa_id=tarea.empresa_id,
        usuario_id=usuario.pk,
        required=requiere_evidencia_cierre,
    )
    return tarea


def register_closure_evidence(
    *, tarea, usuario, formato_archivo, archivo=None, url="", documento=None
):
    storage = resolve_document_storage()
    return storage.register_evidence(EvidenceCreateCommand(
        tarea_id=tarea.pk,
        empresa_id=tarea.empresa_id,
        usuario_id=usuario.pk,
        formato_archivo=formato_archivo,
        archivo=archivo,
        url=url,
        documento_id=documento.pk if documento is not None else None,
    ))