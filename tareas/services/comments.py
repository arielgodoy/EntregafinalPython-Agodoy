"""Domain services for task comments (T098)."""

import logging
from contextlib import nullcontext
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from access_control.services.permissions import user_has_permission_for_empresa
from tareas.models import (
    Comentario,
    ComentarioAdjunto,
    ComentarioVersion,
    ComentarioVersionDocumento,
    DocumentoTarea,
    Tarea,
)
from tareas.services.assignment import _validate_user_in_task_company
from tareas.services.documents import create_document
from tareas.services.hierarchy import is_effectively_annulled
from tareas.services.notifications import emit_task_event
from tareas.services.participants import effective_participant_ids, is_effective_participant
from tareas.services.comment_storage import (
    CommentCreateCommand,
    CommentEditCommand,
    CommentVisibilityCommand,
    resolve_comment_storage,
)


_UNSET = object()
logger = logging.getLogger(__name__)
_OPERATIONAL_STATES = {
    Tarea.Estado.ACTIVA,
    Tarea.Estado.GESTION,
    Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
}


def _current_task(tarea_id, empresa_id=None):
    storage = resolve_comment_storage()
    return storage.task(tarea_id, empresa_id)


def _validate_actor(tarea, usuario, accion):
    _validate_user_in_task_company(tarea, usuario)
    if not is_effective_participant(tarea, usuario):
        raise ValidationError("El usuario no participa funcionalmente en la tarea.")
    if not user_has_permission_for_empresa(
        user=usuario,
        empresa=tarea.empresa,
        vista_nombre="Tareas",
        accion=accion,
    ):
        raise ValidationError("El usuario no tiene autorización para esta operación.")


def _validate_operational_task(tarea):
    if tarea.estado not in _OPERATIONAL_STATES or is_effectively_annulled(tarea):
        raise ValidationError("La tarea no admite mutaciones de comentarios.")


def _document_specs(documentos_nuevos):
    return list(documentos_nuevos or [])


def _resolve_documents(*, tarea, usuario, documentos, documentos_nuevos):
    existentes = list(documentos or [])
    nuevos_specs = _document_specs(documentos_nuevos)
    if len(existentes) + len(nuevos_specs) > 5:
        raise ValidationError("Un Comentario admite como máximo cinco adjuntos.")
    for documento in existentes:
        if not isinstance(documento, DocumentoTarea) or not documento.pk:
            raise ValidationError("Cada adjunto debe ser un DocumentoTarea existente.")
        if documento.tarea_id != tarea.pk:
            raise ValidationError("El documento no pertenece a la tarea.")

    nuevos = []
    for datos in nuevos_specs:
        if not isinstance(datos, dict):
            raise ValidationError("La definición del documento no es válida.")
        nuevos.append(
            create_document(
                tarea=tarea,
                usuario=usuario,
                emit_notification=False,
                **datos,
            )
        )

    documentos_finales = existentes + nuevos
    ids = [documento.pk for documento in documentos_finales]
    if len(ids) != len(set(ids)):
        raise ValidationError("No se puede asociar dos veces el mismo documento.")
    return documentos_finales


def _ensure_content_or_documents(contenido, documentos):
    if not (contenido or "").strip() and not documentos:
        raise ValidationError("El Comentario requiere texto o al menos un adjunto.")


def _replace_current_documents(comentario, documentos):
    comentario.adjuntos.all().delete()
    ComentarioAdjunto.objects.bulk_create(
        [
            ComentarioAdjunto(comentario=comentario, documento=documento)
            for documento in documentos
        ]
    )


def _create_version(*, comentario, evento, actor, contenido, motivo, documentos, numero):
    version = ComentarioVersion.objects.create(
        comentario=comentario,
        evento=evento,
        numero_version=numero,
        contenido=contenido,
        actor=actor,
        motivo=motivo,
    )
    ComentarioVersionDocumento.objects.bulk_create(
        [
            ComentarioVersionDocumento(version=version, documento=documento)
            for documento in documentos
        ]
    )
    return version


def _next_content_version(comentario):
    current = comentario.versiones.aggregate(Max("numero_version"))["numero_version__max"]
    return (current or 0) + 1


def _schedule_comment_event(*, tarea, event, actor):
    if hasattr(tarea, "_state"):
        recipient_ids = effective_participant_ids(tarea)
    else:
        recipient_ids = {
            user_id for user_id in (
                getattr(tarea, "creador_id", None),
                getattr(tarea, "responsable_id", None),
            ) if user_id is not None
        }
    recipients = list(
        User.objects.filter(pk__in=recipient_ids, is_active=True).exclude(pk=actor.pk)
    )
    titles = {
        "comentario_agregado": "Nuevo comentario en la tarea",
        "comentario_editado": "Comentario editado en la tarea",
        "comentario_ocultado": "Comentario ocultado en la tarea",
        "comentario_restaurado": "Comentario restaurado en la tarea",
    }
    body = titles[event]
    def notify_after_commit():
        try:
            emit_task_event(
                tarea=tarea,
                event=event,
                recipients=recipients,
                title=titles[event],
                body=body,
                actor=actor,
            )
        except Exception:
            logger.exception("Comment notification failed: task=%s event=%s", tarea.pk, event)

    transaction.on_commit(notify_after_commit)


def create_comment(*, tarea, usuario, contenido="", documentos=None, documentos_nuevos=None):
    tarea_actual = _current_task(tarea.pk, tarea.empresa_id)
    _validate_actor(tarea_actual, usuario, "crear")
    _validate_operational_task(tarea_actual)
    storage = resolve_comment_storage()
    atomic = transaction.atomic(using=storage.alias) if hasattr(storage, "alias") else nullcontext()
    with atomic:
        documentos_finales = _resolve_documents(
            tarea=tarea_actual,
            usuario=usuario,
            documentos=documentos,
            documentos_nuevos=documentos_nuevos,
        )
        _ensure_content_or_documents(contenido, documentos_finales)
        comentario = storage.create(CommentCreateCommand(
            task_id=tarea_actual.pk,
            empresa_id=tarea_actual.empresa_id,
            author_id=usuario.pk,
            content=contenido or "",
            document_ids=tuple(documento.pk for documento in documentos_finales),
        ), documents=documentos_finales)
    _schedule_comment_event(
        tarea=tarea_actual,
        event="comentario_agregado",
        actor=usuario,
    )
    return comentario


def _create_mini_task_close_comment(
    *, tarea, mini_tarea, usuario, comentario_cierre, documentos_nuevos=None
):
    if mini_tarea.tarea_id != tarea.pk:
        raise ValidationError("La MiniTarea no pertenece a la tarea.")
    documentos = _resolve_documents(
        tarea=tarea,
        usuario=usuario,
        documentos=None,
        documentos_nuevos=documentos_nuevos,
    )
    contenido = (
        f'Ha completado la MiniTarea "{mini_tarea.descripcion}".\n\n'
        f"Comentario: {comentario_cierre}"
    )
    _ensure_content_or_documents(contenido, documentos)
    storage = resolve_comment_storage()
    return storage.create(CommentCreateCommand(
        task_id=tarea.pk, empresa_id=tarea.empresa_id, author_id=usuario.pk,
        content=contenido, document_ids=tuple(documento.pk for documento in documentos),
    ), documents=documentos)


def edit_comment(*, comentario, usuario, contenido=_UNSET, documentos=_UNSET, documentos_nuevos=None):
    storage = resolve_comment_storage()
    comentario_actual = storage.get(
        comentario.pk, comentario.tarea_id, comentario.tarea.empresa_id,
    )
    tarea_actual = _current_task(comentario_actual.tarea_id, comentario_actual.tarea.empresa_id)
    _validate_actor(tarea_actual, usuario, "modificar")
    _validate_operational_task(tarea_actual)
    if comentario_actual.autor_id != usuario.pk:
        raise ValidationError("Solo el autor puede editar el Comentario.")
    if comentario_actual.oculto:
        raise ValidationError("Un Comentario oculto no se puede editar.")
    if timezone.now() > comentario_actual.created_at + timedelta(hours=1):
        raise ValidationError("La ventana de edición del Comentario expiró.")

    contenido_final = comentario_actual.contenido if contenido is _UNSET else (contenido or "")
    documentos_actuales = list(storage.document_ids_for_comment(comentario_actual.pk))
    if documentos is _UNSET:
        documentos_base = storage.documents(tarea_actual.pk, documentos_actuales)
    else:
        documentos_base = list(documentos or [])
    documentos_finales = _resolve_documents(
        tarea=tarea_actual,
        usuario=usuario,
        documentos=documentos_base,
        documentos_nuevos=documentos_nuevos,
    )
    _ensure_content_or_documents(contenido_final, documentos_finales)

    storage = resolve_comment_storage()
    comentario_actual = storage.edit(CommentEditCommand(
        comment_id=comentario_actual.pk,
        task_id=tarea_actual.pk,
        empresa_id=tarea_actual.empresa_id,
        actor_id=usuario.pk,
        content=contenido_final,
        document_ids=tuple(documento.pk for documento in documentos_finales),
    ), documents=documentos_finales)
    _schedule_comment_event(
        tarea=tarea_actual,
        event="comentario_editado",
        actor=usuario,
    )
    return comentario_actual


def hide_comment(*, comentario, usuario, motivo):
    return _set_visibility(
        comentario=comentario,
        usuario=usuario,
        motivo=motivo,
        evento=ComentarioVersion.Evento.OCULTADO,
        oculto=True,
    )


def restore_comment(*, comentario, usuario, motivo):
    return _set_visibility(
        comentario=comentario,
        usuario=usuario,
        motivo=motivo,
        evento=ComentarioVersion.Evento.RESTAURADO,
        oculto=False,
    )


def _set_visibility(*, comentario, usuario, motivo, evento, oculto):
    storage = resolve_comment_storage()
    comentario_actual = storage.get(
        comentario.pk, comentario.tarea_id, comentario.tarea.empresa_id,
    )
    tarea_actual = _current_task(comentario_actual.tarea_id, comentario_actual.tarea.empresa_id)
    _validate_actor(tarea_actual, usuario, "supervisor")
    _validate_operational_task(tarea_actual)
    motivo_limpio = (motivo or "").strip()
    if not motivo_limpio:
        raise ValidationError("El motivo es obligatorio.")
    if comentario_actual.oculto == oculto:
        raise ValidationError("El Comentario ya tiene ese estado.")

    comentario_actual = storage.set_visibility(CommentVisibilityCommand(
        comment_id=comentario_actual.pk,
        task_id=tarea_actual.pk,
        empresa_id=tarea_actual.empresa_id,
        actor_id=usuario.pk,
        motivo=motivo_limpio,
        oculto=oculto,
    ))
    _schedule_comment_event(
        tarea=tarea_actual,
        event=("comentario_ocultado" if oculto else "comentario_restaurado"),
        actor=usuario,
    )
    return comentario_actual
