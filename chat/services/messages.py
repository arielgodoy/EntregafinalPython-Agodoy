from django.http import HttpResponseForbidden

from chat.models import Mensaje
from chat.services.notifications import notify_new_message
from chat.services.unread import invalidate_unread_cache


def create_message(conversacion, sender, texto, empresa_id=None):
    if not texto or not texto.strip():
        raise ValueError("empty_message")
    if empresa_id and conversacion.empresa_id != empresa_id:
        raise ValueError("empresa_mismatch")
    if not conversacion.participantes.filter(id=sender.id).exists():
        raise ValueError("not_participant")

    mensaje = Mensaje.objects.create(
        conversacion=conversacion,
        remitente=sender,
        contenido=texto.strip(),
    )
    participant_ids = list(
        conversacion.participantes.values_list("id", flat=True)
    )
    invalidate_unread_cache(participant_ids, conversacion.empresa_id)
    notify_new_message(conversacion, mensaje)
    return mensaje
