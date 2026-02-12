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


def _base_queryset(user, empresa_id):
    if empresa_id:
        return Notification.objects.filter(destinatario=user).filter(
            Q(empresa_id=empresa_id) | Q(empresa__isnull=True)
        )
    return Notification.objects.filter(destinatario=user)


def get_topbar_counts(user, empresa_id):
    qs = _base_queryset(user, empresa_id).filter(is_read=False)
    return {
        "unread_all": qs.count(),
        "unread_messages": qs.filter(tipo=Notification.Tipo.MESSAGE).count(),
        "unread_alerts": qs.filter(tipo=Notification.Tipo.ALERT).count(),
        "unread_system": qs.filter(tipo=Notification.Tipo.SYSTEM).count(),
    }


def get_sidebar_counts(user, empresa_id):
    return get_topbar_counts(user, empresa_id)


def get_topbar_notifications(user, empresa_id, tipo=None, page=1, page_size=10):
    qs = _base_queryset(user, empresa_id)
    if tipo and tipo != "ALL":
        qs = qs.filter(tipo=tipo)
    qs = qs.order_by("-created_at")

    start = (page - 1) * page_size
    end = start + page_size + 1
    items = list(qs[start:end])
    has_next = len(items) > page_size
    return items[:page_size], has_next
