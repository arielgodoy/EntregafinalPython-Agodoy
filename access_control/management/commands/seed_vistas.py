from django.core.management.base import BaseCommand


VISTAS = [
    {"nombre": "Settings - Configuracion de Empresa", "descripcion": "Configuración por empresa (UI)"},
    {"nombre": "Settings - Emails Acounts", "descripcion": "Cuentas de correo del sistema"},
    {"nombre": "Settings - Configuración del Sistema", "descripcion": "Configuración global del sistema"},
]


class Command(BaseCommand):
    help = "Crear vistas faltantes requeridas por access_control (idempotente)."

    def handle(self, *args, **options):
        from access_control.models import Vista

        for v in VISTAS:
            obj, created = Vista.objects.get_or_create(
                nombre=v["nombre"],
                defaults={"descripcion": v.get("descripcion", "")},
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Vista creada: {obj.nombre}"))
            else:
                self.stdout.write(f"Existe: {obj.nombre}")
