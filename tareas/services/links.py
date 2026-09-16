import hashlib
import logging
import secrets

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from access_control.services.permissions import get_valid_users_for_empresa
from acounts.services.email_service import send_email_for_purpose
from notificaciones.services import create_notification

from tareas.models import EnlaceTarea, EventoAccesoEnlace, Tarea

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


def _record_access(enlace, usuario, resultado):
    return EventoAccesoEnlace.objects.create(
        enlace=enlace,
        usuario=usuario if getattr(usuario, "is_authenticated", False) else None,
        resultado=resultado,
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


def create_task_link(*, tarea, destinatario, creado_por, fecha_expiracion):
    now = timezone.now()
    if tarea is None or not tarea.pk or not Tarea.objects.filter(
        pk=tarea.pk,
        empresa_id=tarea.empresa_id,
    ).exists():
        raise ValidationError("La Tarea debe existir.")
    if fecha_expiracion is None or fecha_expiracion <= now:
        raise ValidationError("La fecha de expiracion debe ser futura.")
    if not _is_valid_company_user(tarea.empresa, destinatario):
        raise ValidationError("El destinatario no pertenece a la Empresa.")
    if not _is_valid_company_user(tarea.empresa, creado_por):
        raise ValidationError("El creador no pertenece a la Empresa.")

    for _ in range(3):
        token = secrets.token_urlsafe(32)
        try:
            with transaction.atomic():
                enlace = EnlaceTarea.objects.create(
                    tarea=tarea,
                    destinatario=destinatario,
                    creado_por=creado_por,
                    token_hash=_hash_token(token),
                    fecha_expiracion=fecha_expiracion,
                )
            break
        except IntegrityError:
            continue
    else:
        raise ValidationError("No fue posible generar un token unico.")

    _notify_link_created(enlace, token, creado_por)
    return enlace, token


def resolve_task_link(*, token, usuario, empresa):
    enlace = EnlaceTarea.objects.select_related(
        "tarea", "tarea__empresa", "destinatario"
    ).filter(token_hash=_hash_token(token)).first()
    if enlace is None:
        raise TaskLinkAccessError("RECHAZADO_TOKEN_INVALIDO")

    if (
        not getattr(usuario, "is_authenticated", False)
        or usuario.pk != enlace.destinatario_id
        or not _is_valid_company_user(enlace.tarea.empresa, usuario)
    ):
        _record_access(enlace, usuario, EventoAccesoEnlace.Resultado.RECHAZADO_USUARIO)
        raise TaskLinkAccessError(EventoAccesoEnlace.Resultado.RECHAZADO_USUARIO)
    if getattr(empresa, "pk", empresa) != enlace.tarea.empresa_id:
        _record_access(enlace, usuario, EventoAccesoEnlace.Resultado.RECHAZADO_EMPRESA)
        raise TaskLinkAccessError(EventoAccesoEnlace.Resultado.RECHAZADO_EMPRESA)
    if enlace.fecha_expiracion <= timezone.now():
        _record_access(enlace, usuario, EventoAccesoEnlace.Resultado.RECHAZADO_EXPIRADO)
        raise TaskLinkAccessError(EventoAccesoEnlace.Resultado.RECHAZADO_EXPIRADO)
    if enlace.revocado_at is not None:
        _record_access(enlace, usuario, EventoAccesoEnlace.Resultado.RECHAZADO_REVOCADO)
        raise TaskLinkAccessError(EventoAccesoEnlace.Resultado.RECHAZADO_REVOCADO)

    _record_access(enlace, usuario, EventoAccesoEnlace.Resultado.ACCESO_OK)
    return enlace


def revoke_task_link(*, enlace, actor):
    if not _is_valid_company_user(enlace.tarea.empresa, actor):
        raise ValidationError("El actor no pertenece a la Empresa.")
    if enlace.revocado_at is None:
        enlace.revocado_at = timezone.now()
        enlace.revocado_por = actor
        enlace.save(update_fields=["revocado_at", "revocado_por"])
    return enlace
