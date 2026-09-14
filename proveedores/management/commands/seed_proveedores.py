from django.core.management.base import BaseCommand

from access_control.models import Vista


class Command(BaseCommand):
    help = "Registra de forma idempotente la Vista VICMEAS del maestro de proveedores."

    def handle(self, *args, **options):
        vista, created = Vista.objects.update_or_create(
            nombre="Proveedores - Maestro",
            defaults={
                "descripcion": "Maestro global de proveedores",
                "route_name": "proveedores:listado",
            },
        )
        estado = "creada" if created else "actualizada"
        self.stdout.write(self.style.SUCCESS(f"Vista {estado}: {vista.nombre}"))
