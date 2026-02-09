from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from acounts.models import CompanyConfig
from access_control.models import Empresa, Permiso, Vista


class CompanyConfigViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='testpass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Test Empresa')
        self.client.force_login(self.user)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def test_denied_without_permission(self):
        vista = Vista.objects.create(nombre='company_config')
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            ingresar=False,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )
        response = self.client.get(reverse('access_control:company_config_list'))
        self.assertEqual(response.status_code, 403)

    def test_list_ok_with_permission(self):
        vista = Vista.objects.create(nombre='company_config')
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            ingresar=False,
            crear=False,
            modificar=True,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )
        response = self.client.get(reverse('access_control:company_config_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Company Settings')

    def test_get_or_create_company_config(self):
        vista = Vista.objects.create(nombre='company_config')
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            ingresar=False,
            crear=False,
            modificar=True,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )
        url = reverse('access_control:company_config_edit', args=[self.empresa.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(CompanyConfig.objects.filter(empresa=self.empresa).exists())
