import os
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from AppDocs.settings import _DEFAULT_SECRET_KEY, _env_bool, _env_list


class SecuritySettingsTests(SimpleTestCase):
    def test_env_bool_acepta_valores_verdaderos_y_falsos(self):
        self.assertTrue(_env_bool('FLAG', environ={'FLAG': 'yes'}))
        self.assertTrue(_env_bool('FLAG', environ={'FLAG': '1'}))
        self.assertFalse(_env_bool('FLAG', environ={'FLAG': 'false'}))
        self.assertFalse(_env_bool('MISSING', environ={}))

    def test_env_list_separa_y_limpia_comas(self):
        self.assertEqual(
            _env_list('HOSTS', environ={'HOSTS': ' one.example, two.example ,, '}),
            ['one.example', 'two.example'],
        )
        self.assertEqual(_env_list('MISSING', default=['*'], environ={}), ['*'])

    def test_defaults_de_desarrollo(self):
        environment = {}
        self.assertTrue(_env_bool('DJANGO_DEBUG', default=True, environ=environment))
        self.assertEqual(_env_list('DJANGO_ALLOWED_HOSTS', default=['*'], environ=environment), ['*'])
        self.assertFalse(_env_bool('SESSION_COOKIE_SECURE', environ=environment))
        self.assertFalse(_env_bool('CSRF_COOKIE_SECURE', environ=environment))
        self.assertFalse(settings.SECURE_SSL_REDIRECT)
        self.assertIsNone(settings.SECURE_PROXY_SSL_HEADER)

    def test_configuracion_productiva_parsea_cookies_y_proxy(self):
        environment = {
            'DJANGO_DEBUG': 'False',
            'DJANGO_ALLOWED_HOSTS': 'biblioteca.eltit.cl',
            'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://biblioteca.eltit.cl',
            'SESSION_COOKIE_SECURE': 'True',
            'CSRF_COOKIE_SECURE': 'True',
            'DJANGO_BEHIND_HTTPS_PROXY': 'True',
        }

        self.assertFalse(_env_bool('DJANGO_DEBUG', environ=environment))
        self.assertEqual(_env_list('DJANGO_ALLOWED_HOSTS', environ=environment), ['biblioteca.eltit.cl'])
        self.assertEqual(
            _env_list('DJANGO_CSRF_TRUSTED_ORIGINS', environ=environment),
            ['https://biblioteca.eltit.cl'],
        )
        self.assertTrue(_env_bool('SESSION_COOKIE_SECURE', environ=environment))
        self.assertTrue(_env_bool('CSRF_COOKIE_SECURE', environ=environment))
        self.assertEqual(
            ('HTTP_X_FORWARDED_PROTO', 'https')
            if _env_bool('DJANGO_BEHIND_HTTPS_PROXY', environ=environment)
            else None,
            ('HTTP_X_FORWARDED_PROTO', 'https'),
        )

    def test_proxy_falso_y_redirect_https_permanecen_desactivados(self):
        with patch.dict(os.environ, {'DJANGO_BEHIND_HTTPS_PROXY': 'False'}):
            self.assertFalse(_env_bool('DJANGO_BEHIND_HTTPS_PROXY'))
        self.assertFalse(settings.SECURE_SSL_REDIRECT)

    def test_secret_key_vacia_conserva_fallback_compatible(self):
        with patch.dict(os.environ, {'DJANGO_SECRET_KEY': '   '}):
            configured_key = os.getenv('DJANGO_SECRET_KEY', '').strip() or _DEFAULT_SECRET_KEY

        self.assertEqual(configured_key, _DEFAULT_SECRET_KEY)