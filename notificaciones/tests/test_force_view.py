from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from notificaciones.models import Notification


class TestForzarNotificaciones(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="user_a",
            email="user_a@example.com",
            password="pass12345",
        )
        self.staff_user = user_model.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="pass12345",
            is_staff=True,
        )
        self.vista = Vista.objects.create(nombre="notificaciones.mis_notificaciones", descripcion="Vista de notificaciones")

    def _login_with_empresa(self, user, empresa):
        self.client.force_login(user)
        session = self.client.session
        session["empresa_id"] = empresa.id
        session["empresa_codigo"] = empresa.codigo
        session["empresa_nombre"] = empresa.descripcion
        session.save()

    def test_non_staff_get_returns_403(self):
        self._login_with_empresa(self.user, self.empresa)
        response = self.client.get(reverse("notificaciones:forzar_notificaciones"))
        self.assertEqual(response.status_code, 403)

    def test_staff_without_empresa_redirects(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("notificaciones:forzar_notificaciones"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-key=\"notifications.force.warning.select_company\"")

    def test_staff_post_creates_notifications(self):
        Permiso.objects.create(
            usuario=self.staff_user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
        )
        self._login_with_empresa(self.staff_user, self.empresa)

        response = self.client.post(
            reverse("notificaciones:forzar_notificaciones"),
            {
                "destinatario_id": self.staff_user.id,
                "cantidad": 2,
                "force_membership": "on",
            },
        )
        self.assertEqual(response.status_code, 302)

        count = Notification.objects.filter(destinatario=self.staff_user, empresa=self.empresa).count()
        self.assertEqual(count, 6)

    def test_staff_post_without_membership_force_false(self):
        self._login_with_empresa(self.staff_user, self.empresa)

        response = self.client.post(
            reverse("notificaciones:forzar_notificaciones"),
            {
                "destinatario_id": self.user.id,
                "cantidad": 2,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-key=\"notifications.force.error.no_permissions_in_target_company\"")
        count = Notification.objects.filter(destinatario=self.user, empresa=self.empresa).count()
        self.assertEqual(count, 0)
