from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from settings.models import UserPreferences


class SystemDateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="user1", password="pass123")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa")
        self.vista = Vista.objects.get_or_create(nombre="Listado de Propiedades")[0]
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
        )

    def test_login_sets_fecha_sistema_and_session(self):
        response = self.client.post(
            reverse("login"),
            {"username": "user1", "password": "pass123"},
            follow=False,
        )
        self.assertEqual(response.status_code, 302)

        prefs = UserPreferences.objects.get(user=self.user)
        self.assertEqual(prefs.fecha_sistema, timezone.localdate())
        self.assertEqual(self.client.session.get("fecha_sistema"), prefs.fecha_sistema.isoformat())

    def test_topbar_renders_fecha_sistema(self):
        prefs = UserPreferences.objects.get(user=self.user)
        prefs.fecha_sistema = timezone.localdate()
        prefs.save(update_fields=["fecha_sistema"])
        self.client.force_login(self.user)

        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session["empresa_codigo"] = self.empresa.codigo
        session["empresa_nombre"] = f"{self.empresa.codigo} - {self.empresa.descripcion}"
        session.save()

        response = self.client.get("/", follow=False)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, prefs.fecha_sistema.isoformat())
