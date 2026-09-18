from django.core.management.base import BaseCommand, CommandError

from access_control.services.view_reconciliation import (
    ReconciliationError,
    apply_reconciliation,
    preview_reconciliation,
)


class Command(BaseCommand):
    help = "Previsualiza o aplica la reconciliación controlada de rutas VICMEAS."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Aplica la reconciliación transaccional explícita.",
        )

    def handle(self, *args, **options):
        operation = apply_reconciliation if options["apply"] else preview_reconciliation
        try:
            result = operation()
        except ReconciliationError as error:
            raise CommandError(str(error)) from error

        self.stdout.write(f"{result.mode} reconciliación de rutas VICMEAS")
        for _, nombre, route_name in result.would_clear:
            self.stdout.write(f"WOULD_CLEAR: {nombre}.route_name ({route_name})")
        for _, nombre, route_name in result.would_set:
            self.stdout.write(f"WOULD_SET: {nombre}.route_name = {route_name}")
        self.stdout.write(f"Cambios: {result.changed}")
        self.stdout.write(
            "Snapshot: "
            f"vistas={len(result.snapshot.view_rows)}, "
            f"permisos={len(result.snapshot.permission_rows)}, "
            f"perfiles={len(result.snapshot.profile_rows)}, "
            f"preferencias={len(result.snapshot.preference_rows)}, "
            f"search={len(result.snapshot.search_rows)}, "
            f"solicitudes={len(result.snapshot.access_request_rows)}"
        )
        self.stdout.write(f"Permisos modificados: {result.permission_changes}")
        self.stdout.write(f"Vistas eliminadas: {result.deleted_views}")
        self.stdout.write(f"Navegación antes: {result.navigation_before}")
        self.stdout.write(f"Navegación después: {result.navigation_after}")
        self.stdout.write(f"Conflictos: {result.conflicts}")
        for name, passed in result.invariants:
            self.stdout.write(f"INVARIANT {name}: {'OK' if passed else 'FAIL'}")