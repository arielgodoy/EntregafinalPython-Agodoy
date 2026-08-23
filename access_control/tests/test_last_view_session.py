from django.test import SimpleTestCase

from access_control.services.empresa_activa import (
    LAST_VIEW_SESSION_KEY,
    get_safe_redirect_target,
    should_record_last_view,
)


class LastViewSessionTests(SimpleTestCase):
    def _make_request(self, path="/gestiondte/cesiones/", method="GET", *, accept="text/html", xhr=False, hx=False, query_string="?mes=8&anio=2026", user_authenticated=True):
        class DummyHeaders(dict):
            def get(self, key, default=None):
                return super().get(key.lower(), super().get(key, default))

        class DummyRequest:
            def __init__(self):
                self.method = method
                self.path = path
                self.GET = {}
                self.POST = {}
                self.session = {}
                self.META = {}
                self.user = type("User", (), {"is_authenticated": user_authenticated})()
                self.headers = DummyHeaders({
                    "accept": accept,
                })
                if xhr:
                    self.headers["x-requested-with"] = "XMLHttpRequest"
                    self.META["HTTP_X_REQUESTED_WITH"] = "XMLHttpRequest"
                if hx:
                    self.headers["HX-Request"] = "true"
                    self.META["HTTP_HX_REQUEST"] = "true"
                self.resolver_match = object()

            def get_full_path(self):
                return f"{path}{query_string}"

            def get_host(self):
                return "testserver"

            def is_ajax(self):
                return bool(xhr)

        return DummyRequest()

    def test_get_normal_guard_requires_path_and_query_string(self):
        request = self._make_request(path="/gestiondte/cesiones/", query_string="?mes=8&anio=2026")
        self.assertTrue(should_record_last_view(request))
        request.session[LAST_VIEW_SESSION_KEY] = request.get_full_path()
        self.assertEqual(request.session[LAST_VIEW_SESSION_KEY], "/gestiondte/cesiones/?mes=8&anio=2026")

    def test_post_normal_does_not_record_last_view(self):
        request = self._make_request(method="POST", path="/gestiondte/cesiones/", query_string="?mes=8&anio=2026")
        self.assertFalse(should_record_last_view(request))

    def test_external_next_is_rejected(self):
        request = self._make_request(path="/access-control/seleccionar_empresa/")
        target = get_safe_redirect_target(
            request,
            fallback_url="/",
            candidate_urls=["https://evil.example.com/"],
        )
        self.assertEqual(target, "/")

    def test_internal_next_is_used(self):
        request = self._make_request(path="/access-control/seleccionar_empresa/")
        target = get_safe_redirect_target(
            request,
            fallback_url="/",
            candidate_urls=["/gestiondte/cesiones/?mes=8&anio=2026"],
        )
        self.assertEqual(target, "/gestiondte/cesiones/?mes=8&anio=2026")

    def test_session_last_view_is_used_when_next_missing(self):
        request = self._make_request(path="/access-control/seleccionar_empresa/")
        request.session[LAST_VIEW_SESSION_KEY] = "/gestiondte/cesiones/?mes=8&anio=2026"
        target = get_safe_redirect_target(request, fallback_url="/", candidate_urls=[])
        self.assertEqual(target, "/gestiondte/cesiones/?mes=8&anio=2026")

    def test_without_valid_targets_uses_dashboard_fallback(self):
        request = self._make_request(path="/access-control/seleccionar_empresa/")
        target = get_safe_redirect_target(request, fallback_url="/", candidate_urls=["/api/v1/maestros/rubros/"])
        self.assertEqual(target, "/")

    def test_selector_path_does_not_replace_last_view(self):
        request = self._make_request(path="/access-control/seleccionar_empresa/", query_string="")
        self.assertFalse(should_record_last_view(request))

    def test_api_path_is_not_recorded(self):
        request = self._make_request(path="/api/v1/maestros/rubros/", query_string="?page=1")
        self.assertFalse(should_record_last_view(request))

    def test_json_request_is_not_recorded(self):
        request = self._make_request(path="/gestiondte/cesiones/", accept="application/json")
        self.assertFalse(should_record_last_view(request))

    def test_request_without_is_ajax_method_is_supported(self):
        class NoAjaxRequest:
            method = "GET"
            path = "/gestiondte/cesiones/"
            GET = {}
            POST = {}
            session = {}
            META = {}
            user = type("User", (), {"is_authenticated": True})()
            headers = {"accept": "text/html"}

            def get_full_path(self):
                return "/gestiondte/cesiones/?mes=8&anio=2026"

            def get_host(self):
                return "testserver"

        request = NoAjaxRequest()
        self.assertTrue(should_record_last_view(request))

    def test_error_paths_are_excluded(self):
        for path in ["/403/", "/404/", "/500/", "/admin/", "/static/test.js"]:
            request = self._make_request(path=path, query_string="")
            self.assertFalse(should_record_last_view(request))

    def test_query_string_is_preserved(self):
        request = self._make_request(path="/gestiondte/cesiones/", query_string="?mes=8&anio=2026")
        self.assertTrue(should_record_last_view(request))
        self.assertEqual(request.get_full_path(), "/gestiondte/cesiones/?mes=8&anio=2026")

    def test_permission_denied_is_not_dashboard_fallback(self):
        request = self._make_request(path="/access-control/seleccionar_empresa/")
        target = get_safe_redirect_target(
            request,
            fallback_url="/",
            candidate_urls=["/access-control/403_forbidden/"]
        )
        self.assertEqual(target, "/")

    def test_logout_clears_last_view(self):
        request = self._make_request(path="/gestiondte/cesiones/", query_string="?mes=8&anio=2026")
        request.session[LAST_VIEW_SESSION_KEY] = "/gestiondte/cesiones/?mes=8&anio=2026"
        request.session.pop(LAST_VIEW_SESSION_KEY, None)
        self.assertNotIn(LAST_VIEW_SESSION_KEY, request.session)
