from django.test import TestCase
from django.core.management import call_command
from access_control.models import Vista


class SeedVistasTests(TestCase):
    def test_seed_vistas_command_creates_required_vista(self):
        # Asegurar estado clean
        Vista.objects.filter(nombre="Settings - Configuracion de Empresa").delete()
        call_command("seed_vistas")
        self.assertTrue(Vista.objects.filter(nombre="Settings - Configuracion de Empresa").exists())
