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


class ViewRegistryTests(TestCase):
    def test_keys_are_unique_and_registration_is_idempotent(self):
        registry = ViewRegistry()
        definition = VistaDefinition(
            key="sample.definition",
            app="sample",
            nombre="Sample",
            route_name="sample:index",
            routes=(RouteBinding("sample:index", "ingresar"),),
        )

        registry.register(definition)
        registry.register(definition)

        self.assertEqual(registry.all(), (definition,))
        with self.assertRaises(DuplicateDefinitionKeyError):
            registry.register(
                VistaDefinition(
                    key=definition.key,
                    app="sample",
                    nombre="Otra Vista",
                    route_name="sample:otra",
                    routes=(RouteBinding("sample:otra", "ingresar"),),
                )
            )

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
