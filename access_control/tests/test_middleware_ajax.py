from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory
from django.http import HttpResponse
from django.urls import reverse

from access_control.middleware import EmpresaActivaMiddleware


def dummy_view(request):
    return HttpResponse('ok')


class EmpresaActivaMiddlewareAjaxTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='tester', password='pass')
        self.middleware = EmpresaActivaMiddleware(get_response=dummy_view)

    def test_ajax_request_without_empresa_returns_401_json(self):
        request = self.factory.get('/some/protected/path/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        request.user = self.user
        # Ensure no empresa_id in session
        request.session = {}

        response = self.middleware(request)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response['Content-Type'], 'application/json')
