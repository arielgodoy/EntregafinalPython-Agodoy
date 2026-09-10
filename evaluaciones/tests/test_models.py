from datetime import datetime, timezone as datetime_timezone
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test import override_settings

from evaluaciones.models import Persona, current_month


class PersonaModelTests(SimpleTestCase):
    def test_current_month_returns_valid_month(self):
        self.assertIn(current_month(), range(1, 13))

    def test_persona_uses_current_month_when_mes_is_omitted(self):
        persona = Persona(person_id=1, full_name="Persona de prueba")

        self.assertEqual(persona.mes, current_month())

    @override_settings(SYSTEM_LOCAL_TIME_ZONE="America/Santiago")
    @patch("django.utils.timezone.now")
    def test_current_month_uses_santiago_at_utc_month_boundary(self, mocked_now):
        mocked_now.return_value = datetime(2026, 10, 1, 2, 30, tzinfo=datetime_timezone.utc)

        self.assertEqual(current_month(), 9)
