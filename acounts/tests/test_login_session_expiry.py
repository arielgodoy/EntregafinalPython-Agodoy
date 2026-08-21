from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

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
