from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from notificaciones.models import Notification


class TestNotificationsTemplateNoDemoText(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="user_a",
            email="user_a@example.com",
            password="pass12345",
        )
        Notification.objects.create(
            empresa=self.empresa,
            destinatario=self.user,
            tipo=Notification.Tipo.SYSTEM,
            titulo="System notice",
            cuerpo="Body text",
        )

    def _login_with_empresa(self):
        self.client.force_login(self.user)
        vista, _ = Vista.objects.get_or_create(
            nombre="Notificaciones - Mis Notificaciones",
            defaults={"descripcion": "Vista de notificaciones"},
        )
        Permiso.objects.update_or_create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            defaults={"ingresar": True},
        )
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session["empresa_codigo"] = self.empresa.codigo
        session["empresa_nombre"] = self.empresa.descripcion
        session.save()

    def test_no_demo_empty_text(self):
        self._login_with_empresa()
        response = self.client.get(reverse("notificaciones:mis_notificaciones"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Hey! You have no any notifications")
        self.assertNotContains(response, "no any notifications")
