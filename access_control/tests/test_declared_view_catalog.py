from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from access_control.services.view_catalog import ensure_declared_views_catalog
from tareas.vicmeas import TASKS_VIEW_DEFINITIONS


class DeclaredViewCatalogTests(TestCase):
    def test_empty_registry_does_not_create_rows(self):
        before = Vista.objects.count()
        result = ensure_declared_views_catalog(
            app="tareas",
            definitions=(),
            dry_run=False,
        )

        self.assertEqual(result.created, 0)
        self.assertEqual(Vista.objects.count(), before)

    def test_missing_declarations_are_created_and_second_run_is_idempotent(self):
        before = Vista.objects.count()
        first = ensure_declared_views_catalog(app="tareas", dry_run=False)
        second = ensure_declared_views_catalog(app="tareas", dry_run=False)

        self.assertEqual(first.created, 5)
        self.assertEqual(first.existing, 0)
        self.assertEqual(second.created, 0)
        self.assertEqual(second.existing, 5)
        self.assertEqual(Vista.objects.count(), before + 5)
        self.assertEqual(
            set(
                Vista.objects.filter(
                    nombre__in=[definition.nombre for definition in TASKS_VIEW_DEFINITIONS]
                ).values_list("nombre", flat=True)
            ),
            {definition.nombre for definition in TASKS_VIEW_DEFINITIONS},
        )

    def test_existing_view_is_reused_and_safe_route_metadata_is_updated(self):
        vista = Vista.objects.create(
            nombre="Tareas",
            route_name=None,
            descripcion="Descripción histórica",
        )

        result = ensure_declared_views_catalog(app="tareas", dry_run=False)

        vista.refresh_from_db()
        self.assertEqual(result.existing, 1)
        self.assertEqual(result.updated, 1)
        self.assertEqual(vista.id, Vista.objects.get(nombre="Tareas").id)
        self.assertEqual(vista.route_name, "tareas:listar_tareas")
        self.assertEqual(vista.descripcion, "Descripción histórica")

    def test_preview_has_zero_writes(self):
        legacy = Vista.objects.create(nombre="Tareas - Listado", route_name="tareas:listado")
        before = set(Vista.objects.values_list("id", "nombre", "route_name"))

        result = ensure_declared_views_catalog(app="tareas", dry_run=True)

        self.assertEqual(result.created, 5)
        self.assertEqual(result.existing, 0)
        self.assertEqual(set(Vista.objects.values_list("id", "nombre", "route_name")), before)
        self.assertEqual(Vista.objects.get(pk=legacy.pk).route_name, "tareas:listado")

    def test_apply_creates_only_declared_views_and_reports_legacy(self):
        legacy = Vista.objects.create(nombre="Tareas - Crear tarea", route_name="tareas:crear_tarea")

        result = ensure_declared_views_catalog(app="tareas", dry_run=False)

        self.assertEqual(result.created, 5)
        self.assertEqual({item.nombre for item in result.legacy}, {legacy.nombre})
        self.assertTrue(Vista.objects.filter(pk=legacy.pk).exists())
        self.assertFalse(Vista.objects.filter(nombre="Biblioteca - Documentos").exists())

    def test_identity_conflict_is_reported_without_overwrite(self):
        conflicting = Vista.objects.create(
            nombre="Tareas histórica",
            route_name="tareas:listar_tareas",
        )

        result = ensure_declared_views_catalog(app="tareas", dry_run=False)

        self.assertTrue(any(conflict.code == "route_identity_conflict" for conflict in result.conflicts))
        self.assertFalse(Vista.objects.filter(nombre="Tareas").exists())
        conflicting.refresh_from_db()
        self.assertEqual(conflicting.nombre, "Tareas histórica")
        self.assertEqual(conflicting.route_name, "tareas:listar_tareas")

    def test_security_fixture_preserves_legacy_permission_and_creates_no_permission(self):
        user = User.objects.create_user(username="catalog-user")
        empresa = Empresa.objects.create(codigo="01")
        legacy = Vista.objects.create(nombre="Tareas - Publicar tarea")
        permiso = Permiso.objects.create(
            usuario=user,
            empresa=empresa,
            vista=legacy,
            ingresar=True,
            modificar=True,
        )

        result = ensure_declared_views_catalog(app="tareas", dry_run=False)

        permiso.refresh_from_db()
        self.assertTrue(Vista.objects.filter(nombre="Tareas").exists())
        self.assertTrue(Vista.objects.filter(pk=legacy.pk).exists())
        self.assertEqual(permiso.vista_id, legacy.pk)
        self.assertEqual(Permiso.objects.count(), 1)
        self.assertEqual(result.created, 5)

    def test_catalog_does_not_depend_on_sidebar_or_protected_url_discovery(self):
        result = ensure_declared_views_catalog(app="tareas", dry_run=True)

        self.assertEqual(
            {item.nombre for item in result.created_rows},
            {definition.nombre for definition in TASKS_VIEW_DEFINITIONS},
        )
        self.assertNotIn(
            "Tareas - Listado",
            {item.nombre for item in result.created_rows},
        )
        self.assertNotIn(
            "Biblioteca - Documentos",
            {item.nombre for item in result.created_rows},
        )

    def test_command_defaults_to_preview_and_apply_is_explicit(self):
        output = StringIO()
        declared_names = [definition.nombre for definition in TASKS_VIEW_DEFINITIONS]

        call_command("ensure_view_catalog", stdout=output)

        self.assertIn("DRY-RUN", output.getvalue())
        self.assertEqual(Vista.objects.filter(nombre__in=declared_names).count(), 0)

        call_command("ensure_view_catalog", "--apply", stdout=StringIO())

        self.assertEqual(Vista.objects.filter(nombre__in=declared_names).count(), 5)
