from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from notificaciones.models import Notification


class TopbarNotificationsTests(TestCase):
    def setUp(self):
        self.empresa_a = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        self.user_a = User.objects.create_user(username="user_a", password="pass")
        self.user_b = User.objects.create_user(username="user_b", password="pass")

    def _login(self, user, empresa_id):
        self.client.force_login(user)
        vista, _ = Vista.objects.get_or_create(
            nombre="notificaciones.mis_notificaciones",
            defaults={"descripcion": "Vista de notificaciones"},
        )
        Permiso.objects.update_or_create(
            usuario=user,
            empresa_id=empresa_id,
            vista=vista,
            defaults={"ingresar": True},
        )
        session = self.client.session
        session["empresa_id"] = empresa_id
        session.save()

    def test_topbar_returns_only_user_notifications(self):
        Notification.objects.create(
            destinatario=self.user_a,
            empresa=self.empresa_a,
            tipo=Notification.Tipo.SYSTEM,
            titulo="A1",
        )
        Notification.objects.create(
            destinatario=self.user_a,
            empresa=self.empresa_a,
            tipo=Notification.Tipo.ALERT,
            titulo="A2",
        )
        Notification.objects.create(
            destinatario=self.user_b,
            empresa=self.empresa_a,
            tipo=Notification.Tipo.SYSTEM,
            titulo="B1",
        )

        self._login(self.user_a, self.empresa_a.id)
        response = self.client.get(reverse("notificaciones:topbar"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        titles = [item["titulo"] for item in payload["items"]]
        self.assertIn("A1", titles)
        self.assertIn("A2", titles)
        self.assertNotIn("B1", titles)

    def test_topbar_scoped_to_empresa_activa_plus_global(self):
        Notification.objects.create(
            destinatario=self.user_a,
            empresa=self.empresa_a,
            tipo=Notification.Tipo.SYSTEM,
            titulo="A1",
        )
        Notification.objects.create(
            destinatario=self.user_a,
            empresa=self.empresa_b,
            tipo=Notification.Tipo.SYSTEM,
            titulo="B1",
        )
        Notification.objects.create(
            destinatario=self.user_a,
            empresa=None,
            tipo=Notification.Tipo.ALERT,
            titulo="GLOBAL",
        )

        self._login(self.user_a, self.empresa_a.id)
        response = self.client.get(reverse("notificaciones:topbar"))
        payload = response.json()
        titles = [item["titulo"] for item in payload["items"]]
        self.assertIn("A1", titles)
        self.assertIn("GLOBAL", titles)
        self.assertNotIn("B1", titles)

    def test_mark_read_requires_owner(self):
        notification = Notification.objects.create(
            destinatario=self.user_a,
            empresa=self.empresa_a,
            tipo=Notification.Tipo.SYSTEM,
            titulo="A1",
        )

        self._login(self.user_b, self.empresa_a.id)
        response = self.client.post(reverse("notificaciones:mark_read", args=[notification.id]))
        self.assertIn(response.status_code, [403, 404])
        notification.refresh_from_db()
        self.assertFalse(notification.is_read)

    def test_mark_all_read(self):
        Notification.objects.create(
            destinatario=self.user_a,
            empresa=self.empresa_a,
            tipo=Notification.Tipo.SYSTEM,
            titulo="A1",
        )
        Notification.objects.create(
            destinatario=self.user_a,
            empresa=None,
            tipo=Notification.Tipo.ALERT,
            titulo="GLOBAL",
        )

        self._login(self.user_a, self.empresa_a.id)
        response = self.client.post(reverse("notificaciones:mark_all_read"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Notification.objects.filter(destinatario=self.user_a, is_read=True).count() >= 2)
