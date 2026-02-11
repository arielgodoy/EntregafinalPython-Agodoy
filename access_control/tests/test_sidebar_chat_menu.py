from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista


class SidebarChatMenuTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="pass")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self.vista_dashboard = Vista.objects.create(nombre="Control Operacional Dashboard")
        self.vista_chat = Vista.objects.create(nombre="chat.inbox")

    def _login_with_empresa(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    def _grant_dashboard_permiso(self):
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_dashboard,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

    def test_sidebar_muestra_chat_con_permiso(self):
        self._login_with_empresa()
        self._grant_dashboard_permiso()
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_chat,
            ingresar=True,
            crear=False,
            modificar=False,
            eliminar=False,
            autorizar=False,
            supervisor=False,
        )

        response = self.client.get(reverse("control_operacional:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-key="menu.chat"')
        self.assertContains(response, reverse("chat_inbox"))

    def test_sidebar_oculta_chat_sin_permiso(self):
        self._login_with_empresa()
        self._grant_dashboard_permiso()

        response = self.client.get(reverse("control_operacional:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'data-key="menu.chat"')
