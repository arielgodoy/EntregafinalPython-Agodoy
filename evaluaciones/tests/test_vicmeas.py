from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from access_control.services.access_utility import resolve_scope_vistas
from access_control.services.permissions import SIDEBAR_DEFINITION_KEYS, get_sidebar_visible_items
from access_control.services.view_catalog import ensure_declared_views_catalog, get_legacy_views_for_app
from access_control.services.view_registry import definitions_for_app
from access_control.services.view_registry_audit import audit_app


class EvaluacionesVicmeasTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="evaluaciones-vicmeas")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self.vista = Vista.objects.create(
            nombre="Evaluaciones - Importar Personas",
            route_name=None,
        )

    def test_registry_has_one_surface_with_real_permissions(self):
        definitions = definitions_for_app("evaluaciones")

        self.assertEqual(len(definitions), 1)
        definition = definitions[0]
        self.assertEqual(definition.key, "evaluaciones.importar_personas")
        self.assertEqual(definition.route_name, "evaluaciones:importar_personas")
        self.assertEqual(
            {(binding.route_name, binding.methods, binding.permiso_requerido) for binding in definition.routes},
            {
                ("evaluaciones:importar_personas", ("GET", "POST"), "ingresar"),
                ("evaluaciones:importar_personas_start", ("POST",), "supervisor"),
                ("evaluaciones:importar_personas_status", ("GET",), "ingresar"),
            },
        )

    def test_audit_covers_all_protected_methods_without_issues(self):
        result = audit_app("evaluaciones")

        self.assertEqual(len(result.definitions), 1)
        self.assertEqual(len(result.bindings), 4)
        self.assertEqual(len(result.protected_routes), 4)
        self.assertEqual(result.issues, ())
        self.assertEqual(
            {(route.route_name, route.method, route.vista_nombre, route.permiso_requerido) for route in result.protected_routes},
            {
                ("evaluaciones:importar_personas", "GET", "Evaluaciones - Importar Personas", "ingresar"),
                ("evaluaciones:importar_personas", "POST", "Evaluaciones - Importar Personas", "ingresar"),
                ("evaluaciones:importar_personas_start", "POST", "Evaluaciones - Importar Personas", "supervisor"),
                ("evaluaciones:importar_personas_status", "GET", "Evaluaciones - Importar Personas", "ingresar"),
            },
        )

    def test_scope_is_one_surface_and_does_not_copy_permissions(self):
        legacy_permission_count = Permiso.objects.count()

        resolution = resolve_scope_vistas("evaluaciones")

        self.assertEqual(resolution.requested_leaf_names, ("Evaluaciones - Importar Personas",))
        self.assertEqual([vista.nombre for vista in resolution.vistas], [self.vista.nombre])
        self.assertEqual(resolution.missing_names, ())
        self.assertEqual(resolution.conflicts, ())
        self.assertEqual(Permiso.objects.count(), legacy_permission_count)

    def test_sidebar_uses_definition_key_and_only_ver(self):
        self.assertEqual(
            SIDEBAR_DEFINITION_KEYS["evaluaciones_import"],
            "evaluaciones.importar_personas",
        )
        permission = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ver=True,
            ingresar=False,
            supervisor=False,
        )

        visible = get_sidebar_visible_items(
            self.user,
            self.empresa.id,
            materialize_permissions=False,
        )
        self.assertIn("evaluaciones_import", visible)
        permission.ver = False
        permission.ingresar = True
        permission.save(update_fields=["ver", "ingresar"])
        visible = get_sidebar_visible_items(
            self.user,
            self.empresa.id,
            materialize_permissions=False,
        )
        self.assertNotIn("evaluaciones_import", visible)

    def test_catalog_reuses_view_and_reports_route_update_without_writing(self):
        before = tuple(Vista.objects.values_list("id", "nombre", "route_name"))

        result = ensure_declared_views_catalog(app="evaluaciones", dry_run=True)

        self.assertEqual(result.created, 0)
        self.assertEqual(result.existing, 1)
        self.assertEqual(result.updated, 1)
        self.assertEqual(result.conflicts, ())
        self.assertEqual(result.legacy, ())
        self.assertEqual(
            tuple(Vista.objects.values_list("id", "nombre", "route_name")),
            before,
        )

    def test_legacy_reporting_is_empty(self):
        self.assertEqual(get_legacy_views_for_app("evaluaciones"), ())
