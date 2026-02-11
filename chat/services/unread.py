from django.core.cache import cache
from django.db.models import Exists, OuterRef

from chat.models import Mensaje, MensajeLeido


def _cache_key(user_id, empresa_id):
    return f"chat_unread:{user_id}:{empresa_id}"


def get_unread_count(user, empresa_id):
    if not user or not user.is_authenticated or not empresa_id:
        return 0

    read_exists = MensajeLeido.objects.filter(
        mensaje_id=OuterRef("pk"),
        user_id=user.id,
    )

    qs = (
        Mensaje.objects.filter(
            conversacion__empresa_id=empresa_id,
            conversacion__participantes__id=user.id,
        )
        .exclude(remitente_id=user.id)
        .annotate(read_exists=Exists(read_exists))
        .filter(read_exists=False)
    )
    return qs.count()


def get_unread_count_cached(user, empresa_id, timeout=15):
    if not user or not user.is_authenticated or not empresa_id:
        return 0

    key = _cache_key(user.id, empresa_id)
    cached = cache.get(key)
    if cached is not None:
        return cached

    count = get_unread_count(user, empresa_id)
    cache.set(key, count, timeout=timeout)
    return count


def invalidate_unread_cache(user_ids, empresa_id):
    if not empresa_id or not user_ids:
        return 0
    deleted = 0
    for user_id in set(user_ids):
        if not user_id:
            continue
        cache.delete(_cache_key(user_id, empresa_id))
        deleted += 1
    return deleted


def mark_conversation_read(conversacion, user):
    if not conversacion or not user or not user.is_authenticated:
        return 0

    unread_ids = (
        Mensaje.objects.filter(conversacion=conversacion)
        .exclude(remitente_id=user.id)
        .exclude(leidos__user=user)
        .values_list("id", flat=True)
    )

    to_create = [
        MensajeLeido(
            empresa=conversacion.empresa,
            mensaje_id=mensaje_id,
            user=user,
        )
        for mensaje_id in unread_ids
    ]

    if not to_create:
        return 0

    MensajeLeido.objects.bulk_create(to_create, ignore_conflicts=True)
    invalidate_unread_cache([user.id], conversacion.empresa_id)
    return len(to_create)
