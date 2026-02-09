from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from acounts.models import EmailAccount, SystemConfig
from access_control.models import Empresa, Permiso, Vista


class SystemEmailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='testpass', email='tester@example.com')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Test Empresa')
        self.client.force_login(self.user)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()
        self.vista = Vista.objects.create(nombre='system_config')

    def _set_permiso(self, crear=False, modificar=False):
        return Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=False,
            crear=crear,
            modificar=modificar,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

    def test_buttons_hidden_without_crear_permission(self):
        self._set_permiso(crear=False, modificar=True)
        response = self.client.get(reverse('access_control:system_config'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Probar Correo de Salida')
        self.assertNotContains(response, 'Enviar Correo de Prueba')

    def test_buttons_visible_with_crear_permission(self):
        self._set_permiso(crear=True, modificar=True)
        response = self.client.get(reverse('access_control:system_config'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Probar Correo de Salida')
        self.assertContains(response, 'Enviar Correo de Prueba')

    @patch('access_control.views.send_email_via_account')
    def test_system_email_endpoint_ok(self, send_email_via_account_mock):
        self._set_permiso(crear=True, modificar=True)
        account = EmailAccount.objects.create(
            name='Cuenta Test',
            from_email='test@example.com',
            from_name='Test',
            smtp_host='smtp.example.com',
            smtp_port=587,
            smtp_user='user',
            smtp_password='pass',
            use_tls=True,
            use_ssl=False,
            reply_to='reply@example.com',
            is_active=True,
        )
        SystemConfig.objects.create(
            is_active=True,
            default_from_email='no-reply@example.com',
            default_from_name='System',
            security_email_account=account,
        )
        response = self.client.post(reverse('access_control:system_config_send_test'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('status'), 'ok')
        send_email_via_account_mock.assert_called_once()

    def test_system_email_endpoint_missing_system_config(self):
        self._set_permiso(crear=True, modificar=True)
        response = self.client.post(reverse('access_control:system_config_send_test'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('No existe una configuración activa del sistema', response.json().get('detail'))

    def test_system_email_endpoint_missing_user_email(self):
        self._set_permiso(crear=True, modificar=True)
        self.user.email = ''
        self.user.save()
        account = EmailAccount.objects.create(
            name='Cuenta Test',
            from_email='test@example.com',
            from_name='Test',
            smtp_host='smtp.example.com',
            smtp_port=587,
            smtp_user='user',
            smtp_password='pass',
            use_tls=True,
            use_ssl=False,
            reply_to='reply@example.com',
            is_active=True,
        )
        SystemConfig.objects.create(
            is_active=True,
            default_from_email='no-reply@example.com',
            default_from_name='System',
            security_email_account=account,
        )
        response = self.client.post(reverse('access_control:system_config_send_test'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('El usuario no tiene email configurado', response.json().get('detail'))

    def test_system_email_endpoint_missing_email_account(self):
        self._set_permiso(crear=True, modificar=True)
        SystemConfig.objects.create(
            is_active=True,
            default_from_email='no-reply@example.com',
            default_from_name='System',
            security_email_account=None,
        )
        response = self.client.post(reverse('access_control:system_config_send_test'))
        self.assertEqual(response.status_code, 400)
        self.assertIn('Falta security_email_account en SystemConfig', response.json().get('detail'))
