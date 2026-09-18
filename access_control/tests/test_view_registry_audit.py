from dataclasses import replace
from types import SimpleNamespace

from django.test import TestCase
from django.urls import URLPattern, URLResolver
from django.urls.resolvers import RegexPattern

from access_control.models import Permiso, Vista
from access_control.services.view_registry import RouteBinding, VistaDefinition
from access_control.services.view_registry_audit import (
    AuditIssue,
    audit_app,
)
from tareas.vicmeas import TASKS_VIEW_DEFINITIONS


def _definition_with_bindings(definition, bindings):
    return replace(definition, routes=tuple(bindings))


class ViewRegistryAuditTests(TestCase):
    def test_real_tareas_snapshot_is_deterministic_and_clean(self):
        result = audit_app("tareas")

        self.assertEqual(len(result.definitions), 5)
        self.assertEqual(len(result.bindings), 34)
        self.assertEqual(len(result.protected_routes), 36)
        self.assertEqual(result.issues, ())
        self.assertEqual(
            tuple(issue for issue in result.issues),
            tuple(sorted(result.issues, key=lambda issue: (
                issue.code,
                issue.route_name,
                issue.definition_key,
                issue.expected,
                issue.actual,
            ))),
        )

    def test_declared_route_not_found_is_reported(self):
        definition = replace(
            TASKS_VIEW_DEFINITIONS[0],
            route_name="tareas:ruta_inexistente",
            routes=(RouteBinding("tareas:ruta_inexistente", "ingresar"),),
        )

        result = audit_app("tareas", definitions=(definition,))

        self.assertEqual(len(result.by_code("route_not_found")), 1)
        self.assertEqual(result.issues[0].route_name, "tareas:ruta_inexistente")

    def test_protected_route_without_definition_is_reported(self):
        definitions = tuple(
            _definition_with_bindings(
                definition,
                tuple(
                    binding
                    for binding in definition.routes
                    if binding.route_name != "tareas:mis_tareas"
                ),
            )
            for definition in TASKS_VIEW_DEFINITIONS
            if definition.key != "tareas.personal_dashboard"
        )

        result = audit_app("tareas", definitions=definitions)

        issues = result.by_code("protected_route_without_definition")
        self.assertTrue(issues)
        self.assertEqual({issue.route_name for issue in issues}, {"tareas:mis_tareas"})

    def test_view_name_mismatch_is_reported(self):
        definitions = (
            replace(TASKS_VIEW_DEFINITIONS[0], nombre="Tareas - Nombre incorrecto"),
            *TASKS_VIEW_DEFINITIONS[1:],
        )

        result = audit_app("tareas", definitions=definitions)

        issues = result.by_code("view_name_mismatch")
        self.assertTrue(issues)
        self.assertEqual(issues[0].expected, "Tareas - Nombre incorrecto")
        self.assertEqual(issues[0].actual, "Tareas")

    def test_permission_mismatch_is_reported(self):
        original = TASKS_VIEW_DEFINITIONS[0]
        bindings = tuple(
            replace(binding, permiso_requerido="crear")
            if binding.route_name == "tareas:listar_tareas"
            else binding
            for binding in original.routes
        )
        definitions = (_definition_with_bindings(original, bindings), *TASKS_VIEW_DEFINITIONS[1:])

        result = audit_app("tareas", definitions=definitions)

        issue = next(issue for issue in result.issues if issue.code == "permission_mismatch")
        self.assertEqual(issue.route_name, "tareas:listar_tareas")
        self.assertEqual(issue.expected, "crear")
        self.assertEqual(issue.actual, "ingresar")

    def test_get_and_post_permissions_are_compared_separately(self):
        result = audit_app("tareas")

        detail_routes = {
            route.method: route
            for route in result.protected_routes
            if route.route_name == "tareas:detalle_tarea"
        }
        self.assertEqual(detail_routes["GET"].permiso_requerido, "ingresar")
        self.assertEqual(detail_routes["POST"].permiso_requerido, "modificar")
        self.assertEqual(result.for_route("tareas:detalle_tarea"), ())

    def test_shared_aliases_do_not_duplicate_an_issue(self):
        class AliasView:
            vista_nombre = "Alias"
            permiso_requerido = "ingresar"

            @classmethod
            def as_view(cls):
                def callback(request):
                    return None

                callback.vista_nombre = cls.vista_nombre
                callback.permiso_requerido = cls.permiso_requerido
                return callback

        callback = AliasView.as_view()
        patterns = [
            URLPattern(RegexPattern(r"^one/$"), callback, name="one"),
            URLPattern(RegexPattern(r"^two/$"), callback, name="two"),
        ]
        resolver = URLResolver(
            RegexPattern(r"^tareas/$"), patterns, app_name="tareas", namespace="tareas"
        )
        definition = SimpleNamespace(
            key="tareas.aliases",
            app="tareas",
            nombre="Alias",
            route_name="tareas:one",
            routes=(
                RouteBinding("tareas:one", "ingresar"),
                RouteBinding("tareas:two", "ingresar"),
            ),
            navigable=False,
            access_utility=False,
        )

        result = audit_app("tareas", definitions=(definition,), resolver=resolver)

        self.assertEqual(result.by_code("protected_route_without_definition"), ())
        self.assertEqual(result.by_code("view_name_mismatch"), ())

    def test_explicit_exclusion_does_not_create_false_positive(self):
        result = audit_app("tareas")

        self.assertNotIn(
            "tareas:enlace_tarea",
            {route.route_name for route in result.protected_routes},
        )
        self.assertEqual(result.for_route("tareas:enlace_tarea"), ())

    def test_structural_issues_are_reported_from_raw_definitions(self):
        duplicate_one = SimpleNamespace(
            key="tareas.duplicate",
            app="tareas",
            nombre="Duplicada",
            route_name="tareas:listar_tareas",
            routes=(),
            navigable=True,
            access_utility=True,
        )
        duplicate_two = SimpleNamespace(
            key="tareas.duplicate",
            app="tareas",
            nombre="Otra",
            route_name="tareas:ruta_inexistente",
            routes=(),
            navigable=True,
            access_utility=True,
        )
        result = audit_app(
            "tareas",
            definitions=(duplicate_one, duplicate_two),
        )
        codes = {issue.code for issue in result.issues}

        self.assertIn("duplicate_definition_key", codes)
        self.assertIn("duplicate_vicmeas_name_incompatible", {
            issue.code for issue in audit_app(
                "tareas",
                definitions=(
                    duplicate_one,
                    SimpleNamespace(**{**duplicate_one.__dict__, "key": "tareas.other"}),
                ),
            ).issues
        })
        self.assertIn("definition_without_routes", codes)
        self.assertIn("navigable_without_route", codes)

    def test_audit_does_not_query_or_write_vista_or_permiso(self):
        vista_count = Vista.objects.count()
        permiso_count = Permiso.objects.count()

        with self.assertNumQueries(0):
            audit_app("tareas")

        self.assertEqual(Vista.objects.count(), vista_count)
        self.assertEqual(Permiso.objects.count(), permiso_count)


class AuditIssueShapeTests(TestCase):
    def test_issue_is_structured_and_filterable(self):
        issue = AuditIssue(
            code="permission_mismatch",
            app="tareas",
            route_name="tareas:detalle_tarea",
            expected="ingresar",
            actual="modificar",
        )

        self.assertEqual(issue.route_name, "tareas:detalle_tarea")
        self.assertEqual(issue.expected, "ingresar")
        self.assertEqual(issue.actual, "modificar")