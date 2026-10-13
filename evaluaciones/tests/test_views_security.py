from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from access_control.services.access_utility import resolve_scope_vistas
from access_control.services.permissions import get_sidebar_visible_items
from evaluaciones.views import (
    EvaluacionesConnectionProbeView,
    EvaluacionesConnectionRolesView,
)
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
        self.connection_vista = Vista.objects.create(
            nombre="Evaluaciones - Conexiones Sql",
            route_name="evaluaciones:connection_roles",
        )

    def test_views_share_one_surface_and_expected_permissions(self):
        expected_name = "Evaluaciones - Importar Personas"

        self.assertEqual(ImportarPersonasView.vista_nombre, expected_name)
        self.assertEqual(ImportarPersonasView.permiso_requerido, "ingresar")
        self.assertEqual(ImportarPersonasStartView.vista_nombre, expected_name)
        self.assertEqual(ImportarPersonasStartView.permiso_requerido, "supervisor")
        self.assertEqual(ImportarPersonasStatusView.vista_nombre, expected_name)
        self.assertEqual(ImportarPersonasStatusView.permiso_requerido, "ingresar")

    def test_connection_admin_uses_its_own_icmeas_view(self):
        expected_name = "Evaluaciones - Conexiones Sql"

        self.assertEqual(EvaluacionesConnectionRolesView.vista_nombre, expected_name)
        self.assertEqual(EvaluacionesConnectionRolesView.permiso_requerido, "ingresar")
        self.assertEqual(EvaluacionesConnectionProbeView.vista_nombre, expected_name)
        self.assertEqual(EvaluacionesConnectionProbeView.permiso_requerido, "supervisor")

    def test_connection_view_is_registered_by_the_existing_seed_command(self):
        call_command("seed_vistas", verbosity=0)

        vista = Vista.objects.get(nombre="Evaluaciones - Conexiones Sql")

        self.assertEqual(vista.route_name, "evaluaciones:connection_roles")

    def test_scope_is_one_surface_without_copying_permissions(self):
        legacy_permission_count = Permiso.objects.count()

        resolution = resolve_scope_vistas("evaluaciones")

        expected_names = (
            "Evaluaciones - Importar Personas",
            "Evaluaciones - Conexiones Sql",
        )
        self.assertEqual(resolution.requested_leaf_names, expected_names)
        self.assertEqual([vista.nombre for vista in resolution.vistas], list(expected_names))
        self.assertEqual(resolution.missing_names, ())
        self.assertEqual(resolution.conflicts, ())
        self.assertEqual(Permiso.objects.count(), legacy_permission_count)

    def test_connection_sidebar_requires_ver_independently_of_ingresar(self):
        permission = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.connection_vista,
            ver=True,
            ingresar=False,
        )
        visible = get_sidebar_visible_items(
            self.user,
            self.empresa.id,
            materialize_permissions=False,
        )
        self.assertIn("evaluaciones_connections", visible)

        permission.ver = False
        permission.ingresar = True
        permission.save(update_fields=["ver", "ingresar"])
        visible = get_sidebar_visible_items(
            self.user,
            self.empresa.id,
            materialize_permissions=False,
        )
        self.assertNotIn("evaluaciones_connections", visible)

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
