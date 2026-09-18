from django.test import TestCase

from access_control.models import Vista
from access_control.services.empresa_activa import get_navigable_vistas
from access_control.services.view_reconciliation import (
    ReconciliationPreconditionError,
    preview_reconciliation,
)


class ViewRouteReconciliationTests(TestCase):
    def setUp(self):
        Vista.objects.create(
            id=34,
            nombre="Tareas - Listado",
            route_name="tareas:listar_tareas",
        )
        Vista.objects.create(
            id=38,
            nombre="Tareas - Publicar tarea",
            route_name="tareas:publicar_tarea",
        )
        Vista.objects.create(id=130, nombre="Tareas")
        Vista.objects.create(id=131, nombre="Tareas - Ciclo de vida")
        Vista.objects.create(
            id=57,
            nombre="Tareas - Dashboard personal",
            route_name="tareas:mis_tareas",
        )

    def test_navigation_guard_uses_declarative_navigable_flag(self):
        route_overrides = {
            34: None,
            38: None,
            130: "tareas:listar_tareas",
            131: "tareas:publicar_tarea",
        }

        visible_names = {
            vista.nombre
            for vista in get_navigable_vistas(route_overrides=route_overrides)
        }

        self.assertIn("Tareas", visible_names)
        self.assertIn("Tareas - Dashboard personal", visible_names)
        self.assertNotIn("Tareas - Ciclo de vida", visible_names)
        self.assertNotIn("Tareas - Listado", visible_names)

    def test_preview_is_pure_and_reports_the_four_route_changes(self):
        before = tuple(Vista.objects.values_list("id", "route_name"))

        result = preview_reconciliation()

        after = tuple(Vista.objects.values_list("id", "route_name"))
        self.assertEqual(result.mode, "PREVIEW")
        self.assertEqual(result.changed, 0)
        self.assertEqual(before, after)
        self.assertEqual(
            result.would_clear,
            (
                (34, "Tareas - Listado", "tareas:listar_tareas"),
                (38, "Tareas - Publicar tarea", "tareas:publicar_tarea"),
            ),
        )
        self.assertEqual(
            result.would_set,
            (
                (130, "Tareas", "tareas:listar_tareas"),
                (131, "Tareas - Ciclo de vida", "tareas:publicar_tarea"),
            ),
        )

    def test_precondition_rejects_unexpected_route(self):
        Vista.objects.filter(pk=34).update(route_name="tareas:otra_ruta")

        with self.assertRaises(ReconciliationPreconditionError):
            preview_reconciliation()