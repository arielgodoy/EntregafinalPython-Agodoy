from django.test import SimpleTestCase

from access_control.services.view_catalog import audit_protected_views
from tareas import urls


class TareasViewMetadataTests(SimpleTestCase):
    def test_endpoints_comparten_vista_madre_por_capacidad(self):
        expected = {
            "listar_tareas": ("Tareas", "ingresar"),
            "mis_tareas": ("Tareas - Dashboard personal", "ingresar"),
            "detalle_tarea": ("Tareas", "ingresar"),
            "crear_tarea": ("Tareas", "crear"),
            "editar_tarea": ("Tareas", "modificar"),
            "publicar_tarea": ("Tareas - Ciclo de vida", "modificar"),
            "gestionar_tarea": ("Tareas - Ciclo de vida", "modificar"),
            "completar_tarea": ("Tareas - Ciclo de vida", "modificar"),
            "aprobar_cierre": ("Tareas - Ciclo de vida", "modificar"),
            "rechazar_cierre": ("Tareas - Ciclo de vida", "modificar"),
            "anular_tarea": ("Tareas - Ciclo de vida", "modificar"),
            "reactivar_tarea": ("Tareas - Ciclo de vida", "modificar"),
            "hitos_tarea": ("Tareas - Hitos", "ingresar"),
            "documentos_tarea": ("Tareas - Documentos y evidencia", "modificar"),
        }

        actual = {
            pattern.name: (
                pattern.callback.view_class.vista_nombre,
                pattern.callback.view_class.permiso_requerido,
            )
            for pattern in urls.urlpatterns
        }

        self.assertEqual(actual, expected)

    def test_catalogo_no_reporta_issues_para_tareas(self):
        definitions, issues = audit_protected_views()

        self.assertFalse(
            [issue for issue in issues if issue.route_name and issue.route_name.startswith("tareas:")]
        )
        self.assertTrue(any(definition.vista_nombre == "Tareas" for definition in definitions))