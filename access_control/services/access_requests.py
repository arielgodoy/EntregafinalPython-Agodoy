from datetime import timedelta
from urllib.parse import urljoin

import logging

from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.urls import reverse
from django.utils import timezone

from access_control.models import AccessRequest, Empresa
from acounts.models import SystemConfig
from settings.models import UserPreferences
from settings.services.email_sender import send_email_message

logger = logging.getLogger(__name__)


def is_user_mail_enabled(user):
    if not (user and (user.email or "").strip()):
        return False
    prefs = UserPreferences.objects.filter(user=user).first()
    if prefs is None:
        return True
    return bool(getattr(prefs, "email_enabled", False))


def get_empresa_from_request(request):
    empresa_id = request.session.get("empresa_id")
    if not empresa_id:
        return None
    return Empresa.objects.filter(id=empresa_id).first()


def build_access_request_context(request, vista_nombre, mensaje):
    empresa = get_empresa_from_request(request)
    empresa_nombre = request.session.get("empresa_nombre") or (
        f"{empresa.codigo} - {empresa.descripcion or 'Sin descripción'}" if empresa else "No definida"
    )
    pending = AccessRequest.objects.filter(
        solicitante=request.user,
        empresa=empresa,
        vista_nombre=vista_nombre,
        status=AccessRequest.Status.PENDING,
    ).order_by("-created_at")[:5]
    # Construir URL para que el personal pueda otorgar acceso (si existe al menos una solicitud)
    staff_grant_url = None
    try:
        if pending and len(pending) > 0:
            staff_grant_url = reverse("access_control:grant_access_request", args=[pending[0].id])
    except Exception:
        staff_grant_url = None
    return {
        "mensaje": mensaje,
        "vista_nombre": vista_nombre,
        "empresa_nombre": empresa_nombre,
        "staff_grant_url": staff_grant_url,
        "empresa_id": empresa.id if empresa else "",
        "mail_enabled": is_user_mail_enabled(request.user),
        "pending_access_requests": pending,
    }


def can_create_access_request(user, empresa, vista_nombre, cooldown_minutes=15):
    return get_recent_access_request(user, empresa, vista_nombre, cooldown_minutes) is None


def get_recent_access_request(user, empresa, vista_nombre, cooldown_minutes=15):
    cutoff = timezone.now() - timedelta(minutes=cooldown_minutes)
    return (
        AccessRequest.objects.filter(
            solicitante=user,
            empresa=empresa,
            vista_nombre=vista_nombre,
            status=AccessRequest.Status.PENDING,
            created_at__gte=cutoff,
        )
        .order_by("-created_at")
        .first()
    )


def get_staff_recipients():
    return User.objects.filter(is_staff=True, is_active=True).distinct()


def get_staff_recipient_data():
    staff_qs = get_staff_recipients()
    staff_emails_qs = staff_qs.exclude(email__isnull=True).exclude(email="")
    staff_emails = list(staff_emails_qs.values_list("email", flat=True))
    staff_ids = list(staff_qs.values_list("id", flat=True))
    return staff_qs, staff_ids, staff_emails


def get_user_smtp_preferences(user):
    return UserPreferences.objects.filter(user=user).first()


def get_user_smtp_from_email(prefs):
    if prefs is None:
        return ""
    custom_from = getattr(prefs, "from_email", None)
    if custom_from:
        return custom_from
    return (prefs.smtp_username or "").strip()


def build_grant_access_request_url(request, access_request):
    config = SystemConfig.objects.order_by("id").first()
    base_url = (getattr(config, "public_base_url", "") or "").strip()
    if not base_url:
        base_url = request.build_absolute_uri("/")
    grant_path = reverse("access_control:grant_access_request", args=[access_request.id])
    base = base_url.rstrip("/") + "/"
    return urljoin(base, grant_path.lstrip("/"))


def get_system_public_base_url():
    config = SystemConfig.objects.filter(is_active=True).first()
    if config is None:
        config = SystemConfig.objects.order_by("id").first()
    return (getattr(config, "public_base_url", "") or "").strip()


def record_access_request_email_audit(
    access_request,
    requester,
    staff_ids,
    staff_emails,
    enviar_email,
    subject,
    body,
):
    prefs = get_user_smtp_preferences(requester)
    from_email = get_user_smtp_from_email(prefs)
    recipients = [email for email in staff_emails if (email or "").strip()]
    access_request.notified_staff_count = len(staff_ids)
    access_request.staff_recipient_ids = ",".join(map(str, staff_ids))
    access_request.email_recipients = ",".join(recipients)
    access_request.email_from = from_email
    access_request.email_error = ""
    access_request.emailed_at = None
    access_request.email_sent_at = None
    access_request.email_status = AccessRequest.EmailStatus.SKIPPED

    # Verificar primero la CAPACIDAD del usuario para enviar email, luego su intención
    reason = None
    if prefs is None or not bool(getattr(prefs, "email_enabled", False)):
        reason = "user_email_disabled"
    elif not (requester and (requester.email or "").strip()):
        reason = "user_missing_email"
    elif not (prefs.smtp_host and prefs.smtp_port and prefs.smtp_username and prefs.smtp_password):
        reason = "missing_smtp_config"
    elif len(recipients) == 0:
        reason = "no_staff_recipients"
    elif not enviar_email:
        reason = "email_option_unchecked"

    email_attempted = reason is None
    access_request.email_attempted = email_attempted
    access_request.email_sent = False

    if reason:
        access_request.email_error = reason
        logger.info(
            "Access request email skipped",
            extra={
                "user_id": requester.id,
                "username": requester.username,
                "from_email": from_email,
                "smtp_host": getattr(prefs, "smtp_host", None) if prefs else None,
                "smtp_port": getattr(prefs, "smtp_port", None) if prefs else None,
                "smtp_encryption": getattr(prefs, "smtp_encryption", None) if prefs else None,
                "source": "USER_PREFERENCES",
                "recipients": recipients,
                "reason": reason,
            },
        )
    else:
        logger.info(
            "Access request email attempt",
            extra={
                "user_id": requester.id,
                "username": requester.username,
                "from_email": from_email,
                "smtp_host": prefs.smtp_host,
                "smtp_port": prefs.smtp_port,
                "smtp_encryption": prefs.smtp_encryption,
                "source": "USER_PREFERENCES",
                "recipients": recipients,
            },
        )
        try:
            base_url = get_system_public_base_url().rstrip("/")
            grant_url = f"{base_url}/access-control/solicitudes/{access_request.id}/otorgar/"
            html_message = (
                "<h2>Solicitud de acceso</h2>"
                f"<p><strong>Usuario:</strong> {access_request.solicitante.username}</p>"
                f"<p><strong>Empresa:</strong> {access_request.empresa}</p>"
                f"<p><strong>Vista:</strong> {access_request.vista_nombre}</p>"
                f"<p><strong>Motivo:</strong> {access_request.motivo}</p>"
                "<br>"
                f"<a href=\"{grant_url}\""
                " style=\""
                "display:inline-block;"
                "padding:10px 18px;"
                "background-color:#2563eb;"
                "color:white;"
                "text-decoration:none;"
                "border-radius:6px;"
                "font-weight:600;"
                "\">"
                "Otorgar acceso"
                "</a>"
                "<br><br>"
                "<p>Si el botón no funciona, copie y pegue la siguiente URL:</p>"
                f"<p>{grant_url}</p>"
            )
            reply_to = (requester.email or "").strip()
            text_body = f"Otorgar acceso: {grant_url}"
            message = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=from_email,
                to=recipients,
                reply_to=[reply_to] if reply_to else None,
            )
            message.attach_alternative(html_message, "text/html")
            send_email_message(prefs, message.message())
            access_request.email_sent = True
            access_request.emailed_at = timezone.now()
            access_request.email_sent_at = access_request.emailed_at
            access_request.email_status = AccessRequest.EmailStatus.SENT
        except Exception as exc:
            access_request.email_sent = False
            access_request.email_error = str(exc)[:300]
            access_request.email_status = AccessRequest.EmailStatus.FAILED
            logger.exception(
                "Access request email failed",
                extra={
                    "user_id": requester.id,
                    "username": requester.username,
                    "from_email": from_email,
                    "smtp_host": prefs.smtp_host,
                    "smtp_port": prefs.smtp_port,
                    "smtp_encryption": prefs.smtp_encryption,
                    "source": "USER_PREFERENCES",
                    "recipients": recipients,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )

    if access_request.email_status == AccessRequest.EmailStatus.SKIPPED:
        access_request.email_sent = False
        access_request.email_attempted = False
    elif access_request.email_status == AccessRequest.EmailStatus.FAILED:
        access_request.email_attempted = True
        access_request.email_sent = False
    else:
        access_request.email_attempted = True
        access_request.email_sent = True

    access_request.save(
        update_fields=[
            "email_attempted",
            "email_sent",
            "email_status",
            "email_from",
            "email_error",
            "email_recipients",
            "staff_recipient_ids",
            "notified_staff_count",
            "emailed_at",
            "email_sent_at",
        ]
    )
