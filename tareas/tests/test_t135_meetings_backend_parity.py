from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from access_control.models import Empresa, Permiso, Vista
from organizacion.models import Local, OrganizationalSource
from tareas.forms import ComentarioForm, ReunionTareaForm
from tareas.models import ReunionParticipante, ReunionRevision, ReunionTarea, Tarea
from tareas.services import meeting_storage
from tareas.services.connection_roles import BackendContext, TareaConnectionRoleNotFoundError
from tareas.services.document_storage import DocumentReference
from tareas.services.meetings import (
    add_meeting_participant,
    add_task_to_meeting,
    convene_meeting,
    create_meeting,
    mark_meeting_completed,
    remove_meeting_participant,
    remove_task_from_meeting,
    update_meeting,
)
from tareas.services.meeting_storage import (
    DjangoMeetingStorage,
    MeetingStorageError,
    MySQLMeetingStorage,
    resolve_meeting_storage,
)


class _SQLiteCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=()):
        values = tuple(
            value.isoformat() if hasattr(value, "isoformat") else value
            for value in params
        )
        self._cursor.execute(sql.replace("%s", "?"), values)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _SQLiteConnection:
    def __init__(self, task, meeting):
        self.database = sqlite3.connect(":memory:", isolation_level=None)
        self.task_id = task.pk + 50000
        self.meeting_id = meeting.pk + 50000
        self.database.executescript(
            """
            CREATE TABLE tareas_tarea (
                id INTEGER PRIMARY KEY, titulo TEXT, descripcion TEXT, prioridad TEXT,
                correlativo TEXT, anulada INTEGER, estado TEXT, responsable_id INTEGER,
                empresa_id INTEGER, tipo_ambito TEXT, local_id INTEGER,
                departamento_id INTEGER, creada_por_id INTEGER, fecha_tope TEXT,
                fecha_publicacion TEXT, fecha_asignacion TEXT
            );
            CREATE TABLE tareas_reunionrevision (
                id INTEGER PRIMARY KEY, empresa_id INTEGER, titulo TEXT, descripcion TEXT,
                fecha_hora_programada TEXT, modalidad TEXT, lugar_o_enlace TEXT,
                tipo_ambito TEXT, local_id INTEGER, departamento_id INTEGER,
                tarea_planificada_id INTEGER, creada_por_id INTEGER, estado TEXT,
                convocada_at TEXT, created_at TEXT, updated_at TEXT
            );
            CREATE TABLE tareas_reuniontarea (
                id INTEGER PRIMARY KEY AUTOINCREMENT, reunion_id INTEGER, tarea_id INTEGER,
                orden INTEGER, comentario_revision TEXT, comentario_cierre TEXT,
                created_at TEXT, UNIQUE(reunion_id,tarea_id), UNIQUE(reunion_id,orden)
            );
            CREATE TABLE tareas_reunionparticipante (
                id INTEGER PRIMARY KEY AUTOINCREMENT, reunion_id INTEGER,
                usuario_id INTEGER, created_at TEXT, UNIQUE(reunion_id,usuario_id)
            );
            """
        )
        self.database.execute(
            "INSERT INTO tareas_tarea VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.task_id, task.titulo, task.descripcion, task.prioridad, task.correlativo,
                task.anulada, task.estado, task.responsable_id, task.empresa_id,
                task.tipo_ambito, task.local_id, task.departamento_id,
                task.creada_por_id, task.fecha_tope.isoformat(),
                task.fecha_publicacion.isoformat() if task.fecha_publicacion else None,
                task.fecha_asignacion.isoformat() if task.fecha_asignacion else None,
            ),
        )
        self.database.execute(
            "INSERT INTO tareas_reunionrevision VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.meeting_id, meeting.empresa_id, meeting.titulo, meeting.descripcion,
                meeting.fecha_hora_programada.isoformat(), meeting.modalidad,
                meeting.lugar_o_enlace, meeting.tipo_ambito, meeting.local_id,
                meeting.departamento_id, self.task_id,
                meeting.creada_por_id, meeting.estado, None,
                meeting.created_at.isoformat(), meeting.updated_at.isoformat(),
            ),
        )

    def cursor(self):
        return _SQLiteCursor(self.database.cursor())

    def begin(self):
        self.database.execute("BEGIN")

    def commit(self):
        self.database.commit()

    def rollback(self):
        self.database.rollback()

    def close(self):
        pass


class MeetingBackendParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Empresa.objects.create(codigo="M135", descripcion="Meetings parity")
        cls.creator = User.objects.create_user("meeting_parity_creator")
        cls.participant = User.objects.create_user("meeting_parity_participant")
        vista = Vista.objects.create(nombre="Tareas")
        for user in (cls.creator, cls.participant):
            Permiso.objects.create(
                usuario=user,
                empresa=cls.company,
                vista=vista,
                ingresar=True,
                crear=True,
                modificar=True,
            )
        cls.local = Local.objects.create(
            empresa=cls.company,
            codigo="LOC-M135",
            nombre="Meeting parity local",
            source=OrganizationalSource.LOCAL,
        )
        cls.task = Tarea.objects.create(
            titulo="Meeting parity task",
            correlativo="A1350001",
            empresa=cls.company,
            creada_por=cls.creator,
            responsable=cls.creator,
            fecha_tope=date(2026, 10, 2),
            tipo_ambito=Tarea.Ambito.LOCAL,
            local=cls.local,
        )
        cls.meeting = ReunionRevision.objects.create(
            empresa=cls.company,
            titulo="Meeting parity",
            descripcion="Operational parity",
            fecha_hora_programada=datetime.combine(date(2026, 10, 1), time(10)),
            modalidad=ReunionRevision.Modalidad.ZOOM,
            lugar_o_enlace="https://example.test/meeting",
            tipo_ambito=ReunionRevision.TipoAmbito.LOCAL,
            local=cls.local,
            tarea_planificada=cls.task,
            creada_por=cls.creator,
        )

    def setUp(self):
        self.connection = _SQLiteConnection(self.task, self.meeting)
        self.addCleanup(self.connection.database.close)
        self.mysql_connection_patch = patch.object(
            meeting_storage,
            "open_mysql_connection",
            self.open_mysql_connection,
        )
        self.mysql_connection_patch.start()
        self.addCleanup(self.mysql_connection_patch.stop)

    def test_comment_form_materializes_backend_neutral_document_choices(self):
        storage = MagicMock()
        storage.list_task_documents.return_value = (
            DocumentReference(11, self.task.pk, self.company.pk),
        )
        storage.get_task_documents.return_value = storage.list_task_documents.return_value
        with patch("tareas.forms.resolve_document_storage", return_value=storage):
            form = ComentarioForm(data={"documentos": ["11"]}, tarea=self.task)
            self.assertTrue(form.is_valid())
            self.assertEqual(form.cleaned_data["documentos"][0].pk, 11)
            storage.get_task_documents.assert_called_once()

    def test_comment_form_rejects_document_outside_task(self):
        storage = MagicMock()
        storage.list_task_documents.return_value = ()
        storage.get_task_documents.side_effect = ValueError
        with patch("tareas.forms.resolve_document_storage", return_value=storage):
            form = ComentarioForm(data={"documentos": ["99"]}, tarea=self.task)
            self.assertFalse(form.is_valid())
            self.assertIn("documentos", form.errors)

    @contextmanager
    def open_mysql_connection(self, *args, **kwargs):
        yield self.connection

    @contextmanager
    def mysql_backend(self):
        context = BackendContext(
            logical_role="BASE_TAREAS", backend_type="MYSQL_CONFIG",
            mysql_connection=object(), database_name="meetings_test",
        )
        with patch.object(meeting_storage, "resolve_operational_backend", return_value=context):
            yield

    def test_resolver_uses_configured_django_alias(self):
        with patch.object(
            meeting_storage,
            "resolve_operational_backend",
            return_value=BackendContext(
                logical_role="BASE_TAREAS", backend_type="DJANGO", django_alias="default",
            ),
        ):
            self.assertIsInstance(resolve_meeting_storage(), DjangoMeetingStorage)

    def test_reunion_task_form_returns_backend_task(self):
        with patch(
            "tareas.services.task_storage.resolve_operational_backend",
            return_value=BackendContext(
                logical_role="BASE_TAREAS", backend_type="DJANGO", django_alias="default",
            ),
        ), patch(
            "tareas.services.meeting_storage.resolve_operational_backend",
            return_value=BackendContext(
                logical_role="BASE_TAREAS", backend_type="DJANGO", django_alias="default",
            ),
        ):
            form = ReunionTareaForm(
                {"tarea": str(self.task.pk), "orden": "1", "comentario_revision": ""},
                empresa=self.company,
            )
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data["tarea"].pk, self.task.pk)

    def test_reunion_task_form_rejects_task_from_another_company(self):
        other_company = Empresa.objects.create(codigo="M136", descripcion="Other company")
        other_task = Tarea.objects.create(
            titulo="Other company task",
            correlativo="A1360001",
            empresa=other_company,
            creada_por=self.creator,
            responsable=self.creator,
            fecha_tope=date(2026, 10, 2),
        )
        with patch(
            "tareas.services.task_storage.resolve_operational_backend",
            return_value=BackendContext(
                logical_role="BASE_TAREAS", backend_type="DJANGO", django_alias="default",
            ),
        ):
            form = ReunionTareaForm(
                {"tarea": str(other_task.pk), "orden": "1", "comentario_revision": ""},
                empresa=self.company,
            )

            self.assertFalse(form.is_valid())
        self.assertIn("tarea", form.errors)

    def test_reunion_task_form_rejects_invalid_task_id(self):
        with patch(
            "tareas.services.task_storage.resolve_operational_backend",
            return_value=BackendContext(
                logical_role="BASE_TAREAS", backend_type="DJANGO", django_alias="default",
            ),
        ):
            form = ReunionTareaForm(
                {"tarea": "999999", "orden": "1", "comentario_revision": ""},
                empresa=self.company,
            )

        self.assertFalse(form.is_valid())
        self.assertIn("tarea", form.errors)

    def test_reunion_task_form_requires_task(self):
        with patch(
            "tareas.services.task_storage.resolve_operational_backend",
            return_value=BackendContext(
                logical_role="BASE_TAREAS", backend_type="DJANGO", django_alias="default",
            ),
        ):
            form = ReunionTareaForm(
                {"orden": "1", "comentario_revision": ""},
                empresa=self.company,
            )

        self.assertFalse(form.is_valid())
        self.assertIn("tarea", form.errors)

    def test_reunion_task_form_uses_mysql_storage_contract(self):
        mysql_task = SimpleNamespace(
            id=9001,
            titulo="MySQL task",
            estado=Tarea.Estado.ACTIVA,
        )
        mysql_entity = SimpleNamespace(pk=mysql_task.id, empresa_id=self.company.pk)
        list_storage = SimpleNamespace(
            list_tasks=lambda **kwargs: SimpleNamespace(items=(mysql_task,)),
        )
        meeting_storage_stub = SimpleNamespace(get_task=lambda task_id: mysql_entity)
        with patch(
            "tareas.services.task_storage.resolve_list_storage",
            return_value=list_storage,
        ), patch(
            "tareas.services.meeting_storage.resolve_meeting_storage",
            return_value=meeting_storage_stub,
        ):
            form = ReunionTareaForm(
                {"tarea": str(mysql_task.id), "orden": "1", "comentario_revision": ""},
                empresa=self.company,
            )

            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data["tarea"].pk, mysql_task.id)

    def test_django_list_and_detail_preserve_company_and_order(self):
        with patch.object(
            meeting_storage,
            "resolve_operational_backend",
            return_value=BackendContext(
                logical_role="BASE_TAREAS", backend_type="DJANGO", django_alias="default",
            ),
        ):
            storage = resolve_meeting_storage()
            meetings = storage.list_meetings(self.company.pk)
            detail = storage.get_meeting(self.meeting.pk)

        self.assertEqual([meeting.pk for meeting in meetings], [self.meeting.pk])
        self.assertEqual(detail.empresa_id, self.company.pk)
        self.assertEqual(storage.list_meetings(self.company.pk + 1), [])

    def test_mysql_list_and_detail_preserve_company_and_order(self):
        with self.mysql_backend():
            storage = meeting_storage.MySQLMeetingStorage(object(), "meetings_test")
            meetings = storage.list_meetings(self.company.pk)
            detail = storage.get_meeting(self.connection.meeting_id)

        self.assertEqual([meeting.pk for meeting in meetings], [self.connection.meeting_id])
        self.assertEqual(detail.empresa_id, self.company.pk)

    @patch("tareas.views.resolve_meeting_storage")
    def test_http_list_reaches_storage_when_backend_is_mysql_config(self, resolve_storage):
        storage = MagicMock()
        storage.list_meetings.return_value = []
        resolve_storage.return_value = storage
        self.client.force_login(self.creator)
        session = self.client.session
        session["empresa_id"] = self.company.pk
        session.save()

        response = self.client.get("/tareas/reuniones/")

        self.assertEqual(response.status_code, 200)
        storage.list_meetings.assert_called_once_with(self.company.pk)

    def test_mysql_agenda_participant_and_completion_do_not_write_default(self):
        with self.mysql_backend():
            item = add_task_to_meeting(
                reunion=SimpleNamespace(pk=self.connection.meeting_id),
                tarea=SimpleNamespace(pk=self.connection.task_id),
                orden=1,
                comentario_revision="Revisar",
            )
            participant = add_meeting_participant(
                reunion=SimpleNamespace(pk=self.connection.meeting_id),
                usuario=self.participant,
            )
            mark_meeting_completed(
                SimpleNamespace(pk=self.connection.meeting_id),
                comentarios={item.pk: "Completado"},
            )

            self.assertEqual(
                self.connection.database.execute(
                    "SELECT comentario_cierre FROM tareas_reuniontarea WHERE id=?",
                    (item.pk,),
                ).fetchone()[0],
                "Completado",
            )
            self.assertEqual(
                self.connection.database.execute(
                    "SELECT estado FROM tareas_reunionrevision WHERE id=?",
                    (self.connection.meeting_id,),
                ).fetchone()[0],
                ReunionRevision.Estado.REALIZADA,
            )
            self.assertEqual(
                self.connection.database.execute(
                    "SELECT usuario_id FROM tareas_reunionparticipante WHERE id=?",
                    (participant.pk,),
                ).fetchone()[0],
                self.participant.pk,
            )
            self.assertEqual(ReunionTarea.objects.using("default").count(), 0)
            self.assertEqual(ReunionParticipante.objects.using("default").count(), 0)
            self.assertEqual(
                ReunionRevision.objects.using("default").get(pk=self.meeting.pk).estado,
                ReunionRevision.Estado.PLANIFICADA,
            )

    def test_mysql_deletes_return_controlled_counts_without_default_writes(self):
        with self.mysql_backend():
            item = add_task_to_meeting(
                reunion=SimpleNamespace(pk=self.connection.meeting_id),
                tarea=SimpleNamespace(pk=self.connection.task_id),
                orden=1,
            )
            participant = add_meeting_participant(
                reunion=SimpleNamespace(pk=self.connection.meeting_id),
                usuario=self.participant,
            )
            self.assertEqual(
                remove_task_from_meeting(
                    reunion=SimpleNamespace(pk=self.connection.meeting_id),
                    tarea=SimpleNamespace(pk=self.connection.task_id),
                )[0],
                1,
            )
            self.assertEqual(
                remove_meeting_participant(
                    reunion=SimpleNamespace(pk=self.connection.meeting_id),
                    usuario=self.participant,
                )[0],
                1,
            )
            self.assertIsNotNone(item.pk)
            self.assertIsNotNone(participant.pk)
            self.assertEqual(ReunionTarea.objects.using("default").count(), 0)
            self.assertEqual(ReunionParticipante.objects.using("default").count(), 0)

    def test_mysql_meeting_update_targets_configured_operational_store(self):
        with self.mysql_backend():
            with CaptureQueriesContext(connections["default"]) as default_queries:
                updated = update_meeting(
                    SimpleNamespace(pk=self.connection.meeting_id),
                    titulo="Updated meeting",
                    descripcion="Updated description",
                )
            self.assertFalse(
                any("tareas_tarea" in query["sql"] for query in default_queries),
                "MySQL meeting validation must not query the default Tareas table.",
            )
            row = self.connection.database.execute(
                "SELECT titulo,descripcion FROM tareas_reunionrevision WHERE id=?",
                (self.connection.meeting_id,),
            ).fetchone()
            task_row = self.connection.database.execute(
                "SELECT titulo,descripcion FROM tareas_tarea WHERE id=?",
                (self.connection.task_id,),
            ).fetchone()
            self.assertEqual(row, ("Updated meeting", "Updated description"))
            self.assertEqual(task_row, ("Reunión: Updated meeting", "Updated description"))
            self.assertEqual(updated.titulo, "Updated meeting")
            self.assertEqual(
                ReunionRevision.objects.using("default").get(pk=self.meeting.pk).titulo,
                "Meeting parity",
            )

    def test_mysql_task_clean_preserves_published_task_rules_without_default_read(self):
        published_at = timezone.now().replace(microsecond=0)
        assigned_at = published_at - timedelta(days=1)
        self.connection.database.execute(
            "UPDATE tareas_tarea SET estado=?,fecha_publicacion=?,fecha_asignacion=? "
            "WHERE id=?",
            (
                Tarea.Estado.ACTIVA,
                published_at.isoformat(),
                assigned_at.isoformat(),
                self.connection.task_id,
            ),
        )

        with self.mysql_backend():
            storage = resolve_meeting_storage()
            with CaptureQueriesContext(connections["default"]) as default_queries:
                task = storage.get_task(self.connection.task_id)
                task.full_clean(validate_unique=False, validate_constraints=False)
                task.estado = Tarea.Estado.BORRADOR
                task.fecha_publicacion = published_at - timedelta(days=2)
                task.fecha_asignacion = assigned_at - timedelta(days=2)
                with self.assertRaises(ValidationError) as error:
                    task.full_clean(validate_unique=False, validate_constraints=False)

            self.assertFalse(
                any("tareas_tarea" in query["sql"] for query in default_queries),
                "MySQL task validation must use the persisted snapshot, not default ORM.",
            )
            self.assertEqual(
                error.exception.message_dict,
                {
                    "estado": [
                        "La publicación es irreversible: una tarea publicada no puede volver a borrador."
                    ],
                    "fecha_publicacion": ["La fecha de publicación es inmutable."],
                    "fecha_asignacion": ["La fecha de asignación es inmutable."],
                },
            )

    @patch("tareas.services.meeting_storage.open_mysql_connection")
    def test_create_meeting_mysql_persists_task_and_meeting_atomically(
        self,
        open_connection,
    ):
        connection = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (4,)
        cursor.lastrowid = 9001
        connection.cursor.return_value = cursor
        open_connection.return_value.__enter__.return_value = connection
        storage = MySQLMeetingStorage(object(), "meetings_test")

        with patch(
            "tareas.services.meetings.resolve_meeting_storage",
            return_value=storage,
        ):
            meeting = create_meeting(
                empresa=self.company,
                creada_por=self.creator,
                titulo="MySQL meeting",
                descripcion="Operational creation",
                fecha_hora_programada=datetime.combine(
                    date(2026, 10, 3), time(10)
                ),
                modalidad=ReunionRevision.Modalidad.ZOOM,
                lugar_o_enlace="https://example.test/mysql-meeting",
                tipo_ambito=ReunionRevision.TipoAmbito.LOCAL,
                local=self.local,
            )

        self.assertEqual(meeting.pk, 9001)
        self.assertEqual(meeting.tarea_planificada.pk, 9001)
        self.assertEqual(meeting.tarea_planificada.estado, Tarea.Estado.ACTIVA)
        self.assertEqual(meeting.tarea_planificada.correlativo, "A0000004")
        self.assertEqual(connection.cursor.call_count, 1)
        connection.begin.assert_called_once()
        connection.commit.assert_called_once()
        connection.rollback.assert_not_called()
        sql = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertTrue(any("INSERT INTO tareas_tarea" in statement for statement in sql))
        self.assertTrue(any("INSERT INTO tareas_tareatransicion" in statement for statement in sql))
        self.assertTrue(any("INSERT INTO tareas_reunionrevision" in statement for statement in sql))

    @patch("tareas.services.meeting_storage.open_mysql_connection")
    def test_create_meeting_mysql_rolls_back_task_when_meeting_validation_fails(
        self,
        open_connection,
    ):
        connection = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (4,)
        cursor.lastrowid = 9002
        connection.cursor.return_value = cursor
        open_connection.return_value.__enter__.return_value = connection
        storage = MySQLMeetingStorage(object(), "meetings_test")

        with patch(
            "tareas.services.meetings.resolve_meeting_storage",
            return_value=storage,
        ):
            with self.assertRaises(ValidationError):
                create_meeting(
                    empresa=self.company,
                    creada_por=self.creator,
                    titulo="",
                    descripcion="Operational creation",
                    fecha_hora_programada=datetime.combine(
                        date(2026, 10, 3), time(10)
                    ),
                    modalidad=ReunionRevision.Modalidad.ZOOM,
                    lugar_o_enlace="https://example.test/mysql-meeting",
                    tipo_ambito=ReunionRevision.TipoAmbito.LOCAL,
                    local=self.local,
                )

        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()

    @patch("tareas.services.meetings.send_task_email")
    @patch("tareas.services.meetings.notify_task_event")
    def test_mysql_convene_uses_storage_transaction_without_django_alias(
        self,
        notify_task_event,
        send_task_email,
    ):
        self.participant.email = "meeting-participant@example.test"
        self.participant.save(update_fields=["email"])
        with self.mysql_backend():
            add_meeting_participant(
                reunion=SimpleNamespace(pk=self.connection.meeting_id),
                usuario=self.participant,
            )

            meeting = convene_meeting(
                SimpleNamespace(pk=self.connection.meeting_id),
                actor=self.creator,
            )

        self.assertIsNotNone(meeting.convocada_at)
        self.assertEqual(
            self.connection.database.execute(
                "SELECT convocada_at FROM tareas_reunionrevision WHERE id=?",
                (self.connection.meeting_id,),
            ).fetchone()[0],
            meeting.convocada_at.isoformat(),
        )
        notify_task_event.assert_called_once()
        send_task_email.assert_called_once()

    def test_missing_backend_fails_closed(self):
        with patch.object(
            meeting_storage,
            "resolve_operational_backend",
            side_effect=TareaConnectionRoleNotFoundError("missing"),
        ):
            with patch.object(
                ReunionRevision.objects,
                "using",
                side_effect=AssertionError("implicit/default operational query"),
            ):
                with self.assertRaises(MeetingStorageError):
                    resolve_meeting_storage()
