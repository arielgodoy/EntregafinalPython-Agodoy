import ast
from dataclasses import dataclass
from pathlib import Path

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
class Dependency:
    origin: str
    destination: str
    path: Path
    line: int
    statement: str


@dataclass(frozen=True)
class DynamicDependency:
    origin: str
    destination: str
    path: Path
    line: int
    reference_type: str
    value: str


def _is_production_path(path):
    return (
        "migrations" not in path.parts
        and "tests" not in path.parts
        and "scripts_debug" not in path.parts
        and not path.name.endswith("_old.py")
    )


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
            if destination in project_app_set and destination != origin:
                dependencies.append(Dependency(origin, destination, path, node.lineno, ast.get_source_segment(source, node) or module_name))
    return dependencies


def _literal_string(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else ""


def _add_dynamic(references, origin, destination, path, node, reference_type, value):
    if destination and destination != origin:
        references.append(DynamicDependency(origin, destination, path, node.lineno, reference_type, value))


def collect_dynamic_dependencies(source, origin, path, project_apps=PROJECT_APPS):
    references = []
    tree = ast.parse(source, filename=str(path))
    project_app_set = set(project_apps)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_name(node.func)
        value = _literal_string(node.args[0]) if node.args else None
        if call_name in RELATION_NAMES and value:
            _add_dynamic(references, origin, value.partition(".")[0] if "." in value and value.partition(".")[0] in project_app_set else None, path, node, "model_relation", value)
        elif call_name == "get_model" and value in project_app_set:
            _add_dynamic(references, origin, value, path, node, "apps_get_model", value)
        elif call_name == "import_module" and value:
            _add_dynamic(references, origin, value.split(".", 1)[0] if value.split(".", 1)[0] in project_app_set else None, path, node, "import_module", value)
        elif call_name in URL_REFERENCE_NAMES and value:
            _add_dynamic(references, origin, URL_NAMESPACE_TO_APP.get(value.partition(":")[0]) if ":" in value else None, path, node, call_name, value)
        elif call_name == "include" and value and value.endswith(".urls"):
            _add_dynamic(references, origin, value.split(".", 1)[0], path, node, "include", value)
        for keyword in node.keywords:
            label = _literal_string(keyword.value)
            if keyword.arg == "app_label" and label in project_app_set:
                _add_dynamic(references, origin, label, path, node, "app_label", label)
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for value in [_literal_string(node.left)] + [_literal_string(item) for item in node.comparators]:
                if value in project_app_set:
                    _add_dynamic(references, origin, value, path, node, "app_label_comparison", value)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {target.id for target in targets if isinstance(target, ast.Name)}
            if names & {"ALLOWED_APPS", "APP_MODEL_MAP", "APP_VISTA_NAMES"}:
                nodes = node.value.keys if isinstance(node.value, ast.Dict) else getattr(node.value, "elts", [])
                for value_node in nodes:
                    value = _literal_string(value_node)
                    if value in project_app_set:
                        _add_dynamic(references, origin, value, path, node, "app_label_mapping", value)
    return references


def production_dependencies(project_root, collector=collect_python_dependencies):
    dependencies = []
    for origin in PROJECT_APPS:
        for path in (project_root / origin).rglob("*.py"):
            relative_path = path.relative_to(project_root)
            if _is_production_path(relative_path):
                dependencies.extend(collector(path.read_text(encoding="utf-8"), origin, relative_path))
    return dependencies


def production_dynamic_dependencies(project_root):
    return production_dependencies(project_root, collect_dynamic_dependencies)


def dependency_classification(dependency):
    if dependency.origin in SYSTEM_APPS and dependency.destination in APPLICATION_APPS:
        return "SYSTEM -> APPLICATION"
    if dependency.origin in APPLICATION_APPS and dependency.destination in SYSTEM_APPS:
        return "APPLICATION -> SYSTEM"
    if dependency.origin in APPLICATION_APPS and dependency.destination in APPLICATION_APPS:
        return "APPLICATION -> APPLICATION"
    return "SYSTEM -> SYSTEM"


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
