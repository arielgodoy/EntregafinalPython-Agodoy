from django.test import TestCase

from access_control.models import Permiso, Vista
from access_control.services.view_registry import (
    DuplicateDefinitionKeyError,
    DuplicateDefinitionNameError,
    DuplicateRouteBindingError,
    RouteBinding,
    ViewRegistry,
    VistaDefinition,
    all_definitions,
    bindings_for_route,
    definition_for_key,
    definitions_for_app,
    definitions_for_group,
    administrable_definitions,
    navigable_definitions,
)
from access_control.services.permissions import SIDEBAR_GROUPS
from tareas.vicmeas import TASKS_VIEW_DEFINITIONS


class ViewRegistryTests(TestCase):
    def test_tareas_registers_five_functional_surfaces(self):
        definitions = definitions_for_app("tareas")

        self.assertEqual(len(definitions), 5)
        self.assertEqual(
            {definition.key for definition in definitions},
            {
                "tareas.tasks",
                "tareas.lifecycle",
                "tareas.milestones",
                "tareas.documents",
                "tareas.personal_dashboard",
            },
        )
        self.assertEqual(
            {definition.nombre for definition in definitions_for_group("tasks")},
            {
                "Tareas",
                "Tareas - Ciclo de vida",
                "Tareas - Hitos",
                "Tareas - Documentos y evidencia",
                "Tareas - Dashboard personal",
            },
        )

    def test_keys_are_unique_and_registration_is_idempotent(self):
        registry = ViewRegistry()
        definition = TASKS_VIEW_DEFINITIONS[0]

        registry.register(definition)
        registry.register(definition)

        self.assertEqual(registry.all(), (definition,))
        with self.assertRaises(DuplicateDefinitionKeyError):
            registry.register(
                VistaDefinition(
                    key=definition.key,
                    app="tareas",
                    nombre="Otra Vista",
                    route_name="tareas:otra",
                    routes=(RouteBinding("tareas:otra", "ingresar"),),
                )
            )

    def test_surface_supports_multiple_routes_and_method_permissions(self):
        definition = definition_for_key("tareas.tasks")

        self.assertEqual(definition_for_key("tareas.tasks"), definition)
        self.assertEqual(definition_for_key("tareas.tasks").route_name, "tareas:listar_tareas")
        self.assertEqual(
            bindings_for_route("tareas:detalle_tarea", "GET")[0].permiso_requerido,
            "ingresar",
        )
        self.assertEqual(
            bindings_for_route("tareas:detalle_tarea", "POST")[0].permiso_requerido,
            "modificar",
        )
        self.assertEqual(
            definition_for_key("tareas.tasks").routes[-1].route_name,
            "tareas:dashboard_general_usuario",
        )

    def test_administrable_surface_can_be_non_navigable(self):
        definitions = {definition.key: definition for definition in administrable_definitions()}
        navigable = {definition.key for definition in navigable_definitions()}

        self.assertIn("tareas.lifecycle", definitions)
        self.assertNotIn("tareas.lifecycle", navigable)
        self.assertIn("tareas.tasks", navigable)
        self.assertIn("tareas.personal_dashboard", navigable)

    def test_technical_non_administrable_definition_is_excluded(self):
        registry = ViewRegistry()
        definition = VistaDefinition(
            key="tareas.technical_link",
            app="tareas",
            nombre="Tareas - Enlace técnico",
            route_name="tareas:enlace_tarea",
            routes=(RouteBinding("tareas:enlace_tarea", "ingresar"),),
            navigable=False,
            access_utility=False,
            group="tasks",
        )

        registry.register(definition)

        self.assertEqual(registry.administrable(), ())
        self.assertEqual(registry.navigable(), ())
        self.assertEqual(registry.by_group("tasks"), (definition,))

    def test_conflicts_are_rejected(self):
        registry = ViewRegistry()
        first = VistaDefinition(
            key="sample.first",
            app="sample",
            nombre="Sample",
            route_name="sample:first",
            routes=(RouteBinding("sample:first", "ingresar"),),
        )
        registry.register(first)

        with self.assertRaises(DuplicateDefinitionNameError):
            registry.register(
                VistaDefinition(
                    key="sample.second",
                    app="sample",
                    nombre="Sample",
                    route_name="sample:second",
                    routes=(RouteBinding("sample:second", "ingresar"),),
                )
            )
        with self.assertRaises(DuplicateRouteBindingError):
            registry.register(
                VistaDefinition(
                    key="sample.third",
                    app="sample",
                    nombre="Third",
                    route_name="sample:first",
                    routes=(RouteBinding("sample:first", "modificar"),),
                )
            )

    def test_importing_declarations_does_not_touch_vista_or_permiso(self):
        vista_count = Vista.objects.count()
        permiso_count = Permiso.objects.count()

        __import__("tareas.vicmeas")

        self.assertEqual(Vista.objects.count(), vista_count)
        self.assertEqual(Permiso.objects.count(), permiso_count)

    def test_registry_order_is_deterministic_without_sidebar_changes(self):
        first = tuple(definition.key for definition in all_definitions())
        second = tuple(definition.key for definition in all_definitions())

        self.assertEqual(first, second)
        self.assertEqual(first, tuple(sorted(first)))
        self.assertEqual(SIDEBAR_GROUPS["tasks"], ("tasks_list", "tasks_create", "tasks_dashboard"))

    def test_new_definition_does_not_require_sidebar_group_edit(self):
        registry = ViewRegistry()
        before = SIDEBAR_GROUPS["tasks"]
        registry.register(
            VistaDefinition(
                key="tareas.future_surface",
                app="tareas",
                nombre="Tareas - Futuro",
                route_name="tareas:futuro",
                routes=(RouteBinding("tareas:futuro", "ingresar"),),
                access_utility=True,
                group="tasks",
            )
        )

        self.assertEqual(SIDEBAR_GROUPS["tasks"], before)
        self.assertEqual(len(registry.by_group("tasks")), 1)
