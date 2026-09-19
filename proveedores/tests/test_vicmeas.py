from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from access_control.services.access_utility import resolve_scope_vistas
from access_control.services.permissions import SIDEBAR_DEFINITION_KEYS, get_sidebar_visible_items
from access_control.services.view_catalog import ensure_declared_views_catalog, get_legacy_views_for_app
from access_control.services.view_registry import definitions_for_app
from access_control.services.view_registry_audit import audit_app


class ProveedoresVicmeasTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="proveedores-vicmeas")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self.vista = Vista.objects.create(
            nombre="Maestros - Proveedores",
            route_name=None,
        )

    def test_registry_defines_one_surface_with_exact_bindings(self):
        definitions = definitions_for_app("proveedores")
        self.assertEqual(len(definitions), 1)
        definition = definitions[0]
        self.assertEqual(definition.key, "proveedores.maestros")
        self.assertEqual(
            {(binding.route_name, binding.methods, binding.permiso_requerido) for binding in definition.routes},
            {
                ("proveedores:listado_raiz", ("GET",), "ingresar"),
                ("proveedores:listado", ("GET",), "ingresar"),
                ("proveedores:crear", ("GET", "POST", "PUT"), "crear"),
                ("proveedores:detalle", ("GET",), "ingresar"),
                ("proveedores:editar", ("GET", "POST", "PUT"), "modificar"),
                ("proveedores:inactivar", ("POST",), "eliminar"),
                ("proveedores:reactivar", ("POST",), "modificar"),
            },
        )

    def test_audit_is_clean(self):
        result = audit_app("proveedores")

        self.assertEqual(len(result.definitions), 1)
        self.assertEqual(len(result.bindings), 11)
        self.assertEqual(len(result.protected_routes), 11)
        self.assertEqual(result.issues, ())

    def test_scope_is_one_surface_without_copying_permissions(self):
        before = Permiso.objects.count()
        resolution = resolve_scope_vistas("proveedores")

        self.assertEqual(resolution.requested_leaf_names, ("Maestros - Proveedores",))
        self.assertEqual([vista.nombre for vista in resolution.vistas], [self.vista.nombre])
        self.assertEqual(resolution.missing_names, ())
        self.assertEqual(resolution.conflicts, ())
        self.assertEqual(Permiso.objects.count(), before)

    def test_sidebar_uses_definition_key_and_only_ver(self):
        self.assertEqual(
            SIDEBAR_DEFINITION_KEYS["suppliers_master"],
            "proveedores.maestros",
        )
        permission = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ver=True,
            ingresar=False,
            crear=False,
            modificar=False,
            eliminar=False,
        )
        visible = get_sidebar_visible_items(
            self.user,
            self.empresa.id,
            materialize_permissions=False,
        )
        self.assertIn("suppliers_master", visible)
        permission.ver = False
        permission.ingresar = True
        permission.save(update_fields=["ver", "ingresar"])
        visible = get_sidebar_visible_items(
            self.user,
            self.empresa.id,
            materialize_permissions=False,
        )
        self.assertNotIn("suppliers_master", visible)

    def test_catalog_reuses_view_and_reports_route_update_without_writing(self):
        before_views = tuple(Vista.objects.values_list("id", "nombre", "route_name"))
        before_permissions = tuple(Permiso.objects.values_list("id", "vista_id"))

        result = ensure_declared_views_catalog(app="proveedores", dry_run=True)

        self.assertEqual(result.created, 0)
        self.assertEqual(result.existing, 1)
        self.assertEqual(result.updated, 1)
        self.assertEqual(result.conflicts, ())
        self.assertEqual(result.legacy, ())
        self.assertEqual(
            tuple(Vista.objects.values_list("id", "nombre", "route_name")),
            before_views,
        )
        self.assertEqual(tuple(Permiso.objects.values_list("id", "vista_id")), before_permissions)

    def test_seed_is_idempotent_and_does_not_create_permissions(self):
        first = StringIO()
        second = StringIO()
        before = tuple(Permiso.objects.values_list("id", "vista_id"))

        call_command("seed_proveedores", stdout=first)
        call_command("seed_proveedores", stdout=second)

        vista = Vista.objects.get(nombre="Maestros - Proveedores")
        self.assertEqual(vista.route_name, "proveedores:listado")
        self.assertEqual(Vista.objects.filter(nombre="Maestros - Proveedores").count(), 1)
        self.assertEqual(tuple(Permiso.objects.values_list("id", "vista_id")), before)

    def test_legacy_reporting_is_empty(self):
        self.assertEqual(get_legacy_views_for_app("proveedores"), ())
