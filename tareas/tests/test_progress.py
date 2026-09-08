from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from tareas.models import Avance
from tareas.services.progress import set_manual_progress, set_weighted_progress_mode
from tareas.tests.factories import create_empresa, create_tarea, create_user


class ProgressModeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa()
        cls.usuario = create_user(username="progress-user")
        cls.tarea = create_tarea(cls.empresa, cls.usuario)

    def test_set_manual_progress(self):
        avance = set_manual_progress(self.tarea, 42.5)

        self.assertEqual(avance.modo, Avance.Modo.MANUAL)
        self.assertEqual(avance.porcentaje, Decimal("42.50"))

    def test_manual_progress_rejects_out_of_range_value(self):
        with self.assertRaises(ValidationError):
            set_manual_progress(self.tarea, 100.01)

    def test_set_weighted_progress_mode(self):
        avance = set_weighted_progress_mode(self.tarea)

        self.assertEqual(avance.modo, Avance.Modo.PONDERADO)
        self.assertEqual(avance.porcentaje, Decimal("0.00"))