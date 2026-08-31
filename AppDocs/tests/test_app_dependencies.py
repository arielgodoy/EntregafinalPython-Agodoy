from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from AppDocs.app_classification import (
    ALLOWED_APPLICATION_CYCLES,
    ALLOWED_SYSTEM_TO_APPLICATION_DEPENDENCIES,
    APPLICATION_APPS,
    PROJECT_APPS,
    SYSTEM_APPS,
)
from AppDocs.architecture_dependencies import application_cycles, collect_python_dependencies, production_dependencies


def is_forbidden_system_to_application(dependency):
    return (
        dependency.origin in SYSTEM_APPS
        and dependency.destination in APPLICATION_APPS
        and (dependency.origin, dependency.destination)
        not in ALLOWED_SYSTEM_TO_APPLICATION_DEPENDENCIES
    )


class AppDependencyTests(SimpleTestCase):
    def test_system_apps_do_not_import_application_apps_without_allowlist(self):
        dependencies = production_dependencies(Path(settings.BASE_DIR))
        forbidden = [
            dependency
            for dependency in dependencies
            if is_forbidden_system_to_application(dependency)
        ]

        self.assertFalse(
            forbidden,
            "\n".join(
                ["SYSTEM -> APPLICATION dependency is not allowed:"]
                + [
                    "origin: {0.origin}\ndestination: {0.destination}\nfile: {0.path}\nline: {0.line}\nstatement: {0.statement}".format(dependency)
                    for dependency in forbidden
                ]
            ),
        )

    def test_application_cycles_are_explicitly_allowlisted(self):
        cycles = application_cycles(production_dependencies(Path(settings.BASE_DIR)))
        unknown_cycles = cycles - set(ALLOWED_APPLICATION_CYCLES)

        self.assertFalse(
            unknown_cycles,
            "New APPLICATION_APP dependency cycles detected: "
            + ", ".join(" -> ".join(sorted(cycle)) for cycle in unknown_cycles),
        )

    def test_ast_detects_forbidden_and_allowed_dependencies(self):
        forbidden = collect_python_dependencies(
            "from gestiondte.models import Cesion",
            "access_control",
            Path("access_control/example.py"),
        )
        allowed = collect_python_dependencies(
            "from access_control.models import Empresa",
            "gestiondte",
            Path("gestiondte/example.py"),
        )

        self.assertEqual(forbidden[0].origin, "access_control")
        self.assertEqual(forbidden[0].destination, "gestiondte")
        self.assertEqual(forbidden[0].line, 1)
        self.assertTrue(is_forbidden_system_to_application(forbidden[0]))
        self.assertEqual(allowed[0].origin, "gestiondte")
        self.assertEqual(allowed[0].destination, "access_control")
        self.assertFalse(is_forbidden_system_to_application(allowed[0]))
