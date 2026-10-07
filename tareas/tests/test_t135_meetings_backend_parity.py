from contextlib import contextmanager
from datetime import date, datetime, time
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from organizacion.models import Local, OrganizationalSource
from tareas.models import ReunionParticipante, ReunionRevision, ReunionTarea, Tarea
from tareas.services import meeting_storage
from tareas.services.connection_roles import BackendContext, TareaConnectionRoleNotFoundError
from tareas.services.meetings import (
    add_meeting_participant,
    add_task_to_meeting,
    create_meeting,
    mark_meeting_completed,
    remove_meeting_participant,
    remove_task_from_meeting,
    update_meeting,
)
from tareas.services.meeting_storage import (
    DjangoMeetingStorage,
    MeetingStorageError,
    resolve_meeting_storage,
)
from tareas.services.task_storage import TaskStorageError


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
                departamento_id INTEGER, creada_por_id INTEGER, fecha_tope TEXT
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
            "INSERT INTO tareas_tarea VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.task_id, task.titulo, task.descripcion, task.prioridad, task.correlativo,
                task.anulada, task.estado, task.responsable_id, task.empresa_id,
                task.tipo_ambito, task.local_id, task.departamento_id,
                task.creada_por_id, task.fecha_tope.isoformat(),
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
            updated = update_meeting(
                SimpleNamespace(pk=self.connection.meeting_id),
                titulo="Updated meeting",
                descripcion="Updated description",
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

    def test_create_meeting_keeps_existing_mysql_lifecycle_block(self):
        with patch.object(
            meeting_storage,
            "resolve_operational_backend",
            return_value=BackendContext(
                logical_role="BASE_TAREAS", backend_type="MYSQL_CONFIG",
                mysql_connection=object(), database_name="meetings_test",
            ),
        ):
            with patch.object(
                Tarea.objects,
                "create",
                side_effect=AssertionError("must not create a default task"),
            ):
                with self.assertRaises(TaskStorageError):
                    create_meeting(
                        empresa=self.company,
                        creada_por=self.creator,
                        titulo="Blocked meeting",
                        descripcion="",
                        fecha_hora_programada=datetime.combine(
                            date(2026, 10, 3), time(10)
                        ),
                        modalidad=ReunionRevision.Modalidad.ZOOM,
                        lugar_o_enlace="https://example.test/blocked",
                        tipo_ambito=ReunionRevision.TipoAmbito.LOCAL,
                        local=self.local,
                    )

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
