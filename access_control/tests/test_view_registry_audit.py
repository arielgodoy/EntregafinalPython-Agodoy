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


def _definition_with_bindings(definition, bindings):
    return replace(definition, routes=tuple(bindings))


class ViewRegistryAuditTests(TestCase):
    def test_audit_exposes_unique_route_count_separately_from_method_bindings(self):
        result = audit_app("control_de_proyectos", definitions=())

        self.assertEqual(result.protected_route_count, 19)
        self.assertGreater(len(result.protected_routes), result.protected_route_count)
        self.assertEqual(len(result.protected_route_names), 19)

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