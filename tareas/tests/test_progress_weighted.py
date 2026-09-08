from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from tareas.models import Avance, Hito, MiniTarea
from tareas.services.progress import (
    create_milestone,
    set_manual_progress,
    set_weighted_progress_mode,
    weighted_progress,
)
from tareas.tests.factories import create_empresa, create_tarea, create_user


class WeightedProgressTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa()
        cls.usuario = create_user(username="weighted-progress-user")
        cls.tarea = create_tarea(cls.empresa, cls.usuario)

    def test_create_milestone_belongs_to_task(self):
        hito = create_milestone(self.tarea, "Inspeccion", 100, 2)

        self.assertEqual(hito.tarea, self.tarea)
        self.assertEqual(hito.cumplimiento, Decimal("100.00"))
        self.assertEqual(hito.peso, Decimal("2.00"))

    def test_manual_mode_is_not_changed_by_milestone(self):
        set_manual_progress(self.tarea, 25)

        create_milestone(self.tarea, "Hito", 100, 1)

        self.tarea.avance.refresh_from_db()
        self.assertEqual(self.tarea.avance.modo, Avance.Modo.MANUAL)
        self.assertEqual(self.tarea.avance.porcentaje, Decimal("25.00"))

    def test_weighted_mode_uses_completed_milestone_weights(self):
        set_weighted_progress_mode(self.tarea)

        create_milestone(self.tarea, "Pendiente", 0, 5)
        create_milestone(self.tarea, "Completado", 100, 3)

        self.tarea.avance.refresh_from_db()
        self.assertEqual(self.tarea.avance.porcentaje, Decimal("37.50"))

    def test_multiple_milestones_use_weighted_formula(self):
        set_weighted_progress_mode(self.tarea)

        create_milestone(self.tarea, "Primero", 50, 1)
        create_milestone(self.tarea, "Segundo", 100, 3)

        self.assertEqual(weighted_progress(self.tarea), Decimal("87.50"))

    def test_adding_milestone_redistributes_existing_progress(self):
        set_weighted_progress_mode(self.tarea)
        create_milestone(self.tarea, "Completado", 100, 1)
        create_milestone(self.tarea, "Nuevo", 0, 1)

        self.tarea.avance.refresh_from_db()
        self.assertEqual(self.tarea.avance.porcentaje, Decimal("50.00"))

    def test_milestones_are_ordered_by_creation(self):
        primero = create_milestone(self.tarea, "Primero")
        segundo = create_milestone(self.tarea, "Segundo")

        self.assertEqual(list(Hito.objects.filter(tarea=self.tarea)), [primero, segundo])

    def test_invalid_milestone_does_not_persist(self):
        with self.assertRaises(ValidationError):
            create_milestone(self.tarea, "Invalido", 101, 1)

        self.assertFalse(Hito.objects.filter(tarea=self.tarea).exists())

    def test_manual_progress_is_rejected_in_weighted_mode(self):
        set_weighted_progress_mode(self.tarea)

        with self.assertRaises(ValidationError):
            set_manual_progress(self.tarea, 20)

    def test_mini_tasks_do_not_participate_in_formula(self):
        set_weighted_progress_mode(self.tarea)
        create_milestone(self.tarea, "Completado", 100, 1)
        MiniTarea.objects.create(
            tarea=self.tarea,
            descripcion="Pendiente",
            persona=self.usuario,
        )

        self.assertEqual(weighted_progress(self.tarea), Decimal("100.00"))