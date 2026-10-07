"""Comment reading, cursor and inactivity services (T099)."""

from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from tareas.models import (
    Comentario,
    ComentarioPausaLectura,
    TareaLectura,
)
from tareas.services.assignment import _validate_user_in_task_company
from tareas.services.participants import effective_participant_ids, is_effective_participant
from tareas.services.comment_storage import (
    CommentPageCommand,
    ReadingCommand,
    RecognizeCommentsCommand,
    resolve_comment_storage,
)


COMMENT_PAGE_SIZE = 20


def count_pending_comments(*, tarea, usuario):
    _validate_user_in_task_company(tarea, usuario)
    if not is_effective_participant(tarea, usuario):
        raise ValidationError("El usuario no participa funcionalmente en la tarea.")
    return len(resolve_comment_storage().pending(CommentPageCommand(
        tarea.pk, tarea.empresa_id, usuario.pk,
    )))


def get_first_pending_comment(*, tarea, usuario):
    _validate_user_in_task_company(tarea, usuario)
    if not is_effective_participant(tarea, usuario):
        raise ValidationError("El usuario no participa funcionalmente en la tarea.")
    pending = resolve_comment_storage().pending(CommentPageCommand(
        tarea.pk, tarea.empresa_id, usuario.pk,
    ))
    return pending[0] if pending else None


def get_initial_comment_page(*, tarea, usuario):
    _validate_user_in_task_company(tarea, usuario)
    if not is_effective_participant(tarea, usuario):
        raise ValidationError("El usuario no participa funcionalmente en la tarea.")
    return resolve_comment_storage().page(CommentPageCommand(
        tarea.pk, tarea.empresa_id, usuario.pk, page_size=COMMENT_PAGE_SIZE,
    ))


def get_previous_comment_page(*, tarea, usuario, before_comment):
    _validate_user_in_task_company(tarea, usuario)
    if not is_effective_participant(tarea, usuario):
        raise ValidationError("El usuario no participa funcionalmente en la tarea.")
    if before_comment.tarea_id != tarea.pk:
        raise ValidationError("El Comentario no pertenece a la tarea.")
    return resolve_comment_storage().previous_page(
        CommentPageCommand(tarea.pk, tarea.empresa_id, usuario.pk, page_size=COMMENT_PAGE_SIZE),
        before_comment,
    )


def recognize_loaded_comments(*, tarea, usuario, comentario_ids):
    _validate_user_in_task_company(tarea, usuario)
    loaded_ids = list(comentario_ids)
    if not loaded_ids or len(loaded_ids) > COMMENT_PAGE_SIZE:
        raise ValidationError("La página de Comentarios no es reconocible.")
    if not is_effective_participant(tarea, usuario):
        raise ValidationError("El usuario no participa funcionalmente en la tarea.")
    return resolve_comment_storage().recognize(RecognizeCommentsCommand(
        tarea.pk, tarea.empresa_id, usuario.pk, tuple(loaded_ids),
    ))


def open_inactivity_pause(*, lectura, at=None):
    return resolve_comment_storage().open_pause(ReadingCommand(
        lectura.tarea_id, lectura.tarea.empresa_id, lectura.usuario_id, at,
    ))


def close_inactivity_pause(*, lectura, at=None):
    return resolve_comment_storage().close_pause(ReadingCommand(
        lectura.tarea_id, lectura.tarea.empresa_id, lectura.usuario_id, at,
    ))


def handle_user_activity_transition(*, usuario, was_active, at=None):
    if was_active == usuario.is_active:
        return
    resolve_comment_storage().handle_user_activity(
        usuario.pk, usuario.is_active, at or timezone.now(),
    )


def ensure_readings_for_comment(*, comentario):
    storage = resolve_comment_storage()
    storage.ensure_readings(
        comentario.tarea_id,
        comentario.pk,
        tuple(effective_participant_ids(comentario.tarea)),
        comentario.created_at,
    )