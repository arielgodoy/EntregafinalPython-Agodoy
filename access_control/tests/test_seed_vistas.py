from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth.models import User

from access_control.models import Empresa, Permiso, Vista


class SeedVistasTests(TestCase):
    def test_seed_vistas_command_creates_required_vista(self):
        # Asegurar estado clean
        Vista.objects.filter(nombre="Settings - Configuracion de Empresa").delete()
        call_command("seed_vistas")
        self.assertTrue(Vista.objects.filter(nombre="Settings - Configuracion de Empresa").exists())

    def test_seed_vistas_creates_api_catalog_entries_without_permissions(self):
        call_command("seed_vistas")

        self.assertEqual(Vista.objects.filter(nombre="API - Acceso").count(), 1)
        self.assertEqual(Vista.objects.filter(nombre="API - Maestros Locales").count(), 1)
        self.assertEqual(
            Vista.objects.get(nombre="API - Acceso").descripcion,
            "Acceso a la API protegido por ICMEAS",
        )
        self.assertEqual(
            Vista.objects.get(nombre="API - Maestros Locales").descripcion,
            "Acceso API al maestro de locales",
        )
        self.assertEqual(Permiso.objects.count(), 0)

    def test_seed_vistas_is_idempotent_and_preserves_existing_permissions(self):
        call_command("seed_vistas")
        user = User.objects.create_user(username="seed-user", password="password")
        empresa = Empresa.objects.create(codigo="00", descripcion="Empresa")
        vista = Vista.objects.get(nombre="API - Acceso")
        permiso = Permiso.objects.create(
            usuario=user,
            empresa=empresa,
            vista=vista,
            ingresar=True,
            crear=False,
            modificar=True,
            eliminar=False,
            autorizar=False,
            supervisor=True,
        )

        call_command("seed_vistas")

        self.assertEqual(Vista.objects.filter(nombre="API - Acceso").count(), 1)
        self.assertEqual(Vista.objects.filter(nombre="API - Maestros Locales").count(), 1)
        permiso.refresh_from_db()
        self.assertEqual(Permiso.objects.count(), 1)
        self.assertTrue(permiso.ingresar)
        self.assertTrue(permiso.modificar)
        self.assertTrue(permiso.supervisor)
