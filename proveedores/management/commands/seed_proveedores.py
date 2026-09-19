from django.core.management.base import BaseCommand

from access_control.services.view_catalog import ensure_declared_views_catalog


class Command(BaseCommand):
    help = "Registra de forma idempotente la Vista VICMEAS del maestro de proveedores."

    def handle(self, *args, **options):
        result = ensure_declared_views_catalog(app="proveedores", dry_run=False)
        if result.created:
            self.stdout.write(self.style.SUCCESS("Vista creada: Maestros - Proveedores"))
        elif result.updated:
            self.stdout.write(self.style.SUCCESS("Vista actualizada: Maestros - Proveedores"))
        else:
            self.stdout.write(self.style.SUCCESS("Vista existente: Maestros - Proveedores"))
