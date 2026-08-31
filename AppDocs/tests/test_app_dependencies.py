import ast
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Dependency:
    origin: str
    destination: str
    path: Path
    line: int
    statement: str


def collect_python_dependencies(source, origin, path, project_apps=PROJECT_APPS):
    dependencies = []
    tree = ast.parse(source, filename=str(path))
    project_app_set = set(project_apps)

    for node in ast.walk(tree):
        module_names = []
        if isinstance(node, ast.Import):
            module_names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            module_names = [node.module]

        for module_name in module_names:
            destination = module_name.split(".", 1)[0]
            if destination not in project_app_set or destination == origin:
                continue
            dependencies.append(
                Dependency(
                    origin=origin,
                    destination=destination,
                    path=path,
                    line=node.lineno,
                    statement=ast.get_source_segment(source, node) or module_name,
                )
            )

    return dependencies


def production_dependencies(project_root):
    dependencies = []
    for origin in PROJECT_APPS:
        for path in (project_root / origin).rglob("*.py"):
            relative_path = path.relative_to(project_root)
            if (
                "migrations" in relative_path.parts
                or "tests" in relative_path.parts
                or path.name.endswith("_old.py")
            ):
                continue
            source = path.read_text(encoding="utf-8")
            dependencies.extend(collect_python_dependencies(source, origin, relative_path))
    return dependencies


def is_forbidden_system_to_application(dependency):
    return (
        dependency.origin in SYSTEM_APPS
        and dependency.destination in APPLICATION_APPS
        and (dependency.origin, dependency.destination)
        not in ALLOWED_SYSTEM_TO_APPLICATION_DEPENDENCIES
    )


def application_cycles(dependencies):
    graph = {app_name: set() for app_name in APPLICATION_APPS}
    for dependency in dependencies:
        if dependency.origin in graph and dependency.destination in graph:
            graph[dependency.origin].add(dependency.destination)

    cycles = set()
    for origin in graph:
        stack = [(origin, [origin])]
        while stack:
            current, path = stack.pop()
            for destination in graph[current]:
                if destination == origin and len(path) > 1:
                    cycles.add(frozenset(path))
                elif destination not in path:
                    stack.append((destination, path + [destination]))
    return cycles


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
