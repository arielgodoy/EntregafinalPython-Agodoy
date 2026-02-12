from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa
from notificaciones.models import Notification


class TestTopbarPagination(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa A")
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
        session.save()

    def test_alert_pagination(self):
        for index in range(12):
            Notification.objects.create(
                destinatario=self.user,
                empresa=self.empresa,
                tipo=Notification.Tipo.ALERT,
                titulo=f"A{index}",
            )

        self._login_with_empresa(self.empresa)
        url = reverse("notificaciones:topbar")

        response = self.client.get(url + "?type=ALERT&page=1&page_size=10")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload.get("items", [])), 10)
        self.assertTrue(payload.get("has_next"))

        response_page2 = self.client.get(url + "?type=ALERT&page=2&page_size=10")
        self.assertEqual(response_page2.status_code, 200)
        payload2 = response_page2.json()
        self.assertEqual(len(payload2.get("items", [])), 2)
        self.assertFalse(payload2.get("has_next"))

    def test_all_counts_and_mix(self):
        Notification.objects.create(
            destinatario=self.user,
            empresa=self.empresa,
            tipo=Notification.Tipo.MESSAGE,
            titulo="M1",
        )
        Notification.objects.create(
            destinatario=self.user,
            empresa=self.empresa,
            tipo=Notification.Tipo.ALERT,
            titulo="A1",
        )
        Notification.objects.create(
            destinatario=self.user,
            empresa=None,
            tipo=Notification.Tipo.SYSTEM,
            titulo="S1",
        )
        Notification.objects.create(
            destinatario=self.other_user,
            empresa=self.empresa,
            tipo=Notification.Tipo.SYSTEM,
            titulo="Other",
        )

        self._login_with_empresa(self.empresa)
        response = self.client.get(reverse("notificaciones:topbar") + "?type=ALL&page=1&page_size=10")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("unread_all"), 3)
        self.assertEqual(payload.get("unread_notification_messages"), 1)
        self.assertEqual(payload.get("unread_alerts"), 1)
        self.assertEqual(payload.get("unread_system"), 1)
        self.assertEqual(len(payload.get("items", [])), 3)

    def test_invalid_type_returns_400(self):
        self._login_with_empresa(self.empresa)
        response = self.client.get(reverse("notificaciones:topbar") + "?type=INVALID")
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("error", payload)
