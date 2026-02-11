from django.db.models import Q
from django.utils import timezone

from notificaciones.models import Notification


def create_notification(destinatario, empresa, tipo, titulo, cuerpo="", url="", actor=None, dedupe_key=""):
    return Notification.objects.create(
        destinatario=destinatario,
        empresa=empresa,
        tipo=tipo,
        titulo=titulo,
        cuerpo=cuerpo,
        url=url,
        actor=actor,
        dedupe_key=dedupe_key,
    )


def mark_read(notification, user):
    if notification.destinatario_id != user.id:
        return False
    if notification.is_read:
        return True
    notification.is_read = True
    notification.read_at = timezone.now()
    notification.save(update_fields=["is_read", "read_at"])
    return True


def mark_all_read(user, empresa_id):
    if empresa_id:
        qs = Notification.objects.filter(destinatario=user, is_read=False).filter(
            Q(empresa_id=empresa_id) | Q(empresa__isnull=True)
        )
    else:
        qs = Notification.objects.filter(destinatario=user, is_read=False)
    return qs.update(is_read=True, read_at=timezone.now())
