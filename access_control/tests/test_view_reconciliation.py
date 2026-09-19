from django.test import TestCase

from access_control.models import Vista
from access_control.services.empresa_activa import get_navigable_vistas
from access_control.services.view_reconciliation import (
    ReconciliationPreconditionError,
    preview_reconciliation,
)


class ViewRouteReconciliationTests(TestCase):
    def setUp(self):
        self.legacy_listado = Vista.objects.create(
            nombre="Tareas - Listado",
            route_name="tareas:listar_tareas",
        )
        self.legacy_publicar = Vista.objects.create(
            nombre="Tareas - Publicar tarea",
            route_name="tareas:publicar_tarea",
        )
        self.canonical_tasks = Vista.objects.create(nombre="Tareas")
        self.canonical_lifecycle = Vista.objects.create(nombre="Tareas - Ciclo de vida")
        Vista.objects.create(
            nombre="Tareas - Hitos",
            route_name="tareas:hitos_tarea",
        )
        Vista.objects.create(
            nombre="Tareas - Documentos y evidencia",
            route_name="tareas:documentos_tarea",
        )
        self.personal_dashboard = Vista.objects.create(
            nombre="Tareas - Dashboard personal",
            route_name="tareas:mis_tareas",
        )

    def test_navigation_guard_uses_declarative_navigable_flag(self):
        route_overrides = {
            self.legacy_listado.id: None,
            self.legacy_publicar.id: None,
            self.canonical_tasks.id: "tareas:listar_tareas",
            self.canonical_lifecycle.id: "tareas:publicar_tarea",
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
                (self.legacy_listado.id, "Tareas - Listado", "tareas:listar_tareas"),
                (self.legacy_publicar.id, "Tareas - Publicar tarea", "tareas:publicar_tarea"),
            ),
        )
        self.assertEqual(
            result.would_set,
            (
                (self.canonical_tasks.id, "Tareas", "tareas:listar_tareas"),
                (self.canonical_lifecycle.id, "Tareas - Ciclo de vida", "tareas:publicar_tarea"),
            ),
        )
        self.assertNotEqual(
            {
                self.legacy_listado.id,
                self.legacy_publicar.id,
                self.canonical_tasks.id,
                self.canonical_lifecycle.id,
            },
            {34, 38, 130, 131},
        )

    def test_precondition_rejects_unexpected_route(self):
        Vista.objects.filter(pk=self.legacy_listado.id).update(route_name="tareas:otra_ruta")

        with self.assertRaises(ReconciliationPreconditionError):
            preview_reconciliation()