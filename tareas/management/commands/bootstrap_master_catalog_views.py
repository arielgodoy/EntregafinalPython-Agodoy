from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from access_control.models import Vista


@dataclass(frozen=True)
class ViewBootstrapDefinition:
    name: str
    description: str
    route_name: str | None = None


MASTER_CATALOG_VIEWS = (
    ViewBootstrapDefinition(
        name="Proveedores - Maestro",
        description="Identidad VICMEAS del maestro de proveedores.",
    ),
    ViewBootstrapDefinition(
        name="Tareas - Maestro de locales",
        description="Identidad VICMEAS del maestro de locales.",
    ),
    ViewBootstrapDefinition(
        name="Tareas - Maestro de departamentos",
        description="Identidad VICMEAS del maestro de departamentos.",
        route_name="tareas:departamentos_maestro",
    ),
)


def inspect_master_catalog_views():
    """Return a read-only plan without creating views or permissions."""
    plan = []
    for definition in MASTER_CATALOG_VIEWS:
        matches = list(Vista.objects.filter(nombre=definition.name).order_by("pk"))
        if len(matches) > 1:
            status = "conflict"
        elif matches:
            status = "exists"
        else:
            status = "missing"
        plan.append(
            {
                "name": definition.name,
                "status": status,
                "count": len(matches),
                "description": definition.description,
                "route_name": definition.route_name,
            }
        )
    return tuple(plan)


def bootstrap_master_catalog_views(*, apply: bool = False):
    """Create only the approved VICMEAS identities when explicitly requested."""
    plan = inspect_master_catalog_views()
    conflicts = [item for item in plan if item["status"] == "conflict"]
    if conflicts:
        raise CommandError(
            "Existen identidades VICMEAS duplicadas para el bootstrap aprobado."
        )
    if not apply:
        return plan

    with transaction.atomic():
        for definition, item in zip(MASTER_CATALOG_VIEWS, plan):
            if item["status"] == "exists":
                continue
            defaults = {"descripcion": definition.description}
            if definition.route_name:
                defaults["route_name"] = definition.route_name
            Vista.objects.create(nombre=definition.name, **defaults)
    return inspect_master_catalog_views()


class Command(BaseCommand):
    help = (
        "Inspecciona las identidades VICMEAS de los maestros; "
        "solo --apply permite crearlas."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Crear únicamente las Vistas aprobadas; no asigna permisos.",
        )

    def handle(self, *args, **options):
        plan = bootstrap_master_catalog_views(apply=options["apply"])
        mode = "aplicado" if options["apply"] else "inspección"
        self.stdout.write(f"bootstrap_mode={mode}")
        for item in plan:
            self.stdout.write(
                f"name={item['name']} status={item['status']} count={item['count']}"
            )
