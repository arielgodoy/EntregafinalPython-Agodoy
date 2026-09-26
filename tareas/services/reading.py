"""Comment reading, cursor and inactivity services (T099)."""

from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from tareas.models import (
    Comentario,
    ComentarioPausaLectura,
    TareaLectura,
)
from tareas.services.assignment import _validate_user_in_task_company
from tareas.services.participants import effective_participant_ids, is_effective_participant


COMMENT_PAGE_SIZE = 20


def _comments_after_cursor(lectura):
    queryset = Comentario.objects.filter(tarea_id=lectura.tarea_id)
    cursor = lectura.comentario_leido_hasta
    if cursor is not None:
        queryset = queryset.filter(
            Q(created_at__gt=cursor.created_at)
            | Q(created_at=cursor.created_at, pk__gt=cursor.pk)
        )
    return queryset.order_by("created_at", "pk")


def _pending_comments(lectura):
    pauses = ComentarioPausaLectura.objects.filter(
        lectura=lectura,
        desde__lte=OuterRef("created_at"),
    ).filter(Q(hasta__isnull=True) | Q(hasta__gt=OuterRef("created_at")))
    return (
        _comments_after_cursor(lectura)
        .exclude(autor_id=lectura.usuario_id)
        .annotate(_during_inactivity=Exists(pauses))
        .filter(_during_inactivity=False)
    )


def _get_linked_reading(*, tarea, usuario, lock=False):
    _validate_user_in_task_company(tarea, usuario)
    if not is_effective_participant(tarea, usuario):
        raise ValidationError("El usuario no participa funcionalmente en la tarea.")
    latest = Comentario.objects.filter(tarea=tarea).order_by("-created_at", "-pk").first()
    queryset = TareaLectura.objects.select_related("comentario_leido_hasta")
    if lock:
        queryset = queryset.select_for_update()
    lectura, _created = queryset.get_or_create(
        tarea=tarea,
        usuario=usuario,
        defaults={"comentario_leido_hasta": latest},
    )
    return lectura


def count_pending_comments(*, tarea, usuario):
    lectura = _get_linked_reading(tarea=tarea, usuario=usuario)
    return _pending_comments(lectura).count()


def get_first_pending_comment(*, tarea, usuario):
    lectura = _get_linked_reading(tarea=tarea, usuario=usuario)
    return _pending_comments(lectura).first()


def get_initial_comment_page(*, tarea, usuario):
    lectura = _get_linked_reading(tarea=tarea, usuario=usuario)
    if _pending_comments(lectura).exists():
        return list(_comments_after_cursor(lectura)[:COMMENT_PAGE_SIZE])
    latest = list(
        Comentario.objects.filter(tarea=tarea)
        .order_by("-created_at", "-pk")[:COMMENT_PAGE_SIZE]
    )
    latest.reverse()
    return latest


def get_previous_comment_page(*, tarea, usuario, before_comment):
    _get_linked_reading(tarea=tarea, usuario=usuario)
    if before_comment.tarea_id != tarea.pk:
        raise ValidationError("El Comentario no pertenece a la tarea.")
    previous = list(
        Comentario.objects.filter(tarea=tarea)
        .filter(
            Q(created_at__lt=before_comment.created_at)
            | Q(created_at=before_comment.created_at, pk__lt=before_comment.pk)
        )
        .order_by("-created_at", "-pk")[:COMMENT_PAGE_SIZE]
    )
    previous.reverse()
    return previous


@transaction.atomic
def recognize_loaded_comments(*, tarea, usuario, comentario_ids):
    lectura = _get_linked_reading(tarea=tarea, usuario=usuario, lock=True)
    loaded_ids = list(comentario_ids)
    if not loaded_ids or len(loaded_ids) > COMMENT_PAGE_SIZE:
        raise ValidationError("La página de Comentarios no es reconocible.")
    expected = list(_comments_after_cursor(lectura)[:COMMENT_PAGE_SIZE])
    expected_ids = [comentario.pk for comentario in expected]
    if loaded_ids != expected_ids:
        raise ValidationError("Solo se puede reconocer la siguiente página contigua.")
    lectura.comentario_leido_hasta = expected[-1]
    lectura.save(update_fields=["comentario_leido_hasta"])
    return lectura


@transaction.atomic
def open_inactivity_pause(*, lectura, at=None):
    locked = TareaLectura.objects.select_for_update().get(pk=lectura.pk)
    current = (
        ComentarioPausaLectura.objects.filter(lectura=locked, hasta__isnull=True)
        .order_by("desde", "pk")
        .first()
    )
    if current is not None:
        return current
    return ComentarioPausaLectura.objects.create(
        lectura=locked,
        desde=at or timezone.now(),
    )


@transaction.atomic
def close_inactivity_pause(*, lectura, at=None):
    locked = TareaLectura.objects.select_for_update().get(pk=lectura.pk)
    current = (
        ComentarioPausaLectura.objects.filter(lectura=locked, hasta__isnull=True)
        .order_by("desde", "pk")
        .first()
    )
    if current is None:
        return None
    closed_at = at or timezone.now()
    current.hasta = max(closed_at, current.desde)
    current.save(update_fields=["hasta"])
    return current


def handle_user_activity_transition(*, usuario, was_active, at=None):
    if was_active == usuario.is_active:
        return
    transition_at = at or timezone.now()
    if usuario.is_active:
        readings = TareaLectura.objects.filter(
            usuario=usuario,
            pausas_comentarios__hasta__isnull=True,
        ).distinct()
        for lectura in readings:
            close_inactivity_pause(lectura=lectura, at=transition_at)
        return
    readings = TareaLectura.objects.filter(usuario=usuario).filter(
        Q(tarea__responsable=usuario) | Q(tarea__participantes__usuario=usuario)
    ).distinct()
    for lectura in readings:
        open_inactivity_pause(lectura=lectura, at=transition_at)


@transaction.atomic
def ensure_readings_for_comment(*, comentario):
    predecessor = (
        Comentario.objects.filter(tarea_id=comentario.tarea_id)
        .filter(
            Q(created_at__lt=comentario.created_at)
            | Q(created_at=comentario.created_at, pk__lt=comentario.pk)
        )
        .order_by("-created_at", "-pk")
        .first()
    )
    user_model = get_user_model()
    users = user_model.objects.in_bulk(effective_participant_ids(comentario.tarea))
    for usuario_id in effective_participant_ids(comentario.tarea):
        usuario = users.get(usuario_id)
        if usuario is None:
            continue
        lectura, created = TareaLectura.objects.get_or_create(
            tarea_id=comentario.tarea_id,
            usuario_id=usuario_id,
            defaults={"comentario_leido_hasta": predecessor},
        )
        if created and not usuario.is_active:
            open_inactivity_pause(lectura=lectura, at=comentario.created_at)