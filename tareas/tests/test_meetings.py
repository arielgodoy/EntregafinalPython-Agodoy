from datetime import date, datetime, time
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from organizacion.models import Departamento, Local, OrganizationalSource
from tareas.models import ReunionRevision, Tarea
from tareas.services.meetings import (
    add_meeting_participant,
    add_task_to_meeting,
    convene_meeting,
    create_meeting,
    mark_meeting_completed,
)


class MeetingServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="M55", descripcion="Empresa reunión")
        cls.user = User.objects.create_user(username="meeting_creator", email="creator@example.test")
        cls.participant = User.objects.create_user(username="meeting_participant", email="participant@example.test")
        vista = Vista.objects.create(nombre="Tareas")
        for user in (cls.user, cls.participant):
            Permiso.objects.create(usuario=user, empresa=cls.empresa, vista=vista, ingresar=True, crear=True, modificar=True)
        cls.local = Local.objects.create(
            empresa=cls.empresa, codigo="LOC-M55", nombre="Local reunión", source=OrganizationalSource.LOCAL
        )
        cls.department = Departamento.objects.create(
            empresa=cls.empresa, codigo="DEP-M55", nombre="Departamento reunión", source=OrganizationalSource.LOCAL
        )

    def meeting(self, **changes):
        values = {
            "empresa": self.empresa,
            "creada_por": self.user,
            "titulo": "Revisión operativa",
            "descripcion": "Objetivo",
            "fecha_hora_programada": datetime.combine(date(2026, 9, 20), time(10, 0)),
            "modalidad": ReunionRevision.Modalidad.ZOOM,
            "lugar_o_enlace": "https://zoom.example.test/reunion",
            "tipo_ambito": ReunionRevision.TipoAmbito.LOCAL,
            "local": self.local,
        }
        values.update(changes)
        return create_meeting(**values)

    def task(self, **changes):
        values = {
            "titulo": "Tarea revisable",
            "empresa": self.empresa,
            "creada_por": self.user,
            "responsable": self.user,
            "fecha_tope": date(2026, 9, 30),
            "tipo_ambito": Tarea.Ambito.LOCAL,
            "local": self.local,
        }
        values.update(changes)
        task = Tarea.objects.create(**values)
        task.publicar(self.user)
        return task

    def test_create_meeting_creates_published_planned_task(self):
        meeting = self.meeting()
        self.assertEqual(meeting.estado, ReunionRevision.Estado.PLANIFICADA)
        self.assertEqual(meeting.tarea_planificada.estado, Tarea.Estado.ACTIVA)
        self.assertEqual(meeting.tarea_planificada.local_id, self.local.pk)

    def test_scope_xor_is_enforced(self):
        with self.assertRaises(ValidationError):
            self.meeting(local=None)
        with self.assertRaises(ValidationError):
            self.meeting(departamento=self.department)

    def test_agenda_requires_same_scope(self):
        meeting = self.meeting()
        item = add_task_to_meeting(reunion=meeting, tarea=self.task(), orden=1)
        self.assertEqual(item.reunion_id, meeting.pk)
        with self.assertRaises(ValidationError):
            add_task_to_meeting(
                reunion=meeting,
                tarea=self.task(tipo_ambito=Tarea.Ambito.DEPARTAMENTO, local=None, departamento=self.department),
                orden=2,
            )

    @patch("tareas.services.meetings.send_task_email")
    @patch("tareas.services.meetings.notify_task_event")
    def test_convene_notifies_once_and_records_timestamp(self, notify, email):
        meeting = self.meeting()
        add_meeting_participant(reunion=meeting, usuario=self.participant)
        convene_meeting(meeting, actor=self.user)
        meeting.refresh_from_db()
        self.assertIsNotNone(meeting.convocada_at)
        notify.assert_called_once()
        email.assert_called_once()
        with self.assertRaises(ValidationError):
            convene_meeting(meeting)

    def test_completion_requires_comments(self):
        meeting = self.meeting()
        item = add_task_to_meeting(reunion=meeting, tarea=self.task(), orden=1)
        with self.assertRaises(ValidationError):
            mark_meeting_completed(meeting)
        mark_meeting_completed(meeting, comentarios={item.pk: "Revisado"})
        meeting.refresh_from_db()
        self.assertEqual(meeting.estado, ReunionRevision.Estado.REALIZADA)
