from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from access_control.services.access_utility import resolve_scope_vistas
from access_control.services.permissions import get_sidebar_visible_items
from evaluaciones.views import (
    ImportarPersonasStartView,
    ImportarPersonasStatusView,
    ImportarPersonasView,
)


class EvaluacionesViewsSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="evaluaciones-views")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self.vista = Vista.objects.create(
            nombre="Evaluaciones - Importar Personas",
            route_name="evaluaciones:importar_personas",
        )

    def test_views_share_one_surface_and_expected_permissions(self):
        expected_name = "Evaluaciones - Importar Personas"

        self.assertEqual(ImportarPersonasView.vista_nombre, expected_name)
        self.assertEqual(ImportarPersonasView.permiso_requerido, "ingresar")
        self.assertEqual(ImportarPersonasStartView.vista_nombre, expected_name)
        self.assertEqual(ImportarPersonasStartView.permiso_requerido, "supervisor")
        self.assertEqual(ImportarPersonasStatusView.vista_nombre, expected_name)
        self.assertEqual(ImportarPersonasStatusView.permiso_requerido, "ingresar")

    def test_scope_is_one_surface_without_copying_permissions(self):
        legacy_permission_count = Permiso.objects.count()

        resolution = resolve_scope_vistas("evaluaciones")

        self.assertEqual(resolution.requested_leaf_names, ("Evaluaciones - Importar Personas",))
        self.assertEqual([vista.nombre for vista in resolution.vistas], [self.vista.nombre])
        self.assertEqual(resolution.missing_names, ())
        self.assertEqual(resolution.conflicts, ())
        self.assertEqual(Permiso.objects.count(), legacy_permission_count)

    def test_sidebar_uses_view_name_and_only_ver(self):
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
