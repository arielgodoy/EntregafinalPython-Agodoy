from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa
from tareas.models import DocumentoTarea, Tarea, TareaParticipante
from tareas.services.assignment import add_participant, assign_responsible, mark_task_read
from tareas.services.documents import create_document
from tareas.services.lifecycle import (
    annul_task,
    approve_closure,
    complete_task,
    reactivate_task,
    reject_closure,
    transition_task,
)
from tareas.services.notifications import emit_task_event
from tareas.tests.factories import assign_permission, create_tarea

T054_COMMENT_EVENT_DEFERRED_NON_BLOCKING = True


class T054NotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="T54", descripcion="T054")
        cls.creator = User.objects.create_user(
            username="t54_creator", email="creator@example.test", password="x"
        )
        cls.responsible = User.objects.create_user(
            username="t54_responsible", email="responsible@example.test", password="x"
        )
        cls.new_responsible = User.objects.create_user(
            username="t54_new_responsible", email="new@example.test", password="x"
        )
        cls.authorizer = User.objects.create_user(
            username="t54_authorizer", email="authorizer@example.test", password="x"
        )
        cls.second_authorizer = User.objects.create_user(
            username="t54_authorizer_2", email="authorizer2@example.test", password="x"
        )
        cls.supervisor = User.objects.create_user(
            username="t54_supervisor", email="supervisor@example.test", password="x"
        )
        cls.participant = User.objects.create_user(
            username="t54_participant", email="participant@example.test", password="x"
        )
        for user in [
            cls.creator,
            cls.responsible,
            cls.new_responsible,
            cls.authorizer,
            cls.second_authorizer,
            cls.supervisor,
            cls.participant,
        ]:
            assign_permission(user, cls.empresa, "Tareas", ingresar=True)
        cls.participants_admin = User.objects.create_user(
            username="t54_participants_admin", password="x"
        )
        assign_permission(
            cls.participants_admin, cls.empresa, "Tareas", ingresar=True, modificar=True
        )

    def make_task(self, **kwargs):
        defaults = {
            "responsable": self.responsible,
            "fecha_tope": date.today(),
        }
        defaults.update(kwargs)
        return create_tarea(self.empresa, self.creator, **defaults)

    def test_comment_event_is_deferred_and_non_blocking(self):
        self.assertTrue(T054_COMMENT_EVENT_DEFERRED_NON_BLOCKING)

    def start_task(self, task):
        task.publicar(self.creator)
        transition_task(task, Tarea.Estado.GESTION, self.creator, "INICIAR_GESTION")
        return task

    @patch("tareas.services.notifications.send_task_email")
    @patch("tareas.services.notifications.notify_task_event")
    def test_reasignacion_notifica_nuevo_responsable_y_excluye_actor(
        self, notify_task_event, send_task_email
    ):
        task = self.make_task(responsable=None)

        assign_responsible(task, self.new_responsible, self.creator)

        self.assertEqual(
            [call.kwargs["destinatario"] for call in notify_task_event.call_args_list],
            [self.new_responsible],
        )
        send_task_email.assert_not_called()

    @patch("tareas.services.notifications.send_task_email")
    @patch("tareas.services.notifications.notify_task_event")
    def test_lectura_no_notifica(self, notify_task_event, send_task_email):
        task = self.make_task()

        mark_task_read(task, self.participant)

        notify_task_event.assert_not_called()
        send_task_email.assert_not_called()

    @patch("tareas.services.notifications.send_task_email")
    @patch("tareas.services.notifications.notify_task_event")
    def test_documento_notifica_creador_responsable_y_participante(
        self, notify_task_event, send_task_email
    ):
        task = self.make_task()
        add_participant(task, self.participant, actor=self.participants_admin)

        create_document(
            tarea=task,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            usuario=self.creator,
            url="https://example.test/informe",
        )

        self.assertEqual(
            {call.kwargs["destinatario"] for call in notify_task_event.call_args_list},
            {self.responsible, self.participant},
        )
        send_task_email.assert_not_called()

    @patch("tareas.services.notifications.send_task_email")
    @patch("tareas.services.notifications.notify_task_event")
    def test_solicitud_cierre_solo_autorizadores_activos(self, notify_task_event, send_task_email):
        task = self.make_task()
        admin = self.participants_admin
        add_participant(task, self.authorizer, TareaParticipante.Rol.AUTORIZADOR, actor=admin)
        add_participant(
            task, self.second_authorizer, TareaParticipante.Rol.AUTORIZADOR, actor=admin
        )
        add_participant(task, self.supervisor, TareaParticipante.Rol.SUPERVISOR, actor=admin)
        self.start_task(task)

        complete_task(task, self.responsible)

        self.assertEqual(
            {call.kwargs["destinatario"] for call in notify_task_event.call_args_list},
            {self.authorizer, self.second_authorizer},
        )
        send_task_email.assert_not_called()

    @patch("tareas.services.notifications.send_task_email")
    @patch("tareas.services.notifications.notify_task_event")
    def test_solicitud_cierre_usa_fallback_creador(self, notify_task_event, send_task_email):
        task = self.make_task()
        self.start_task(task)

        complete_task(task, self.responsible)

        self.assertEqual(
            [call.kwargs["destinatario"] for call in notify_task_event.call_args_list],
            [self.creator],
        )
        send_task_email.assert_not_called()

    @patch("tareas.services.notifications.send_task_email")
    @patch("tareas.services.notifications.notify_task_event")
    def test_autorizadores_inactivos_usan_fallback_creador(
        self, notify_task_event, send_task_email
    ):
        inactive_authorizer = User.objects.create_user(
            username="t54_inactive_authorizer", email="inactive@example.test", password="x"
        )
        inactive_authorizer.is_active = False
        inactive_authorizer.save(update_fields=["is_active"])
        task = self.make_task()
        TareaParticipante.objects.create(
            tarea=task,
            usuario=inactive_authorizer,
            rol=TareaParticipante.Rol.AUTORIZADOR,
        )
        self.start_task(task)

        complete_task(task, self.responsible)

        self.assertEqual(
            [call.kwargs["destinatario"] for call in notify_task_event.call_args_list],
            [self.creator],
        )
        send_task_email.assert_not_called()

    @patch("tareas.services.notifications.send_task_email")
    @patch("tareas.services.notifications.notify_task_event")
    def test_aprobacion_y_rechazo_notifican_creador_y_responsable_sin_actor(
        self, notify_task_event, send_task_email
    ):
        task = self.make_task()
        self.start_task(task)
        complete_task(task, self.responsible)
        notify_task_event.reset_mock()
        approve_closure(task, self.authorizer)

        self.assertEqual(
            {call.kwargs["destinatario"] for call in notify_task_event.call_args_list},
            {self.creator, self.responsible},
        )

        task = self.make_task(titulo="Rechazo")
        self.start_task(task)
        complete_task(task, self.responsible)
        notify_task_event.reset_mock()
        reject_closure(task, self.authorizer)

        self.assertEqual(
            {call.kwargs["destinatario"] for call in notify_task_event.call_args_list},
            {self.creator, self.responsible},
        )
        send_task_email.assert_not_called()

    @patch("tareas.services.notifications.send_task_email")
    @patch("tareas.services.notifications.notify_task_event")
    def test_anulacion_y_reactivacion_notifican_participantes(self, notify_task_event, send_task_email):
        task = self.make_task()
        add_participant(task, self.participant, actor=self.participants_admin)
        self.start_task(task)

        annul_task(task, self.creator)
        destinatarios_anulacion = {
            call.kwargs["destinatario"] for call in notify_task_event.call_args_list
        }
        self.assertEqual(destinatarios_anulacion, {self.responsible, self.participant})

        notify_task_event.reset_mock()
        reactivate_task(task, self.creator)
        destinatarios_reactivacion = {
            call.kwargs["destinatario"] for call in notify_task_event.call_args_list
        }
        self.assertEqual(destinatarios_reactivacion, {self.responsible, self.participant})
        send_task_email.assert_not_called()

    @patch("tareas.services.notifications.send_task_email")
    @patch("tareas.services.notifications.notify_task_event")
    def test_normal_solo_in_app_y_critica_usa_email_sistema(
        self, notify_task_event, send_task_email
    ):
        task = self.make_task()
        emit_task_event(
            tarea=task,
            event="cambio_relevante",
            recipients=[self.responsible, self.responsible],
            title="Cambio",
            actor=self.creator,
        )
        self.assertEqual(notify_task_event.call_count, 1)
        send_task_email.assert_not_called()

        notify_task_event.reset_mock()
        task.prioridad = Tarea.Prioridad.CRITICA
        task.save(update_fields=["prioridad"])
        emit_task_event(
            tarea=task,
            event="cambio_relevante",
            recipients=[self.responsible, self.responsible],
            title="Cambio crítico",
            actor=self.creator,
        )
        self.assertEqual(notify_task_event.call_count, 1)
        send_task_email.assert_called_once()
        self.assertEqual(send_task_email.call_args.kwargs["to_emails"], [self.responsible.email])

    @patch("tareas.services.notifications.create_notification")
    def test_fallo_in_app_no_revierte_y_continua_con_otros_destinatarios(
        self, create_notification
    ):
        task = self.make_task()
        create_notification.side_effect = [RuntimeError("in-app failure"), None]

        emit_task_event(
            tarea=task,
            event="cambio_relevante",
            recipients=[self.responsible, self.participant],
            title="Cambio",
            actor=self.creator,
        )

        task.refresh_from_db()
        self.assertEqual(task.responsable, self.responsible)
        self.assertEqual(create_notification.call_count, 2)

    @patch("tareas.services.notifications.send_email_for_purpose")
    @patch("tareas.services.notifications.create_notification")
    def test_fallo_email_critico_no_revierte_y_continua_con_otros_destinatarios(
        self, create_notification, send_email_for_purpose
    ):
        task = self.make_task(prioridad=Tarea.Prioridad.CRITICA)
        send_email_for_purpose.side_effect = [RuntimeError("email failure"), None]

        emit_task_event(
            tarea=task,
            event="cambio_relevante",
            recipients=[self.responsible, self.participant],
            title="Cambio crítico",
            actor=self.creator,
        )

        task.refresh_from_db()
        self.assertEqual(task.responsable, self.responsible)
        self.assertEqual(create_notification.call_count, 2)
        self.assertEqual(send_email_for_purpose.call_count, 2)
