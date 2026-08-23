from urllib.parse import urlsplit

from django.urls import NoReverseMatch, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme

from access_control.models import Empresa, Permiso

LAST_VIEW_SESSION_KEY = "ultima_vista_url"

EXCLUDED_LAST_VIEW_PATHS = (
    "/acounts/login/",
    "/acounts/logout/",
    "/access-control/seleccionar_empresa/",
    "/auth/activate/",
    "/admin/",
    "/static/",
    "/media/",
    "/api/",
    "/notificaciones/forzar/",
    "/notificaciones/alerta-personalizada/",
    "/settings/fecha-sistema/",
    "/search/menu/",
    "/favicon.ico",
    "/403/",
    "/404/",
    "/500/",
)


def set_empresa_activa_en_sesion(request, empresa):
    request.session["empresa_id"] = empresa.id
    request.session["empresa_codigo"] = empresa.codigo
    request.session["empresa_nombre"] = f"{empresa.codigo} - {empresa.descripcion or 'Sin descripción'}"


def get_safe_redirect_target(request, *, fallback_url=None, candidate_urls=None):
    try:
        fallback_url = fallback_url or reverse("dashboard:dashboard_general")
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


def is_valid_internal_path(path):
    try:
        resolve(path)
        return True
    except Exception:
        return False


def is_excluded_last_view_path(path):
    normalized = (path or "/").strip()
    if not normalized.startswith("/"):
        return True
    for excluded in EXCLUDED_LAST_VIEW_PATHS:
        if normalized == excluded or normalized.startswith(excluded):
            return True
    return False


def should_record_last_view(request):
    if request.method != "GET":
        return False
    if not getattr(request.user, "is_authenticated", False):
        return False

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return False
    if request.headers.get("HX-Request") == "true":
        return False
    if request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest":
        return False
    if request.META.get("HTTP_HX_REQUEST") == "true":
        return False

    is_ajax_callable = getattr(request, "is_ajax", None)
    if callable(is_ajax_callable) and is_ajax_callable():
        return False

    accept_header = request.headers.get("accept", "")
    if "application/json" in accept_header.lower():
        return False

    path = request.path or ""
    if not path.startswith("/"):
        return False
    if path.startswith("/api/"):
        return False
    if is_excluded_last_view_path(path):
        return False
    if not is_valid_internal_path(path):
        return False
    return True


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
