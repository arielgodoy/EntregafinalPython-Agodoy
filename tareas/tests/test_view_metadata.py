from django.test import SimpleTestCase
from django.test import TestCase

from access_control.models import Permiso, Vista
from access_control.services.view_catalog import ensure_declared_views_catalog
from access_control.services.view_catalog import audit_protected_views
from access_control.services.view_registry import definitions_for_app
from tareas import urls
from tareas.services.authorization import MEETINGS_VISTA_NAME
from tareas.vicmeas import MEETINGS


class TareasViewMetadataTests(SimpleTestCase):
    def test_endpoints_comparten_vista_madre_por_capacidad(self):
        expected = {
            "listar_tareas": ("Tareas", "ingresar"),
            "mis_tareas": ("Tareas - Dashboard personal", "ingresar"),
            "dashboard_general": ("Tareas", "supervisor"),
            "dashboard_general_empresa": ("Tareas", "supervisor"),
            "dashboard_general_departamento": ("Tareas", "supervisor"),
            "dashboard_general_usuario": ("Tareas", "supervisor"),
            "detalle_tarea": ("Tareas", "ingresar"),
            "crear_tarea": ("Tareas", "crear"),
            "editar_tarea": ("Tareas", "modificar"),
            "publicar_tarea": ("Tareas - Ciclo de vida", "modificar"),
            "similitud_tarea": ("Tareas - Ciclo de vida", "modificar"),
            "confirmar_similitud": ("Tareas - Ciclo de vida", "modificar"),
            "gestionar_tarea": ("Tareas - Ciclo de vida", "modificar"),
            "completar_tarea": ("Tareas - Ciclo de vida", "modificar"),
            "aprobar_cierre": ("Tareas - Ciclo de vida", "modificar"),
            "rechazar_cierre": ("Tareas - Ciclo de vida", "modificar"),
            "anular_tarea": ("Tareas - Ciclo de vida", "modificar"),
            "reactivar_tarea": ("Tareas - Ciclo de vida", "modificar"),
            "hitos_tarea": ("Tareas - Hitos", "ingresar"),
            "documentos_tarea": ("Tareas - Documentos y evidencia", "modificar"),
            "reunion_revision_lista": (MEETINGS_VISTA_NAME, "ingresar"),
            "reunion_revision_crear": (MEETINGS_VISTA_NAME, "crear"),
            "reunion_revision_detalle": (MEETINGS_VISTA_NAME, "ingresar"),
            "reunion_revision_editar": (MEETINGS_VISTA_NAME, "modificar"),
            "reunion_revision_accion": (MEETINGS_VISTA_NAME, "modificar"),
        }

        actual = {
            pattern.name: (
                pattern.callback.view_class.vista_nombre,
                pattern.callback.view_class.permiso_requerido,
            )
            for pattern in urls.urlpatterns
            if pattern.name in expected
        }

        self.assertEqual(actual, expected)

    def test_catalogo_no_reporta_issues_para_tareas(self):
        definitions, issues = audit_protected_views()

        self.assertFalse(
            [issue for issue in issues if issue.route_name and issue.route_name.startswith("tareas:")]
        )
        self.assertTrue(any(definition.vista_nombre == "Tareas" for definition in definitions))


class MeetingViewRegistryTests(SimpleTestCase):
    def test_canonical_definition_has_unique_identity_and_route_bindings(self):
        definitions = definitions_for_app("tareas")
        meeting_definitions = [
            definition
            for definition in definitions
            if definition.nombre == MEETINGS_VISTA_NAME
        ]

        self.assertEqual(meeting_definitions, [MEETINGS])
        self.assertEqual(MEETINGS.key, "tasks_meetings")
        self.assertEqual(MEETINGS.app, "tareas")
        self.assertEqual(MEETINGS.route_name, "tareas:reunion_revision_lista")
        self.assertTrue(MEETINGS.navigable)
        self.assertEqual(MEETINGS.group, "tasks")


class MeetingViewCatalogDryRunTests(TestCase):
    def test_catalog_dry_run_does_not_persist_view_or_permissions(self):
        self.assertFalse(Vista.objects.filter(nombre=MEETINGS_VISTA_NAME).exists())
        permissions_before = Permiso.objects.count()

        result = ensure_declared_views_catalog(app="tareas", dry_run=True)

        self.assertTrue(
            any(item.nombre == MEETINGS_VISTA_NAME for item in result.created_rows)
        )
        self.assertFalse(Vista.objects.filter(nombre=MEETINGS_VISTA_NAME).exists())
        self.assertEqual(Permiso.objects.count(), permissions_before)