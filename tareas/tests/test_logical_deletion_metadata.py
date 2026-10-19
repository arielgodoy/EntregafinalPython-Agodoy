from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
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

    def test_queryset_update_cannot_set_deletion_metadata(self):
        update_fields = {
            "eliminada": True,
            "eliminada_en": timezone.now(),
            "eliminada_por_id": self.actor.pk,
            "eliminacion_operacion_id": uuid4(),
        }
        for manager in (Tarea.objects, Tarea.all_objects, Tarea._base_manager):
            with self.subTest(manager=manager.name):
                with self.assertRaises(ValidationError):
                    manager.filter(pk=self.task.pk).update(**update_fields)

        stored = Tarea.all_objects.get(pk=self.task.pk)
        self.assertFalse(stored.eliminada)
        self.assertIsNone(stored.eliminada_en)
        self.assertIsNone(stored.eliminada_por_id)
        self.assertIsNone(stored.eliminacion_operacion_id)

    def test_bulk_update_cannot_change_deletion_metadata(self):
        candidate = Tarea.all_objects.get(pk=self.task.pk)
        candidate.eliminada = True
        candidate.eliminada_en = timezone.now()
        candidate.eliminada_por_id = self.actor.pk
        candidate.eliminacion_operacion_id = uuid4()
        fields = (
            "eliminada",
            "eliminada_en",
            "eliminada_por",
            "eliminacion_operacion_id",
        )

        for manager in (Tarea.objects, Tarea.all_objects, Tarea._base_manager):
            with self.subTest(manager=manager.name):
                with self.assertRaises(ValidationError):
                    manager.bulk_update([candidate], fields)

        self.assertFalse(Tarea.all_objects.get(pk=self.task.pk).eliminada)

    def test_bulk_create_cannot_create_deleted_tasks_or_update_their_mark(self):
        deleted_task = Tarea(
            titulo="No crear eliminada por bulk",
            empresa=self.empresa,
            creada_por=self.actor,
            correlativo="L0000002",
            eliminada=True,
            eliminada_en=timezone.now(),
            eliminada_por_id=self.actor.pk,
            eliminacion_operacion_id=uuid4(),
        )
        for manager in (Tarea.objects, Tarea.all_objects, Tarea._base_manager):
            with self.subTest(manager=manager.name):
                with self.assertRaises(ValidationError):
                    manager.bulk_create([deleted_task])

        active_task = Tarea(
            titulo="No alterar marca en upsert",
            empresa=self.empresa,
            creada_por=self.actor,
            correlativo="L0000002",
        )
        with self.assertRaises(ValidationError):
            Tarea.objects.bulk_create(
                [active_task],
                update_conflicts=True,
                update_fields=["eliminada"],
                unique_fields=["empresa", "correlativo"],
            )
        self.assertFalse(
            Tarea.all_objects.filter(correlativo="L0000002").exists()
        )

    def test_save_update_fields_cannot_change_deletion_metadata(self):
        self.task.eliminada = True
        self.task.eliminada_en = timezone.now()
        self.task.eliminada_por_id = self.actor.pk
        self.task.eliminacion_operacion_id = uuid4()

        with self.assertRaises(ValidationError):
            self.task.save(
                update_fields=(
                    "eliminada",
                    "eliminada_en",
                    "eliminada_por",
                    "eliminacion_operacion_id",
                )
            )

        self.assertFalse(Tarea.all_objects.get(pk=self.task.pk).eliminada)

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
                table = connection.ops.quote_name(Tarea._meta.db_table)
                deleted_column = connection.ops.quote_name(
                    Tarea._meta.get_field("eliminada").column
                )
                pk_column = connection.ops.quote_name(Tarea._meta.pk.column)
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"UPDATE {table} SET {deleted_column}=%s "
                        f"WHERE {pk_column}=%s",
                        (True, self.task.pk),
                    )


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
