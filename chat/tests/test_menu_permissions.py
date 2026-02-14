from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista


class TestChatMenuPermissions(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="user_a",
            email="user_a@example.com",
            password="pass12345",
        )
        self.vista = Vista.objects.create(nombre="Chat - Bandeja de entrada")
        self.vista_notificaciones, _ = Vista.objects.get_or_create(
            nombre="Notificaciones - Mis Notificaciones",
            defaults={"descripcion": ""},
        )

    def _login_with_empresa(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session["empresa_codigo"] = self.empresa.codigo
        session["empresa_nombre"] = self.empresa.descripcion
        session.save()

    def test_menu_visible_with_permiso(self):
        Permiso.objects.update_or_create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_notificaciones,
            defaults={"ingresar": True},
        )
        Permiso.objects.update_or_create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            defaults={"ingresar": True},
        )
        self._login_with_empresa()
        response = self.client.get(reverse("notificaciones:mis_notificaciones"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-key=\"menu.chat\"")
        self.assertContains(response, reverse("chat_inbox"))

    def test_menu_hidden_without_permiso(self):
        Permiso.objects.update_or_create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista_notificaciones,
            defaults={"ingresar": True},
        )
        self._login_with_empresa()
        response = self.client.get(reverse("notificaciones:mis_notificaciones"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-key=\"menu.chat\"")
