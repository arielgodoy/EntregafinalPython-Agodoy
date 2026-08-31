from django.core.management.base import BaseCommand


VISTAS = [
    {
        "nombre": "Control de Acceso - Permisos por Vista",
        "descripcion": "Gestión de permisos ICMEAS por empresa y vista",
        "route_name": "access_control:permisos_por_vista",
    },
    {"nombre": "Settings - Configuracion de Empresa", "descripcion": "Configuración por empresa (UI)"},
    {"nombre": "Settings - Emails Acounts", "descripcion": "Cuentas de correo del sistema"},
    {"nombre": "Settings - Configuración del Sistema", "descripcion": "Configuración global del sistema"},
    {"nombre": "API - Acceso", "descripcion": "Acceso a la API protegido por ICMEAS"},
    {"nombre": "API - Maestros Locales", "descripcion": "Acceso API al maestro de locales"},
]


class Command(BaseCommand):
    help = "Crear vistas faltantes requeridas por access_control (idempotente)."

    def handle(self, *args, **options):
        from access_control.models import Vista

        for v in VISTAS:
            obj, created = Vista.objects.get_or_create(
                nombre=v["nombre"],
                defaults={
                    "descripcion": v.get("descripcion", ""),
                    "route_name": v.get("route_name"),
                },
            )
            route_name = v.get("route_name")
            if route_name and obj.route_name != route_name:
                obj.route_name = route_name
                obj.save(update_fields=["route_name"])
            if created:
                self.stdout.write(self.style.SUCCESS(f"Vista creada: {obj.nombre}"))
            else:
                self.stdout.write(f"Existe: {obj.nombre}")
