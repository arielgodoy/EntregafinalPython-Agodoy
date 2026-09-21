from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from access_control.services.view_catalog import ensure_protected_views_catalog


class ProtectedViewCatalogCompatibilityTests(TestCase):
    def test_active_views_catalog_is_idempotent_and_does_not_create_permissions(self):
        first = ensure_protected_views_catalog()
        permissions_before = Permiso.objects.count()
        second = ensure_protected_views_catalog()

        self.assertGreater(first.created, 0)
        self.assertEqual(second.created, 0)
        self.assertEqual(Permiso.objects.count(), permissions_before)

    def test_active_views_catalog_preserves_existing_view_and_permissions(self):
        user = User.objects.create_user(username="catalog-user")
        empresa = Empresa.objects.create(codigo="01")
        vista = Vista.objects.create(
            nombre="Tareas",
            route_name="tareas:listar_tareas",
        )
        permiso = Permiso.objects.create(
            usuario=user,
            empresa=empresa,
            vista=vista,
            ingresar=True,
        )

        ensure_protected_views_catalog()

        permiso.refresh_from_db()
        vista.refresh_from_db()
        self.assertEqual(vista.route_name, "tareas:listar_tareas")
        self.assertEqual(permiso.vista_id, vista.id)
        self.assertTrue(permiso.ingresar)
