from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from gestiondte.models import LecturaAutomaticaConfig
from gestiondte.services.lectura_automatica import ejecutar_lote, rango_automatico


class Command(BaseCommand):
    help = 'Ejecuta la lectura automática de cesiones RPETC si corresponde.'

    def handle(self, *args, **options):
        config = LecturaAutomaticaConfig.objects.filter(pk=1).first()
        if not config or not config.habilitado:
            self.stdout.write('Lectura automática deshabilitada.')
            return
        ahora = timezone.now()
        if config.proxima_ejecucion and config.proxima_ejecucion > ahora:
            self.stdout.write('Aún no corresponde ejecutar la lectura automática.')
            return
        desde, hasta = rango_automatico(ahora.date())
        resultado = ejecutar_lote(
            desde,
            hasta,
            tipo_ejecucion='AUTOMATICA',
            ahora=ahora,
        )
        if resultado['bloqueado']:
            self.stdout.write(self.style.WARNING('Ya existe una lectura de cesiones en proceso.'))
            return
        errores = sum(1 for ejecucion in resultado['ejecuciones'] if ejecucion.estado == 'ERROR')
        if errores:
            self.stdout.write(self.style.WARNING(
                f'Lectura automática finalizada con {errores} empresa(s) en error.'
            ))
            raise CommandError('La lectura automática terminó con errores por empresa.')
        else:
            self.stdout.write(self.style.SUCCESS('Lectura automática finalizada correctamente.'))
