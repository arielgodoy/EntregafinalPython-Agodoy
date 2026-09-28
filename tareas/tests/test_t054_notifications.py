from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import transaction
from django.test import TestCase

from access_control.models import Empresa
from tareas.models import Comentario, DocumentoTarea, Hito, Tarea, TareaLectura, TareaParticipante
from tareas.services.assignment import add_participant, assign_responsible, mark_task_read
from tareas.services.comments import create_comment, edit_comment, hide_comment, restore_comment
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
        assign_permission(cls.participant, cls.empresa, "Tareas", modificar=True)
        assign_permission(
            cls.supervisor,
            cls.empresa,
            "Tareas",
            modificar=True,
            supervisor=True,
        )
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

    def start_task(self, task):
        task.publicar(self.creator)
        transition_task(task, Tarea.Estado.GESTION, self.creator, "INICIAR_GESTION")
        return task

    def prepare_comment_task(self, *, prioridad=Tarea.Prioridad.NORMAL):
        task = self.make_task(prioridad=prioridad)
        add_participant(task, self.participant, actor=self.participants_admin)
        add_participant(task, self.supervisor, actor=self.participants_admin)
        Hito.objects.create(
            tarea=task,
            nombre="Hito T054",
            responsable=self.new_responsible,
            peso=1,
        )
        inactive = User.objects.create_user(
            username=f"t54_inactive_{task.pk}",
            email=f"inactive-{task.pk}@example.test",
            password="x",
        )
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])
        TareaParticipante.objects.create(tarea=task, usuario=inactive)
        self.start_task(task)
        return task

    def _recipient_ids(self, notify_task_event):
        return {
            call.kwargs["destinatario"].pk
            for call in notify_task_event.call_args_list
        }

    @patch("tareas.services.notifications.send_email_for_purpose")
    @patch("tareas.services.notifications.notify_task_event")
    def test_comment_create_notifies_effective_participants_without_document_event(
        self, notify_task_event, send_email_for_purpose
    ):
        task = self.prepare_comment_task()
        documento = create_document(
            tarea=task,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            usuario=self.participant,
            url="https://example.test/t054.pdf",
        )
        notify_task_event.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            create_comment(
                tarea=task,
                usuario=self.participant,
                contenido="contenido de prueba",
                documentos=[documento],
            )

        self.assertEqual(
            self._recipient_ids(notify_task_event),
            {self.responsible.pk, self.supervisor.pk, self.new_responsible.pk},
        )
        self.assertEqual(
            {call.kwargs["dedupe_key"].split(":")[2] for call in notify_task_event.call_args_list},
            {"comentario_agregado"},
        )
        self.assertNotIn(self.participant.pk, self._recipient_ids(notify_task_event))
        self.assertNotIn("documento_agregado", str(notify_task_event.call_args_list))
        send_email_for_purpose.assert_not_called()

    @patch("tareas.services.notifications.send_email_for_purpose")
    @patch("tareas.services.notifications.notify_task_event")
    def test_comment_edit_notifies_without_advancing_comment_cursor(
        self, notify_task_event, send_email_for_purpose
    ):
        task = self.prepare_comment_task()
        with self.captureOnCommitCallbacks(execute=True):
            comentario = create_comment(
                tarea=task,
                usuario=self.participant,
                contenido="original",
            )
        notify_task_event.reset_mock()
        lectura = TareaLectura.objects.get(tarea=task, usuario=self.supervisor)
        cursor_before = lectura.comentario_leido_hasta_id

        with self.captureOnCommitCallbacks(execute=True):
            edit_comment(
                comentario=comentario,
                usuario=self.participant,
                contenido="editado",
            )

        lectura.refresh_from_db()
        self.assertEqual(lectura.comentario_leido_hasta_id, cursor_before)
        self.assertEqual(
            {call.kwargs["dedupe_key"].split(":")[2] for call in notify_task_event.call_args_list},
            {"comentario_editado"},
        )
        self.assertNotIn("texto privado de edición", str(notify_task_event.call_args_list))
        send_email_for_purpose.assert_not_called()

    @patch("tareas.services.notifications.send_email_for_purpose")
    @patch("tareas.services.notifications.notify_task_event")
    def test_comment_hide_is_private_and_does_not_create_comment_unread(
        self, notify_task_event, send_email_for_purpose
    ):
        task = self.prepare_comment_task()
        with self.captureOnCommitCallbacks(execute=True):
            comentario = create_comment(
                tarea=task,
                usuario=self.participant,
                contenido="secreto ocultable",
            )
        notify_task_event.reset_mock()
        lectura = TareaLectura.objects.get(tarea=task, usuario=self.supervisor)
        cursor_before = lectura.comentario_leido_hasta_id

        with self.captureOnCommitCallbacks(execute=True):
            hide_comment(
                comentario=comentario,
                usuario=self.supervisor,
                motivo="Moderación T054",
            )

        lectura.refresh_from_db()
        self.assertEqual(lectura.comentario_leido_hasta_id, cursor_before)
        self.assertEqual(
            {call.kwargs["dedupe_key"].split(":")[2] for call in notify_task_event.call_args_list},
            {"comentario_ocultado"},
        )
        self.assertNotIn("secreto ocultable", str(notify_task_event.call_args_list))
        self.assertNotIn("Moderación T054", str(notify_task_event.call_args_list))
        send_email_for_purpose.assert_not_called()

    @patch("tareas.services.notifications.send_email_for_purpose")
    @patch("tareas.services.notifications.notify_task_event")
    def test_comment_restore_is_private_and_does_not_create_comment_unread(
        self, notify_task_event, send_email_for_purpose
    ):
        task = self.prepare_comment_task()
        with self.captureOnCommitCallbacks(execute=True):
            comentario = create_comment(
                tarea=task,
                usuario=self.participant,
                contenido="contenido restaurable",
            )
            hide_comment(
                comentario=comentario,
                usuario=self.supervisor,
                motivo="Ocultación previa",
            )
        notify_task_event.reset_mock()
        lectura = TareaLectura.objects.get(tarea=task, usuario=self.supervisor)
        cursor_before = lectura.comentario_leido_hasta_id

        with self.captureOnCommitCallbacks(execute=True):
            restore_comment(
                comentario=comentario,
                usuario=self.supervisor,
                motivo="Restauración T054",
            )

        lectura.refresh_from_db()
        self.assertEqual(lectura.comentario_leido_hasta_id, cursor_before)
        self.assertEqual(
            {call.kwargs["dedupe_key"].split(":")[2] for call in notify_task_event.call_args_list},
            {"comentario_restaurado"},
        )
        self.assertNotIn("contenido restaurable", str(notify_task_event.call_args_list))
        self.assertNotIn("Restauración T054", str(notify_task_event.call_args_list))
        send_email_for_purpose.assert_not_called()

    @patch("tareas.services.notifications.send_email_for_purpose")
    @patch("tareas.services.notifications.notify_task_event")
    def test_critical_comment_uses_system_email_notifications_purpose(self, notify_task_event, send_email_for_purpose):
        task = self.prepare_comment_task(prioridad=Tarea.Prioridad.CRITICA)

        with self.captureOnCommitCallbacks(execute=True):
            create_comment(
                tarea=task,
                usuario=self.participant,
                contenido="comentario crítico",
            )

        self.assertTrue(notify_task_event.called)
        self.assertEqual(
            {call.kwargs["purpose"] for call in send_email_for_purpose.call_args_list},
            {"notifications"},
        )
        self.assertTrue(
            all(call.kwargs["empresa"] == task.empresa for call in send_email_for_purpose.call_args_list)
        )
        self.assertTrue(
            all("comentario crítico" not in str(call) for call in send_email_for_purpose.call_args_list)
        )

    @patch("tareas.services.notifications.send_email_for_purpose")
    @patch("tareas.services.notifications.notify_task_event")
    def test_comment_create_deduplicates_multi_route_participants_and_actor(
        self, notify_task_event, send_email_for_purpose
    ):
        task = self.make_task(responsable=self.supervisor)
        add_participant(task, self.supervisor, actor=self.participants_admin)
        add_participant(task, self.participant, actor=self.participants_admin)
        Hito.objects.create(
            tarea=task,
            nombre="Hito actor T054",
            responsable=self.supervisor,
            peso=1,
        )
        Hito.objects.create(
            tarea=task,
            nombre="Hito destinatario T054",
            responsable=self.participant,
            peso=1,
        )
        self.start_task(task)

        with self.captureOnCommitCallbacks(execute=True):
            create_comment(
                tarea=task,
                usuario=self.supervisor,
                contenido="comentario con participación duplicada",
            )

        self.assertEqual(notify_task_event.call_count, 1)
        self.assertEqual(
            [call.kwargs["destinatario"] for call in notify_task_event.call_args_list],
            [self.participant],
        )
        self.assertEqual(
            [call.kwargs["dedupe_key"].split(":")[2] for call in notify_task_event.call_args_list],
            ["comentario_agregado"],
        )
        self.assertNotIn(
            self.supervisor,
            [call.kwargs["destinatario"] for call in notify_task_event.call_args_list],
        )
        send_email_for_purpose.assert_not_called()

    @patch("tareas.services.notifications.send_email_for_purpose")
    @patch("tareas.services.notifications.notify_task_event")
    def test_comment_create_inline_attachment_has_only_comment_event(
        self, notify_task_event, send_email_for_purpose
    ):
        task = self.prepare_comment_task()

        with self.captureOnCommitCallbacks(execute=True):
            comentario = create_comment(
                tarea=task,
                usuario=self.participant,
                contenido="comentario con adjunto inline",
                documentos_nuevos=[
                    {
                        "tipo": DocumentoTarea.Tipo.INFORME,
                        "formato_archivo": DocumentoTarea.FormatoArchivo.PDF,
                        "url": "https://example.test/t054-inline.pdf",
                    }
                ],
            )

        documento = DocumentoTarea.objects.get(
            tarea=task,
            url="https://example.test/t054-inline.pdf",
        )
        self.assertTrue(
            Comentario.objects.filter(pk=comentario.pk, adjuntos__documento=documento).exists()
        )
        self.assertEqual(notify_task_event.call_count, 3)
        self.assertEqual(
            {call.kwargs["dedupe_key"].split(":")[2] for call in notify_task_event.call_args_list},
            {"comentario_agregado"},
        )
        self.assertNotIn("documento_agregado", str(notify_task_event.call_args_list))
        send_email_for_purpose.assert_not_called()

    @patch("tareas.services.notifications.send_email_for_purpose")
    @patch("tareas.services.notifications.notify_task_event")
    def test_comment_attachment_only_edit_has_only_comment_event(
        self, notify_task_event, send_email_for_purpose
    ):
        task = self.prepare_comment_task()
        documento = create_document(
            tarea=task,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            usuario=self.participant,
            url="https://example.test/t054-edit-inline.pdf",
        )
        with self.captureOnCommitCallbacks(execute=True):
            comentario = create_comment(
                tarea=task,
                usuario=self.participant,
                contenido="comentario editable",
                documentos=[documento],
            )
        notify_task_event.reset_mock()
        send_email_for_purpose.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            edit_comment(
                comentario=comentario,
                usuario=self.participant,
                documentos_nuevos=[
                    {
                        "tipo": DocumentoTarea.Tipo.INFORME,
                        "formato_archivo": DocumentoTarea.FormatoArchivo.PDF,
                        "url": "https://example.test/t054-edit-new.pdf",
                    }
                ],
            )

        self.assertTrue(
            Comentario.objects.filter(
                pk=comentario.pk,
                adjuntos__documento=documento,
            ).exists()
        )
        self.assertTrue(
            Comentario.objects.filter(
                pk=comentario.pk,
                adjuntos__documento__url="https://example.test/t054-edit-new.pdf",
            ).exists()
        )
        self.assertEqual(notify_task_event.call_count, 3)
        self.assertEqual(
            {call.kwargs["dedupe_key"].split(":")[2] for call in notify_task_event.call_args_list},
            {"comentario_editado"},
        )
        self.assertNotIn("documento_agregado", str(notify_task_event.call_args_list))
        send_email_for_purpose.assert_not_called()

    @patch("tareas.services.notifications.send_email_for_purpose")
    @patch("tareas.services.notifications.notify_task_event")
    def test_comment_priorities_send_email_only_for_critical(
        self, notify_task_event, send_email_for_purpose
    ):
        for prioridad in (
            Tarea.Prioridad.SIMPLE,
            Tarea.Prioridad.NORMAL,
            Tarea.Prioridad.URGENTE,
            Tarea.Prioridad.CRITICA,
        ):
            with self.subTest(prioridad=prioridad):
                task = self.prepare_comment_task(prioridad=prioridad)
                notify_task_event.reset_mock()
                send_email_for_purpose.reset_mock()

                with self.captureOnCommitCallbacks(execute=True):
                    create_comment(
                        tarea=task,
                        usuario=self.participant,
                        contenido=f"comentario {prioridad}",
                    )

                self.assertTrue(notify_task_event.called)
                if prioridad == Tarea.Prioridad.CRITICA:
                    self.assertEqual(send_email_for_purpose.call_count, 3)
                    self.assertEqual(
                        {call.kwargs["purpose"] for call in send_email_for_purpose.call_args_list},
                        {"notifications"},
                    )
                    self.assertTrue(
                        all(
                            call.kwargs["empresa"] == task.empresa
                            for call in send_email_for_purpose.call_args_list
                        )
                    )
                else:
                    send_email_for_purpose.assert_not_called()

    @patch("tareas.services.comments.emit_task_event")
    def test_comment_create_rollback_discards_on_commit_callback(self, emit_task_event):
        task = self.prepare_comment_task()

        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            try:
                with transaction.atomic():
                    create_comment(
                        tarea=task,
                        usuario=self.participant,
                        contenido="comentario revertido",
                    )
                    raise RuntimeError("rollback T054")
            except RuntimeError:
                pass

        emit_task_event.assert_not_called()
        self.assertEqual(callbacks, [])
        self.assertFalse(Comentario.objects.filter(contenido="comentario revertido").exists())

    @patch("tareas.services.comments.emit_task_event")
    def test_comment_create_outer_transaction_emits_after_commit(self, emit_task_event):
        task = self.prepare_comment_task()

        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                create_comment(
                    tarea=task,
                    usuario=self.participant,
                    contenido="comentario confirmado",
                )
                emit_task_event.assert_not_called()

            emit_task_event.assert_not_called()

        self.assertEqual(emit_task_event.call_count, 1)
        self.assertEqual(emit_task_event.call_args.kwargs["event"], "comentario_agregado")

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
