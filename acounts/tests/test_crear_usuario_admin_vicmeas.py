from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista


class CrearUsuarioAdminVICMEASTests(TestCase):
    vista_nombre = "Control de Acceso - Maestro Usuarios"

    def setUp(self):
        self.user = User.objects.create_superuser(
            username="admin-creator",
            password="pass123",
        )
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa Test")
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    def _url(self):
        return reverse("crear_usuario_admin")

    def test_missing_view_and_permission_create_empty_permission_then_return_403(self):
        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 403)
        vista = Vista.objects.get(nombre=self.vista_nombre)
        permiso = Permiso.objects.get(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
        )
        for field_name in ("ver", "ingresar", "crear", "modificar", "eliminar", "autorizar", "supervisor"):
            self.assertFalse(getattr(permiso, field_name))
        self.assertFalse(Permiso.objects.exclude(pk=permiso.pk).filter(usuario=self.user).exists())

    def test_create_permission_allows_admin_form(self):
        vista = Vista.objects.create(nombre=self.vista_nombre)
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
            crear=True,
        )

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "crear_usuario_admin.html")

    def test_permission_is_company_scoped(self):
        other_empresa = Empresa.objects.create(codigo="02", descripcion="Otra Empresa")
        vista = Vista.objects.create(nombre=self.vista_nombre)
        Permiso.objects.create(
            usuario=self.user,
            empresa=other_empresa,
            vista=vista,
            crear=True,
        )

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 403)
        active_permission = Permiso.objects.get(
            usuario=self.user,
            empresa=self.empresa,
            vista=vista,
        )
        self.assertFalse(active_permission.crear)