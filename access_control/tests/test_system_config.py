from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils.translation import gettext as _

from acounts.models import SystemConfig
from access_control.forms import SystemConfigForm
from access_control.models import Empresa, Permiso, Vista


class SystemConfigFormTests(TestCase):
    def test_public_base_url_required(self):
        form = SystemConfigForm(data={
            'public_base_url': '',
            'default_from_email': '',
            'default_from_name': '',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('public_base_url', form.errors)


class SystemConfigViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='testpass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Test Empresa')
        self.client.force_login(self.user)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def test_missing_vista_returns_400(self):
        response = self.client.get(reverse('access_control:system_config'))
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, _('NO ENCONTRADO: Vista system_config'), status_code=400)

    def test_view_ok_with_permission(self):
        vista = Vista.objects.create(nombre='system_config')
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
        response = self.client.get(reverse('access_control:system_config'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(SystemConfig.objects.filter(is_active=True).exists())
