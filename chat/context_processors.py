from chat.services.unread import get_unread_count_cached


def chat_unread_count(request):
    user = getattr(request, "user", None)
    empresa_id = None
    if hasattr(request, "session"):
        empresa_id = request.session.get("empresa_id")
    cache = getattr(request, "_chat_unread_cache", None)
    if cache is None:
        cache = {}
        setattr(request, "_chat_unread_cache", cache)

    cache_key = empresa_id
    if cache_key in cache:
        return {"chat_unread_count": cache[cache_key]}

    count = get_unread_count_cached(user, empresa_id)
    cache[cache_key] = count
    return {"chat_unread_count": count}
