from django.contrib.auth import get_user_model
from django.test import TestCase

from access_control.models import Empresa
from notificaciones.models import Notification


class TestListadoNotificaciones(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="user_a",
            email="user_a@example.com",
            password="pass12345",
        )
        self.other_user = user_model.objects.create_user(
            username="user_b",
            email="user_b@example.com",
            password="pass12345",
        )

    def _login_with_empresa(self, empresa):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = empresa.id
        session["empresa_codigo"] = empresa.codigo
        session["empresa_nombre"] = empresa.descripcion
        session.save()

    def test_listado_scoped_por_usuario_y_empresa(self):
        Notification.objects.create(
            destinatario=self.user,
            empresa=self.empresa_a,
            tipo=Notification.Tipo.ALERT,
            titulo="Notif A",
            cuerpo="",
        )
        Notification.objects.create(
            destinatario=self.user,
            empresa=self.empresa_b,
            tipo=Notification.Tipo.ALERT,
            titulo="Notif B",
            cuerpo="",
        )
        Notification.objects.create(
            destinatario=self.user,
            empresa=None,
            tipo=Notification.Tipo.SYSTEM,
            titulo="Notif Global",
            cuerpo="",
        )
        Notification.objects.create(
            destinatario=self.other_user,
            empresa=self.empresa_a,
            tipo=Notification.Tipo.ALERT,
            titulo="Notif Otro",
            cuerpo="",
        )

        self._login_with_empresa(self.empresa_a)
        response = self.client.get("/notificaciones/mis-notificaciones/")

        self.assertContains(response, "Notif A")
        self.assertContains(response, "Notif Global")
        self.assertNotContains(response, "Notif B")
        self.assertNotContains(response, "Notif Otro")

    def test_ver_notificacion_marca_leida_y_redirige(self):
        notif = Notification.objects.create(
            destinatario=self.user,
            empresa=self.empresa_a,
            tipo=Notification.Tipo.MESSAGE,
            titulo="Notif URL",
            cuerpo="",
            url="/chat/",
        )
        self._login_with_empresa(self.empresa_a)
        response = self.client.get(f"/notificaciones/mis-notificaciones/{notif.id}/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/chat/")

        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

    def test_filtros_tipo_y_estado(self):
        Notification.objects.create(
            destinatario=self.user,
            empresa=self.empresa_a,
            tipo=Notification.Tipo.MESSAGE,
            titulo="Unread Message",
            cuerpo="",
            is_read=False,
        )
        Notification.objects.create(
            destinatario=self.user,
            empresa=self.empresa_a,
            tipo=Notification.Tipo.MESSAGE,
            titulo="Read Message",
            cuerpo="",
            is_read=True,
        )
        Notification.objects.create(
            destinatario=self.user,
            empresa=self.empresa_a,
            tipo=Notification.Tipo.ALERT,
            titulo="Unread Alert",
            cuerpo="",
            is_read=False,
        )

        self._login_with_empresa(self.empresa_a)
        response = self.client.get(
            "/notificaciones/mis-notificaciones/?tipo=message&estado=unread"
        )

        self.assertContains(response, "Unread Message")
        self.assertNotContains(response, "Read Message")
        self.assertNotContains(response, "Unread Alert")
