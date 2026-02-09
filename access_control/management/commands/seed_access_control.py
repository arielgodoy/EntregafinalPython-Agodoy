from django.core.management.base import BaseCommand

from access_control.models import Vista


class Command(BaseCommand):
    help = 'Crea Vista base requerida para permisos (idempotente).'

    def handle(self, *args, **options):
        vistas = [
            'Maestro Usuarios',
            'system_config',
            'company_config',
            'email_accounts',
        ]
        for vista_nombre in vistas:
            vista, created = Vista.objects.get_or_create(nombre=vista_nombre)
            if created:
                self.stdout.write(self.style.SUCCESS(f'Vista creada: {vista.nombre}'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Vista ya existe: {vista.nombre}'))
