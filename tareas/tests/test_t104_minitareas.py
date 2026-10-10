from datetime import date
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa
from tareas.forms import MiniTareaCloseForm
from tareas.models import (
    Comentario,
    ComentarioVersion,
    DocumentoTarea,
    MiniTarea,
    MiniTareaEvento,
    Tarea,
    TareaConnectionRole,
    TareaParticipante,
)
from tareas.services.closure import (
    close_mini_task,
    create_mini_task,
    reopen_mini_task,
    set_mini_task_done,
)
from tareas.services.lifecycle import transition_task
from tareas.tests.factories import activate_company, assign_permission, simple_jpeg_upload


class MiniTareaT104Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = Empresa.objects.create(codigo="00", descripcion="T104")
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS", source_type="DJANGO", django_alias="default"
        )
        cls.otra_empresa = Empresa.objects.create(codigo="02", descripcion="T104 B")
        cls.creador = User.objects.create_user("t104_creador", email="creador@example.test")
        cls.responsable = User.objects.create_user("t104_responsable", email="responsable@example.test")
        cls.asignado = User.objects.create_user("t104_asignado", email="asignado@example.test")
        cls.supervisor = User.objects.create_user("t104_supervisor", email="supervisor@example.test")
        cls.tercero = User.objects.create_user("t104_tercero", email="tercero@example.test")
        for user in (cls.creador, cls.responsable, cls.asignado, cls.supervisor, cls.tercero):
            assign_permission(
                user,
                cls.empresa,
                "Tareas",
                ingresar=True,
                modificar=True,
                crear=user in {cls.creador, cls.responsable, cls.supervisor},
                supervisor=user == cls.supervisor,
            )
        cls.foreign_user = User.objects.create_user("t104_externo", email="externo@example.test")

    def make_task(self, estado=Tarea.Estado.GESTION):
        tarea = Tarea.objects.create(
            titulo="Tarea T104",
            empresa=self.empresa,
            creada_por=self.creador,
            responsable=self.responsable,
            fecha_tope=date.today(),
        )
        tarea.publicar(self.creador)
        if estado == Tarea.Estado.GESTION:
            transition_task(tarea, Tarea.Estado.GESTION, self.creador, "INICIAR_GESTION")
        return tarea

    def make_pdf_spec(self, filename):
        return {
            "tipo": DocumentoTarea.Tipo.OTRO,
            "formato_archivo": DocumentoTarea.FormatoArchivo.PDF,
            "archivo": SimpleUploadedFile(
                filename,
                b"%PDF-1.4\nT104 attachment\n",
                content_type="application/pdf",
            ),
        }

    def test_create_responsible_and_supervisor_only(self):
        tarea = self.make_task()
        created = create_mini_task(
            tarea=tarea,
            descripcion="Validar cotización",
            persona=self.asignado,
            actor=self.responsable,
        )
        self.assertEqual(created.persona_id, self.asignado.pk)
        with self.assertRaises(ValidationError):
            create_mini_task(
                tarea=tarea,
                descripcion="No autorizado",
                persona=self.asignado,
                actor=self.tercero,
            )
        supervised = create_mini_task(
            tarea=tarea,
            descripcion="Revisión S",
            persona=self.asignado,
            actor=self.supervisor,
        )
        self.assertEqual(supervised.descripcion, "Revisión S")

    def test_create_rejects_foreign_assignee_and_frozen_lifecycle(self):
        tarea = self.make_task()
        with self.assertRaises(ValidationError):
            create_mini_task(
                tarea=tarea,
                descripcion="Fuera de empresa",
                persona=self.foreign_user,
                actor=self.responsable,
            )
        tarea.estado = Tarea.Estado.PENDIENTE_APROBACION_CIERRE
        tarea.save(update_fields=["estado"])
        with self.assertRaises(ValidationError):
            create_mini_task(
                tarea=tarea,
                descripcion="Congelada",
                persona=self.asignado,
                actor=self.responsable,
            )

    @patch("tareas.services.minitask_storage.send_task_email")
    @patch("tareas.services.minitask_storage.emit_task_event")
    def test_close_persists_event_snapshot_and_opt_in_channels(
        self, emit_task_event, send_task_email
    ):
        tarea = self.make_task()
        mini_tarea = create_mini_task(
            tarea=tarea,
            descripcion="Enviar informe",
            persona=self.asignado,
            actor=self.responsable,
        )
        TareaParticipante.objects.create(tarea=tarea, usuario=self.supervisor)
        with self.captureOnCommitCallbacks(execute=True):
            _mini_tarea, evento = close_mini_task(
                tarea=tarea,
                mini_tarea=mini_tarea,
                actor=self.asignado,
                comentario="Informe enviado",
                notification_recipient_ids=[self.supervisor.pk, self.asignado.pk],
                email_recipient_ids=[self.supervisor.pk],
            )
        mini_tarea.refresh_from_db()
        evento = MiniTareaEvento.objects.get(mini_tarea=mini_tarea)
        self.assertTrue(mini_tarea.hecho)
        self.assertIsNotNone(mini_tarea.fecha_completado)
        self.assertEqual(evento.tipo, MiniTareaEvento.Tipo.CIERRE)
        self.assertEqual(evento.actor_id, self.asignado.pk)
        self.assertEqual(evento.comentario, "Informe enviado")
        self.assertEqual(evento.destinatarios_notificacion, [self.supervisor.pk])
        self.assertEqual(evento.destinatarios_email, [self.supervisor.pk])
        self.assertIsNotNone(evento.comentario_feed_id)
        self.assertEqual(evento.comentario_feed.autor_id, self.asignado.pk)
        self.assertEqual(evento.comentario_feed.adjuntos.count(), 0)
        emit_task_event.assert_called_once()
        self.assertFalse(emit_task_event.call_args.kwargs["send_email"])
        send_task_email.assert_called_once()

    @patch("tareas.services.minitask_storage.emit_task_event")
    def test_close_creates_feed_comment_with_author_version_and_attachment(self, emit_task_event):
        tarea = self.make_task()
        mini_tarea = create_mini_task(
            tarea=tarea,
            descripcion="Adjuntar evidencia",
            persona=self.asignado,
            actor=self.responsable,
        )
        archivo = simple_jpeg_upload("evidencia.jpg")

        with self.captureOnCommitCallbacks(execute=True):
            close_mini_task(
                tarea=tarea,
                mini_tarea=mini_tarea,
                actor=self.asignado,
                comentario="Evidencia cargada",
                documentos_nuevos=[
                    {
                        "tipo": DocumentoTarea.Tipo.OTRO,
                        "formato_archivo": DocumentoTarea.FormatoArchivo.JPG,
                        "archivo": archivo,
                    }
                ],
            )

        comentario = Comentario.objects.get(tarea=tarea)
        self.assertEqual(comentario.autor_id, self.asignado.pk)
        self.assertIn("Adjuntar evidencia", comentario.contenido)
        self.assertIn("Evidencia cargada", comentario.contenido)
        self.assertEqual(comentario.adjuntos.count(), 1)
        self.assertEqual(comentario.adjuntos.get().documento.tipo, DocumentoTarea.Tipo.OTRO)
        self.assertEqual(
            comentario.versiones.get().evento,
            ComentarioVersion.Evento.CREADO,
        )
        emit_task_event.assert_not_called()

    def test_close_form_accepts_five_files_and_rejects_invalid_or_sixth(self):
        tarea = self.make_task()
        valid_files = [simple_jpeg_upload(f"evidencia-{index}.jpg") for index in range(5)]
        valid_form = MiniTareaCloseForm(
            {"comentario": "Cierre"},
            {"archivos": valid_files},
            tarea=tarea,
            actor=self.asignado,
        )
        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        self.assertEqual(len(valid_form.nuevos_documentos()), 5)

        too_many_form = MiniTareaCloseForm(
            {"comentario": "Cierre"},
            {"archivos": valid_files + [simple_jpeg_upload("evidencia-5.jpg")]},
            tarea=tarea,
            actor=self.asignado,
        )
        self.assertFalse(too_many_form.is_valid())

        invalid_form = MiniTareaCloseForm(
            {"comentario": "Cierre"},
            {"archivos": [simple_jpeg_upload("evidencia.exe")]},
            tarea=tarea,
            actor=self.asignado,
        )
        self.assertFalse(invalid_form.is_valid())

    def test_reopen_requires_responsible_or_supervisor_and_preserves_cycles(self):
        tarea = self.make_task()
        mini_tarea = create_mini_task(
            tarea=tarea,
            descripcion="Completar revisión",
            persona=self.asignado,
            actor=self.responsable,
        )
        _, primer_evento = close_mini_task(
            tarea=tarea,
            mini_tarea=mini_tarea,
            actor=self.asignado,
            comentario="Primera revisión lista",
            documentos_nuevos=[self.make_pdf_spec("a.pdf")],
        )
        primer_archivo = primer_evento.comentario_feed.adjuntos.get().documento.archivo.name
        self.assertTrue(primer_archivo.startswith("tareas/documentos/a"))
        self.assertTrue(primer_archivo.endswith(".pdf"))
        self.assertEqual(Comentario.objects.filter(tarea=tarea).count(), 1)
        with self.assertRaises(ValidationError):
            reopen_mini_task(
                tarea=tarea,
                mini_tarea=mini_tarea,
                actor=self.asignado,
                comentario="No puedo reabrir por asignación",
            )
        reopen_mini_task(
            tarea=tarea,
            mini_tarea=mini_tarea,
            actor=self.responsable,
            comentario="Falta un antecedente",
        )
        self.assertEqual(Comentario.objects.filter(tarea=tarea).count(), 1)
        _, segundo_evento = close_mini_task(
            tarea=tarea,
            mini_tarea=mini_tarea,
            actor=self.responsable,
            comentario="Antecedente incorporado",
            documentos_nuevos=[
                self.make_pdf_spec("b.pdf"),
                self.make_pdf_spec("c.pdf"),
            ],
        )
        self.assertEqual(Comentario.objects.filter(tarea=tarea).count(), 2)
        self.assertIsNone(
            MiniTareaEvento.objects.get(
                mini_tarea=mini_tarea,
                tipo=MiniTareaEvento.Tipo.REAPERTURA,
            ).comentario_feed_id
        )
        self.assertEqual(segundo_evento.comentario_feed.adjuntos.count(), 2)
        archivos_historial = [
            adjunto.documento.archivo.name
            for evento in (primer_evento, segundo_evento)
            for adjunto in evento.comentario_feed.adjuntos.select_related("documento")
        ]

        client = self.client
        client.force_login(self.responsable)
        activate_company(client, self.empresa)
        detail = client.get(reverse("tareas:detalle_tarea", args=[tarea.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'data-key="tareas.minitareas.attachment">Evidencia')
        self.assertContains(detail, 'class="task-detail__mini-evidence"')
        history = client.get(
            reverse("tareas:historial_minitarea", args=[tarea.pk, mini_tarea.pk])
        )
        self.assertEqual(history.status_code, 200)
        for archivo in archivos_historial:
            self.assertContains(history, archivo)
        self.assertTrue(MiniTarea.objects.get(pk=mini_tarea.pk).hecho)
        self.assertEqual(
            list(
                MiniTareaEvento.objects.filter(mini_tarea=mini_tarea).values_list(
                    "tipo", "comentario"
                )
            ),
            [
                (MiniTareaEvento.Tipo.CIERRE, "Primera revisión lista"),
                (MiniTareaEvento.Tipo.REAPERTURA, "Falta un antecedente"),
                (MiniTareaEvento.Tipo.CIERRE, "Antecedente incorporado"),
            ],
        )

    def test_web_create_close_reopen_and_history(self):
        tarea = self.make_task()
        client = self.client
        client.force_login(self.responsable)
        activate_company(client, self.empresa)
        response = client.post(
            reverse("tareas:minitareas_tarea", args=[tarea.pk]),
            {"descripcion": "Alta web", "persona": self.asignado.pk},
        )
        self.assertEqual(response.status_code, 302)
        mini_tarea = MiniTarea.objects.get(tarea=tarea)
        client.force_login(self.asignado)
        activate_company(client, self.empresa)
        response = client.post(
            reverse("tareas:cerrar_minitarea", args=[tarea.pk, mini_tarea.pk]),
            {
                "comentario": "Cierre web",
                "archivos": simple_jpeg_upload("cierre-web.jpg"),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Comentario.objects.filter(tarea=tarea).count(), 1)
        client.force_login(self.responsable)
        activate_company(client, self.empresa)
        response = client.post(
            reverse("tareas:reabrir_minitarea", args=[tarea.pk, mini_tarea.pk]),
            {"comentario": "Revisión adicional"},
        )
        self.assertEqual(response.status_code, 302)
        history = client.get(
            reverse("tareas:historial_minitarea", args=[tarea.pk, mini_tarea.pk])
        )
        self.assertEqual(history.status_code, 200)
        self.assertContains(history, "Cierre web")
        self.assertContains(history, "Revisión adicional")

    def test_detail_renders_minitarea_block(self):
        tarea = self.make_task()
        create_mini_task(
            tarea=tarea,
            descripcion="Visible en detalle",
            persona=self.asignado,
            actor=self.responsable,
        )
        client = self.client
        client.force_login(self.responsable)
        activate_company(client, self.empresa)
        response = client.get(reverse("tareas:detalle_tarea", args=[tarea.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visible en detalle")
        self.assertContains(response, "data-key=\"tareas.minitareas.title\"")
        self.assertContains(response, "data-key=\"tareas.minitareas.assignee\"")
        self.assertContains(response, 'data-key="tareas.minitareas.pending">Pendiente')
        self.assertNotContains(response, 'data-key="tareas.minitareas.pending">Sí')

        set_mini_task_done(MiniTarea.objects.get(pk=MiniTarea.objects.get(tarea=tarea).pk))
        response = client.get(reverse("tareas:detalle_tarea", args=[tarea.pk]))
        self.assertContains(response, 'data-key="tareas.minitareas.done">Hecha')
        self.assertNotContains(response, 'data-key="tareas.minitareas.done">Sí')

    def test_history_renders_historical_event_without_comment_relation(self):
        tarea = self.make_task()
        mini_tarea = create_mini_task(
            tarea=tarea,
            descripcion="Evento histórico",
            persona=self.asignado,
            actor=self.responsable,
        )
        MiniTareaEvento.objects.create(
            mini_tarea=mini_tarea,
            tipo=MiniTareaEvento.Tipo.CIERRE,
            actor=self.asignado,
            comentario="Cierre anterior a la relación",
        )
        client = self.client
        client.force_login(self.responsable)
        activate_company(client, self.empresa)
        response = client.get(
            reverse("tareas:historial_minitarea", args=[tarea.pk, mini_tarea.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cierre anterior a la relación")
        self.assertNotContains(response, "Adjuntos:")
