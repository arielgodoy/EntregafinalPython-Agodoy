"""Domain services for task comments (T098)."""

from datetime import timedelta

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
from tareas.services.participants import is_effective_participant


_UNSET = object()
_OPERATIONAL_STATES = {
    Tarea.Estado.ACTIVA,
    Tarea.Estado.GESTION,
    Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
}


def _current_task(tarea_id):
    try:
        return (
            Tarea.objects.select_for_update()
            .select_related("empresa")
            .get(pk=tarea_id)
        )
    except Tarea.DoesNotExist as exc:
        raise ValidationError("La tarea no existe.") from exc


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
    for documento in existentes:
        if not isinstance(documento, DocumentoTarea) or not documento.pk:
            raise ValidationError("Cada adjunto debe ser un DocumentoTarea existente.")
        if documento.tarea_id != tarea.pk:
            raise ValidationError("El documento no pertenece a la tarea.")

    nuevos = []
    for datos in _document_specs(documentos_nuevos):
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
    if len(documentos_finales) > 5:
        raise ValidationError("Un Comentario admite como máximo cinco adjuntos.")
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


@transaction.atomic
def create_comment(*, tarea, usuario, contenido="", documentos=None, documentos_nuevos=None):
    tarea_actual = _current_task(tarea.pk)
    _validate_actor(tarea_actual, usuario, "modificar")
    _validate_operational_task(tarea_actual)
    documentos_finales = _resolve_documents(
        tarea=tarea_actual,
        usuario=usuario,
        documentos=documentos,
        documentos_nuevos=documentos_nuevos,
    )
    _ensure_content_or_documents(contenido, documentos_finales)

    comentario = Comentario.objects.create(
        tarea=tarea_actual,
        autor=usuario,
        contenido=contenido or "",
    )
    _replace_current_documents(comentario, documentos_finales)
    _create_version(
        comentario=comentario,
        evento=ComentarioVersion.Evento.CREADO,
        actor=usuario,
        contenido=comentario.contenido,
        motivo="",
        documentos=documentos_finales,
        numero=1,
    )
    return comentario


@transaction.atomic
def edit_comment(*, comentario, usuario, contenido=_UNSET, documentos=_UNSET, documentos_nuevos=None):
    comentario_actual = (
        Comentario.objects.select_for_update()
        .select_related("tarea__empresa")
        .get(pk=comentario.pk)
    )
    tarea_actual = _current_task(comentario_actual.tarea_id)
    _validate_actor(tarea_actual, usuario, "modificar")
    _validate_operational_task(tarea_actual)
    if comentario_actual.autor_id != usuario.pk:
        raise ValidationError("Solo el autor puede editar el Comentario.")
    if comentario_actual.oculto:
        raise ValidationError("Un Comentario oculto no se puede editar.")
    if timezone.now() > comentario_actual.created_at + timedelta(hours=1):
        raise ValidationError("La ventana de edición del Comentario expiró.")

    contenido_final = comentario_actual.contenido if contenido is _UNSET else (contenido or "")
    documentos_actuales = list(comentario_actual.adjuntos.values_list("documento", flat=True))
    if documentos is _UNSET:
        documentos_base = list(
            DocumentoTarea.objects.filter(pk__in=documentos_actuales, tarea=tarea_actual)
        )
    else:
        documentos_base = list(documentos or [])
    documentos_finales = _resolve_documents(
        tarea=tarea_actual,
        usuario=usuario,
        documentos=documentos_base,
        documentos_nuevos=documentos_nuevos,
    )
    _ensure_content_or_documents(contenido_final, documentos_finales)

    comentario_actual.contenido = contenido_final
    comentario_actual.save(update_fields=["contenido", "updated_at"])
    _replace_current_documents(comentario_actual, documentos_finales)
    _create_version(
        comentario=comentario_actual,
        evento=ComentarioVersion.Evento.EDITADO,
        actor=usuario,
        contenido=comentario_actual.contenido,
        motivo="",
        documentos=documentos_finales,
        numero=_next_content_version(comentario_actual),
    )
    return comentario_actual


@transaction.atomic
def hide_comment(*, comentario, usuario, motivo):
    return _set_visibility(
        comentario=comentario,
        usuario=usuario,
        motivo=motivo,
        evento=ComentarioVersion.Evento.OCULTADO,
        oculto=True,
    )


@transaction.atomic
def restore_comment(*, comentario, usuario, motivo):
    return _set_visibility(
        comentario=comentario,
        usuario=usuario,
        motivo=motivo,
        evento=ComentarioVersion.Evento.RESTAURADO,
        oculto=False,
    )


def _set_visibility(*, comentario, usuario, motivo, evento, oculto):
    comentario_actual = (
        Comentario.objects.select_for_update()
        .select_related("tarea__empresa")
        .get(pk=comentario.pk)
    )
    tarea_actual = _current_task(comentario_actual.tarea_id)
    _validate_actor(tarea_actual, usuario, "supervisor")
    _validate_operational_task(tarea_actual)
    motivo_limpio = (motivo or "").strip()
    if not motivo_limpio:
        raise ValidationError("El motivo es obligatorio.")
    if comentario_actual.oculto == oculto:
        raise ValidationError("El Comentario ya tiene ese estado.")

    documentos = list(
        DocumentoTarea.objects.filter(
            adjuntos_comentarios__comentario=comentario_actual,
            tarea=tarea_actual,
        )
    )
    comentario_actual.oculto = oculto
    comentario_actual.save(update_fields=["oculto", "updated_at"])
    _create_version(
        comentario=comentario_actual,
        evento=evento,
        actor=usuario,
        contenido=comentario_actual.contenido,
        motivo=motivo_limpio,
        documentos=documentos,
        numero=None,
    )
    return comentario_actual
