from django.core.management.base import BaseCommand


VISTAS = [
    {
        "nombre": "Control de Acceso - Permisos por Vista",
        "descripcion": "Gestión de permisos ICMEAS por empresa y vista",
        "route_name": "access_control:permisos_por_vista",
    },
    {
        "nombre": "Control de Acceso - Utilitario de Acceso",
        "descripcion": "Asignación masiva aditiva de permisos VICMEAS",
        "route_name": "access_control:utilitario_acceso",
    },
    {"nombre": "Configuración - Configuracion de Empresa", "descripcion": "Configuración por empresa (UI)"},
    {"nombre": "Configuración - Cuentas de Correo", "descripcion": "Cuentas de correo del sistema"},
    {"nombre": "Configuración - Configuración del Sistema", "descripcion": "Configuración global del sistema"},
    {
        "nombre": "Gestion DTE - Conexiones SQL",
        "descripcion": "Configuración global de roles de conexión Gestión DTE",
        "route_name": "gestion_dte:connection_roles",
        "legacy_names": ("Configuración - Conexiones Gestión DTE",),
    },
    {"nombre": "API - Acceso", "descripcion": "Acceso a la API protegido por ICMEAS"},
    {"nombre": "API - Maestros Locales", "descripcion": "Acceso API al maestro de locales"},
]


class Command(BaseCommand):
    help = "Crear vistas faltantes requeridas por access_control (idempotente)."

    def handle(self, *args, **options):
        from access_control.models import Vista

        for v in VISTAS:
            route_name = v.get("route_name")
            obj = Vista.objects.filter(route_name=route_name).first() if route_name else None
            if obj is None:
                names = (v["nombre"],) + tuple(v.get("legacy_names", ()))
                obj = Vista.objects.filter(nombre__in=names).first()
            created = obj is None
            if obj is None:
                obj = Vista.objects.create(
                    nombre=v["nombre"],
                    descripcion=v.get("descripcion", ""),
                    route_name=route_name,
                )
            updates = []
            if obj.nombre != v["nombre"]:
                obj.nombre = v["nombre"]
                updates.append("nombre")
            if route_name and obj.route_name != route_name:
                obj.route_name = route_name
                updates.append("route_name")
            if updates:
                obj.save(update_fields=updates)
            if created:
                self.stdout.write(self.style.SUCCESS(f"Vista creada: {obj.nombre}"))
            else:
                self.stdout.write(f"Existe: {obj.nombre}")
