from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from acounts.models import UserActiveSession
from acounts.services.active_session import clear_active_session


class ActiveSessionTests(TestCase):
    def setUp(self):
        self.password = 'pass1234'
        self.user = User.objects.create_user(
            username='active-session-user',
            password=self.password,
        )
        self.other_user = User.objects.create_user(
            username='other-active-session-user',
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
        Permiso.objects.create(
            usuario=self.other_user,
            empresa=empresa,
            vista=vista,
            ingresar=True,
        )
        self.login_url = reverse('login')

    def _login(self, client, remember_me=False):
        data = {
            'username': self.user.username,
            'password': self.password,
        }
        if remember_me:
            data['remember_me'] = '1'
        response = client.post(self.login_url, data=data)
        self.assertEqual(response.status_code, 302)
        return client.session.session_key

    def test_primer_login_crea_sesion_activa(self):
        session_key = self._login(self.client)

        active_session = UserActiveSession.objects.get(user=self.user)
        self.assertEqual(active_session.session_key, session_key)
        self.assertTrue(Session.objects.filter(session_key=session_key).exists())

    def test_misma_cookie_en_varias_requests_conserva_la_misma_sesion(self):
        session_key = self._login(self.client)

        self.client.get(reverse('editar_perfil'))
        self.client.get(reverse('editar_perfil'))

        self.assertEqual(self.client.session.session_key, session_key)
        self.assertEqual(
            UserActiveSession.objects.get(user=self.user).session_key,
            session_key,
        )

    def test_segundo_login_mismo_usuario_invalida_sesion_anterior(self):
        client_a = self.client
        session_key_a = self._login(client_a)
        client_b = self.client_class()
        session_key_b = self._login(client_b)

        self.assertNotEqual(session_key_a, session_key_b)
        self.assertFalse(Session.objects.filter(session_key=session_key_a).exists())
        self.assertTrue(Session.objects.filter(session_key=session_key_b).exists())
        self.assertEqual(
            UserActiveSession.objects.get(user=self.user).session_key,
            session_key_b,
        )

        self.assertEqual(client_b.get(reverse('editar_perfil')).status_code, 200)
        self.assertEqual(client_a.get(reverse('editar_perfil')).status_code, 302)
        self.assertIn(reverse('login'), client_a.get(reverse('editar_perfil')).url)

    def test_login_usuario_diferente_no_invalida_sesion_ajena(self):
        session_key_a = self._login(self.client)
        client_b = self.client_class()
        response = client_b.post(
            self.login_url,
            data={
                'username': self.other_user.username,
                'password': self.password,
            },
        )
        self.assertEqual(response.status_code, 302)

        self.assertTrue(Session.objects.filter(session_key=session_key_a).exists())
        self.assertEqual(
            UserActiveSession.objects.get(user=self.user).session_key,
            session_key_a,
        )
        self.assertTrue(
            UserActiveSession.objects.filter(user=self.other_user).exists()
        )

    def test_logout_de_sesion_activa_limpia_la_asociacion(self):
        session_key = self._login(self.client)

        response = self.client.get(reverse('logout'))

        self.assertRedirects(response, self.login_url)
        self.assertFalse(UserActiveSession.objects.filter(user=self.user).exists())
        self.assertFalse(Session.objects.filter(session_key=session_key).exists())

    def test_logout_viejo_no_elimina_asociacion_de_sesion_nueva(self):
        session_key_a = self._login(self.client)
        client_b = self.client_class()
        session_key_b = self._login(client_b)

        clear_active_session(self.user, session_key_a)

        self.assertEqual(
            UserActiveSession.objects.get(user=self.user).session_key,
            session_key_b,
        )

    def test_remember_me_no_cambia_la_exclusividad(self):
        session_key_a = self._login(self.client, remember_me=False)
        client_b = self.client_class()
        session_key_b = self._login(client_b, remember_me=True)

        self.assertNotEqual(session_key_a, session_key_b)
        self.assertFalse(Session.objects.filter(session_key=session_key_a).exists())
        self.assertEqual(
            UserActiveSession.objects.get(user=self.user).session_key,
            session_key_b,
        )