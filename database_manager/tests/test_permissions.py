from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista


class DatabaseManagerPermissionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='db-user', password='test-pass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Empresa test')
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def grant(self, view_name):
        vista = Vista.objects.create(nombre=view_name)
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            ingresar=True,
        )

    def test_dashboard_requires_authentication(self):
        self.client.logout()
        response = self.client.get(reverse('database_manager:dashboard'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('/acounts/login/', response.url)

    def test_dashboard_uses_icmeas(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('database_manager:dashboard'))

        self.assertEqual(response.status_code, 403)

    def test_dashboard_allows_authorized_user(self):
        self.grant('Gestión de Bases - Dashboard')
        self.client.force_login(self.user)

        response = self.client.get(reverse('database_manager:dashboard'))

        self.assertEqual(response.status_code, 200)

    def test_compare_uses_icmeas(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('database_manager:compare'))

        self.assertEqual(response.status_code, 403)
