from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.contrib.sessions.middleware import SessionMiddleware

from access_control.models import Empresa
from chat.context_processors import chat_unread_count
from chat.services.unread import get_unread_count_cached


class TestUnreadPerf(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="user_perf",
            email="user_perf@example.com",
            password="pass12345",
        )

    def _request_with_session(self):
        factory = RequestFactory()
        request = factory.get("/")
        request.user = self.user
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session["empresa_id"] = self.empresa.id
        request.session.save()
        return request

    def test_request_cache_evitar_recalculo(self):
        request = self._request_with_session()
        with mock.patch("chat.context_processors.get_unread_count_cached", return_value=3) as mocked:
            chat_unread_count(request)
            chat_unread_count(request)
        self.assertEqual(mocked.call_count, 1)

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "test-chat-unread",
            }
        }
    )
    def test_cache_corto_evitar_recalculo(self):
        cache.clear()
        with mock.patch("chat.services.unread.get_unread_count", return_value=5) as mocked:
            first = get_unread_count_cached(self.user, self.empresa.id, timeout=15)
            second = get_unread_count_cached(self.user, self.empresa.id, timeout=15)
        self.assertEqual(first, 5)
        self.assertEqual(second, 5)
        self.assertEqual(mocked.call_count, 1)
