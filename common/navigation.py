from django.urls import resolve


EXCLUDED_NAVIGATION_PATHS = (
    "/acounts/login/",
    "/acounts/logout/",
    "/access-control/seleccionar_empresa/",
    "/auth/activate/",
    "/admin/",
    "/static/",
    "/media/",
    "/api/",
    "/notificaciones/topbar/",
    "/notificaciones/forzar/",
    "/notificaciones/alerta-personalizada/",
    "/settings/fecha-sistema/",
    "/search/menu/",
    "/favicon.ico",
    "/403/",
    "/404/",
    "/500/",
)


def is_technical_navigation_path(path):
    normalized = (path or "/").strip()
    if not normalized.startswith("/"):
        return False

    try:
        match = resolve(normalized)
    except Exception:
        return False

    namespace = (match.namespace or "").strip().lower()
    url_name = (match.url_name or "").strip().lower()
    if namespace == "notificaciones" and url_name in {"topbar", "mark_read", "mark_all_read"}:
        return True

    view_name = (match.view_name or "").strip()
    if view_name.startswith("api."):
        return True

    return False


def is_excluded_navigation_path(path):
    normalized = (path or "/").strip()
    if not normalized.startswith("/"):
        return True
    if is_technical_navigation_path(normalized):
        return True
    return any(
        normalized == excluded or normalized.startswith(excluded)
        for excluded in EXCLUDED_NAVIGATION_PATHS
    )


def is_valid_internal_path(path):
    try:
        resolve(path)
        return True
    except Exception:
        return False


def is_navigable_request(request):
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
    if is_excluded_navigation_path(path):
        return False
    return is_valid_internal_path(path)
