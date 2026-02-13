from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from settings.models import UserPreferences


class SetFechaSistemaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user2", password="pass123")

    def test_post_sin_login_redirige(self):
        response = self.client.post(
            reverse("set_fecha_sistema"),
            {"fecha_sistema": "2026-02-13"},
            follow=False,
        )
        self.assertIn(response.status_code, [302, 403])

    def test_post_fecha_valida_actualiza_prefs_y_sesion(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("set_fecha_sistema"),
            {"fecha_sistema": "2026-02-13"},
            follow=False,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("fecha_sistema"), "2026-02-13")

        prefs = UserPreferences.objects.get(user=self.user)
        self.assertEqual(prefs.fecha_sistema, date(2026, 2, 13))
        self.assertEqual(self.client.session.get("fecha_sistema"), "2026-02-13")

    def test_post_fecha_invalida_rechaza(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("set_fecha_sistema"),
            {"fecha_sistema": "2026-13-40"},
            follow=False,
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data.get("ok"))

    def test_post_formato_invalido_rechaza(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("set_fecha_sistema"),
            {"fecha_sistema": "13-02-2026"},
            follow=False,
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data.get("ok"))
