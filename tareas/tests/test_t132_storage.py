from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from settings.models import SettingsMySQLConnection
from tareas.models import Tarea, TareaConnectionRole
from tareas.services.task_storage import TaskListFilters, MySQLTaskListStorage, resolve_list_storage


class TaskListStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="132S", descripcion="Empresa")
        cls.catalog = Empresa.objects.create(codigo="00", descripcion="Catálogo")
        cls.user = User.objects.create_user(username="t132-storage", password="pass")
        cls.vista = Vista.objects.create(nombre="Tareas")
        Permiso.objects.create(
            usuario=cls.user,
            empresa=cls.empresa,
            vista=cls.vista,
            ingresar=True,
        )
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS",
            source_type="DJANGO",
            django_alias="default",
        )

    def _task(self, **kwargs):
        values = {
            "titulo": "Storage list task",
            "empresa": self.empresa,
            "creada_por": self.user,
            "fecha_tope": date(2026, 10, 31),
        }
        values.update(kwargs)
        return Tarea.objects.create(**values)

    def test_django_storage_returns_dto_and_summary_over_company(self):
        visible = self._task(titulo="Visible", estado=Tarea.Estado.GESTION)
        self._task(titulo="Closed", estado=Tarea.Estado.CERRADA)
        self._task(
            titulo="Other company",
            empresa=self.catalog,
            estado=Tarea.Estado.GESTION,
        )
        storage = resolve_list_storage()

        result = storage.list_tasks(
            empresa_id=self.empresa.pk,
            filters=TaskListFilters(estado=Tarea.Estado.GESTION),
        )

        self.assertEqual([item.id for item in result.items], [visible.pk])
        self.assertEqual(result.summary["total"], 2)
        self.assertEqual(result.summary["gestion"], 1)
        self.assertEqual(result.summary["cerradas"], 1)

    def test_mysql_selection_returns_mysql_storage_without_django_fallback(self):
        connection = SettingsMySQLConnection.objects.create(
            empresa=self.catalog,
            nombre_logico="mysql-list",
            host="mysql.example.test",
            user="user",
            password="secret",
            db_name="tareas",
            is_active=True,
        )
        role = TareaConnectionRole.objects.get(role="BASE_TAREAS")
        role.source_type = "MYSQL_CONFIG"
        role.django_alias = None
        role.mysql_connection = connection
        role.database_name = "tareas"
        role.save()

        storage = resolve_list_storage()

        self.assertIsInstance(storage, MySQLTaskListStorage)
