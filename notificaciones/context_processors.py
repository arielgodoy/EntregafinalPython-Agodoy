from django.db.models import Q

from notificaciones.models import Notification


def notifications_unread_count(request):
    user = getattr(request, "user", None)
    empresa_id = None
    if hasattr(request, "session"):
        empresa_id = request.session.get("empresa_id")

    if not user or not user.is_authenticated or not empresa_id:
        return {"notifications_unread_count": 0}

    cache = getattr(request, "_notifications_unread_cache", None)
    if cache is None:
        cache = {}
        setattr(request, "_notifications_unread_cache", cache)

    if empresa_id in cache:
        return {"notifications_unread_count": cache[empresa_id]}

    count = Notification.objects.filter(destinatario=user, is_read=False).filter(
        Q(empresa_id=empresa_id) | Q(empresa__isnull=True)
    ).count()
    cache[empresa_id] = count
    return {"notifications_unread_count": count}
