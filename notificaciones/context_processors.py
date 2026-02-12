from django.db.models import Q

from notificaciones.models import Notification
from notificaciones.services import get_sidebar_counts


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


def notifications_sidebar_counts(request):
    user = getattr(request, "user", None)
    empresa_id = None
    if hasattr(request, "session"):
        empresa_id = request.session.get("empresa_id")

    if not user or not user.is_authenticated or not empresa_id:
        return {
            "notifications_unread_all": 0,
            "notifications_unread_messages": 0,
            "notifications_unread_alerts": 0,
            "notifications_unread_system": 0,
        }

    cache = getattr(request, "_notifications_sidebar_cache", None)
    if cache is None:
        cache = {}
        setattr(request, "_notifications_sidebar_cache", cache)

    if empresa_id not in cache:
        cache[empresa_id] = get_sidebar_counts(user, empresa_id)

    counts = cache[empresa_id]
    return {
        "notifications_unread_all": counts.get("unread_all", 0),
        "notifications_unread_messages": counts.get("unread_messages", 0),
        "notifications_unread_alerts": counts.get("unread_alerts", 0),
        "notifications_unread_system": counts.get("unread_system", 0),
    }
