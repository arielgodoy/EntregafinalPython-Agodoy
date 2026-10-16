from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from access_control.models import Empresa
from tareas.models import (
    CorrelativoEmpresa,
    Tarea,
    TareaConnectionRole,
    TareaRelacion,
)
from tareas.services.hierarchy_creation import create_child_task_atomic
from tareas.services.task_storage import CreateTaskDraftInput


class AtomicChildTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="2G", descripcion="Fase 2G")
        cls.otra_empresa = Empresa.objects.create(
            codigo="2G-OTRA",
            descripcion="Fase 2G otra empresa",
        )
        cls.actor = User.objects.create_user(
            username="fase-2g-actor",
            password="test-password",
        )
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS",
            source_type="DJANGO",
            django_alias="default",
        )
        CorrelativoEmpresa.objects.create(
            empresa=cls.empresa,
            siguiente_numero=10,
        )

    def _data(self):
        return CreateTaskDraftInput(
            titulo="Hija atómica",
            descripcion="Prueba transaccional",
            prioridad=Tarea.Prioridad.NORMAL,
            responsable_id=None,
            fecha_tope=date(2026, 10, 20),
        )

    def _task(self, empresa=None, *, anulada=False, correlativo="B0000001"):
        return Tarea.objects.create(
            titulo="Padre",
            descripcion="Padre de prueba",
            prioridad=Tarea.Prioridad.NORMAL,
            correlativo=correlativo,
            empresa=empresa or self.empresa,
            creada_por=self.actor,
            anulada=anulada,
        )

    def test_creates_task_and_relation_in_one_operation(self):
        parent = self._task()

        result = create_child_task_atomic(
            self._data(),
            active_company=self.empresa,
            actor=self.actor,
            parent_id=parent.pk,
        )

        self.assertTrue(Tarea.objects.filter(pk=result.task.id).exists())
        self.assertTrue(
            TareaRelacion.objects.filter(
                pk=result.relation_id,
                padre_id=parent.pk,
                hija_id=result.task.id,
            ).exists()
        )

    def test_failure_after_insert_rolls_back_task_and_relation(self):
        parent = self._task()
        before = Tarea.objects.count()

        with patch(
            "tareas.services.hierarchy_creation.validate_relation",
            side_effect=ValidationError("relación inválida"),
        ):
            with self.assertRaises(ValidationError):
                create_child_task_atomic(
                    self._data(),
                    active_company=self.empresa,
                    actor=self.actor,
                    parent_id=parent.pk,
                )

        self.assertEqual(Tarea.objects.count(), before)
        self.assertFalse(
            Tarea.objects.filter(titulo=self._data().titulo).exists()
        )
        self.assertFalse(TareaRelacion.objects.filter(padre_id=parent.pk).exists())

    def test_missing_parent_is_rejected_without_orphan(self):
        before = Tarea.objects.count()

        with self.assertRaises(ValidationError):
            create_child_task_atomic(
                self._data(),
                active_company=self.empresa,
                actor=self.actor,
                parent_id=999999,
            )

        self.assertEqual(Tarea.objects.count(), before)

    def test_parent_from_other_company_is_rejected(self):
        parent = self._task(self.otra_empresa, correlativo="B0000002")
        before = Tarea.objects.count()

        with self.assertRaises(ValidationError):
            create_child_task_atomic(
                self._data(),
                active_company=self.empresa,
                actor=self.actor,
                parent_id=parent.pk,
            )

        self.assertEqual(Tarea.objects.count(), before)

    def test_annulled_parent_is_incompatible(self):
        parent = self._task(anulada=True, correlativo="B0000003")

        with self.assertRaises(ValidationError):
            create_child_task_atomic(
                self._data(),
                active_company=self.empresa,
                actor=self.actor,
                parent_id=parent.pk,
            )

        self.assertFalse(TareaRelacion.objects.filter(padre_id=parent.pk).exists())
