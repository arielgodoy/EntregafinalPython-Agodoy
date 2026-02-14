from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista


class TestNotificacionesPermissions(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="user_perm",
            email="user_perm@example.com",
            password="pass12345",
        )
        self.empresa_a = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        self.vista = Vista.objects.create(
            nombre="Notificaciones - Mis Notificaciones",
            descripcion="Vista de notificaciones",
        )

    def _login_with_empresa(self, empresa):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = empresa.id
        session["empresa_codigo"] = empresa.codigo
        session["empresa_nombre"] = empresa.descripcion
        session.save()

    def test_requires_ingresar_permission(self):
        self._login_with_empresa(self.empresa_a)
        response = self.client.get(reverse("notificaciones:mis_notificaciones"))
        self.assertEqual(response.status_code, 403)

    def test_allows_with_ingresar_permission(self):
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa_a,
            vista=self.vista,
            ingresar=True,
        )
        self._login_with_empresa(self.empresa_a)
        response = self.client.get(reverse("notificaciones:mis_notificaciones"))
        self.assertEqual(response.status_code, 200)

    def test_denies_cross_empresa_access(self):
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa_a,
            vista=self.vista,
            ingresar=True,
        )
        self._login_with_empresa(self.empresa_b)
        response = self.client.get(reverse("notificaciones:mis_notificaciones"))
        self.assertEqual(response.status_code, 403)
