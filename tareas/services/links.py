import hashlib
import logging
import secrets
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone

from access_control.services.permissions import get_valid_users_for_empresa
from acounts.services.email_service import send_email_for_purpose
from notificaciones.services import create_notification

from tareas.models import EnlaceTarea, EventoAccesoEnlace
from access_control.models import Empresa
from tareas.services.shared_link_storage import (
    SharedLinkCreateCommand,
    SharedLinkRevokeCommand,
    DjangoSharedLinkStorage,
    resolve_shared_link_storage,
)

logger = logging.getLogger(__name__)


class TaskLinkAccessError(ValidationError):
    def __init__(self, resultado):
        self.resultado = resultado
        super().__init__("No es posible acceder al enlace.")


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _is_valid_company_user(empresa, usuario):
    return (
        usuario is not None
        and getattr(usuario, "is_authenticated", True)
        and usuario.is_active
        and get_valid_users_for_empresa(empresa, active_only=True)
        .filter(pk=usuario.pk)
        .exists()
    )


def _notify_link_created(enlace, token, creado_por):
    url = reverse("tareas:enlace_tarea", kwargs={"token": token})
    title = f"Enlace compartido: {enlace.tarea.titulo}"
    body = (
        f"{creado_por.get_username()} compartio la Tarea "
        f"{enlace.tarea.titulo} de la Empresa {enlace.tarea.empresa}. "
        f"El enlace expira el {enlace.fecha_expiracion}. URL: {url}"
    )
    try:
        create_notification(
            destinatario=enlace.destinatario,
            empresa=enlace.tarea.empresa,
            tipo="SYSTEM",
            titulo=title,
            cuerpo=body,
            url=url,
            actor=creado_por,
            dedupe_key=f"tarea-enlace:{enlace.pk}",
        )
    except Exception:
        logger.exception("T058 in-app notification failed for link=%s", enlace.pk)

    if not enlace.destinatario.email:
        return
    try:
        send_email_for_purpose(
            empresa=enlace.tarea.empresa,
            purpose="notifications",
            subject=title,
            body_text=body,
            to_emails=[enlace.destinatario.email],
        )
    except Exception:
        logger.exception("T058 email notification failed for link=%s", enlace.pk)


def create_task_link(*, tarea=None, tarea_id=None, empresa=None, destinatario, creado_por, fecha_expiracion):
    now = timezone.now()
    if tarea is not None:
        tarea_id = tarea.pk
        empresa = tarea.empresa
    if not tarea_id or empresa is None:
        raise ValidationError("La Tarea debe existir.")
    if fecha_expiracion is None or fecha_expiracion <= now:
        raise ValidationError("La fecha de expiracion debe ser futura.")
    if not _is_valid_company_user(empresa, destinatario):
        raise ValidationError("El destinatario no pertenece a la Empresa.")
    if not _is_valid_company_user(empresa, creado_por):
        raise ValidationError("El creador no pertenece a la Empresa.")

    storage = resolve_shared_link_storage()
    for _ in range(3):
        token = secrets.token_urlsafe(32)
        try:
            result = storage.create(SharedLinkCreateCommand(
                task_id=tarea_id,
                empresa_id=empresa.pk,
                destinatario_id=destinatario.pk,
                creado_por_id=creado_por.pk,
                fecha_expiracion=fecha_expiracion,
                token=token,
                token_hash=_hash_token(token),
            ))
            break
        except IntegrityError:
            continue
    else:
        raise ValidationError("No fue posible generar un token unico.")

    if result.record is not None:
        _notify_link_created(result.record, result.token, creado_por)
        return result.record, result.token
    task_ref = result.tarea
    link_ref = SimpleNamespace(
        pk=result.id, tarea=task_ref, destinatario=destinatario,
        fecha_expiracion=result.fecha_expiracion,
    )
    _notify_link_created(link_ref, result.token, creado_por)
    return link_ref, result.token


def resolve_task_link(*, token, usuario, empresa):
    if not getattr(usuario, "is_authenticated", False):
        raise TaskLinkAccessError(EventoAccesoEnlace.Resultado.RECHAZADO_USUARIO)
    empresa_id = getattr(empresa, "pk", empresa)
    try:
        result = resolve_shared_link_storage().resolve(token, usuario.pk, empresa_id)
    except ValidationError as exc:
        raise TaskLinkAccessError(str(exc)) from exc
    if result.__class__.__name__ == "SharedLinkAccessResult":
        return SimpleNamespace(tarea=result.task, pk=result.link_id)
    return result


def revoke_task_link(*, enlace, actor):
    if not _is_valid_company_user(enlace.tarea.empresa, actor):
        raise ValidationError("El actor no pertenece a la Empresa.")
    storage = resolve_shared_link_storage()
    if isinstance(storage, DjangoSharedLinkStorage):
        current = getattr(enlace, "revocado_at", None)
        if current is None:
            enlace.revocado_at = timezone.now()
            enlace.revocado_por = actor
            enlace.save(using=storage.alias, update_fields=["revocado_at", "revocado_por"])
        return enlace
    storage.revoke(SharedLinkRevokeCommand(enlace.pk, enlace.tarea.empresa_id, actor.pk))
    return enlace


def revoke_task_link_by_id(*, link_id, empresa_id, actor):
    empresa = Empresa.objects.using("default").get(pk=empresa_id)
    if not _is_valid_company_user(empresa, actor):
        raise ValidationError("El actor no pertenece a la Empresa.")
    resolve_shared_link_storage().revoke(
        SharedLinkRevokeCommand(link_id, empresa_id, actor.pk)
    )
