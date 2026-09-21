from django.contrib.auth.models import User
from django.test import TestCase
from types import SimpleNamespace
from unittest.mock import patch

from access_control.models import Empresa, Permiso, Vista
from access_control.decorators import verificar_permiso
from access_control.services.permissions import SIDEBAR_VIEW_NAMES, VICMEAS_FIELDS, ensure_sidebar_permissions
from access_control.services.view_catalog import (
    audit_protected_views,
    discover_protected_views,
    ensure_protected_views_catalog,
)
from proveedores.views import (
    CrearProveedorView,
    DetalleProveedorView,
    EditarProveedorView,
    InactivarProveedorView,
    ListadoProveedoresView,
    ReactivarProveedorView,
)


class ProtectedViewCatalogTests(TestCase):
    def test_catalog_discovers_biblioteca_mother_views_from_active_views(self):
        result = ensure_protected_views_catalog()

        expected_names = {
            "Biblioteca - Propiedades",
            "Biblioteca - Propietarios",
            "Biblioteca - Tipos de Documento",
            "Biblioteca - Documentos",
            "Biblioteca - Respaldo Biblioteca",
        }
        catalog_names = {
            item.nombre
            for item in (*result.created_rows, *result.existing_rows, *result.updated_rows)
        }

        self.assertTrue(expected_names.issubset(catalog_names))
        self.assertEqual(
            Vista.objects.filter(nombre__in=expected_names).count(),
            len(expected_names),
        )

    def test_proveedores_crud_shares_master_view_and_action_permissions(self):
        expected = {
            ListadoProveedoresView: "ingresar",
            DetalleProveedorView: "ingresar",
            CrearProveedorView: "crear",
            EditarProveedorView: "modificar",
            InactivarProveedorView: "eliminar",
            ReactivarProveedorView: "modificar",
        }

        for view_class, permission in expected.items():
            self.assertEqual(view_class.vista_nombre, "Maestros - Proveedores")
            self.assertEqual(view_class.permiso_requerido, permission)

        definitions = [
            definition
            for definition in discover_protected_views()
            if definition.namespace == "proveedores"
        ]
        self.assertEqual(len(definitions), 1)
        self.assertEqual({definition.vista_nombre for definition in definitions}, {"Maestros - Proveedores"})
        self.assertEqual(
            Vista.objects.filter(nombre="Maestros - Proveedores").count(),
            0,
        )

    def test_decorator_preserves_name_and_metadata(self):
        def sample_view(request):
            return None

        decorated = verificar_permiso("Catalog Test", "ingresar")(sample_view)

        self.assertEqual(decorated.__name__, "sample_view")
        self.assertEqual(decorated.vista_nombre, "Catalog Test")
        self.assertEqual(decorated.permiso_requerido, "ingresar")

    def test_active_cbv_and_fbv_are_discovered(self):
        definitions = {definition.vista_nombre: definition for definition in discover_protected_views()}

        self.assertEqual(
            definitions["Control de Acceso - Utilitario de Acceso"].route_name,
            "access_control:utilitario_acceso",
        )
        self.assertEqual(definitions["Biblioteca - Documentos"].view_type, "CBV")

    def test_audit_reports_active_mixin_without_metadata(self):
        _, issues = audit_protected_views()

        self.assertTrue(
            any(issue.issue == "missing_vicmeas_metadata" for issue in issues)
        )

    def test_audit_reports_invalid_permission(self):
        def sample_view(request):
            return None

        sample_view.vista_nombre = "Catalog Test"
        sample_view.permiso_requerido = "invalid"
        pattern = SimpleNamespace(callback=sample_view)

        with patch(
            "access_control.services.view_catalog._iter_url_patterns",
            return_value=[(pattern, "test:invalid")],
        ):
            definitions, issues = audit_protected_views()

        self.assertEqual(definitions, ())
        self.assertEqual(
            [(issue.issue, issue.route_name, issue.vista_nombre) for issue in issues],
            [("invalid_permission", "test:invalid", "Catalog Test")],
        )

    def test_catalog_ignores_unconnected_views_and_is_idempotent(self):
        Vista.objects.create(nombre="Vista desconectada", route_name="test:dead")

        first = ensure_protected_views_catalog()
        second = ensure_protected_views_catalog()

        self.assertEqual(Vista.objects.filter(nombre="Vista desconectada").count(), 1)
        self.assertGreater(first.created, 0)
        self.assertEqual(second.created, 0)
        self.assertEqual(Vista.objects.filter(nombre="Biblioteca - Documentos").count(), 1)

    def test_catalog_does_not_create_permissions_and_sidebar_materializes_empty_rows(self):
        ensure_protected_views_catalog()
        Vista.objects.bulk_create(
            [
                Vista(nombre=nombre)
                for nombre in set(SIDEBAR_VIEW_NAMES.values())
                if not Vista.objects.filter(nombre=nombre).exists()
            ]
        )
        self.assertEqual(Permiso.objects.count(), 0)

        user = User.objects.create_user(username="catalog-user")
        empresa = Empresa.objects.create(codigo="01")
        ensure_sidebar_permissions(user, empresa.id)

        sidebar_names = {
            nombre
            for item_key, nombre in SIDEBAR_VIEW_NAMES.items()
            if item_key not in {"tasks_list", "tasks_create"}
        }
        sidebar_names.add("Tareas")
        permisos = Permiso.objects.filter(usuario=user, empresa=empresa)
        self.assertEqual(permisos.count(), len(sidebar_names))
        for permiso in permisos:
            self.assertFalse(any(getattr(permiso, field) for field in VICMEAS_FIELDS))
