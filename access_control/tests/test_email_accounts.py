from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from acounts.models import EmailAccount
from access_control.models import Empresa, Permiso, Vista


class EmailAccountViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='testpass')
        self.empresa = Empresa.objects.create(codigo='01', descripcion='Test Empresa')
        self.client.force_login(self.user)
        session = self.client.session
        session['empresa_id'] = self.empresa.id
        session.save()

    def test_missing_vista_returns_400(self):
        response = self.client.get(reverse('access_control:email_accounts_list'))
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'NO ENCONTRADO: Vista email_accounts', status_code=400)

    def test_list_ok_with_permiso_ingresar(self):
        vista = Vista.objects.create(nombre='email_accounts')
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )
        EmailAccount.objects.create(
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
        response = self.client.get(reverse('access_control:email_accounts_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cuenta Test')
