from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista


class TogglePermisoTests(TestCase):
    vista_admin_nombre = "Control de Acceso - Maestro Permisos"

    def setUp(self):
        self.actor = User.objects.create_user(username="actor", password="pass")
        self.target = User.objects.create_user(username="target", password="pass")
        self.empresa_a = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        self.vista_admin = Vista.objects.create(nombre=self.vista_admin_nombre)
        self.vista_target = Vista.objects.create(nombre="Vista objetivo")
        self.client.force_login(self.actor)
        session = self.client.session
        session["empresa_id"] = self.empresa_a.id
        session.save()

    def _url(self):
        return reverse("access_control:toggle_permiso")

    def _post(self, permiso, field="modificar", value="true"):
        return self.client.post(
            self._url(),
            {"permiso_id": permiso.id, "permiso_field": field, "value": value},
            HTTP_ACCEPT="application/json",
        )

    def _grant_admin(self, **flags):
        defaults = {"modificar": True}
        defaults.update(flags)
        return Permiso.objects.create(
            usuario=self.actor,
            empresa=self.empresa_a,
            vista=self.vista_admin,
            **defaults,
        )

    def test_without_administrative_permission_returns_403_without_changing_target(self):
        target_permission = Permiso.objects.create(
            usuario=self.target,
            empresa=self.empresa_a,
            vista=self.vista_target,
            ingresar=True,
        )

        response = self._post(target_permission, value="false")

        self.assertEqual(response.status_code, 403)
        target_permission.refresh_from_db()
        self.assertTrue(target_permission.ingresar)

    def test_cannot_modify_permission_from_another_company(self):
        self._grant_admin()
        target_permission = Permiso.objects.create(
            usuario=self.target,
            empresa=self.empresa_b,
            vista=self.vista_target,
            supervisor=False,
        )

        response = self._post(target_permission, field="supervisor")

        self.assertEqual(response.status_code, 403)
        target_permission.refresh_from_db()
        self.assertFalse(target_permission.supervisor)

    def test_can_modify_active_company_permission_and_preserves_other_flags(self):
        self._grant_admin()
        target_permission = Permiso.objects.create(
            usuario=self.target,
            empresa=self.empresa_a,
            vista=self.vista_target,
            ingresar=True,
            crear=True,
            modificar=False,
            eliminar=True,
            autorizar=True,
            supervisor=True,
        )

        response = self._post(target_permission, field="modificar")

        self.assertEqual(response.status_code, 200)
        target_permission.refresh_from_db()
        self.assertTrue(target_permission.ingresar)
        self.assertTrue(target_permission.crear)
        self.assertTrue(target_permission.modificar)
        self.assertTrue(target_permission.eliminar)
        self.assertTrue(target_permission.autorizar)
        self.assertTrue(target_permission.supervisor)

    def test_invalid_field_is_rejected_without_changing_permission(self):
        self._grant_admin()
        target_permission = Permiso.objects.create(
            usuario=self.target,
            empresa=self.empresa_a,
            vista=self.vista_target,
            ingresar=True,
        )

        response = self._post(target_permission, field="invalid")

        self.assertEqual(response.status_code, 400)
        target_permission.refresh_from_db()
        self.assertTrue(target_permission.ingresar)

    def test_administratively_authorized_actor_can_change_supervisor(self):
        self._grant_admin()
        target_permission = Permiso.objects.create(
            usuario=self.target,
            empresa=self.empresa_a,
            vista=self.vista_target,
            supervisor=False,
        )

        response = self._post(target_permission, field="supervisor")

        self.assertEqual(response.status_code, 200)
        target_permission.refresh_from_db()
        self.assertTrue(target_permission.supervisor)
