from collections import Counter, defaultdict
from pathlib import Path

from AppDocs.app_classification import ALLOWED_APPLICATION_CYCLES, ALLOWED_SYSTEM_TO_APPLICATION_DEPENDENCIES, APPLICATION_APPS, SYSTEM_APPS
from AppDocs.architecture_dependencies import application_cycles, dependency_classification, production_dependencies, production_dynamic_dependencies


def _status_and_severity(dependency, dynamic=False):
    classification = dependency_classification(dependency)
    pair = (dependency.origin, dependency.destination)
    if classification == "SYSTEM -> APPLICATION":
        if dynamic:
            return "REPORT_ONLY_DYNAMIC", "MEDIUM"
        if pair in ALLOWED_SYSTEM_TO_APPLICATION_DEPENDENCIES:
            return "ALLOWED_BY_STATIC_ALLOWLIST", "MEDIUM"
        return "BLOCKED_BY_STATIC_RULE", "HIGH"
    if classification == "APPLICATION -> APPLICATION":
        if frozenset(pair) in ALLOWED_APPLICATION_CYCLES:
            return "ALLOWED_APPLICATION_CYCLE", "MEDIUM"
        return "APPLICATION_COUPLING", "LOW"
    return "NORMAL_ALLOWED_DEPENDENCY", "INFO"


def build_report(project_root, allowed_dependencies=ALLOWED_SYSTEM_TO_APPLICATION_DEPENDENCIES):
    static = production_dependencies(project_root)
    dynamic = production_dynamic_dependencies(project_root)
    cycles = application_cycles(static)
    grouped = defaultdict(lambda: {"static": [], "dynamic": []})
    for dependency in static:
        grouped[(dependency.origin, dependency.destination)]["static"].append(dependency)
    for dependency in dynamic:
        grouped[(dependency.origin, dependency.destination)]["dynamic"].append(dependency)
    allowlists = []
    for pair, reason in allowed_dependencies.items():
        references = grouped[pair]
        allowlists.append({"origin": pair[0], "destination": pair[1], "reason": reason, "count": len(references["static"]) + len(references["dynamic"]), "stale": not any(references.values())})
    return {"static": static, "dynamic": dynamic, "cycles": cycles, "groups": grouped, "allowlists": allowlists}


def render_report(report, summary=False):
    static = report["static"]
    dynamic = report["dynamic"]
    classifications = Counter(dependency_classification(item) for item in static + dynamic)
    lines = ["=" * 58, "ARCHITECTURE REPORT", "=" * 58, f"System apps: {', '.join(SYSTEM_APPS)}", f"Application apps: {', '.join(APPLICATION_APPS)}", "", "Summary:", f"  Static dependencies: {len(static)}", f"  Dynamic references: {len(dynamic)}"]
    for classification in ("SYSTEM -> APPLICATION", "APPLICATION -> APPLICATION", "APPLICATION -> SYSTEM", "SYSTEM -> SYSTEM"):
        lines.append(f"  {classification}: {classifications[classification]}")
    lines.append(f"  Application cycles: {len(report['cycles'])}")
    lines.append(f"  Allowlisted dependencies: {len(report['allowlists'])}")
    lines.extend(_render_group_summary(report))
    if summary:
        return "\n".join(lines + _render_allowlists_and_cycles(report))
    lines.extend(_render_allowlists_and_cycles(report))
    for title in ("SYSTEM -> APPLICATION", "APPLICATION -> APPLICATION", "APPLICATION -> SYSTEM", "SYSTEM -> SYSTEM"):
        lines.extend(["", "-" * 58, title, "-" * 58])
        for kind, dependencies in (("static", static), ("dynamic", dynamic)):
            for dependency in sorted((item for item in dependencies if dependency_classification(item) == title), key=lambda item: (item.origin, item.destination, str(item.path), item.line)):
                status, severity = _status_and_severity(dependency, dynamic=kind == "dynamic")
                detail = dependency.statement if kind == "static" else f"{dependency.reference_type}: {dependency.value}"
                lines.extend((f"{dependency.origin} -> {dependency.destination}", f"  status: {status}", f"  severity: {severity}", f"  {kind}: {dependency.path}:{dependency.line} {detail}"))
    return "\n".join(lines)


def _render_allowlists_and_cycles(report):
    lines = ["", "Allowlists:"]
    for item in report["allowlists"]:
        state = "STALE ALLOWLIST" if item["stale"] else "active"
        lines.append(f"  {item['origin']} -> {item['destination']}: {state}; references={item['count']}; {item['reason']}")
    lines.append("Cycles:")
    for cycle in report["cycles"]:
        status = "ALLOWED_APPLICATION_CYCLE" if cycle in ALLOWED_APPLICATION_CYCLES else "NEW_APPLICATION_CYCLE"
        lines.append(f"  {' -> '.join(sorted(cycle))}: {status}")
    for cycle in set(ALLOWED_APPLICATION_CYCLES) - report["cycles"]:
        lines.append(f"  {' -> '.join(sorted(cycle))}: STALE CYCLE ALLOWLIST")
    return lines


def _render_group_summary(report):
    lines = ["", "Dependency pairs:"]
    for (origin, destination), references in sorted(report["groups"].items()):
        sample = (references["static"] or references["dynamic"])[0]
        status, severity = _status_and_severity(sample, dynamic=not references["static"])
        lines.append(
            f"  {origin} -> {destination}: static={len(references['static'])}; "
            f"dynamic={len(references['dynamic'])}; status={status}; severity={severity}"
        )
    return lines


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Report Django app dependencies.")
    parser.add_argument("--summary", action="store_true", help="Show counts, allowlists, and cycles only.")
    args = parser.parse_args()
    print(render_report(build_report(Path.cwd()), summary=args.summary))