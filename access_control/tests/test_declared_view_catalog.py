from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from access_control.services.view_catalog import ensure_protected_views_catalog


class ProtectedViewCatalogCompatibilityTests(TestCase):
    def test_route_identity_renames_legacy_gestion_dte_view_without_duplicate(self):
        legacy = Vista.objects.create(
            nombre="Configuración - Conexiones Gestión DTE",
            route_name="gestion_dte:connection_roles",
        )

        result = ensure_protected_views_catalog()

        legacy.refresh_from_db()
        self.assertEqual(result.updated, 1)
        self.assertEqual(legacy.nombre, "Gestion DTE - Conexiones SQL")
        self.assertEqual(legacy.route_name, "gestion_dte:connection_roles")
        self.assertEqual(
            Vista.objects.filter(route_name="gestion_dte:connection_roles").count(),
            1,
        )

    def test_route_identity_creates_and_reuses_gestion_dte_view(self):
        first = ensure_protected_views_catalog()
        second = ensure_protected_views_catalog()

        self.assertEqual(
            Vista.objects.filter(route_name="gestion_dte:connection_roles").count(),
            1,
        )
        self.assertEqual(
            Vista.objects.get(route_name="gestion_dte:connection_roles").nombre,
            "Gestion DTE - Conexiones SQL",
        )
        self.assertEqual(
            sum(item.route_name == "gestion_dte:connection_roles" for item in first.created_rows),
            1,
        )
        self.assertEqual(second.created, 0)

    def test_duplicate_route_identity_is_reported_without_merging(self):
        first = Vista.objects.create(
            nombre="Configuración - Conexiones Gestión DTE",
            route_name="gestion_dte:connection_roles",
        )
        second = Vista.objects.create(
            nombre="Otra Vista Gestión DTE",
            route_name="gestion_dte:connection_roles",
        )

        result = ensure_protected_views_catalog()

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(any(item.code == "persistent_identity_conflict" for item in result.conflicts))
        self.assertEqual(first.nombre, "Configuración - Conexiones Gestión DTE")
        self.assertEqual(second.nombre, "Otra Vista Gestión DTE")

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
