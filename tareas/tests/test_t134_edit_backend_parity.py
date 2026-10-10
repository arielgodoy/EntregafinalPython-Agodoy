from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from tareas.models import Tarea
from tareas.services.task_storage import (
    DjangoTaskStorage,
    MySQLTaskStorage,
    TaskEditData,
    UpdateTaskCommand,
)


class MySQLEditStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="134MYSQL", descripcion="Edit MySQL")
        cls.connection = MagicMock()

    def _connection(self, rowcount=1):
        connection = MagicMock()
        cursor = MagicMock()
        cursor.rowcount = rowcount
        cursor.fetchone.return_value = (
            3,
            self.empresa.pk,
            "Editada",
            "Descripción",
            "URGENTE",
            None,
            "2026-10-31",
            "BORRADOR",
        )
        connection.cursor.return_value = cursor
        return connection, cursor

    @patch("tareas.services.task_storage.open_mysql_connection")
    def test_update_is_parameterized_and_company_scoped(self, open_connection):
        connection, cursor = self._connection()
        open_connection.return_value = nullcontext(connection)
        storage = MySQLTaskStorage(self.connection, "tareas")
        command = UpdateTaskCommand(
            task_id=3,
            empresa_id=self.empresa.pk,
            titulo="Editada",
            descripcion="Descripción",
            prioridad="URGENTE",
            responsable_id=None,
            fecha_tope="2026-10-31",
        )

        result = storage.update_task(command)

        update_call = next(call for call in cursor.execute.call_args_list if "UPDATE tareas_tarea" in call.args[0])
        self.assertIn("WHERE id = %s AND empresa_id = %s", update_call.args[0])
        self.assertEqual(update_call.args[1][-2:], (3, self.empresa.pk))
        self.assertEqual(result.id, 3)
        connection.commit.assert_called_once()

    @patch("tareas.services.task_storage.open_mysql_connection")
    def test_zero_rowcount_rolls_back_and_does_not_fallback(self, open_connection):
        connection, cursor = self._connection(rowcount=0)
        open_connection.return_value = nullcontext(connection)
        storage = MySQLTaskStorage(self.connection, "tareas")
        command = UpdateTaskCommand(3, self.empresa.pk, "X", "", "NORMAL", None, "2026-10-31")

        with self.assertRaises(Exception):
            storage.update_task(command)

        connection.rollback.assert_called()


class MySQLEditViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="00", descripcion="Edit View")
        cls.user = User.objects.create_user("t134-edit-user", password="pass")
        vista = Vista.objects.create(nombre="Tareas")
        Permiso.objects.create(
            usuario=cls.user,
            empresa=cls.empresa,
            vista=vista,
            ingresar=True,
            modificar=True,
        )
        cls.data = TaskEditData(
            id=3,
            empresa_id=cls.empresa.pk,
            titulo="Original",
            descripcion="Texto",
            prioridad=Tarea.Prioridad.NORMAL,
            responsable_id=None,
            fecha_tope="2026-10-31",
            estado=Tarea.Estado.BORRADOR,
        )

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()
        self.storage = MagicMock()
        self.storage.get_task_for_edit.return_value = self.data
        self.storage.update_task.return_value = self.data
        detail = MagicMock()
        detail.core.creada_por_id = self.user.pk
        detail.hierarchy.effectively_annulled = False
        resolver = patch("tareas.views.resolve_detail_storage")
        resolve_detail = resolver.start()
        self.addCleanup(resolver.stop)
        resolve_detail.return_value.get_task_detail.return_value = detail

    @patch("tareas.views.resolve_edit_storage")
    def test_get_renders_backend_neutral_initial_values(self, resolve):
        resolve.return_value = self.storage

        response = self.client.get(reverse("tareas:editar_tarea", args=[3]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Original")
        self.assertContains(response, "2026-10-31")
        self.storage.get_task_for_edit.assert_called_once_with(
            task_id=3,
            empresa_id=self.empresa.pk,
        )

    @patch("tareas.views.reassign_responsible")
    @patch("tareas.views.resolve_edit_storage")
    def test_valid_post_updates_mysql_storage_without_default_lookup(self, resolve, reassign):
        resolve.return_value = self.storage

        with patch(
            "tareas.views.Tarea.objects.get",
            side_effect=AssertionError("Django lookup before MySQL edit"),
        ):
            response = self.client.post(
                reverse("tareas:editar_tarea", args=[3]),
                {
                    "titulo": "Nueva",
                    "descripcion": "Cambio",
                    "prioridad": Tarea.Prioridad.URGENTE,
                    "fecha_tope": "2026-10-31",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.storage.update_task.assert_not_called()
        reassign.assert_called_once()
        self.assertEqual(reassign.call_args.args[0].edit.task_id, 3)
        self.assertEqual(reassign.call_args.args[0].actor_id, self.user.pk)

    @patch("tareas.views.resolve_edit_storage")
    def test_invalid_post_renders_errors_without_update_or_503(self, resolve):
        resolve.return_value = self.storage

        response = self.client.post(
            reverse("tareas:editar_tarea", args=[3]),
            {"titulo": "", "prioridad": Tarea.Prioridad.NORMAL},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.storage.update_task.assert_not_called()
