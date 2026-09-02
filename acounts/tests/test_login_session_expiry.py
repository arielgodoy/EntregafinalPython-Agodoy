from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista


class LoginSessionExpiryTests(TestCase):
    def setUp(self):
        self.password = 'pass1234'
        self.user = User.objects.create_user(
            username='session-user',
            password=self.password,
        )
        empresa = Empresa.objects.create(codigo='01', descripcion='Empresa 01')
        vista = Vista.objects.create(nombre='Listado de Propiedades')
        Permiso.objects.create(
            usuario=self.user,
            empresa=empresa,
            vista=vista,
            ingresar=True,
        )
        self.login_url = reverse('login')

    def test_login_sin_recordarme_expira_al_cerrar_navegador(self):
        response = self.client.post(
            self.login_url,
            data={'username': self.user.username, 'password': self.password},
        )

        self.assertEqual(response.status_code, 302)
        session = self.client.session
        self.assertTrue(session.get_expire_at_browser_close())
        self.assertEqual(session.get('_auth_user_id'), str(self.user.pk))

    def test_login_con_recordarme_expira_en_ocho_horas(self):
        response = self.client.post(
            self.login_url,
            data={
                'username': self.user.username,
                'password': self.password,
                'remember_me': '1',
            },
        )

        self.assertEqual(response.status_code, 302)
        session = self.client.session
        self.assertFalse(session.get_expire_at_browser_close())
        self.assertEqual(session.get_expiry_age(), 8 * 60 * 60)
        self.assertEqual(session.get('_auth_user_id'), str(self.user.pk))

    def test_credenciales_invalidas_no_crean_sesion_autenticada(self):
        response = self.client.post(
            self.login_url,
            data={
                'username': self.user.username,
                'password': 'wrong-password',
                'remember_me': '1',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_logout_elimina_la_sesion_autenticada(self):
        self.client.post(
            self.login_url,
            data={
                'username': self.user.username,
                'password': self.password,
                'remember_me': '1',
            },
        )

        response = self.client.get(reverse('logout'))

        self.assertRedirects(response, self.login_url)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_no_almacena_credenciales_en_frontend(self):
        template_path = (
            Path(__file__).resolve().parents[2]
            / 'templates/pages/authentication/auth-signin-basic.html'
        )
        template = template_path.read_text(encoding='utf-8')

        self.assertIn('name="remember_me"', template)
        self.assertNotIn('localStorage', template)
        self.assertNotIn('sessionStorage', template)
        self.assertNotIn('type="hidden" name="password"', template)
        self.assertNotIn('type="hidden" name="token"', template)

    def test_session_cookie_age_es_ocho_horas(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 8 * 60 * 60)

    def test_login_sin_recordarme_no_supera_ocho_horas_en_backend(self):
        """set_expiry(0) cae en SESSION_COOKIE_AGE (8h), nunca en el default de 14 dias."""
        self.client.post(
            self.login_url,
            data={'username': self.user.username, 'password': self.password},
        )

        session = self.client.session
        self.assertEqual(session.get_expiry_age(), 8 * 60 * 60)

    def _session_row(self):
        key = self.client.session.session_key
        return Session.objects.get(session_key=key)

    def test_actividad_desplaza_la_expiracion_por_inactividad(self):
        self.client.post(
            self.login_url,
            data={'username': self.user.username, 'password': self.password, 'remember_me': '1'},
        )
        expire_antes = self._session_row().expire_date

        future = timezone.now() + timedelta(hours=4)
        with mock.patch('django.utils.timezone.now', return_value=future):
            self.client.get(reverse('editar_perfil'))

        expire_despues = self._session_row().expire_date
        self.assertGreater(expire_despues, expire_antes)

    def test_sesion_expirada_redirige_a_login(self):
        self.client.post(
            self.login_url,
            data={'username': self.user.username, 'password': self.password, 'remember_me': '1'},
        )
        key = self.client.session.session_key
        Session.objects.filter(session_key=key).update(expire_date=timezone.now() - timedelta(hours=1))

        response = self.client.get(reverse('editar_perfil'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_fecha_sistema_no_interviene_en_la_expiracion(self):
        frozen_now = timezone.now()
        with mock.patch('django.utils.timezone.now', return_value=frozen_now):
            self.client.post(
                self.login_url,
                data={'username': self.user.username, 'password': self.password, 'remember_me': '1'},
            )
            expire_antes = self._session_row().expire_date

            session = self.client.session
            session['fecha_sistema'] = (timezone.localdate() - timedelta(days=30)).isoformat()
            session.save()

            expire_despues = self._session_row().expire_date

        self.assertEqual(expire_antes, expire_despues)

    def test_login_registra_datos_de_sesion(self):
        self.client.post(
            self.login_url,
            data={'username': self.user.username, 'password': self.password, 'remember_me': '1'},
            HTTP_USER_AGENT='UnitTestAgent/1.0',
        )

        session = self.client.session
        self.assertIn('login_at', session)
        self.assertIn('last_activity', session)
        self.assertEqual(session.get('ip_address'), '127.0.0.1')
        self.assertEqual(session.get('user_agent'), 'UnitTestAgent/1.0')
        self.assertTrue(session.get('remember_me'))

    def test_login_sin_recordarme_registra_remember_me_false(self):
        self.client.post(
            self.login_url,
            data={'username': self.user.username, 'password': self.password},
        )

        self.assertFalse(self.client.session.get('remember_me'))
