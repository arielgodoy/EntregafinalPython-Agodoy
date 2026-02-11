from django import template

from access_control.models import Permiso, Vista

register = template.Library()


@register.simple_tag(takes_context=True)
def has_permiso(context, vista_nombre, permiso_requerido):
    request = context.get("request")
    if not request or not getattr(request, "user", None) or not request.user.is_authenticated:
        return False

    empresa_id = request.session.get("empresa_id")
    if not empresa_id:
        return False

    cache = getattr(request, "_permiso_cache", {})
    cache_key = (empresa_id, vista_nombre, permiso_requerido)
    if cache_key in cache:
        return cache[cache_key]

    vista = Vista.objects.filter(nombre=vista_nombre).first()
    if not vista:
        cache[cache_key] = False
        request._permiso_cache = cache
        return False

    permiso = Permiso.objects.filter(
        usuario=request.user,
        empresa_id=empresa_id,
        vista=vista,
    ).first()

    allowed = bool(permiso and getattr(permiso, permiso_requerido, False))
    cache[cache_key] = allowed
    request._permiso_cache = cache
    return allowed
