from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.models import AccessRequest, Empresa, Permiso, Vista
from notificaciones.models import Notification


class TestNotificationsGrantAccessButton(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="user_a",
            email="user_a@example.com",
            password="pass12345",
        )
        self.access_request = AccessRequest.objects.create(
            solicitante=self.user,
            empresa=self.empresa,
            vista_nombre="X",
            motivo="Test",
        )
        self.vista = Vista.objects.create(
            nombre="notificaciones.mis_notificaciones",
            descripcion="Vista de notificaciones",
        )
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
        )
        Notification.objects.create(
            empresa=self.empresa,
            destinatario=self.user,
            tipo=Notification.Tipo.MESSAGE,
            titulo="Demo message",
            cuerpo="Body text",
        )
        self.access_request_url = reverse(
            "access_control:grant_access_request",
            args=[self.access_request.id],
        )
        Notification.objects.create(
            empresa=self.empresa,
            destinatario=self.user,
            tipo=Notification.Tipo.SYSTEM,
            titulo="Solicitud de acceso",
            cuerpo=(
                "Usuario: user_a\n"
                "Empresa: 01 - Empresa A\n"
                "Vista: X\n"
                "Motivo: Test\n"
                f"Otorgar acceso: {self.access_request_url}"
            ),
            url=self.access_request_url,
        )

    def _login_with_empresa(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session["empresa_codigo"] = self.empresa.codigo
        session["empresa_nombre"] = self.empresa.descripcion
        session.save()

    def test_grant_access_button_only_for_access_requests(self):
        self._login_with_empresa()
        response = self.client.get(reverse("notificaciones:mis_notificaciones"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertEqual(content.count(self.access_request_url), 1)
        self.assertGreaterEqual(content.count('data-key="notifications.open"'), 1)
