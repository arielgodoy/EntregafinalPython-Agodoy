from urllib.parse import urlsplit

from django.urls import NoReverseMatch, reverse
from django.utils.http import url_has_allowed_host_and_scheme

from access_control.models import Empresa, Permiso, Vista
from common.navigation import (
    EXCLUDED_NAVIGATION_PATHS,
    is_excluded_navigation_path,
    is_navigable_request,
    is_valid_internal_path,
)

LAST_VIEW_SESSION_KEY = "ultima_vista_url"

EXCLUDED_LAST_VIEW_PATHS = EXCLUDED_NAVIGATION_PATHS


def set_empresa_activa_en_sesion(request, empresa):
    request.session["empresa_id"] = empresa.id
    request.session["empresa_codigo"] = empresa.codigo
    request.session["empresa_nombre"] = f"{empresa.codigo} - {empresa.descripcion or 'Sin descripción'}"


def get_safe_redirect_target(request, *, fallback_url=None, candidate_urls=None):
    try:
        fallback_url = (
            reverse("dashboard:dashboard_general")
            if fallback_url is None
            else fallback_url
        )
    except NoReverseMatch:
        fallback_url = "/"

    candidates = []
    if candidate_urls:
        candidates.extend(candidate_urls)
    candidates.extend([
        request.POST.get("next") if hasattr(request, "POST") else None,
        request.GET.get("next") if hasattr(request, "GET") else None,
        request.session.get(LAST_VIEW_SESSION_KEY),
    ])

    for candidate in candidates:
        if not candidate:
            continue

        if not isinstance(candidate, str):
            continue

        candidate = candidate.strip()
        if not candidate:
            continue

        parsed = urlsplit(candidate)
        path = parsed.path or candidate

        if not path.startswith("/"):
            continue

        if is_excluded_last_view_path(path):
            continue

        if not is_valid_internal_path(path):
            continue

        if parsed.scheme or parsed.netloc:
            allowed_hosts = {request.get_host()} if request.get_host() else {"localhost"}
            if not url_has_allowed_host_and_scheme(candidate, allowed_hosts=allowed_hosts):
                continue
        elif not url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host() or "localhost"}):
            continue

        return candidate

    return fallback_url


def get_user_initial_view_url(user):
    try:
        from settings.models import UserPreferences

        preferences = UserPreferences.objects.select_related("vista_inicial").get(user=user)
        vista = preferences.vista_inicial
        route_name = (vista.route_name or "").strip() if vista else ""
        if not route_name:
            raise NoReverseMatch

        target = reverse(route_name)
        path = urlsplit(target).path or target
        if is_excluded_last_view_path(path) or not is_valid_internal_path(path):
            raise NoReverseMatch
        return target
    except (NoReverseMatch, UserPreferences.DoesNotExist):
        return reverse("dashboard:dashboard_general")


def get_navigable_vistas():
    vistas = []
    for vista in Vista.objects.exclude(route_name__isnull=True).exclude(route_name="").order_by("nombre"):
        if _is_navigable_vista(vista):
            vistas.append(vista)
    return vistas


def get_user_navigable_vistas(user):
    return get_navigable_vistas_by_user_ids([user.id]).get(user.id, [])


def get_navigable_vistas_by_user_ids(user_ids):
    user_ids = set(user_ids)
    if not user_ids:
        return {}

    permissions = Permiso.objects.filter(
        usuario_id__in=user_ids,
        ingresar=True,
    ).select_related("vista").order_by("vista__nombre").distinct()
    vistas_by_id = {}
    user_vista_ids = {user_id: [] for user_id in user_ids}
    for permission in permissions:
        vista = permission.vista
        if vista.id not in vistas_by_id:
            if not _is_navigable_vista(vista):
                continue
            vistas_by_id[vista.id] = vista
        if vista.id not in user_vista_ids[permission.usuario_id]:
            user_vista_ids[permission.usuario_id].append(vista.id)

    return {
        user_id: [vistas_by_id[vista_id] for vista_id in vista_ids]
        for user_id, vista_ids in user_vista_ids.items()
    }


def _is_navigable_vista(vista):
    try:
        target = reverse((vista.route_name or "").strip())
        path = urlsplit(target).path or target
        return not is_excluded_last_view_path(path) and is_valid_internal_path(path)
    except (NoReverseMatch, AttributeError):
        return False


def is_excluded_last_view_path(path):
    return is_excluded_navigation_path(path)


def should_record_last_view(request):
    return is_navigable_request(request)


def remember_last_valid_view(request):
    if not should_record_last_view(request):
        return

    path = request.get_full_path()
    if not path or not path.startswith("/"):
        return

    request.session[LAST_VIEW_SESSION_KEY] = path


def get_empresas_usuario(user):
    return Empresa.objects.filter(permiso__usuario=user).distinct()


def resolve_post_login(request, user):
    empresas = get_empresas_usuario(user)
    count = empresas.count()
    if count == 0:
        return "NONE", None
    if count == 1:
        return "ONE", empresas.first()
    return "MANY", None
