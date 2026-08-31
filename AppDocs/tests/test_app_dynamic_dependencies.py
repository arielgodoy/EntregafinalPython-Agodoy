import ast
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from AppDocs.app_classification import APPLICATION_APPS, PROJECT_APPS, SYSTEM_APPS


URL_NAMESPACE_TO_APP = {
    "access_control": "access_control",
    "auditoria": "auditoria",
    "biblioteca": "biblioteca",
    "control_de_proyectos": "control_de_proyectos",
    "control_operacional": "control_operacional",
    "dashboard": "dashboard",
    "gestion_dte": "gestiondte",
    "notificaciones": "notificaciones",
}

RELATION_NAMES = {"ForeignKey", "OneToOneField", "ManyToManyField"}
URL_REFERENCE_NAMES = {"reverse", "redirect", "reverse_lazy"}


@dataclass(frozen=True)
class DynamicDependency:
    origin: str
    destination: str
    path: Path
    line: int
    reference_type: str
    value: str


def _literal_string(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _app_from_model_reference(value, project_apps):
    app_name, separator, _ = value.partition(".")
    return app_name if separator and app_name in project_apps else None


def _app_from_url_reference(value):
    namespace, separator, _ = value.partition(":")
    if not separator:
        return None
    return URL_NAMESPACE_TO_APP.get(namespace)


def _add_reference(references, origin, destination, path, node, reference_type, value):
    if destination and destination != origin:
        references.append(
            DynamicDependency(origin, destination, path, node.lineno, reference_type, value)
        )


def collect_dynamic_dependencies(source, origin, path, project_apps=PROJECT_APPS):
    references = []
    tree = ast.parse(source, filename=str(path))
    project_app_set = set(project_apps)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        call_name = _call_name(node.func)
        first_argument = _literal_string(node.args[0]) if node.args else None
        if call_name in RELATION_NAMES and first_argument:
            _add_reference(
                references,
                origin,
                _app_from_model_reference(first_argument, project_app_set),
                path,
                node,
                "model_relation",
                first_argument,
            )
        elif call_name == "get_model" and first_argument in project_app_set:
            _add_reference(references, origin, first_argument, path, node, "apps_get_model", first_argument)
        elif call_name == "import_module" and first_argument:
            _add_reference(
                references,
                origin,
                first_argument.split(".", 1)[0] if first_argument.split(".", 1)[0] in project_app_set else None,
                path,
                node,
                "import_module",
                first_argument,
            )
        elif call_name in URL_REFERENCE_NAMES and first_argument:
            _add_reference(
                references, origin, _app_from_url_reference(first_argument), path, node, call_name, first_argument
            )
        elif call_name == "include" and first_argument:
            _add_reference(
                references,
                origin,
                first_argument.split(".", 1)[0] if first_argument.endswith(".urls") else None,
                path,
                node,
                "include",
                first_argument,
            )

        for keyword in node.keywords:
            value = _literal_string(keyword.value)
            if keyword.arg == "app_label" and value in project_app_set:
                _add_reference(references, origin, value, path, node, "app_label", value)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        values = [_literal_string(node.left)] + [_literal_string(comparator) for comparator in node.comparators]
        for value in values:
            if value in project_app_set:
                _add_reference(references, origin, value, path, node, "app_label_comparison", value)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        target_names = {target.id for target in targets if isinstance(target, ast.Name)}
        if not target_names & {"ALLOWED_APPS", "APP_MODEL_MAP", "APP_VISTA_NAMES"}:
            continue
        values = node.value.keys if isinstance(node.value, ast.Dict) else node.value.elts if isinstance(node.value, (ast.Set, ast.Tuple, ast.List)) else []
        for value_node in values:
            value = _literal_string(value_node)
            if value in project_app_set:
                _add_reference(references, origin, value, path, node, "app_label_mapping", value)

    return references


def production_dynamic_dependencies(project_root):
    references = []
    for origin in PROJECT_APPS:
        for path in (project_root / origin).rglob("*.py"):
            relative_path = path.relative_to(project_root)
            if (
                "migrations" in relative_path.parts
                or "tests" in relative_path.parts
                or path.name.endswith("_old.py")
            ):
                continue
            references.extend(
                collect_dynamic_dependencies(path.read_text(encoding="utf-8"), origin, relative_path)
            )
    return references


def dependency_classification(reference):
    if reference.origin in SYSTEM_APPS and reference.destination in APPLICATION_APPS:
        return "SYSTEM -> APPLICATION"
    if reference.origin in APPLICATION_APPS and reference.destination in SYSTEM_APPS:
        return "APPLICATION -> SYSTEM"
    if reference.origin in APPLICATION_APPS and reference.destination in APPLICATION_APPS:
        return "APPLICATION -> APPLICATION"
    return "SYSTEM -> SYSTEM"


class AppDynamicDependencyTests(SimpleTestCase):
    def test_detector_finds_literal_django_reference_types(self):
        source = "\n".join(
            (
                'models.ForeignKey("gestiondte.Cesion", on_delete=models.CASCADE)',
                'apps.get_model("biblioteca", "Propietario")',
                'reverse("gestion_dte:detalle")',
                'import_module("biblioteca.services")',
                'ContentType.objects.get(app_label="biblioteca", model="propiedad")',
            )
        )
        references = collect_dynamic_dependencies(source, "access_control", Path("access_control/example.py"))

        self.assertEqual(
            {(reference.reference_type, reference.destination) for reference in references},
            {
                ("model_relation", "gestiondte"),
                ("apps_get_model", "biblioteca"),
                ("reverse", "gestiondte"),
                ("import_module", "biblioteca"),
                ("app_label", "biblioteca"),
            },
        )

    def test_application_to_system_relation_is_classified_as_permitted_direction(self):
        references = collect_dynamic_dependencies(
            'models.ForeignKey("access_control.Empresa", on_delete=models.CASCADE)',
            "gestiondte",
            Path("gestiondte/example.py"),
        )

        self.assertEqual(references[0].destination, "access_control")
        self.assertEqual(dependency_classification(references[0]), "APPLICATION -> SYSTEM")

    def test_current_dynamic_inventory_contains_known_references(self):
        references = production_dynamic_dependencies(Path(settings.BASE_DIR))
        identities = {(reference.origin, reference.destination, reference.reference_type) for reference in references}

        self.assertIn(("auditoria", "biblioteca", "app_label_comparison"), identities)
        self.assertIn(("auditoria", "biblioteca", "app_label_mapping"), identities)
        self.assertIn(("auditoria", "gestiondte", "app_label_mapping"), identities)
        self.assertIn(("control_de_proyectos", "biblioteca", "model_relation"), identities)
        self.assertIn(("control_operacional", "control_de_proyectos", "reverse"), identities)