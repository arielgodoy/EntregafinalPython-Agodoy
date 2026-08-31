from types import SimpleNamespace
from unittest.mock import patch
from contextlib import nullcontext

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from database_manager.services.preflight import (
    PreflightCheckStatus,
    PreflightResult,
    _check,
    _unique_check,
    run_preflight,
)


class PreflightServiceTests(SimpleTestCase):
    def comparison(self, **overrides):
        result = {
            'source_alias': 'default', 'target_alias': 'system_test',
            'source_classification': 'SYSTEM', 'target_classification': 'SYSTEM',
            'status': 'COMPATIBLE', 'blocking_errors': [],
            'migration_sets_equal': True, 'migrations_only_source': [], 'migrations_only_target': [],
            'missing_in_source': [], 'missing_in_target': [],
            'managed_false_tables_present': [], 'managed_tables_expected': [],
            'table_counts': {}, 'pk_max_values': {},
        }
        result.update(overrides)
        return result

    def execute_preflight(self, comparison=None, extra_checks=None):
        extra_checks = extra_checks or []
        with patch('database_manager.services.preflight.compare_databases', return_value=SimpleNamespace(to_dict=lambda: comparison or self.comparison())), \
             patch('database_manager.services.preflight._managed_models', return_value=[]), \
             patch('database_manager.services.preflight._schema_check', return_value=_check('schema', 'Schema', PreflightCheckStatus.PASS, 'ok')), \
             patch('database_manager.services.preflight._foreign_key_check', return_value=_check('foreign_keys', 'Foreign keys', PreflightCheckStatus.PASS, 'ok')), \
             patch('database_manager.services.preflight._unique_check', return_value=_check('unique_constraints', 'Unique constraints', PreflightCheckStatus.PASS, 'ok')), \
             patch('database_manager.services.preflight._destination_check', return_value=_check('destination', 'Destination', PreflightCheckStatus.PASS, 'ok')), \
             patch('database_manager.services.preflight._autoincrement_check', return_value=_check('autoincrement', 'Autoincrement', PreflightCheckStatus.NOT_CHECKED, 'not checked')), \
             patch('database_manager.services.preflight._data_integrity_checks', return_value=extra_checks):
            return run_preflight('default', 'system_test')

    def test_blocked_comparison_stops_dependent_checks(self):
        result = self.execute_preflight(self.comparison(status='BLOCKED', blocking_errors=['migration sets are different']))

        self.assertEqual(result.status, 'BLOCKED')
        self.assertEqual([check.key for check in result.checks], ['classification', 'comparison'])

    def test_migration_difference_blocks_preflight(self):
        result = self.execute_preflight(self.comparison(migration_sets_equal=False, migrations_only_source=[('app', '0002')]))

        self.assertEqual(next(check for check in result.checks if check.key == 'migrations').status, PreflightCheckStatus.BLOCKED)
        self.assertEqual(result.status, 'BLOCKED')

    def test_missing_managed_table_and_managed_false_block(self):
        result = self.execute_preflight(self.comparison(missing_in_target=['app_item'], managed_false_tables_present=['legacy_table']))

        statuses = {check.key: check.status for check in result.checks}
        self.assertEqual(statuses['managed_tables'], PreflightCheckStatus.BLOCKED)
        self.assertEqual(statuses['managed_false'], PreflightCheckStatus.BLOCKED)

    def test_schema_fk_and_unique_blocks_are_propagated(self):
        checks = [
            _check('schema', 'Schema', PreflightCheckStatus.BLOCKED, 'column missing'),
            _check('foreign_keys', 'Foreign keys', PreflightCheckStatus.BLOCKED, 'FK missing'),
            _check('unique_constraints', 'Unique constraints', PreflightCheckStatus.BLOCKED, 'unique missing'),
        ]
        result = self.execute_preflight(extra_checks=checks)

        self.assertEqual(result.status, 'BLOCKED')

    def test_warning_conditions_do_not_block(self):
        result = self.execute_preflight(extra_checks=[
            _check('destination_data', 'Destination data', PreflightCheckStatus.WARNING, 'target contains data'),
            _check('pk_max', 'Maximum PK values', PreflightCheckStatus.WARNING, 'target PK is greater'),
        ])

        self.assertEqual(result.status, 'WARNING')
        self.assertEqual(result.summary['warning_count'], 2)
        self.assertEqual(result.summary['blocking_count'], 0)

    def test_non_system_target_blocks_classification(self):
        result = self.execute_preflight(self.comparison(target_classification='LEGACY', status='BLOCKED', blocking_errors=['target alias is not classified as SYSTEM']))

        self.assertEqual(result.checks[0].status, PreflightCheckStatus.BLOCKED)
        self.assertEqual(result.status, 'BLOCKED')

    def test_result_is_serializable_and_contains_no_secrets(self):
        result = self.execute_preflight()
        serialized = repr(result.to_dict()).lower()

        self.assertNotIn('password', serialized)
        self.assertNotIn('token', serialized)
        self.assertNotIn('credential', serialized)

    def test_unique_check_normalizes_foreign_key_columns(self):
        empresa_field = SimpleNamespace(column='empresa_id', unique=False)
        cesion_field = SimpleNamespace(column='cesion_id', unique=False)
        model_meta = SimpleNamespace(
            db_table='app_relation',
            local_fields=[empresa_field, cesion_field],
            constraints=[SimpleNamespace(fields=('empresa', 'cesion'))],
            get_field=lambda name: {
                'empresa': empresa_field,
                'cesion': cesion_field,
            }[name],
        )
        model = SimpleNamespace(_meta=model_meta)
        cursor_context = object()
        connection = SimpleNamespace(
            cursor=lambda: nullcontext(cursor_context),
            introspection=SimpleNamespace(
                get_constraints=lambda cursor, table: {
                    'target_unique': {'columns': ['empresa_id', 'cesion_id'], 'unique': True},
                }
            ),
        )

        with patch('database_manager.services.preflight.connections', {'system_test': connection}), \
             patch('database_manager.services.preflight.models.UniqueConstraint', SimpleNamespace):
            check = _unique_check('system_test', [model])

        self.assertEqual(check.status, PreflightCheckStatus.PASS)


class PreflightCommandTests(SimpleTestCase):
    @patch('database_manager.management.commands.preflight_databases.run_preflight')
    def test_command_reports_ready_or_warning_without_error(self, run_preflight):
        run_preflight.return_value = PreflightResult('default', 'system_test', {}, [
            _check('classification', 'Classification', PreflightCheckStatus.PASS, 'ok'),
        ])

        call_command('preflight_databases', 'default', 'system_test')

    @patch('database_manager.management.commands.preflight_databases.run_preflight')
    def test_command_returns_error_for_blocked_result(self, run_preflight):
        run_preflight.return_value = PreflightResult('default', 'system_test', {}, [
            _check('classification', 'Classification', PreflightCheckStatus.BLOCKED, 'blocked'),
        ])

        with self.assertRaises(CommandError):
            call_command('preflight_databases', 'default', 'system_test')