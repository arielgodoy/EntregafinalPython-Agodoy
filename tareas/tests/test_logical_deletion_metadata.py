from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from tareas.models import (
    LOGICAL_DELETION_RESULT_CODE,
    Tarea,
    TareaEliminacionOperacion,
)
from tareas.tests.factories import create_empresa, create_tarea, create_user


class TareaLogicalDeletionMetadataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa("LDM", "Empresa eliminación lógica")
        cls.actor = create_user("logical-deletion-actor")
        cls.task = create_tarea(
            cls.empresa,
            cls.actor,
            titulo="Tarea conservada",
            correlativo="L0000001",
        )

    def test_new_tasks_have_clear_logical_deletion_metadata(self):
        self.assertFalse(self.task.eliminada)
        self.assertIsNone(self.task.eliminada_en)
        self.assertIsNone(self.task.eliminada_por_id)
        self.assertIsNone(self.task.eliminacion_operacion_id)

    def test_complete_metadata_is_persisted_without_changing_lifecycle(self):
        operation_id = uuid4()
        original_state = self.task.estado
        original_annulled = self.task.anulada
        self.task.eliminada = True
        self.task.eliminada_en = timezone.now()
        self.task.eliminada_por = self.actor
        self.task.eliminacion_operacion_id = operation_id
        self.task.save(
            update_fields=[
                "eliminada",
                "eliminada_en",
                "eliminada_por",
                "eliminacion_operacion_id",
            ]
        )

        stored = Tarea.objects.get(pk=self.task.pk)
        self.assertTrue(stored.eliminada)
        self.assertEqual(stored.eliminacion_operacion_id, operation_id)
        self.assertEqual(stored.eliminada_por_id, self.actor.pk)
        self.assertIsNotNone(stored.eliminada_en)
        self.assertEqual(stored.estado, original_state)
        self.assertEqual(stored.anulada, original_annulled)

    def test_model_validation_requires_all_deletion_metadata_together(self):
        self.task.eliminada = True

        with self.assertRaises(ValidationError) as raised:
            self.task.clean()

        self.assertIn("eliminada", raised.exception.message_dict)

        self.task.eliminada = False
        self.task.eliminada_en = timezone.now()
        with self.assertRaises(ValidationError) as raised:
            self.task.clean()
        self.assertIn("eliminada", raised.exception.message_dict)

    def test_database_constraint_rejects_partial_deletion_metadata(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Tarea.objects.filter(pk=self.task.pk).update(eliminada=True)


class DeletionOperationReasonTests(TestCase):
    def test_logical_deletion_result_requires_a_nonblank_reason(self):
        operation = TareaEliminacionOperacion(
            actor_id=1,
            empresa_id=1,
            root_task_id=1,
            root_correlativo="L0000001",
            backend_type="DJANGO",
            backend_identity="django:default",
            fingerprint="a" * 64,
            result_code=LOGICAL_DELETION_RESULT_CODE,
            motivo="   ",
        )

        with self.assertRaises(ValidationError) as raised:
            operation.clean()

        self.assertIn("motivo", raised.exception.message_dict)

        operation.motivo = "Resguardo administrativo"
        operation.clean()
