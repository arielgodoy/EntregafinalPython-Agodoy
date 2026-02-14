from django.test import TestCase, Client
from django.contrib.auth.models import User

from access_control.models import Empresa, Permiso, Vista
from notificaciones.models import Notification


class TestAlertaPersonalizada(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(username="staff", password="pass123", is_staff=True)
        self.normal_user = User.objects.create_user(username="normal", password="pass123", is_staff=False)
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 1")
        self.vista = Vista.objects.create(
            nombre="Alerta Personalizada",
            descripcion="Vista de alerta personalizada",
        )

    def test_no_staff_get_y_post_403(self):
        self.client.login(username="normal", password="pass123")
        response_get = self.client.get("/notificaciones/alerta-personalizada/")
        self.assertEqual(response_get.status_code, 403)

        response_post = self.client.post("/notificaciones/alerta-personalizada/", {
            "empresa_objetivo_id": self.empresa.id,
            "destinatario_id": self.normal_user.id,
            "tipo": "ALERT",
            "titulo": "Titulo",
            "cuerpo": "Cuerpo",
        })
        self.assertEqual(response_post.status_code, 403)

    def test_staff_get_sin_usuarios_con_permiso_muestra_placeholder(self):
        self.client.login(username="staff", password="pass123")
        response = self.client.get(f"/notificaciones/alerta-personalizada/?empresa={self.empresa.id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("destinatarios", response.context)
        self.assertEqual(len(response.context["destinatarios"]), 0)
        content = response.content.decode("utf-8")
        self.assertIn("notifications.custom.recipient.no_users", content)

    def test_post_sin_permiso_sin_force_membership_error(self):
        self.client.login(username="staff", password="pass123")
        response = self.client.post("/notificaciones/alerta-personalizada/", {
            "empresa_objetivo_id": self.empresa.id,
            "destinatario_id": self.normal_user.id,
            "tipo": "ALERT",
            "titulo": "Titulo",
            "cuerpo": "Cuerpo",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["error_key"], "notifications.custom.error.no_permissions")
        self.assertEqual(Notification.objects.count(), 0)

    def test_post_sin_permiso_con_force_membership_crea_permiso_y_notificacion(self):
        self.client.login(username="staff", password="pass123")
        response = self.client.post("/notificaciones/alerta-personalizada/", {
            "empresa_objetivo_id": self.empresa.id,
            "destinatario_id": self.normal_user.id,
            "tipo": "ALERT",
            "titulo": "Titulo",
            "cuerpo": "Cuerpo",
            "force_membership": "on",
        })
        self.assertEqual(response.status_code, 200)
        permisos = Permiso.objects.filter(usuario=self.normal_user, empresa=self.empresa)
        self.assertGreater(permisos.count(), 0)
        permiso = permisos.first()
        self.assertTrue(permiso.ingresar)
        self.assertFalse(permiso.crear)
        self.assertFalse(permiso.modificar)
        self.assertFalse(permiso.eliminar)
        self.assertFalse(permiso.autorizar)
        self.assertFalse(permiso.supervisor)

        notification = Notification.objects.filter(destinatario=self.normal_user, empresa=self.empresa).first()
        self.assertIsNotNone(notification)
        self.assertEqual(notification.tipo, "ALERT")
        self.assertEqual(notification.titulo, "Titulo")
        self.assertEqual(notification.cuerpo, "Cuerpo")

    def test_post_con_permiso_crea_notificacion(self):
        Permiso.objects.create(
            usuario=self.normal_user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
        )
        self.client.login(username="staff", password="pass123")
        response = self.client.post("/notificaciones/alerta-personalizada/", {
            "empresa_objetivo_id": self.empresa.id,
            "destinatario_id": self.normal_user.id,
            "tipo": "MESSAGE",
            "titulo": "Titulo",
            "cuerpo": "Cuerpo",
        })
        self.assertEqual(response.status_code, 200)
        notification = Notification.objects.filter(destinatario=self.normal_user, empresa=self.empresa).first()
        self.assertIsNotNone(notification)
        self.assertEqual(notification.tipo, "MESSAGE")
