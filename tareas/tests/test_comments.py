from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from tareas.models import (
    Comentario,
    ComentarioAdjunto,
    ComentarioVersion,
    ComentarioVersionDocumento,
    DocumentoTarea,
    Tarea,
)
from tareas.services.assignment import add_participant
from tareas.services.comments import (
    create_comment,
    edit_comment,
    hide_comment,
    restore_comment,
)
from tareas.services.documents import create_document
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user


class CommentServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="C098", descripcion="Empresa Comentarios")
        cls.otra_empresa = create_empresa(codigo="C099", descripcion="Otra Empresa")
        cls.autor = create_user(username="comment-author")
        cls.editor = create_user(username="comment-editor")
        cls.supervisor = create_user(username="comment-supervisor")
        cls.no_vinculado = create_user(username="comment-unlinked")
        cls.inactivo = create_user(username="comment-inactive")
        cls.inactivo.is_active = False
        cls.inactivo.save(update_fields=["is_active"])
        cls.foreign = create_user(username="comment-foreign")
        for user in (cls.autor, cls.editor, cls.supervisor, cls.no_vinculado, cls.inactivo):
            assign_permission(user, cls.empresa, "Tareas", modificar=True)
        assign_permission(cls.supervisor, cls.empresa, "Tareas", supervisor=True)
        assign_permission(cls.foreign, cls.otra_empresa, "Tareas", modificar=True)

    def make_task(self, *, usuario=None, estado=Tarea.Estado.ACTIVA):
        tarea = create_tarea(self.empresa, self.autor, responsable=self.autor)
        add_participant(tarea, usuario or self.autor, actor=self.autor)
        tarea.estado = estado
        tarea.fecha_publicacion = timezone.now()
        tarea.save(update_fields=["estado", "fecha_publicacion"])
        return tarea

    def make_document(self, tarea, usuario=None, suffix="one"):
        return create_document(
            tarea=tarea,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            usuario=usuario or self.autor,
            url=f"https://example.com/{suffix}.pdf",
        )

    def test_create_text_only(self):
        tarea = self.make_task()

        comentario = create_comment(
            tarea=tarea,
            usuario=self.autor,
            contenido="Texto del comentario",
        )

        self.assertEqual(comentario.contenido, "Texto del comentario")
        self.assertEqual(comentario.versiones.get().numero_version, 1)
        self.assertFalse(ComentarioAdjunto.objects.filter(comentario=comentario).exists())

    def test_create_with_existing_documents_and_only_documents(self):
        tarea = self.make_task()
        documento = self.make_document(tarea)

        comentario = create_comment(
            tarea=tarea,
            usuario=self.autor,
            documentos=[documento],
        )

        self.assertEqual(comentario.contenido, "")
        self.assertEqual(list(comentario.adjuntos.values_list("documento_id", flat=True)), [documento.pk])
        self.assertEqual(
            list(comentario.versiones.get().documentos.values_list("documento_id", flat=True)),
            [documento.pk],
        )

    def test_create_rejects_empty_and_more_than_five_documents(self):
        tarea = self.make_task()
        documentos = [self.make_document(tarea, suffix=f"doc-{index}") for index in range(6)]

        with self.assertRaises(ValidationError):
            create_comment(tarea=tarea, usuario=self.autor)
        with self.assertRaises(ValidationError):
            create_comment(tarea=tarea, usuario=self.autor, documentos=documentos)

        self.assertFalse(Comentario.objects.filter(tarea=tarea).exists())

    def test_create_rolls_back_database_when_new_document_fails(self):
        tarea = self.make_task()

        with self.assertRaises(ValidationError):
            create_comment(
                tarea=tarea,
                usuario=self.autor,
                contenido="Comentario válido",
                documentos_nuevos=[
                    {
                        "tipo": DocumentoTarea.Tipo.INFORME,
                        "formato_archivo": DocumentoTarea.FormatoArchivo.PDF,
                        "url": "https://example.com/ok.pdf",
                    },
                    {
                        "tipo": DocumentoTarea.Tipo.INFORME,
                        "formato_archivo": DocumentoTarea.FormatoArchivo.DOC,
                        "url": "https://example.com/falla.pdf",
                    },
                ],
            )

        self.assertFalse(Comentario.objects.filter(tarea=tarea).exists())
        self.assertFalse(DocumentoTarea.objects.filter(tarea=tarea).exists())

    def test_create_requires_permission_and_formal_participant(self):
        tarea = self.make_task()

        with self.assertRaises(ValidationError):
            create_comment(tarea=tarea, usuario=self.no_vinculado, contenido="Sin vínculo")

        add_participant(tarea, self.editor, actor=self.autor)
        comentario = create_comment(tarea=tarea, usuario=self.editor, contenido="Permitido")
        self.assertEqual(comentario.autor, self.editor)

    def test_responsible_without_explicit_participant_can_create_comment(self):
        tarea = create_tarea(self.empresa, self.autor, responsable=self.editor)
        tarea.estado = Tarea.Estado.ACTIVA
        tarea.fecha_publicacion = timezone.now()
        tarea.save(update_fields=["estado", "fecha_publicacion"])

        comentario = create_comment(
            tarea=tarea,
            usuario=self.editor,
            contenido="Comentario del responsable",
        )

        self.assertEqual(comentario.autor_id, self.editor.pk)
        self.assertFalse(tarea.participantes.filter(usuario=self.editor).exists())

    def test_create_rejects_inactive_foreign_and_non_operational_users(self):
        tarea = self.make_task()
        with self.assertRaises(ValidationError):
            create_comment(tarea=tarea, usuario=self.inactivo, contenido="Inactivo")

        tarea_cerrada = self.make_task(estado=Tarea.Estado.CERRADA)
        with self.assertRaises(ValidationError):
            create_comment(tarea=tarea_cerrada, usuario=self.autor, contenido="Cerrada")

        tarea_foreign = create_tarea(
            self.otra_empresa,
            self.foreign,
            responsable=self.foreign,
            estado=Tarea.Estado.ACTIVA,
            fecha_publicacion=timezone.now(),
        )
        tarea_foreign.estado = Tarea.Estado.ACTIVA
        tarea_foreign.fecha_publicacion = timezone.now()
        tarea_foreign.save(update_fields=["estado", "fecha_publicacion"])
        add_participant(tarea_foreign, self.foreign, actor=self.foreign)
        with self.assertRaises(ValidationError):
            create_comment(tarea=tarea_foreign, usuario=self.autor, contenido="Cross-company")

    def test_edit_requires_author_and_original_one_hour(self):
        tarea = self.make_task()
        comentario = create_comment(tarea=tarea, usuario=self.autor, contenido="Original")
        add_participant(tarea, self.editor, actor=self.autor)

        with self.assertRaises(ValidationError):
            edit_comment(comentario=comentario, usuario=self.editor, contenido="No autorizado")

        comentario.created_at = timezone.now() - timedelta(hours=1, minutes=1)
        comentario.save(update_fields=["created_at"])
        with self.assertRaises(ValidationError):
            edit_comment(comentario=comentario, usuario=self.autor, contenido="Tarde")

    def test_edit_preserves_versions_and_document_references(self):
        tarea = self.make_task()
        first = self.make_document(tarea, suffix="first")
        second = self.make_document(tarea, suffix="second")
        comentario = create_comment(
            tarea=tarea,
            usuario=self.autor,
            contenido="Original",
            documentos=[first],
        )

        edit_comment(
            comentario=comentario,
            usuario=self.autor,
            contenido="Editado",
            documentos=[second],
        )

        comentario.refresh_from_db()
        self.assertEqual(comentario.contenido, "Editado")
        self.assertEqual(comentario.adjuntos.get().documento_id, second.pk)
        self.assertEqual(ComentarioVersion.objects.filter(comentario=comentario).count(), 2)
        self.assertEqual(
            set(
                ComentarioVersionDocumento.objects.filter(
                    version__comentario=comentario,
                    version__numero_version=1,
                ).values_list("documento_id", flat=True)
            ),
            {first.pk},
        )
        self.assertTrue(DocumentoTarea.objects.filter(pk=first.pk).exists())

    def test_hidden_comment_cannot_be_edited(self):
        tarea = self.make_task()
        add_participant(tarea, self.supervisor, actor=self.autor)
        comentario = create_comment(tarea=tarea, usuario=self.autor, contenido="Original")
        hide_comment(comentario=comentario, usuario=self.supervisor, motivo="Moderación")

        with self.assertRaises(ValidationError):
            edit_comment(comentario=comentario, usuario=self.autor, contenido="No")

    def test_hide_and_restore_require_supervisor_reason_and_preserve_content(self):
        tarea = self.make_task()
        add_participant(tarea, self.supervisor, actor=self.autor)
        comentario = create_comment(tarea=tarea, usuario=self.autor, contenido="Visible")

        with self.assertRaises(ValidationError):
            hide_comment(comentario=comentario, usuario=self.autor, motivo="")
        with self.assertRaises(ValidationError):
            hide_comment(comentario=comentario, usuario=self.autor, motivo="Motivo")

        hide_comment(comentario=comentario, usuario=self.supervisor, motivo=" Motivo válido ")
        comentario.refresh_from_db()
        self.assertTrue(comentario.oculto)
        self.assertEqual(comentario.versiones.order_by("pk").last().motivo, "Motivo válido")

        restore_comment(comentario=comentario, usuario=self.supervisor, motivo="Restauración")
        comentario.refresh_from_db()
        self.assertFalse(comentario.oculto)
        self.assertEqual(comentario.contenido, "Visible")
        self.assertEqual(
            list(comentario.versiones.values_list("evento", flat=True)),
            ["CREADO", "OCULTADO", "RESTAURADO"],
        )
