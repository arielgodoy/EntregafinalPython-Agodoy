from django.core.management import call_command
from django.test import TestCase

from access_control.models import Permiso, Vista


class DatabaseManagerSeedTests(TestCase):
    expected = {
        'Gestión de Bases - Dashboard': 'database_manager:dashboard',
        'Gestión de Bases - Comparar': 'database_manager:compare',
        'Gestión de Bases - Preflight': 'database_manager:preflight',
    }

    def test_seed_creates_catalog_views_without_permissions(self):
        call_command('seed_database_manager_views')

        self.assertEqual(
            Vista.objects.filter(nombre__in=self.expected).count(),
            len(self.expected),
        )
        self.assertEqual(
            set(Vista.objects.filter(nombre__in=self.expected).values_list('route_name', flat=True)),
            set(self.expected.values()),
        )
        self.assertFalse(Permiso.objects.filter(vista__nombre__in=self.expected).exists())

    def test_seed_is_idempotent(self):
        call_command('seed_database_manager_views')
        first = list(
            Vista.objects.filter(nombre__in=self.expected)
            .order_by('nombre')
            .values_list('id', 'nombre', 'route_name')
        )

        call_command('seed_database_manager_views')
        second = list(
            Vista.objects.filter(nombre__in=self.expected)
            .order_by('nombre')
            .values_list('id', 'nombre', 'route_name')
        )

        self.assertEqual(second, first)
        self.assertEqual(
            Vista.objects.filter(nombre__in=self.expected).count(),
            len(self.expected),
        )
        self.assertFalse(Permiso.objects.filter(vista__nombre__in=self.expected).exists())
