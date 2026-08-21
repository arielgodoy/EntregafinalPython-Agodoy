from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa
from access_control.services.empresa_activa import set_empresa_activa_en_sesion


class DashboardGeneralTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='dashboard-user',
            password='pass1234',
        )
        self.empresa = Empresa.objects.create(
            codigo='01',
            descripcion='Empresa 01',
        )

    def _login_with_active_empresa(self):
        self.client.force_login(self.user)
        session = self.client.session
        set_empresa_activa_en_sesion(type('Request', (), {'session': session})(), self.empresa)
        session.save()

    def test_usuario_autenticado_con_empresa_ve_dashboard(self):
        self._login_with_active_empresa()

        response = self.client.get(reverse('dashboard:dashboard_general'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dashboard General')

    def test_usuario_autenticado_sin_empresa_va_al_selector(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('dashboard:dashboard_general'))

        self.assertRedirects(response, reverse('access_control:seleccionar_empresa'))

    def test_usuario_anonimo_va_al_login(self):
        response = self.client.get(reverse('dashboard:dashboard_general'))

        self.assertRedirects(
            response,
            f'{reverse("login")}?next={reverse("dashboard:dashboard_general")}',
        )

    def test_raiz_es_dashboard(self):
        self._login_with_active_empresa()

        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dashboard General')
