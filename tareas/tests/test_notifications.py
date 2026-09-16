from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase

from tareas.services.notifications import notify_task_event, send_task_email
from tareas.tests.factories import create_empresa, create_tarea


class TaskNotificationAdapterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="NT", descripcion="Notificaciones")
        cls.creator = User.objects.create_user(username="notification_creator")
        cls.recipient = User.objects.create_user(username="notification_recipient")
        cls.second_recipient = User.objects.create_user(username="notification_second")
        cls.tarea = create_tarea(
            empresa=cls.empresa,
            creada_por=cls.creator,
            titulo="Tarea notificable",
        )

    @patch("tareas.services.notifications.create_notification")
    def test_notify_task_event_maps_task_context(self, create_notification):
        notification = Mock()
        create_notification.return_value = notification

        result = notify_task_event(
            tarea=self.tarea,
            destinatario=self.recipient,
            titulo="Tarea asignada",
            cuerpo="Revisar antecedentes",
            tipo="ALERT",
            url="/tareas/1/",
            actor=self.creator,
            dedupe_key="task:1:assigned",
        )

        self.assertIs(result, notification)
        create_notification.assert_called_once_with(
            destinatario=self.recipient,
            empresa=self.empresa,
            tipo="ALERT",
            titulo="Tarea asignada",
            cuerpo="Revisar antecedentes",
            url="/tareas/1/",
            actor=self.creator,
            dedupe_key="task:1:assigned",
        )

    @patch("tareas.services.notifications.send_email_for_purpose")
    def test_send_task_email_uses_notifications_account_for_multiple_recipients(
        self, send_email_for_purpose
    ):
        result = send_task_email(
            tarea=self.tarea,
            subject="Tarea asignada",
            body_text="Revisar antecedentes",
            to_emails=[self.recipient.email, self.second_recipient.email],
            body_html="<p>Revisar antecedentes</p>",
            reply_to="reply@example.test",
        )

        self.assertIs(result, send_email_for_purpose.return_value)
        send_email_for_purpose.assert_called_once_with(
            empresa=self.empresa,
            purpose="notifications",
            subject="Tarea asignada",
            body_text="Revisar antecedentes",
            to_emails=[self.recipient.email, self.second_recipient.email],
            body_html="<p>Revisar antecedentes</p>",
            reply_to="reply@example.test",
        )

    @patch("tareas.services.notifications.create_notification")
    def test_notification_errors_are_propagated(self, create_notification):
        create_notification.side_effect = RuntimeError("notification failure")

        with self.assertRaisesMessage(RuntimeError, "notification failure"):
            notify_task_event(
                tarea=self.tarea,
                destinatario=self.recipient,
                titulo="Tarea asignada",
            )

    @patch("tareas.services.notifications.send_email_for_purpose")
    def test_email_errors_are_propagated_without_real_delivery(self, send_email_for_purpose):
        send_email_for_purpose.side_effect = RuntimeError("email failure")

        with self.assertRaisesMessage(RuntimeError, "email failure"):
            send_task_email(
                tarea=self.tarea,
                subject="Tarea asignada",
                body_text="Revisar antecedentes",
                to_emails=[self.recipient.email],
            )
