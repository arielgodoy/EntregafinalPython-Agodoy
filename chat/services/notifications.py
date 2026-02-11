from django.urls import reverse

from notificaciones.models import Notification
from notificaciones.services import create_notification


def notify_new_message(conversacion, mensaje):
    if not conversacion or not mensaje:
        return 0

    empresa = conversacion.empresa
    recipients = conversacion.participantes.exclude(id=mensaje.remitente_id)
    if not recipients.exists():
        return 0

    url = f"{reverse('chat_inbox')}?conversation_id={conversacion.id}"
    cuerpo = (mensaje.contenido or "").strip()
    if len(cuerpo) > 120:
        cuerpo = cuerpo[:117] + "..."

    created = 0
    for user in recipients:
        dedupe_key = f"chat:msg:{mensaje.id}:to:{user.id}"
        notification, was_created = Notification.objects.get_or_create(
            destinatario=user,
            empresa=empresa,
            dedupe_key=dedupe_key,
            defaults={
                "tipo": Notification.Tipo.MESSAGE,
                "titulo": "Nuevo mensaje",
                "cuerpo": cuerpo,
                "url": url,
                "actor": mensaje.remitente,
            },
        )
        if was_created:
            created += 1
    return created
