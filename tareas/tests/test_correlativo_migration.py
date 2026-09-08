from importlib import import_module
from types import SimpleNamespace

from django.apps import apps as django_apps
from django.db import connection, transaction
from django.test import TransactionTestCase

from access_control.models import Empresa
from tareas.models import Tarea


forwards = import_module(
    "tareas.migrations.0007_swap_correlativo_prefixes"
).forwards


class CorrelativoMigrationTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="MIG", descripcion="Migracion")
        self.creator = Tarea._meta.get_field("creada_por").remote_field.model.objects.create_user(
            username="migration_creator"
        )

    def _run_forward(self):
        forwards(django_apps, SimpleNamespace(connection=connection))

    def test_remaps_historical_prefixes_by_state(self):
        draft = Tarea.objects.create(
            titulo="Borrador historico",
            empresa=self.empresa,
            creada_por=self.creator,
        )
        active = Tarea.objects.create(
            titulo="Activa historica",
            empresa=self.empresa,
            creada_por=self.creator,
        )
        Tarea.objects.filter(pk=draft.pk).update(correlativo="A0000001")
        Tarea.objects.filter(pk=active.pk).update(
            correlativo="B0000002", estado=Tarea.Estado.ACTIVA
        )

        self._run_forward()

        draft.refresh_from_db()
        active.refresh_from_db()
        self.assertEqual(draft.correlativo, "B0000001")
        self.assertEqual(active.correlativo, "A0000002")
        self.assertEqual(draft.pk, 1)
        self.assertEqual(active.pk, 2)
        self.assertEqual(draft.empresa_id, active.empresa_id)

    def test_collision_aborts_before_writing(self):
        draft_one = Tarea.objects.create(
            titulo="Borrador uno",
            empresa=self.empresa,
            creada_por=self.creator,
        )
        draft_two = Tarea.objects.create(
            titulo="Borrador dos",
            empresa=self.empresa,
            creada_por=self.creator,
        )
        Tarea.objects.filter(pk=draft_one.pk).update(correlativo="A0000001")
        Tarea.objects.filter(pk=draft_two.pk).update(correlativo="B0000001")

        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self._run_forward()

        self.assertEqual(
            set(Tarea.objects.values_list("correlativo", flat=True)),
            {"A0000001", "B0000001"},
        )