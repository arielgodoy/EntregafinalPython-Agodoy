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
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user


class WeightedProgressTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa()
        cls.usuario = create_user(username="weighted-progress-user")
        assign_permission(cls.usuario, cls.empresa, "Tareas - Hitos", ingresar=True, modificar=True)
        cls.tarea = create_tarea(cls.empresa, cls.usuario, responsable=cls.usuario)

    def _create(self, nombre, cumplimiento=0, peso=1, responsable=None):
        return create_milestone(
            self.tarea,
            nombre,
            cumplimiento,
            peso,
            responsable=responsable or self.usuario,
            actor=self.usuario,
        )

    def test_create_milestone_belongs_to_task(self):
        hito = self._create("Inspeccion", 100, 2)

        self.assertEqual(hito.tarea, self.tarea)
        self.assertEqual(hito.cumplimiento, Decimal("100.00"))
        self.assertEqual(hito.peso, Decimal("2.00"))

    def test_manual_mode_is_not_changed_by_milestone(self):
        set_manual_progress(self.tarea, 25)

        self._create("Hito", 100, 1)

        self.tarea.avance.refresh_from_db()
        self.assertEqual(self.tarea.avance.modo, Avance.Modo.MANUAL)
        self.assertEqual(self.tarea.avance.porcentaje, Decimal("25.00"))

    def test_weighted_mode_uses_completed_milestone_weights(self):
        set_weighted_progress_mode(self.tarea)

        self._create("Pendiente", 0, 5)
        self._create("Completado", 100, 3)

        self.tarea.avance.refresh_from_db()
        self.assertEqual(self.tarea.avance.porcentaje, Decimal("37.50"))

    def test_multiple_milestones_use_weighted_formula(self):
        set_weighted_progress_mode(self.tarea)

        self._create("Primero", 50, 1)
        self._create("Segundo", 100, 3)

        self.assertEqual(weighted_progress(self.tarea), Decimal("87.50"))

    def test_adding_milestone_redistributes_existing_progress(self):
        set_weighted_progress_mode(self.tarea)
        anterior = self._create("Completado", 100, 4)
        self.tarea.avance.refresh_from_db()
        porcentaje_previo = self.tarea.avance.porcentaje
        fecha_previa = anterior.fecha_creacion

        nuevo = self._create("Nuevo", 0, 1)

        self.tarea.avance.refresh_from_db()
        anterior.refresh_from_db()
        self.assertEqual(porcentaje_previo, Decimal("100.00"))
        self.assertEqual(anterior.cumplimiento, Decimal("100.00"))
        self.assertEqual(anterior.peso, Decimal("4.00"))
        self.assertEqual(anterior.fecha_creacion, fecha_previa)
        self.assertEqual(self.tarea.avance.porcentaje, Decimal("80.00"))
        self.assertEqual(nuevo.cumplimiento, Decimal("0.00"))

    def test_adding_partially_completed_milestone_recalculates_progress(self):
        set_weighted_progress_mode(self.tarea)
        anterior = self._create("Completado", 100, 4)

        self._create("En curso", 50, 1)

        anterior.refresh_from_db()
        self.tarea.avance.refresh_from_db()
        self.assertEqual(anterior.cumplimiento, Decimal("100.00"))
        self.assertEqual(self.tarea.avance.porcentaje, Decimal("90.00"))

    def test_successive_milestones_preserve_previous_identity_and_completion(self):
        set_weighted_progress_mode(self.tarea)
        primero = self._create("Primero", 100, 4)
        segundo = self._create("Segundo", 50, 1)
        ids_previos = (primero.pk, segundo.pk)

        tercero = self._create("Tercero", 0, 2)

        primero.refresh_from_db()
        segundo.refresh_from_db()
        self.tarea.avance.refresh_from_db()
        self.assertEqual((primero.pk, segundo.pk), ids_previos)
        self.assertEqual(primero.cumplimiento, Decimal("100.00"))
        self.assertEqual(primero.peso, Decimal("4.00"))
        self.assertEqual(segundo.cumplimiento, Decimal("50.00"))
        formula = (
            (primero.cumplimiento * primero.peso)
            + (segundo.cumplimiento * segundo.peso)
            + (tercero.cumplimiento * tercero.peso)
        ) / (primero.peso + segundo.peso + tercero.peso)
        self.assertEqual(formula.quantize(Decimal("0.01")), Decimal("64.29"))
        self.assertEqual(self.tarea.avance.porcentaje, Decimal("64.29"))
        self.assertEqual(tercero.cumplimiento, Decimal("0.00"))

    def test_milestones_are_ordered_by_creation(self):
        primero = self._create("Primero")
        segundo = self._create("Segundo")

        self.assertEqual(list(Hito.objects.filter(tarea=self.tarea)), [primero, segundo])

    def test_invalid_milestone_does_not_persist(self):
        set_weighted_progress_mode(self.tarea)
        anterior = self._create("Valido", 100, 1)
        self.tarea.avance.refresh_from_db()
        porcentaje_previo = self.tarea.avance.porcentaje

        with self.assertRaises(ValidationError):
            self._create("Invalido", 101, 1)

        self.assertEqual(Hito.objects.filter(tarea=self.tarea).count(), 1)
        anterior.refresh_from_db()
        self.tarea.avance.refresh_from_db()
        self.assertEqual(anterior.cumplimiento, Decimal("100.00"))
        self.assertEqual(self.tarea.avance.porcentaje, porcentaje_previo)

    def test_manual_progress_is_rejected_in_weighted_mode(self):
        set_weighted_progress_mode(self.tarea)

        with self.assertRaises(ValidationError):
            set_manual_progress(self.tarea, 20)

    def test_mini_tasks_do_not_participate_in_formula(self):
        set_weighted_progress_mode(self.tarea)
        self._create("Completado", 100, 1)
        MiniTarea.objects.create(
            tarea=self.tarea,
            descripcion="Pendiente",
            persona=self.usuario,
        )

        self.assertEqual(weighted_progress(self.tarea), Decimal("100.00"))