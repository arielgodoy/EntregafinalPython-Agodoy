from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from database_manager.services.comparison import (
    DatabaseSnapshot,
    compare_databases,
)


class DatabaseComparisonTests(SimpleTestCase):
    def setUp(self):
        self.source = DatabaseSnapshot(
            alias='default',
            vendor='sqlite',
            migrations=frozenset({('auth', '0001_initial')}),
            tables=frozenset({'auth_user', 'managed_table'}),
            table_counts={'auth_user': 2, 'managed_table': 1},
            pk_max_values={'auth_user': 2, 'managed_table': 1},
        )
        self.target = DatabaseSnapshot(
            alias='system_test',
            vendor='mysql',
            migrations=frozenset({('auth', '0001_initial')}),
            tables=frozenset({'auth_user', 'managed_table'}),
            table_counts={'auth_user': 0, 'managed_table': 1},
            pk_max_values={'auth_user': None, 'managed_table': 1},
        )
        self.models = [
            SimpleNamespace(_meta=SimpleNamespace(db_table='auth_user')),
            SimpleNamespace(_meta=SimpleNamespace(db_table='managed_table')),
        ]

    def _compare(self, target=None, unmanaged=None):
        with patch(
            'database_manager.services.comparison._read_snapshot',
            side_effect=[self.source, target or self.target],
        ), patch(
            'database_manager.services.comparison._managed_models',
            return_value=self.models,
        ), patch(
            'database_manager.services.comparison._unmanaged_tables',
            return_value=unmanaged or set(),
        ):
            return compare_databases('default', 'system_test')

    def test_equal_migrations_are_compatible_even_when_counts_differ(self):
        result = self._compare()

        self.assertEqual(result.status, 'COMPATIBLE')
        self.assertTrue(result.migration_sets_equal)
        self.assertEqual(result.table_counts['auth_user']['difference'], -2)
        self.assertIn('table row counts differ', result.warnings)

    def test_different_migrations_are_blocked(self):
        target = DatabaseSnapshot(**{**self.target.__dict__, 'migrations': frozenset()})

        result = self._compare(target=target)

        self.assertEqual(result.status, 'BLOCKED')
        self.assertFalse(result.migration_sets_equal)
        self.assertIn('migration sets are different', result.blocking_errors)

    def test_unknown_source_is_blocked(self):
        result = compare_databases('unknown', 'system_test')

        self.assertEqual(result.status, 'BLOCKED')
        self.assertIsNone(result.source_vendor)
        self.assertEqual(result.source_classification, 'UNKNOWN')

    def test_legacy_target_is_blocked(self):
        result = compare_databases('default', 'dinamica')

        self.assertEqual(result.status, 'BLOCKED')
        self.assertIn('not classified as SYSTEM', result.blocking_errors[0])

    def test_missing_managed_table_is_blocked(self):
        target = DatabaseSnapshot(**{**self.target.__dict__, 'tables': frozenset({'auth_user'})})

        result = self._compare(target=target)

        self.assertEqual(result.status, 'BLOCKED')
        self.assertEqual(result.missing_in_target, ['managed_table'])

    def test_unexpected_unmanaged_table_in_target_is_blocked(self):
        target = DatabaseSnapshot(
            **{**self.target.__dict__, 'tables': self.target.tables | {'legacy_table'}}
        )
        result = self._compare(target=target, unmanaged={'legacy_table'})

        self.assertEqual(result.status, 'BLOCKED')
        self.assertEqual(result.managed_false_tables_present, ['legacy_table'])

    def test_missing_migrations_table_is_blocked(self):
        with patch(
            'database_manager.services.comparison._read_snapshot',
            side_effect=RuntimeError('target: missing django_migrations table'),
        ):
            result = compare_databases('default', 'system_test')

        self.assertEqual(result.status, 'BLOCKED')
        self.assertIn('django_migrations', result.blocking_errors[0])

    def test_missing_mysql_host_returns_clear_blocking_error_with_vendors(self):
        mysql_connection = SimpleNamespace(
            vendor='mysql',
            settings_dict={
                'NAME': 'system',
                'HOST': None,
                'USER': 'configured-user',
                'PASSWORD': 'configured-password',
                'PORT': '3306',
            },
        )
        sqlite_connection = SimpleNamespace(vendor='sqlite', settings_dict={})

        with patch(
            'database_manager.services.comparison.connections',
            {'default': sqlite_connection, 'system_test': mysql_connection},
        ), patch('database_manager.services.comparison._read_snapshot') as read_snapshot:
            result = compare_databases('default', 'system_test')

        self.assertEqual(result.status, 'BLOCKED')
        self.assertEqual(result.source_vendor, 'sqlite')
        self.assertEqual(result.target_vendor, 'mysql')
        self.assertEqual(
            result.blocking_errors,
            ['system_test: database host is not configured'],
        )
        read_snapshot.assert_not_called()

    def test_serialized_result_contains_metadata_only(self):
        serialized = repr(self._compare().to_dict())

        self.assertNotIn('password', serialized.lower())
        self.assertNotIn('secret', serialized.lower())
        self.assertNotIn('token_hash', serialized.lower())
        self.assertNotIn('business value', serialized.lower())
