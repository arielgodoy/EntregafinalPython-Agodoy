from django.shortcuts import redirect
from django.urls import reverse


class EmpresaActivaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._should_enforce(request):
            if not request.session.get("empresa_id"):
                return redirect(self._get_selector_url())
        return self.get_response(request)

    def _get_selector_url(self):
        try:
            return reverse("access_control:seleccionar_empresa")
        except Exception:
            return "/access-control/seleccionar_empresa/"

    def _get_login_url(self):
        try:
            return reverse("login")
        except Exception:
            return "/acounts/login/"

    def _get_logout_url(self):
        try:
            return reverse("logout")
        except Exception:
            return "/acounts/logout/"

    def _should_enforce(self, request):
        if not request.user.is_authenticated:
            return False

        path = request.path or ""
        selector_url = self._get_selector_url()
        login_url = self._get_login_url()
        logout_url = self._get_logout_url()

        whitelist_prefixes = (
            selector_url,
            login_url,
            logout_url,
            "/auth/activate/",
            "/admin/",
            "/static/",
            "/media/",
            "/notificaciones/forzar/",  # Herramienta admin: permite elegir empresa objetivo explícitamente
            "/notificaciones/alerta-personalizada/",  # Herramienta admin: permite elegir empresa objetivo explícitamente
            "/settings/fecha-sistema/",  # Fecha sistema por usuario
            "/search/menu/",  # Busqueda global (retorna vacio sin empresa activa)
        )

        if path == selector_url or path.startswith(whitelist_prefixes):
            return False

        return True
