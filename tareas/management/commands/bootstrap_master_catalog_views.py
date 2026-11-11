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
        name="Maestros - Proveedores",
        description="Identidad VICMEAS del maestro de proveedores.",
    ),
    ViewBootstrapDefinition(
        name="Tareas - Maestro de locales",
        description="Identidad VICMEAS del maestro de locales.",
        route_name="tareas:locales_maestro",
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
            current_route_name = matches[0].route_name
            if (
                definition.route_name
                and current_route_name not in (None, "", definition.route_name)
            ):
                status = "route_conflict"
            elif definition.route_name and current_route_name != definition.route_name:
                status = "route_missing"
            else:
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
                "current_route_name": matches[0].route_name if matches else None,
                "vista_id": matches[0].pk if matches else None,
            }
        )
    return tuple(plan)


def bootstrap_master_catalog_views(*, apply: bool = False):
    """Create only the approved VICMEAS identities when explicitly requested."""
    plan = inspect_master_catalog_views()
    conflicts = [
        item
        for item in plan
        if item["status"] in {"conflict", "route_conflict"}
    ]
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
            if item["status"] == "route_missing":
                updated = Vista.objects.filter(
                    pk=item["vista_id"],
                    route_name=item["current_route_name"],
                ).update(route_name=definition.route_name)
                if updated != 1:
                    raise CommandError(
                        "La ruta VICMEAS cambió durante el bootstrap."
                    )
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
