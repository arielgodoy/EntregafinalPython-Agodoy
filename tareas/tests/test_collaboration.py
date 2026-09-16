from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from access_control.models import Empresa, Permiso, PerfilAcceso, UsuarioPerfilEmpresa, Vista
from organizacion.models import Local, OrganizationalSource
from tareas.models import ReunionRevision, Tarea
from tareas.services.links import create_task_link, resolve_task_link
from tareas.services.meetings import add_meeting_participant, convene_meeting, create_meeting


class T061CollaborationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="C61", descripcion="Empresa colaboración")
        cls.otra_empresa = Empresa.objects.create(codigo="C62", descripcion="Otra empresa")
        cls.usuario = User.objects.create_user("collab_creator", email="creator@example.test")
        cls.participante = User.objects.create_user("collab_participant", email="participant@example.test")
        cls.externo = User.objects.create_user("collab_external", email="external@example.test")
        vista = Vista.objects.create(nombre="Tareas")
        for usuario in (cls.usuario, cls.participante):
            Permiso.objects.create(
                usuario=usuario,
                empresa=cls.empresa,
                vista=vista,
                ingresar=True,
                crear=True,
                modificar=True,
            )
        perfil = PerfilAcceso.objects.create(nombre="Perfil colaboración")
        UsuarioPerfilEmpresa.objects.create(usuario=cls.usuario, empresa=cls.empresa, perfil=perfil)
        UsuarioPerfilEmpresa.objects.create(usuario=cls.participante, empresa=cls.empresa, perfil=perfil)
        UsuarioPerfilEmpresa.objects.create(usuario=cls.externo, empresa=cls.otra_empresa, perfil=perfil)
        cls.local = Local.objects.create(
            empresa=cls.empresa,
            codigo="LOC-C61",
            nombre="Local colaboración",
            source=OrganizationalSource.LOCAL,
        )

    def create_meeting(self):
        return create_meeting(
            empresa=self.empresa,
            creada_por=self.usuario,
            titulo="Revisión colaborativa",
            descripcion="Revisión",
            fecha_hora_programada=datetime.combine(date(2026, 10, 1), time(10, 0)),
            modalidad=ReunionRevision.Modalidad.ZOOM,
            lugar_o_enlace="https://zoom.example.test/collab",
            tipo_ambito=ReunionRevision.TipoAmbito.LOCAL,
            local=self.local,
        )

    def test_meeting_convene_mocks_notification_and_email(self):
        meeting = self.create_meeting()
        add_meeting_participant(reunion=meeting, usuario=self.participante)
        with patch("tareas.services.meetings.notify_task_event") as notify, patch(
            "tareas.services.meetings.send_task_email"
        ) as email:
            convene_meeting(meeting, actor=self.usuario)
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(email.call_count, 1)
        meeting.refresh_from_db()
        self.assertIsNotNone(meeting.convocada_at)

    def test_link_rejects_cross_company_access(self):
        tarea = Tarea.objects.create(
            titulo="Tarea compartida",
            correlativo="B6100001",
            empresa=self.empresa,
            creada_por=self.usuario,
            responsable=self.usuario,
            fecha_tope=date(2026, 10, 1),
        )
        with patch("tareas.services.links.create_notification"), patch(
            "tareas.services.links.send_email_for_purpose"
        ):
            _, token = create_task_link(
                tarea=tarea,
                destinatario=self.participante,
                creado_por=self.usuario,
                fecha_expiracion=timezone.now() + timedelta(days=1),
            )
        with self.assertRaises(ValidationError):
            resolve_task_link(token=token, usuario=self.externo, empresa=self.otra_empresa)
