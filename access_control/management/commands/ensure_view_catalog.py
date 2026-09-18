from django.core.management.base import BaseCommand, CommandError

from access_control.services.view_catalog import ensure_declared_views_catalog


class Command(BaseCommand):
    help = "Reconcilia el catálogo persistente desde el registry VICMEAS."

    def add_arguments(self, parser):
        parser.add_argument("--app", default="tareas")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Crea Vistas declaradas faltantes y actualiza route_name seguro.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra la reconciliación sin escribir la base de datos.",
        )

    def handle(self, *args, **options):
        if options["apply"] and options["dry_run"]:
            raise CommandError("--apply y --dry-run son opciones excluyentes.")
        dry_run = not options["apply"]
        summary = ensure_declared_views_catalog(
            app=options["app"],
            dry_run=dry_run,
        )
        mode = "DRY-RUN" if dry_run else "APPLY"
        self.stdout.write(
            self.style.WARNING(
                f"{mode} catálogo declarativo: "
                f"creadas {summary.created}, existentes {summary.existing}, "
                f"actualizadas {summary.updated}, "
                f"legacy {len(summary.legacy)}, "
                f"conflictos {len(summary.conflicts)}."
            )
        )
        for item in summary.created_rows:
            self.stdout.write(f"CREAR: {item.nombre} ({item.route_name})")
        for item in summary.updated_rows:
            self.stdout.write(f"ACTUALIZAR route_name: {item.nombre} -> {item.route_name}")
        for item in summary.legacy:
            self.stdout.write(f"LEGACY: {item.nombre} ({item.route_name or 'sin ruta'})")
        for conflict in summary.conflicts:
            self.stdout.write(
                self.style.ERROR(
                    f"CONFLICTO {conflict.code}: {conflict.nombre or conflict.key} - "
                    f"{conflict.detail}"
                )
            )
        self.stdout.write("Permisos creados: 0; permisos modificados: 0; Vistas eliminadas: 0")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN: no se realizaron escrituras."))