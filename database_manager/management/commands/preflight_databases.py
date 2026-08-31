from django.core.management.base import BaseCommand, CommandError

from database_manager.services.preflight import run_preflight


class Command(BaseCommand):
    help = 'Ejecuta validaciones de solo lectura antes de una futura migracion.'

    def add_arguments(self, parser):
        parser.add_argument('source_alias')
        parser.add_argument('target_alias')

    def handle(self, *args, **options):
        result = run_preflight(options['source_alias'], options['target_alias'])
        self.stdout.write(f'Source: {result.source_alias}')
        self.stdout.write(f'Target: {result.target_alias}')
        for check in result.checks:
            self.stdout.write(f'[{check.status.value}] {check.label}: {check.message}')
        self.stdout.write(
            f'FINAL STATUS: {result.status} '
            f'(warnings={result.summary["warning_count"]}, '
            f'blockers={result.summary["blocking_count"]})'
        )
        if result.status == 'BLOCKED':
            raise CommandError('Database preflight blocked')