from django.core.management.base import BaseCommand

from access_control.models import Vista, PerfilAcceso, PerfilAccesoDetalle


class Command(BaseCommand):
    help = 'Crea Vista base requerida para permisos (idempotente).'

    def handle(self, *args, **options):
        vistas = [
            'Maestro Usuarios',
            'auth_invite',
            'invitaciones',
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

        perfiles = [
            {
                'nombre': 'Usuario (Basico)',
                'descripcion': 'Acceso basico',
                'detalles': {
                    'Maestro Usuarios': {
                        'ingresar': True,
                    },
                },
            },
            {
                'nombre': 'Profesional',
                'descripcion': 'Acceso ampliado',
                'detalles': {
                    'Maestro Usuarios': {
                        'ingresar': True,
                        'crear': True,
                    },
                },
            },
            {
                'nombre': 'Administrador',
                'descripcion': 'Acceso total',
                'detalles': {
                    'Maestro Usuarios': {
                        'ingresar': True,
                        'crear': True,
                        'modificar': True,
                        'eliminar': True,
                        'autorizar': True,
                        'supervisor': True,
                    },
                },
            },
        ]

        for perfil_data in perfiles:
            perfil, created = PerfilAcceso.objects.get_or_create(
                nombre=perfil_data['nombre'],
                defaults={
                    'descripcion': perfil_data['descripcion'],
                    'is_active': True,
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Perfil creado: {perfil.nombre}'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Perfil ya existe: {perfil.nombre}'))

            for vista_nombre, flags in perfil_data['detalles'].items():
                vista = Vista.objects.filter(nombre=vista_nombre).first()
                if not vista:
                    self.stdout.write(self.style.WARNING(
                        f'Vista no encontrada para perfil {perfil.nombre}: {vista_nombre}'
                    ))
                    continue

                defaults = {
                    'ingresar': flags.get('ingresar', False),
                    'crear': flags.get('crear', False),
                    'modificar': flags.get('modificar', False),
                    'eliminar': flags.get('eliminar', False),
                    'autorizar': flags.get('autorizar', False),
                    'supervisor': flags.get('supervisor', False),
                }
                PerfilAccesoDetalle.objects.get_or_create(
                    perfil=perfil,
                    vista=vista,
                    defaults=defaults,
                )
