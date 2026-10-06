from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa, PerfilAcceso, UsuarioPerfilEmpresa
from tareas.models import Tarea, TareaConnectionRole, TareaLectura
from tareas.services.assignment import mark_task_read
from tareas.services.lifecycle import transition_task
from tareas.services.task_storage import TaskStorageError


class T135QuickWinsTests(TestCase):
    databases = {"default", "system_test"}

    @classmethod
    def setUpTestData(cls):
        cls.role = TareaConnectionRole.objects.create(
            role="BASE_TAREAS", source_type="DJANGO", django_alias="default",
        )
        cls.empresa = Empresa.objects.create(codigo="QW", descripcion="Quick wins")
        cls.user = User.objects.create_user("quick_wins_user")
        perfil = PerfilAcceso.objects.create(nombre="Quick wins")
        UsuarioPerfilEmpresa.objects.create(
            usuario=cls.user, empresa=cls.empresa, perfil=perfil,
        )

    def setUp(self):
        self.tarea = Tarea.objects.create(
            titulo="Quick win task",
            correlativo="B0000001",
            empresa=self.empresa,
            creada_por=self.user,
            responsable=self.user,
            fecha_tope=date.today(),
            estado=Tarea.Estado.ACTIVA,
        )

    def test_lifecycle_uses_configured_django_storage(self):
        transition_task(
            self.tarea,
            Tarea.Estado.GESTION,
            self.user,
            "INICIAR_GESTION",
        )
        self.tarea.refresh_from_db()
        self.assertEqual(self.tarea.estado, Tarea.Estado.GESTION)

    def test_mark_task_read_uses_participant_storage(self):
        reading = mark_task_read(self.tarea, self.user)
        self.assertTrue(reading.leido)
        self.assertEqual(reading.tarea_id, self.tarea.pk)

    def test_mark_task_read_is_safe_when_pk_collides_across_aliases(self):
        alias = "system_test"
        Empresa.objects.using(alias).create(
            pk=self.empresa.pk, codigo="B", descripcion="BASE_TAREAS company",
        )
        User.objects.using(alias).bulk_create([
            User(pk=self.user.pk, username="quick_wins_user"),
        ])
        backend_task = Tarea(
            pk=self.tarea.pk,
            titulo="BASE_TAREAS task B",
            correlativo="B0000001",
            empresa_id=self.empresa.pk,
            creada_por_id=self.user.pk,
            responsable_id=self.user.pk,
            fecha_tope=date.today(),
            estado=Tarea.Estado.ACTIVA,
        )
        backend_task.save(using=alias)
        self.role.django_alias = alias
        self.role.save(update_fields=["django_alias"])

        reading = mark_task_read(self.tarea, self.user)

        self.assertEqual(reading.tarea_id, self.tarea.pk)
        self.assertEqual(
            Tarea.objects.using(alias).get(pk=self.tarea.pk).titulo,
            "BASE_TAREAS task B",
        )
        self.assertTrue(
            TareaLectura.objects.using(alias).filter(
                tarea_id=self.tarea.pk, usuario_id=self.user.pk, leido=True,
            ).exists()
        )
        self.assertFalse(
            TareaLectura.objects.using("default").filter(
                tarea_id=self.tarea.pk, usuario_id=self.user.pk,
            ).exists()
        )

    def test_lifecycle_backend_resolution_failure_does_not_fallback(self):
        with patch(
            "tareas.services.lifecycle.resolve_edit_storage",
            side_effect=TaskStorageError("backend"),
        ):
            with self.assertRaises(TaskStorageError):
                transition_task(
                    self.tarea,
                    Tarea.Estado.GESTION,
                    self.user,
                    "INICIAR_GESTION",
                )
