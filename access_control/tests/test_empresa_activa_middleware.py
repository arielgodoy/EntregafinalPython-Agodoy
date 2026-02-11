from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from acounts.services.tokens import generate_token


class EmpresaActivaMiddlewareTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="pass")

    def test_middleware_usuario_autenticado_sin_empresa_redirige_a_selector(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("configurar_email"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("access_control:seleccionar_empresa"))

    def test_middleware_no_interfiere_en_login_y_activacion(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)

        inactive_user = User.objects.create(username="invited@test.local", email="invited@test.local", is_active=False)
        inactive_user.set_unusable_password()
        inactive_user.save(update_fields=["password"])

        token = generate_token(inactive_user, ttl_seconds=3600)
        response = self.client.get(reverse("acounts_activation:activate", args=[token]))
        if response.status_code == 302:
            self.assertNotEqual(response.url, reverse("access_control:seleccionar_empresa"))
