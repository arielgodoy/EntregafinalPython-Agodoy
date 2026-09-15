from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista

from proveedores.forms import ProveedorForm
from proveedores.models import Proveedor


VISTA = "Maestros - Proveedores"


class ProveedorCrudTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="proveedor-user", password="pass")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa uno")
        self.otra_empresa = Empresa.objects.create(codigo="02", descripcion="Empresa dos")
        self.vista = Vista.objects.create(
            nombre=VISTA,
            route_name="proveedores:listado",
        )
        self.client.login(username="proveedor-user", password="pass")
        self.activate_company(self.empresa)

    def activate_company(self, empresa):
        session = self.client.session
        session["empresa_id"] = empresa.id
        session.save()

    def grant(self, **flags):
        defaults = {
            "ver": False,
            "ingresar": False,
            "crear": False,
            "modificar": False,
            "eliminar": False,
            "autorizar": False,
            "supervisor": False,
        }
        defaults.update(flags)
        return Permiso.objects.update_or_create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            defaults=defaults,
        )[0]

    def test_ingresar_allows_list_and_missing_ingresar_returns_403(self):
        self.grant(ingresar=True)
        response = self.client.get(reverse("proveedores:listado"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>Proveedores | Operational Apps</title>", html=False)

        self.grant(ingresar=False)
        response = self.client.get(reverse("proveedores:listado"))
        self.assertEqual(response.status_code, 403)

    def test_create_requires_crear_and_creates_active_provider(self):
        self.grant(crear=True)
        response = self.client.post(
            reverse("proveedores:crear"),
            {"nombre": "Proveedor creado", "rut": "12.345.678-5"},
        )
        self.assertEqual(response.status_code, 302)
        proveedor = Proveedor.objects.get(nombre="Proveedor creado")
        self.assertTrue(proveedor.activo)

        self.grant(crear=False)
        response = self.client.post(reverse("proveedores:crear"), {"nombre": "No permitido"})
        self.assertEqual(response.status_code, 403)

    def test_edit_requires_modificar_and_does_not_change_active_state(self):
        proveedor = Proveedor.objects.create(nombre="Proveedor original")
        self.grant(modificar=True)
        response = self.client.post(
            reverse("proveedores:editar", args=[proveedor.pk]),
            {"nombre": "Proveedor editado"},
        )
        self.assertEqual(response.status_code, 302)
        proveedor.refresh_from_db()
        self.assertEqual(proveedor.nombre, "Proveedor editado")
        self.assertTrue(proveedor.activo)

        self.grant(modificar=False)
        response = self.client.post(
            reverse("proveedores:editar", args=[proveedor.pk]),
            {"nombre": "No permitido"},
        )
        self.assertEqual(response.status_code, 403)

    def test_eliminar_inactivates_without_deleting_or_releasing_rut(self):
        proveedor = Proveedor.objects.create(nombre="Proveedor activo", rut="12.345.678-5")
        self.grant(eliminar=True)
        response = self.client.post(reverse("proveedores:inactivar", args=[proveedor.pk]))
        self.assertEqual(response.status_code, 302)
        proveedor.refresh_from_db()
        self.assertFalse(proveedor.activo)
        self.assertTrue(Proveedor.objects.filter(pk=proveedor.pk).exists())
        self.assertEqual(Proveedor.objects.filter(rut="12345678-5").count(), 1)

    def test_reactivar_requires_modificar(self):
        proveedor = Proveedor.objects.create(nombre="Proveedor inactivo", activo=False)
        self.grant(modificar=True)
        response = self.client.post(reverse("proveedores:reactivar", args=[proveedor.pk]))
        self.assertEqual(response.status_code, 302)
        proveedor.refresh_from_db()
        self.assertTrue(proveedor.activo)

        proveedor.activo = False
        proveedor.save()
        self.grant(modificar=False)
        response = self.client.post(reverse("proveedores:reactivar", args=[proveedor.pk]))
        self.assertEqual(response.status_code, 403)

    def test_list_is_global_and_includes_active_and_inactive(self):
        Proveedor.objects.create(nombre="Proveedor activo")
        Proveedor.objects.create(nombre="Proveedor inactivo", activo=False)
        Proveedor.objects.create(nombre="Proveedor otra empresa")
        self.grant(ingresar=True)

        response = self.client.get(reverse("proveedores:listado"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Proveedor activo")
        self.assertContains(response, "Proveedor inactivo")
        self.assertContains(response, "Proveedor otra empresa")

    def test_form_rejects_invalid_duplicate_rut_and_invalid_email(self):
        Proveedor.objects.create(nombre="Proveedor existente", rut="12.345.678-5")

        invalid_rut = ProveedorForm(data={"nombre": "Inválido", "rut": "12.345.678-9"})
        self.assertFalse(invalid_rut.is_valid())
        self.assertIn("rut", invalid_rut.errors)

        duplicate_rut = ProveedorForm(data={"nombre": "Duplicado", "rut": "12345678-5"})
        self.assertFalse(duplicate_rut.is_valid())
        self.assertIn("rut", duplicate_rut.errors)

        invalid_email = ProveedorForm(data={"nombre": "Email inválido", "email1": "no-es-email"})
        self.assertFalse(invalid_email.is_valid())
        self.assertIn("email1", invalid_email.errors)

    def test_seed_is_idempotent_and_does_not_grant_permissions(self):
        first_output = StringIO()
        call_command("seed_proveedores", stdout=first_output)
        second_output = StringIO()
        call_command("seed_proveedores", stdout=second_output)

        self.assertEqual(Vista.objects.filter(nombre=VISTA).count(), 1)
        vista = Vista.objects.get(nombre=VISTA)
        self.assertEqual(vista.route_name, "proveedores:listado")
        self.assertFalse(Permiso.objects.filter(vista=vista).exists())
