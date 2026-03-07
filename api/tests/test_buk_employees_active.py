from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from access_control.models import Empresa


class BukEmployeesActiveEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='p')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 1')
        self.client = Client()
        self.client.force_login(self.user)

        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session['empresa_codigo'] = self.empresa.codigo
        session.save()

    def test_missing_date_returns_400(self):
        url = reverse('employees_active')
        resp = self.client.get(url)

        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.json())

    def test_invalid_date_returns_400(self):
        url = reverse('employees_active')
        resp = self.client.get(url, {'date': '2026-13-40'})

        self.assertEqual(resp.status_code, 400)
        self.assertIn('detail', resp.json())

    @override_settings(BUK_API_BASE_URL='https://buk.example/api/v1', BUK_API_AUTH_TOKEN='token')
    @patch('api.views.urlopen')
    def test_success_proxies_response(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"employees": [{"id": 1}]}'
        mock_urlopen.return_value = mock_resp

        url = reverse('employees_active')
        resp = self.client.get(url, {'date': '2026-01-01', 'exclude_pending': 'true'})

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertIn('data', payload)
        self.assertEqual(payload['data']['employees'][0]['id'], 1)

        req = mock_urlopen.call_args[0][0]
        self.assertIn('employees/active', req.full_url)
        self.assertIn('date=2026-01-01', req.full_url)
        self.assertIn('exclude_pending=true', req.full_url)

        headers = {}
        headers.update(getattr(req, 'headers', {}) or {})
        headers.update(getattr(req, 'unredirected_hdrs', {}) or {})

        self.assertEqual(headers.get('Accept') or headers.get('accept'), 'application/json')

        token_value = None
        for key, value in headers.items():
            if str(key).lower().replace('-', '_') == 'auth_token':
                token_value = value
                break
        self.assertEqual(token_value, 'token')

    @override_settings(BUK_API_BASE_URL='https://buk.example/api/v1', BUK_API_AUTH_TOKEN='token')
    @patch('api.views.urlopen')
    def test_upstream_http_error_returns_controlled_502(self, mock_urlopen):
        http_error = HTTPError(
            url='https://buk.example/api/v1/employees/active',
            code=500,
            msg='Internal Server Error',
            hdrs=None,
            fp=BytesIO(b'{"error": "boom"}'),
        )
        mock_urlopen.side_effect = http_error

        url = reverse('employees_active')
        resp = self.client.get(url, {'date': '2026-01-01'})

        self.assertEqual(resp.status_code, 502)
        payload = resp.json()
        self.assertEqual(payload.get('detail'), 'Error al consultar Buk.')
        self.assertEqual(payload.get('upstream_status'), 500)
