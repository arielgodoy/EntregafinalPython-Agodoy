from django.core.management.base import BaseCommand, CommandError

from database_manager.services.comparison import compare_databases


class Command(BaseCommand):
    help = 'Compara metadata de dos aliases Django sin escribir en las bases.'

    def add_arguments(self, parser):
        parser.add_argument('source_alias')
        parser.add_argument('target_alias')

    def handle(self, *args, **options):
        result = compare_databases(options['source_alias'], options['target_alias'])
        self.stdout.write(f'Source: {result.source_alias}')
        self.stdout.write(f'Target: {result.target_alias}')
        self.stdout.write(
            f'Classification: {result.source_classification} -> {result.target_classification}'
        )
        self.stdout.write(f'Vendor: {result.source_vendor or "unknown"} -> {result.target_vendor or "unknown"}')
        self.stdout.write(
            f'Migrations: {result.source_migration_count} / {result.target_migration_count} '
            f'(equal={result.migration_sets_equal})'
        )
        self.stdout.write(
            f'Tables: expected={len(result.managed_tables_expected)} '
            f'missing_source={len(result.missing_in_source)} '
            f'missing_target={len(result.missing_in_target)}'
        )
        different_counts = sum(
            item['difference'] != 0 for item in result.table_counts.values()
        )
        self.stdout.write(f'Counts summary: {different_counts} tables differ')
        self.stdout.write(f'Warnings: {len(result.warnings)}')
        for warning in result.warnings:
            self.stdout.write(f'  - {warning}')
        self.stdout.write(f'Blocking errors: {len(result.blocking_errors)}')
        for error in result.blocking_errors:
            self.stdout.write(f'  - {error}')
        self.stdout.write(f'Status: {result.status}')
        if result.status != 'COMPATIBLE':
            raise CommandError('Database comparison blocked')
