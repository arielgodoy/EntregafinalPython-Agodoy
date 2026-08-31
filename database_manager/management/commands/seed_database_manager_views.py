from django.core.management.base import BaseCommand


VISTAS = (
    {
        'nombre': 'Gestión de Bases - Dashboard',
        'route_name': 'database_manager:dashboard',
        'descripcion': 'Panel de gestión de bases del sistema.',
    },
    {
        'nombre': 'Gestión de Bases - Comparar',
        'route_name': 'database_manager:compare',
        'descripcion': 'Comparación de bases del sistema.',
    },
    {
        'nombre': 'Gestión de Bases - Preflight',
        'route_name': 'database_manager:preflight',
        'descripcion': 'Validación previa de bases del sistema.',
    },
)


class Command(BaseCommand):
    help = 'Registra las vistas ICMEAS de database_manager.'

    def handle(self, *args, **options):
        from access_control.models import Vista

        for item in VISTAS:
            vista, created = Vista.objects.update_or_create(
                nombre=item['nombre'],
                defaults={
                    'route_name': item['route_name'],
                    'descripcion': item['descripcion'],
                },
            )
            action = 'creada' if created else 'actualizada'
            self.stdout.write(f'Vista {action}: {vista.nombre}')
