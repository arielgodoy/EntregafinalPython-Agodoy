from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from settings.models import SettingsMySQLConnection
from tareas.models import Tarea, TareaConnectionRole
from tareas.services.task_storage import (
    CreateTaskDraftInput,
    CreatedTaskResult,
    MySQLTaskStorage,
    create_task_draft,
)


class CreateTaskStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="131S", descripcion="Storage")
        cls.user = User.objects.create_user(username="t131-storage", password="pass")
        cls.vista = Vista.objects.create(nombre="Tareas")
        Permiso.objects.create(
            usuario=cls.user,
            empresa=cls.empresa,
            vista=cls.vista,
            ingresar=True,
            crear=True,
        )
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS",
            source_type="DJANGO",
            django_alias="default",
        )

    def _input(self, responsable_id=None):
        return CreateTaskDraftInput(
            titulo="Storage draft",
            descripcion="Descripción",
            prioridad=Tarea.Prioridad.NORMAL,
            responsable_id=responsable_id,
            fecha_tope=date(2026, 10, 20),
        )

    def test_django_storage_returns_minimal_created_result(self):
        result = create_task_draft(
            self._input(),
            active_company=self.empresa,
            actor=self.user,
        )

        self.assertIsInstance(result.id, int)
        self.assertEqual(result.empresa_id, self.empresa.pk)
        self.assertRegex(result.correlativo, r"^B[0-9]{7}$")
        self.assertEqual(result.estado, Tarea.Estado.BORRADOR)
        self.assertEqual(Tarea.objects.get(pk=result.id).empresa_id, self.empresa.pk)

    @patch("tareas.services.task_storage.MySQLTaskStorage.create_draft")
    def test_mysql_base_does_not_fallback_to_django(self, mysql_create):
        catalog = Empresa.objects.create(codigo="00", descripcion="Catálogo")
        connection = SettingsMySQLConnection.objects.create(
            empresa=catalog,
            nombre_logico="mysql-create",
            host="mysql.example.test",
            user="user",
            password="secret",
            db_name="tareas",
            is_active=True,
        )
        role = TareaConnectionRole.objects.get(role="BASE_TAREAS")
        role.source_type = "MYSQL_CONFIG"
        role.mysql_connection = connection
        role.database_name = "tareas"
        role.django_alias = None
        role.save()

        mysql_create.return_value = CreatedTaskResult(
            id=99,
            empresa_id=self.empresa.pk,
            correlativo="B0000099",
            estado=Tarea.Estado.BORRADOR,
            responsable_id=None,
        )
        result = create_task_draft(
            self._input(),
            active_company=self.empresa,
            actor=self.user,
        )

        mysql_create.assert_called_once()
        self.assertEqual(result.id, 99)
        self.assertFalse(Tarea.objects.filter(titulo="Storage draft").exists())

    @patch("tareas.services.notifications.notify_task_event", side_effect=RuntimeError("notify"))
    def test_notification_failure_does_not_remove_persisted_task(self, _notify):
        responsible = User.objects.create_user(
            username="t131-storage-responsible",
            password="pass",
        )
        Permiso.objects.create(
            usuario=responsible,
            empresa=self.empresa,
            vista=self.vista,
            ingresar=True,
        )

        result = create_task_draft(
            self._input(responsable_id=responsible.pk),
            active_company=self.empresa,
            actor=self.user,
        )

        self.assertTrue(Tarea.objects.filter(pk=result.id).exists())
