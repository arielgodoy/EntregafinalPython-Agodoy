import logging

from acounts.services.email_service import send_email_for_purpose
from notificaciones.services import create_notification
from tareas.models import Tarea, TareaParticipante

logger = logging.getLogger(__name__)


def notify_task_event(
    *,
    tarea,
    destinatario,
    titulo,
    cuerpo="",
    tipo="SYSTEM",
    url="",
    actor=None,
    dedupe_key="",
):
    return create_notification(
        destinatario=destinatario,
        empresa=tarea.empresa,
        tipo=tipo,
        titulo=titulo,
        cuerpo=cuerpo,
        url=url,
        actor=actor,
        dedupe_key=dedupe_key,
    )


def send_task_email(
    *,
    tarea,
    subject,
    body_text,
    to_emails,
    body_html=None,
    reply_to=None,
):
    return send_email_for_purpose(
        empresa=tarea.empresa,
        purpose="notifications",
        subject=subject,
        body_text=body_text,
        to_emails=to_emails,
        body_html=body_html,
        reply_to=reply_to,
    )


def task_recipients(
    tarea,
    *,
    actor=None,
    include_creator=False,
    include_responsible=False,
    participant_roles=None,
    fallback_creator=False,
):
    """Return active, unique task recipients without using VICMEAS permissions."""
    users = []
    if include_creator:
        users.append(tarea.creada_por)
    if include_responsible:
        users.append(tarea.responsable)

    roles = set(participant_roles or [])
    participantes = tarea.participantes.select_related("usuario")
    if roles:
        participantes = participantes.filter(rol__in=roles)
    if participant_roles is not None:
        users.extend(participante.usuario for participante in participantes)

    recipients = {}
    for user in users:
        if user is None or not user.is_active:
            continue
        if actor is not None and user.pk == actor.pk:
            continue
        recipients[user.pk] = user
    if fallback_creator and not recipients:
        creator = tarea.creada_por
        if (
            creator is not None
            and creator.is_active
            and (actor is None or creator.pk != actor.pk)
        ):
            recipients[creator.pk] = creator
    return list(recipients.values())


def emit_task_event(
    *,
    tarea,
    event,
    recipients,
    title,
    body="",
    actor=None,
):
    """Emit one task event through the T053 adapters and both critical channels."""
    unique_recipients = {}
    for recipient in recipients:
        if recipient is None or not recipient.is_active:
            continue
        if actor is not None and recipient.pk == actor.pk:
            continue
        unique_recipients[recipient.pk] = recipient

    for recipient in unique_recipients.values():
        try:
            notify_task_event(
                tarea=tarea,
                destinatario=recipient,
                titulo=title,
                cuerpo=body,
                actor=actor,
                dedupe_key=f"tarea:{tarea.pk}:{event}:{recipient.pk}",
            )
        except Exception:
            logger.exception(
                "T054 notification failure: tarea=%s event=%s recipient=%s channel=in_app",
                tarea.pk,
                event,
                recipient.pk,
            )

        if tarea.prioridad == Tarea.Prioridad.CRITICA and recipient.email:
            email = recipient.email.strip()
            if email:
                try:
                    send_task_email(
                        tarea=tarea,
                        subject=title,
                        body_text=body,
                        to_emails=[email],
                    )
                except Exception:
                    logger.exception(
                        "T054 notification failure: tarea=%s event=%s recipient=%s channel=email",
                        tarea.pk,
                        event,
                        recipient.pk,
                    )
