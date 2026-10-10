from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from settings.models import SettingsMySQLConnection
from tareas.models import TareaConnectionRole
from tareas.services.detail_storage import (
    DetailTaskNotFound,
    MySQLTaskDetailStorage,
    TaskDetailSections,
)


class MySQLDetailStorageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="00", descripcion="Empresa MySQL")
        cls.user = User.objects.create_user("t133-mysql-user", password="pass")
        cls.vista_tareas = Vista.objects.create(nombre="Tareas")
        Permiso.objects.create(
            usuario=cls.user,
            empresa=cls.empresa,
            vista=cls.vista_tareas,
            ingresar=True,
        )
        cls.connection = SettingsMySQLConnection.objects.create(
            empresa=cls.empresa,
            nombre_logico="mysql-detail-test",
            host="mysql.example.test",
            user="user",
            password="secret",
            db_name="tareas",
            is_active=True,
        )

    def setUp(self):
        role = TareaConnectionRole.objects.filter(role="BASE_TAREAS").first()
        if role is None:
            role = TareaConnectionRole.objects.create(
                role="BASE_TAREAS",
                source_type="MYSQL_CONFIG",
                mysql_connection=self.connection,
                database_name="tareas",
            )
        role.source_type = "MYSQL_CONFIG"
        role.django_alias = None
        role.mysql_connection = self.connection
        role.database_name = "tareas"
        role.save()

    def _fake_connection(self, task_rows=None, parent_rows=None, child_rows=None, participant_rows=None,
                         mini_rows=None, event_rows=None, attachment_rows=None):
        connection = MagicMock()
        cursor = MagicMock()
        task_rows = task_rows if task_rows is not None else []
        parent_rows = parent_rows if parent_rows is not None else []
        child_rows = child_rows if child_rows is not None else []
        participant_rows = participant_rows if participant_rows is not None else []

        def execute(sql, params=()):
            cursor._last_sql = sql
            lower = sql.lower()
            if "from tareas_tarea where id" in lower:
                cursor.description = [
                    (name,) for name in (
                        "id", "titulo", "descripcion", "prioridad", "correlativo", "anulada",
                        "fechas_pendientes_confirmacion", "requiere_evidencia_cierre", "estado",
                        "responsable_id", "empresa_id", "creada_por_id", "fecha_creacion",
                        "fecha_publicacion", "fecha_asignacion", "fecha_tope", "fecha_cumplimiento",
                    )
                ]
                cursor._result = task_rows
            elif "from tareas_tarearelacion" in lower and "padre_id" in lower:
                cursor.description = [(name,) for name in ("id", "correlativo", "titulo", "estado", "anulada")]
                cursor._result = child_rows
            elif "from tareas_tarearelacion" in lower:
                cursor.description = [(name,) for name in ("id", "correlativo", "titulo", "estado", "anulada")]
                cursor._result = parent_rows
            elif "from tareas_tareaparticipante" in lower:
                cursor.description = [("usuario_id",), ("rol",)]
                cursor._result = participant_rows
            elif "select id, descripcion, persona_id" in lower:
                cursor.description = [(name,) for name in (
                    "id", "descripcion", "persona_id", "hecho", "fecha_creacion", "fecha_completado",
                )]
                cursor._result = mini_rows or []
            elif "from tareas_minitareaevento" in lower:
                cursor.description = [(name,) for name in (
                    "id", "mini_tarea_id", "comentario_feed_id", "tipo", "actor_id", "fecha",
                    "comentario", "oculto", "destinatarios_notificacion", "destinatarios_email",
                )]
                cursor._result = event_rows or []
            elif "from tareas_comentarioadjunto" in lower:
                cursor.description = [(name,) for name in (
                    "comentario_id", "id", "tipo", "formato_archivo", "archivo", "url",
                )]
                cursor._result = attachment_rows or []
            else:
                cursor.description = []
                cursor._result = []

        cursor.execute.side_effect = execute
        cursor.fetchall.side_effect = lambda: cursor._result
        connection.cursor.return_value = cursor
        return connection, cursor

    @patch("tareas.services.detail_storage.open_mysql_connection")
    def test_minitask_history_retains_external_actor_recipients_feed_and_file_url(self, open_connection):
        from tareas.services.minitask_storage import MySQLMiniTaskStorage
        from tareas.tests.factories import activate_company

        task_row = (
            3, "MYSQL task", "Description", "NORMAL", "B0000003", 0, 0, 0,
            "GESTION", self.user.pk, self.empresa.pk, self.user.pk,
            "2026-10-05", None, None, "2026-10-31", None,
        )
        connection, cursor = self._fake_connection(
            task_rows=[task_row],
            mini_rows=[(5, "MYSQL MiniTask", self.user.pk, 1, "2026-10-05", "2026-10-05")],
            event_rows=[
                (6, 5, 7, "CIERRE", self.user.pk, "2026-10-05", "Completed", 0, "[8]", "[]"),
                (9, 5, None, "REAPERTURA", self.user.pk, "2026-10-05", "Reopened", None, "[]", "[]"),
            ],
            attachment_rows=[(7, 10, "OTRO", "PDF", "tareas/documentos/proof.pdf", "")],
        )
        open_connection.return_value = nullcontext(connection)
        _detail, mini = MySQLMiniTaskStorage(self.connection, "tareas").history(
            task_id=3, empresa_id=self.empresa.pk, mini_task_id=5, actor_id=self.user.pk,
        )
        event = mini.eventos_t104[0]
        self.assertEqual(event.actor_id, self.user.pk)
        self.assertEqual(event.actor_username, self.user.username)
        self.assertEqual(event.destinatarios_notificacion, (8,))
        self.assertEqual(event.comentario_feed_id, 7)
        self.assertTrue(event.attachments[0].archivo_url.endswith("tareas/documentos/proof.pdf"))
        self.assertIsNone(mini.eventos_t104[1].comentario_feed_id)
        self.client.force_login(self.user)
        activate_company(self.client, self.empresa)
        response = self.client.get(reverse("tareas:historial_minitarea", args=[3, 5]))
        self.assertContains(response, self.user.username)
        self.assertContains(response, "proof.pdf")

    @patch("tareas.services.detail_storage.open_mysql_connection")
    def test_mysql_detail_returns_same_core_contract_and_is_company_scoped(self, open_connection):
        task_row = (
            3, "MYSQL task", "Description", "NORMAL", "B0000003", 0, 0, 0,
            "BORRADOR", self.user.pk, self.empresa.pk, self.user.pk,
            "2026-10-05", None, None, "2026-10-31", None,
        )
        connection, cursor = self._fake_connection(
            task_rows=[task_row],
            participant_rows=[(self.user.pk, "PARTICIPANTE")],
        )
        open_connection.return_value = nullcontext(connection)

        result = MySQLTaskDetailStorage(self.connection, "tareas").get_task_detail(
            task_id=3,
            empresa_id=self.empresa.pk,
            sections=TaskDetailSections(
                mini_tasks=False,
                links=False,
                milestones=False,
                documents=False,
            ),
        )

        self.assertEqual(result.core.id, 3)
        self.assertEqual(result.core.correlativo, "B0000003")
        self.assertEqual(result.core.titulo, "MYSQL task")
        self.assertEqual(result.participants[0].username, self.user.username)
        self.assertTrue(any("id = %s AND empresa_id = %s" in call.args[0] for call in cursor.execute.call_args_list))
        open_connection.assert_called_once_with(self.connection, database_name="tareas")

    @patch("tareas.services.detail_storage.open_mysql_connection")
    def test_missing_mysql_task_has_no_django_fallback(self, open_connection):
        connection, cursor = self._fake_connection()
        open_connection.return_value = nullcontext(connection)

        with self.assertRaises(DetailTaskNotFound):
            MySQLTaskDetailStorage(self.connection, "tareas").get_task_detail(
                task_id=99,
                empresa_id=self.empresa.pk,
                sections=TaskDetailSections(
                    mini_tasks=False,
                    links=False,
                    milestones=False,
                    documents=False,
                ),
            )
        self.assertTrue(any("empresa_id = %s" in call.args[0] for call in cursor.execute.call_args_list))

    @patch("tareas.services.detail_storage.open_mysql_connection")
    def test_disabled_sections_do_not_query_their_mysql_tables(self, open_connection):
        task_row = (
            3, "MYSQL task", "Description", "NORMAL", "B0000003", 0, 0, 0,
            "BORRADOR", self.user.pk, self.empresa.pk, self.user.pk,
            "2026-10-05", None, None, "2026-10-31", None,
        )
        connection, cursor = self._fake_connection(task_rows=[task_row])
        open_connection.return_value = nullcontext(connection)

        MySQLTaskDetailStorage(self.connection, "tareas").get_task_detail(
            task_id=3,
            empresa_id=self.empresa.pk,
            sections=TaskDetailSections(
                mini_tasks=False,
                links=False,
                milestones=False,
                documents=False,
            ),
        )

        sql = " ".join(call.args[0].lower() for call in cursor.execute.call_args_list)
        for table in (
            "tareas_avance", "tareas_hitoevidencia", "tareas_hitohistorial",
            "tareas_documentotarea", "tareas_documentohistorial", "tareas_evidenciacierre",
        ):
            self.assertNotIn(table, sql)


class MySQLWriteGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="00", descripcion="Guard")
        cls.catalog = cls.empresa
        cls.user = User.objects.create_user("t133-guard-user", password="pass")
        vista = Vista.objects.create(nombre="Tareas")
        Permiso.objects.create(usuario=cls.user, empresa=cls.empresa, vista=vista, ingresar=True, modificar=True)
        cls.connection = SettingsMySQLConnection.objects.create(
            empresa=cls.catalog,
            nombre_logico="mysql-guard-test",
            host="mysql.example.test",
            user="user",
            password="secret",
            db_name="tareas",
            is_active=True,
        )
        role = TareaConnectionRole.objects.create(
            role="BASE_TAREAS", source_type="MYSQL_CONFIG", mysql_connection=cls.connection, database_name="tareas"
        )

    def test_responsible_uses_configured_backend_before_default_lookup(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

        with patch("tareas.views.Tarea.objects.get", side_effect=AssertionError("default lookup")), patch(
            "tareas.views.reassign_responsible",
        ) as reassign:
            response = self.client.post(
                reverse("tareas:administrar_responsable_detalle", args=[3]),
                {"responsable": self.user.pk},
            )

        self.assertEqual(response.status_code, 302)
        reassign.assert_called_once()
        self.assertEqual(reassign.call_args.args[0].task_id, 3)
        self.assertNotIn("password", response.content.decode().lower())
