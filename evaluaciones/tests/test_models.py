from datetime import datetime, timezone as datetime_timezone
from importlib import import_module
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test import override_settings

from evaluaciones.models import Persona, current_month


class PersonaModelTests(SimpleTestCase):
    def test_current_month_returns_valid_month(self):
        self.assertIn(current_month(), range(1, 13))

    def test_monthly_period_fields_are_required(self):
        for field_name in ("anio", "mes"):
            field = Persona._meta.get_field(field_name)
            with self.subTest(field=field_name):
                self.assertFalse(field.null)
                self.assertFalse(field.has_default())

    def test_monthly_schema_migration_is_state_only(self):
        migration = import_module(
            "evaluaciones.migrations.0008_persona_monthly_schema_state"
        ).Migration("0008_persona_monthly_schema_state", "evaluaciones")
        operation = migration.operations[0]

        self.assertEqual(operation.database_operations, [])
        self.assertTrue(operation.state_operations)

    @override_settings(SYSTEM_LOCAL_TIME_ZONE="America/Santiago")
    @patch("django.utils.timezone.now")
    def test_current_month_uses_santiago_at_utc_month_boundary(self, mocked_now):
        mocked_now.return_value = datetime(2026, 10, 1, 2, 30, tzinfo=datetime_timezone.utc)

        self.assertEqual(current_month(), 9)
