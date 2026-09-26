from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, SimpleTestCase, TestCase
from django.test import override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from tareas.models import DocumentoTarea, Hito, Tarea, TareaLectura, TareaParticipante
from tareas.services.assignment import add_participant
from tareas.services.comments import create_comment, edit_comment, hide_comment
from tareas.services.documents import create_document
from tareas.tests.factories import (
    assign_permission,
    create_empresa,
    create_tarea,
    create_user,
)


class CommentWebUrlTests(SimpleTestCase):
    def test_comment_list_route_is_registered_under_tareas(self):
        url = reverse("tareas:listar_comentarios", kwargs={"tarea_id": 123})

        self.assertEqual(url, "/tareas/123/comentarios/")
        self.assertEqual(resolve(url).url_name, "listar_comentarios")

        rutas = [
            ("marcar_comentarios_leidos", {"tarea_id": 123}, "/tareas/123/comentarios/leer/"),
            ("crear_comentario", {"tarea_id": 123}, "/tareas/123/comentarios/crear/"),
            (
                "editar_comentario",
                {"tarea_id": 123, "comentario_id": 456},
                "/tareas/123/comentarios/456/editar/",
            ),
            (
                "ocultar_comentario",
                {"tarea_id": 123, "comentario_id": 456},
                "/tareas/123/comentarios/456/ocultar/",
            ),
            (
                "restaurar_comentario",
                {"tarea_id": 123, "comentario_id": 456},
                "/tareas/123/comentarios/456/restaurar/",
            ),
            (
                "vincular_participante",
                {"tarea_id": 123, "usuario_id": 789},
                "/tareas/123/participantes/789/vincular/",
            ),
            (
                "desvincular_participante",
                {"tarea_id": 123, "usuario_id": 789},
                "/tareas/123/participantes/789/desvincular/",
            ),
        ]
        for name, kwargs, expected_url in rutas:
            with self.subTest(name=name):
                url = reverse(f"tareas:{name}", kwargs=kwargs)
                self.assertEqual(url, expected_url)
                self.assertEqual(resolve(url).url_name, name)


class CommentReadViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="C100R", descripcion="Empresa Lectura Web")
        cls.lector = create_user(username="reading-web-user")
        cls.autor = create_user(username="reading-web-author")
        cls.supervisor = create_user(username="reading-web-supervisor")
        cls.sin_vinculo = create_user(username="reading-web-unlinked")
        cls.sin_permiso = create_user(username="reading-web-no-permission")
        cls.nuevo_participante = create_user(username="reading-web-new-participant")
        cls.hito_responsable = create_user(username="reading-web-hito-responsible")
        for user in (cls.lector, cls.autor):
            assign_permission(user, cls.empresa, "Tareas", ingresar=True, modificar=True)
        assign_permission(cls.supervisor, cls.empresa, "Tareas", ingresar=True, supervisor=True)
        assign_permission(cls.sin_vinculo, cls.empresa, "Tareas", ingresar=True)
        assign_permission(cls.nuevo_participante, cls.empresa, "Tareas", ingresar=True)
        assign_permission(
            cls.hito_responsable,
            cls.empresa,
            "Tareas",
            ingresar=True,
            modificar=True,
        )
        cls.admin_participantes = create_user(username="reading-web-participants-admin")
        assign_permission(
            cls.admin_participantes, cls.empresa, "Tareas", ingresar=True, modificar=True
        )
        cls.otra_empresa = create_empresa(codigo="C100Y", descripcion="Empresa externa")
        cls.usuario_ajeno = create_user(username="reading-web-foreign-user")
        assign_permission(cls.usuario_ajeno, cls.otra_empresa, "Tareas", ingresar=True)

    def setUp(self):
        self.tarea = self.make_active_task()
        add_participant(self.tarea, self.autor, actor=self.autor)
        add_participant(self.tarea, self.lector, actor=self.autor)
        self.login_as(self.lector)

    def make_active_task(self):
        tarea = create_tarea(self.empresa, self.autor, responsable=self.autor)
        tarea.estado = Tarea.Estado.ACTIVA
        tarea.fecha_publicacion = timezone.now()
        tarea.save(update_fields=["estado", "fecha_publicacion"])
        return tarea

    def link_url(self, tarea, usuario):
        return reverse(
            "tareas:vincular_participante",
            kwargs={"tarea_id": tarea.pk, "usuario_id": usuario.pk},
        )

    def unlink_url(self, tarea, usuario):
        return reverse(
            "tareas:desvincular_participante",
            kwargs={"tarea_id": tarea.pk, "usuario_id": usuario.pk},
        )

    def login_as(self, usuario):
        self.client.force_login(usuario)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    def test_get_uses_next_chronological_page_and_pending_cursor(self):
        comentarios = [
            create_comment(tarea=self.tarea, usuario=self.autor, contenido=f"Comentario {index}")
            for index in range(22)
        ]

        response = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk})
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["page_size"], 20)
        self.assertEqual(
            [item["id"] for item in payload["comentarios"]],
            [comentario.pk for comentario in comentarios[:20]],
        )
        self.assertEqual(payload["pendientes"], 22)
        self.assertEqual(payload["primer_pendiente_id"], comentarios[0].pk)
        lectura = TareaLectura.objects.get(tarea=self.tarea, usuario=self.lector)
        self.assertIsNone(lectura.comentario_leido_hasta_id)

    def test_incremental_get_returns_only_new_comments_without_moving_cursor(self):
        first = create_comment(tarea=self.tarea, usuario=self.autor, contenido="Inicial")
        lectura = TareaLectura.objects.get(tarea=self.tarea, usuario=self.lector)
        self.assertIsNone(lectura.comentario_leido_hasta_id)

        no_new = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk}),
            {"after_id": first.pk},
        )

        self.assertEqual(no_new.status_code, 200)
        self.assertEqual(no_new.json()["comentarios"], [])
        lectura.refresh_from_db()
        self.assertIsNone(lectura.comentario_leido_hasta_id)

        second = create_comment(tarea=self.tarea, usuario=self.autor, contenido="Segundo")
        third = create_comment(tarea=self.tarea, usuario=self.autor, contenido="Tercero")
        incremental = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk}),
            {"after_id": first.pk},
        )

        self.assertEqual(incremental.status_code, 200)
        payload = incremental.json()
        self.assertEqual([item["id"] for item in payload["comentarios"]], [second.pk, third.pk])
        self.assertEqual(payload["pendientes"], 0)
        lectura.refresh_from_db()
        self.assertIsNone(lectura.comentario_leido_hasta_id)

    def test_incremental_get_for_unlinked_reader_has_no_reading_side_effect(self):
        comentario = create_comment(tarea=self.tarea, usuario=self.autor, contenido="Visible")
        self.login_as(self.sin_vinculo)
        self.assertFalse(TareaLectura.objects.filter(tarea=self.tarea, usuario=self.sin_vinculo).exists())

        response = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk}),
            {"after_id": comentario.pk - 1},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["comentarios"]], [comentario.pk])
        self.assertFalse(TareaLectura.objects.filter(tarea=self.tarea, usuario=self.sin_vinculo).exists())

    def test_comment_payload_includes_existing_avatar_for_normal_incremental_and_create(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.autor.avatar.imagen = SimpleUploadedFile(
                "autor.png",
                b"image-data",
                content_type="image/png",
            )
            self.autor.avatar.save(update_fields=["imagen"])
            comentario = create_comment(
                tarea=self.tarea,
                usuario=self.autor,
                contenido="Con avatar",
            )

            normal = self.client.get(
                reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk})
            ).json()["comentarios"][-1]
            self.assertTrue(normal["autor"]["avatar_url"].endswith("autor.png"))

            incremental = self.client.get(
                reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk}),
                {"after_id": comentario.pk - 1},
            ).json()["comentarios"][-1]
            self.assertEqual(incremental["autor"]["avatar_url"], normal["autor"]["avatar_url"])

            self.login_as(self.autor)
            created = self.client.post(
                reverse("tareas:crear_comentario", kwargs={"tarea_id": self.tarea.pk}),
                {"contenido": "Nuevo con avatar"},
            ).json()["comentario"]
            self.assertEqual(created["autor"]["avatar_url"], normal["autor"]["avatar_url"])

    def test_comment_payload_without_existing_avatar_uses_empty_url(self):
        self.autor.avatar.imagen = ""
        self.autor.avatar.save(update_fields=["imagen"])
        comentario = create_comment(tarea=self.tarea, usuario=self.autor, contenido="Sin foto")

        item = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk}),
            {"after_id": comentario.pk - 1},
        ).json()["comentarios"][-1]

        self.assertEqual(item["autor"]["avatar_url"], "")

    def test_comment_avatar_matches_topbar_contract_for_default_image(self):
        comentario = create_comment(tarea=self.tarea, usuario=self.autor, contenido="Avatar default")
        topbar_url = self.autor.avatar.imagen.url

        item = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk}),
            {"after_id": comentario.pk - 1},
        ).json()["comentarios"][-1]

        self.assertEqual(topbar_url, "/media/avatares/default.jpg")
        self.assertEqual(item["autor"]["avatar_url"], topbar_url)

    def test_comment_attachment_payload_exposes_safe_real_filename(self):
        documento = create_document(
            tarea=self.tarea,
            usuario=self.autor,
            tipo=DocumentoTarea.Tipo.OTRO,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            url="https://example.com/cotizacion_jc_morales.pdf",
        )
        comentario = create_comment(
            tarea=self.tarea,
            usuario=self.autor,
            contenido="Adjunto",
            documentos=[documento],
        )

        item = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk}),
            {"after_id": comentario.pk - 1},
        ).json()["comentarios"][-1]

        attachment = item["adjuntos"][0]
        self.assertEqual(attachment["nombre_archivo"], "cotizacion_jc_morales.pdf")
        self.assertEqual(attachment["tipo"], DocumentoTarea.Tipo.OTRO)
        self.assertEqual(attachment["url"], "https://example.com/cotizacion_jc_morales.pdf")

    def test_create_post_delegates_comment_creation_and_returns_controlled_payload(self):
        response = self.client.post(
            reverse("tareas:crear_comentario", kwargs={"tarea_id": self.tarea.pk}),
            {"contenido": "Comentario desde formulario"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["comentario"]["contenido"], "Comentario desde formulario")
        self.assertEqual(self.tarea.comentarios.count(), 1)

    def test_create_post_keeps_existing_feed_contract(self):
        existing = [
            create_comment(tarea=self.tarea, usuario=self.autor, contenido=f"Previo {index}")
            for index in range(2)
        ]

        response = self.client.post(
            reverse("tareas:crear_comentario", kwargs={"tarea_id": self.tarea.pk}),
            {"contenido": "Comentario nuevo"},
        )

        self.assertEqual(response.status_code, 200)
        created_id = response.json()["comentario"]["id"]
        feed = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk})
        ).json()["comentarios"]
        self.assertEqual([item["id"] for item in feed], [item.pk for item in existing] + [created_id])

    def test_hito_responsible_gets_composer_and_can_create_comment(self):
        tarea = self.make_active_task()
        Hito.objects.create(
            tarea=tarea,
            nombre="Hito activo",
            responsable=self.hito_responsable,
            peso=1,
        )
        self.login_as(self.hito_responsable)

        detail = self.client.get(reverse("tareas:detalle_tarea", args=[tarea.pk]))
        self.assertContains(detail, "data-comments-composer")

        response = self.client.post(
            reverse("tareas:crear_comentario", kwargs={"tarea_id": tarea.pk}),
            {"contenido": "Comentario del responsable de Hito"},
        )
        self.assertEqual(response.status_code, 200)

    def test_anulled_hito_does_not_grant_comment_participation(self):
        tarea = self.make_active_task()
        Hito.objects.create(
            tarea=tarea,
            nombre="Hito anulado",
            responsable=self.hito_responsable,
            peso=1,
            anulado=True,
        )
        self.login_as(self.hito_responsable)

        detail = self.client.get(reverse("tareas:detalle_tarea", args=[tarea.pk]))
        self.assertNotContains(detail, "data-comments-composer")
        response = self.client.post(
            reverse("tareas:crear_comentario", kwargs={"tarea_id": tarea.pk}),
            {"contenido": "No permitido"},
        )
        self.assertEqual(response.status_code, 403)

    @patch("tareas.views.create_comment", side_effect=RuntimeError("internal details"))
    def test_unexpected_service_error_returns_only_generic_response(self, _create_comment):
        response = self.client.post(
            reverse("tareas:crear_comentario", kwargs={"tarea_id": self.tarea.pk}),
            {"contenido": "Comentario"},
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {"success": False, "message_key": "tareas.messages.generic_error"},
        )
        self.assertNotIn("internal details", response.content.decode())

    def test_create_post_can_attach_an_existing_task_document_without_text(self):
        documento = create_document(
            tarea=self.tarea,
            usuario=self.lector,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            url="https://example.com/adjunto.pdf",
        )

        response = self.client.post(
            reverse("tareas:crear_comentario", kwargs={"tarea_id": self.tarea.pk}),
            {"documentos": [documento.pk]},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["comentario"]["contenido"], "")
        self.assertEqual(payload["comentario"]["adjuntos"][0]["id"], documento.pk)

    def test_create_post_stores_new_file_through_t098_document_flow(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            archivo = SimpleUploadedFile(
                "captura.jpg",
                b"image-data",
                content_type="image/jpeg",
            )
            response = self.client.post(
                reverse("tareas:crear_comentario", kwargs={"tarea_id": self.tarea.pk}),
                {
                    "contenido": "",
                    "tipo_documento": DocumentoTarea.Tipo.FOTOGRAFIA,
                    "archivos": archivo,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        documento_id = payload["comentario"]["adjuntos"][0]["id"]
        documento = DocumentoTarea.objects.get(pk=documento_id)
        self.assertEqual(documento.formato_archivo, DocumentoTarea.FormatoArchivo.JPG)
        self.assertEqual(documento.archivo.name.rsplit("/", 1)[-1], "captura.jpg")

    def test_edit_post_is_limited_to_the_author(self):
        comentario = create_comment(
            tarea=self.tarea,
            usuario=self.autor,
            contenido="Antes",
        )
        self.login_as(self.autor)

        response = self.client.post(
            reverse(
                "tareas:editar_comentario",
                kwargs={"tarea_id": self.tarea.pk, "comentario_id": comentario.pk},
            ),
            {"contenido": "Después"},
        )

        self.assertEqual(response.status_code, 200)
        comentario.refresh_from_db()
        self.assertEqual(comentario.contenido, "Después")
        self.assertEqual(comentario.versiones.count(), 2)

    def test_edit_post_and_feed_return_current_history(self):
        comentario = create_comment(
            tarea=self.tarea,
            usuario=self.autor,
            contenido="Versión inicial",
        )
        self.login_as(self.autor)

        edit_response = self.client.post(
            reverse(
                "tareas:editar_comentario",
                kwargs={"tarea_id": self.tarea.pk, "comentario_id": comentario.pk},
            ),
            {"contenido": "Versión editada"},
        )

        self.assertEqual(edit_response.status_code, 200)
        edit_item = edit_response.json()["comentario"]
        self.assertTrue(edit_item["editado"])
        self.assertEqual(
            [version["contenido"] for version in edit_item["historial"]],
            ["Versión inicial", "Versión editada"],
        )

        feed_response = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk})
        )

        self.assertEqual(feed_response.status_code, 200)
        feed_item = feed_response.json()["comentarios"][-1]
        self.assertEqual(feed_item["contenido"], "Versión editada")
        self.assertTrue(feed_item["editado"])
        self.assertEqual(
            [version["contenido"] for version in feed_item["historial"]],
            ["Versión inicial", "Versión editada"],
        )

    def test_edit_post_allows_implicit_responsible_without_participant_row(self):
        tarea = create_tarea(self.empresa, self.autor, responsable=self.autor)
        tarea.estado = Tarea.Estado.ACTIVA
        tarea.fecha_publicacion = timezone.now()
        tarea.save(update_fields=["estado", "fecha_publicacion"])
        comentario = create_comment(tarea=tarea, usuario=self.autor, contenido="Antes")
        self.login_as(self.autor)

        response = self.client.post(
            reverse(
                "tareas:editar_comentario",
                kwargs={"tarea_id": tarea.pk, "comentario_id": comentario.pk},
            ),
            {"contenido": "Después", "documentos_modificados": "1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertFalse(tarea.participantes.filter(usuario=self.autor).exists())
        comentario.refresh_from_db()
        self.assertEqual(comentario.contenido, "Después")
        self.assertEqual(comentario.versiones.count(), 2)

    def test_supervisor_routes_hide_and_restore_with_motives(self):
        comentario = create_comment(
            tarea=self.tarea,
            usuario=self.autor,
            contenido="Contenido moderado",
        )
        add_participant(self.tarea, self.supervisor, actor=self.autor)
        self.login_as(self.supervisor)

        ocultar = self.client.post(
            reverse(
                "tareas:ocultar_comentario",
                kwargs={"tarea_id": self.tarea.pk, "comentario_id": comentario.pk},
            ),
            {"motivo": "  Moderación  "},
        )
        self.assertEqual(ocultar.status_code, 200)
        self.assertTrue(ocultar.json()["comentario"]["oculto"])
        self.assertFalse(ocultar.json()["comentario"]["editado"])

        restaurar = self.client.post(
            reverse(
                "tareas:restaurar_comentario",
                kwargs={"tarea_id": self.tarea.pk, "comentario_id": comentario.pk},
            ),
            {"motivo": "Revisión completada"},
        )
        self.assertEqual(restaurar.status_code, 200)
        self.assertFalse(restaurar.json()["comentario"]["oculto"])
        self.assertFalse(restaurar.json()["comentario"]["editado"])
        comentario.refresh_from_db()
        self.assertEqual(comentario.versiones.count(), 3)
        self.assertEqual(
            comentario.versiones.get(evento="OCULTADO").motivo,
            "Moderación",
        )

    def test_edit_hide_restore_payload_preserves_independent_states(self):
        comentario = create_comment(
            tarea=self.tarea,
            usuario=self.autor,
            contenido="Contenido original",
        )
        self.login_as(self.autor)
        edit_response = self.client.post(
            reverse(
                "tareas:editar_comentario",
                kwargs={"tarea_id": self.tarea.pk, "comentario_id": comentario.pk},
            ),
            {"contenido": "Contenido editado"},
        )
        self.assertTrue(edit_response.json()["comentario"]["editado"])

        add_participant(self.tarea, self.supervisor, actor=self.autor)
        self.login_as(self.supervisor)
        hide_response = self.client.post(
            reverse(
                "tareas:ocultar_comentario",
                kwargs={"tarea_id": self.tarea.pk, "comentario_id": comentario.pk},
            ),
            {"motivo": "Moderación"},
        )
        hidden_item = hide_response.json()["comentario"]
        self.assertTrue(hidden_item["oculto"])
        self.assertTrue(hidden_item["editado"])

        restore_response = self.client.post(
            reverse(
                "tareas:restaurar_comentario",
                kwargs={"tarea_id": self.tarea.pk, "comentario_id": comentario.pk},
            ),
            {"motivo": "Revisión completada"},
        )
        restored_item = restore_response.json()["comentario"]
        self.assertFalse(restored_item["oculto"])
        self.assertTrue(restored_item["editado"])

    def test_hidden_comment_is_a_redacted_tombstone_for_other_participants(self):
        comentario = create_comment(
            tarea=self.tarea,
            usuario=self.autor,
            contenido="Contenido moderado",
        )
        add_participant(self.tarea, self.supervisor, actor=self.autor)
        hide_comment(comentario=comentario, usuario=self.supervisor, motivo="Motivo de prueba")

        response = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk})
        )

        self.assertEqual(response.status_code, 200)
        item = response.json()["comentarios"][-1]
        self.assertTrue(item["tombstone"])
        self.assertTrue(item["oculto"])
        self.assertNotIn("contenido", item)
        self.assertNotIn("autor", item)
        self.assertNotIn("adjuntos", item)
        self.assertNotIn("historial", item)

    def test_only_author_receives_version_history(self):
        comentario = create_comment(
            tarea=self.tarea,
            usuario=self.autor,
            contenido="Versión inicial",
        )
        edit_comment(comentario=comentario, usuario=self.autor, contenido="Versión editada")

        lector_response = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk})
        )
        self.assertEqual(lector_response.status_code, 200)
        lector_item = lector_response.json()["comentarios"][-1]
        self.assertFalse(lector_item["puede_ver_historial"])
        self.assertEqual(lector_item["historial"], [])
        self.assertEqual(lector_item["contenido"], "Versión editada")

        self.login_as(self.autor)
        autor_response = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk})
        )
        self.assertEqual(autor_response.status_code, 200)
        autor_item = autor_response.json()["comentarios"][-1]
        self.assertTrue(autor_item["puede_ver_historial"])
        self.assertEqual(
            [version["contenido"] for version in autor_item["historial"]],
            ["Versión inicial", "Versión editada"],
        )

    def test_opening_task_detail_does_not_advance_comment_cursor(self):
        create_comment(tarea=self.tarea, usuario=self.autor, contenido="Pendiente")
        lectura = TareaLectura.objects.get(tarea=self.tarea, usuario=self.lector)
        self.assertIsNone(lectura.comentario_leido_hasta_id)

        response = self.client.get(reverse("tareas:detalle_tarea", args=[self.tarea.pk]))

        self.assertEqual(response.status_code, 200)
        lectura.refresh_from_db()
        self.assertIsNone(lectura.comentario_leido_hasta_id)

    def test_recognition_post_advances_only_the_next_loaded_page(self):
        comentarios = [
            create_comment(tarea=self.tarea, usuario=self.autor, contenido=f"Página {index}")
            for index in range(21)
        ]

        response = self.client.post(
            reverse("tareas:marcar_comentarios_leidos", kwargs={"tarea_id": self.tarea.pk}),
            {"comentario_ids": [item.pk for item in comentarios[:20]]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pendientes"], 1)
        lectura = TareaLectura.objects.get(tarea=self.tarea, usuario=self.lector)
        self.assertEqual(lectura.comentario_leido_hasta_id, comentarios[19].pk)

        response = self.client.post(
            reverse("tareas:marcar_comentarios_leidos", kwargs={"tarea_id": self.tarea.pk}),
            {"comentario_ids": [comentarios[0].pk]},
        )
        self.assertEqual(response.status_code, 400)
        lectura.refresh_from_db()
        self.assertEqual(lectura.comentario_leido_hasta_id, comentarios[19].pk)

    def test_late_participant_starts_at_latest_comment_and_unlink_preserves_reading(self):
        comentario = create_comment(
            tarea=self.tarea,
            usuario=self.autor,
            contenido="Anterior al vínculo",
        )

        response = self.client.post(
            reverse(
                "tareas:vincular_participante",
                kwargs={"tarea_id": self.tarea.pk, "usuario_id": self.nuevo_participante.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        lectura = TareaLectura.objects.get(tarea=self.tarea, usuario=self.nuevo_participante)
        self.assertEqual(lectura.comentario_leido_hasta_id, comentario.pk)

        response = self.client.post(
            reverse(
                "tareas:desvincular_participante",
                kwargs={"tarea_id": self.tarea.pk, "usuario_id": self.nuevo_participante.pk},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            TareaParticipante.objects.filter(
                tarea=self.tarea,
                usuario=self.nuevo_participante,
            ).exists()
        )
        lectura.refresh_from_db()
        self.assertEqual(lectura.comentario_leido_hasta_id, comentario.pk)

    def test_unlinked_user_can_read_comments_but_foreign_company_task_is_not_readable(self):
        create_comment(tarea=self.tarea, usuario=self.autor, contenido="Visible para lector VICMEAS")
        self.login_as(self.sin_vinculo)
        response = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["comentarios"]), 1)
        self.assertEqual(response.json()["pendientes"], 0)
        self.assertFalse(TareaLectura.objects.filter(tarea=self.tarea, usuario=self.sin_vinculo).exists())

        otra_empresa = create_empresa(codigo="C100X", descripcion="Empresa ajena")
        tarea_ajena = create_tarea(otra_empresa, self.autor, responsable=self.autor)
        self.login_as(self.lector)
        response = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": tarea_ajena.pk})
        )
        self.assertEqual(response.status_code, 404)

    def test_missing_vicmeas_permission_returns_forbidden(self):
        self.login_as(self.sin_permiso)

        response = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk})
        )

        self.assertEqual(response.status_code, 403)

    def test_closed_or_annulled_task_allows_reading_and_personal_recognition(self):
        for campo, valor in (("estado", Tarea.Estado.CERRADA), ("anulada", True)):
            with self.subTest(campo=campo):
                tarea = self.make_active_task()
                add_participant(tarea, self.autor, actor=self.autor)
                add_participant(tarea, self.lector, actor=self.autor)
                primero = create_comment(tarea=tarea, usuario=self.autor, contenido="Uno")
                segundo = create_comment(tarea=tarea, usuario=self.autor, contenido="Dos")
                setattr(tarea, campo, valor)
                tarea.save(update_fields=[campo])
                leer_url = reverse(
                    "tareas:marcar_comentarios_leidos", kwargs={"tarea_id": tarea.pk}
                )

                get_response = self.client.get(
                    reverse("tareas:listar_comentarios", kwargs={"tarea_id": tarea.pk})
                )
                self.assertEqual(get_response.status_code, 200)

                salto = self.client.post(leer_url, {"comentario_ids": [segundo.pk]})
                self.assertEqual(salto.status_code, 400)
                valido = self.client.post(
                    leer_url, {"comentario_ids": [primero.pk, segundo.pk]}
                )
                self.assertEqual(valido.status_code, 200)
                self.assertEqual(valido.json()["pendientes"], 0)

                lectura = TareaLectura.objects.get(tarea=tarea, usuario=self.lector)
                self.assertEqual(lectura.comentario_leido_hasta_id, segundo.pk)
                primero.refresh_from_db()
                segundo.refresh_from_db()
                self.assertEqual((primero.contenido, segundo.contenido), ("Uno", "Dos"))
                self.assertEqual(primero.versiones.count() + segundo.versiones.count(), 2)

                crear = self.client.post(
                    reverse("tareas:crear_comentario", kwargs={"tarea_id": tarea.pk}),
                    {"contenido": "Congelada"},
                )
                self.assertEqual(crear.status_code, 400)
                self.assertEqual(tarea.comentarios.count(), 2)

    def test_non_participant_admin_links_first_participant_but_cannot_comment(self):
        tarea = self.make_active_task()
        self.assertFalse(tarea.participantes.exists())
        self.login_as(self.admin_participantes)

        crear_sin_vinculo = self.client.post(
            reverse("tareas:crear_comentario", kwargs={"tarea_id": tarea.pk}),
            {"contenido": "Administrador sin vínculo"},
        )
        self.assertEqual(crear_sin_vinculo.status_code, 403)

        response = self.client.post(self.link_url(tarea, self.lector))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(tarea.participantes.values_list("usuario", flat=True)),
            [self.lector.pk],
        )
        self.assertFalse(tarea.comentarios.exists())

    def test_link_requires_modificar_permission(self):
        tarea = self.make_active_task()
        self.login_as(self.sin_vinculo)

        response = self.client.post(self.link_url(tarea, self.lector))

        self.assertEqual(response.status_code, 403)
        self.assertFalse(tarea.participantes.exists())

    def test_link_rejects_user_from_another_company(self):
        self.login_as(self.admin_participantes)

        response = self.client.post(self.link_url(self.tarea, self.usuario_ajeno))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.tarea.participantes.filter(usuario=self.usuario_ajeno).exists())

    def test_closed_or_annulled_task_blocks_participant_changes(self):
        self.login_as(self.admin_participantes)
        for campo, valor in (("estado", Tarea.Estado.CERRADA), ("anulada", True)):
            with self.subTest(campo=campo):
                tarea = self.make_active_task()
                add_participant(tarea, self.lector, actor=self.autor)
                setattr(tarea, campo, valor)
                tarea.save(update_fields=[campo])

                vincular = self.client.post(self.link_url(tarea, self.nuevo_participante))
                desvincular = self.client.post(self.unlink_url(tarea, self.lector))

                self.assertEqual(vincular.status_code, 400)
                self.assertEqual(desvincular.status_code, 400)
                self.assertEqual(
                    list(tarea.participantes.values_list("usuario", flat=True)),
                    [self.lector.pk],
                )

    def test_non_participant_admin_unlinks_and_unlinked_user_loses_access(self):
        comentario = create_comment(tarea=self.tarea, usuario=self.autor, contenido="Previo")
        lectura = TareaLectura.objects.get(tarea=self.tarea, usuario=self.lector)
        self.login_as(self.admin_participantes)

        response = self.client.post(self.unlink_url(self.tarea, self.lector))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(TareaLectura.objects.filter(pk=lectura.pk).exists())
        self.login_as(self.lector)
        listar = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk})
        )
        crear = self.client.post(
            reverse("tareas:crear_comentario", kwargs={"tarea_id": self.tarea.pk}),
            {"contenido": "Sin vínculo"},
        )
        leer = self.client.post(
            reverse("tareas:marcar_comentarios_leidos", kwargs={"tarea_id": self.tarea.pk}),
            {"comentario_ids": [comentario.pk]},
        )
        self.assertEqual((listar.status_code, crear.status_code, leer.status_code), (200, 403, 403))
        self.assertEqual(self.tarea.comentarios.count(), 1)

    def test_edit_by_non_author_is_rejected(self):
        comentario = create_comment(tarea=self.tarea, usuario=self.autor, contenido="Original")

        response = self.client.post(
            reverse(
                "tareas:editar_comentario",
                kwargs={"tarea_id": self.tarea.pk, "comentario_id": comentario.pk},
            ),
            {"contenido": "Ajeno"},
        )

        self.assertEqual(response.status_code, 403)
        comentario.refresh_from_db()
        self.assertEqual(comentario.contenido, "Original")

    def test_hide_without_supervisor_permission_is_rejected(self):
        comentario = create_comment(tarea=self.tarea, usuario=self.autor, contenido="Visible")

        response = self.client.post(
            reverse(
                "tareas:ocultar_comentario",
                kwargs={"tarea_id": self.tarea.pk, "comentario_id": comentario.pk},
            ),
            {"motivo": "Sin S"},
        )

        self.assertEqual(response.status_code, 403)
        comentario.refresh_from_db()
        self.assertFalse(comentario.oculto)

    def test_hide_and_restore_reject_blank_motive(self):
        visible = create_comment(tarea=self.tarea, usuario=self.autor, contenido="Visible")
        oculto = create_comment(tarea=self.tarea, usuario=self.autor, contenido="Oculto")
        add_participant(self.tarea, self.supervisor, actor=self.autor)
        hide_comment(comentario=oculto, usuario=self.supervisor, motivo="Previo")
        self.login_as(self.supervisor)

        for name, comentario in (("ocultar_comentario", visible), ("restaurar_comentario", oculto)):
            with self.subTest(name=name):
                response = self.client.post(
                    reverse(
                        f"tareas:{name}",
                        kwargs={"tarea_id": self.tarea.pk, "comentario_id": comentario.pk},
                    ),
                    {"motivo": "   "},
                )
                self.assertEqual(response.status_code, 400)

        visible.refresh_from_db()
        oculto.refresh_from_db()
        self.assertFalse(visible.oculto)
        self.assertTrue(oculto.oculto)

    def test_supervisor_receives_history_of_another_users_comment(self):
        comentario = create_comment(tarea=self.tarea, usuario=self.autor, contenido="Inicial")
        edit_comment(comentario=comentario, usuario=self.autor, contenido="Editado")
        add_participant(self.tarea, self.supervisor, actor=self.autor)
        self.login_as(self.supervisor)

        response = self.client.get(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk})
        )

        self.assertEqual(response.status_code, 200)
        item = response.json()["comentarios"][-1]
        self.assertTrue(item["puede_ver_historial"])
        self.assertEqual(
            [version["contenido"] for version in item["historial"]],
            ["Inicial", "Editado"],
        )

    def test_create_rejects_document_from_another_task(self):
        otra_tarea = self.make_active_task()
        documento = create_document(
            tarea=otra_tarea,
            usuario=self.autor,
            tipo=DocumentoTarea.Tipo.INFORME,
            formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
            url="https://example.com/ajeno.pdf",
        )

        response = self.client.post(
            reverse("tareas:crear_comentario", kwargs={"tarea_id": self.tarea.pk}),
            {"contenido": "Con documento ajeno", "documentos": [documento.pk]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.tarea.comentarios.exists())

    def test_create_rejects_more_than_five_attachments(self):
        documentos = [
            create_document(
                tarea=self.tarea,
                usuario=self.lector,
                tipo=DocumentoTarea.Tipo.INFORME,
                formato_archivo=DocumentoTarea.FormatoArchivo.PDF,
                url=f"https://example.com/doc-{index}.pdf",
            )
            for index in range(6)
        ]

        response = self.client.post(
            reverse("tareas:crear_comentario", kwargs={"tarea_id": self.tarea.pk}),
            {"documentos": [documento.pk for documento in documentos]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.tarea.comentarios.exists())

    def test_wrong_http_methods_return_405(self):
        crear = self.client.get(
            reverse("tareas:crear_comentario", kwargs={"tarea_id": self.tarea.pk})
        )
        listar = self.client.post(
            reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk})
        )

        self.assertEqual((crear.status_code, listar.status_code), (405, 405))

    def test_post_without_csrf_token_is_rejected(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.lector)
        session = client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

        response = client.post(
            reverse("tareas:crear_comentario", kwargs={"tarea_id": self.tarea.pk}),
            {"contenido": "Sin token"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.tarea.comentarios.exists())

    def test_previous_page_uses_before_without_moving_cursor(self):
        comentarios = [
            create_comment(tarea=self.tarea, usuario=self.lector, contenido=f"Propio {index}")
            for index in range(25)
        ]
        cursor_inicial = TareaLectura.objects.get(
            tarea=self.tarea, usuario=self.lector
        ).comentario_leido_hasta_id
        url = reverse("tareas:listar_comentarios", kwargs={"tarea_id": self.tarea.pk})

        inicial = self.client.get(url).json()
        anterior = self.client.get(url, {"before": inicial["before_comment_id"]})

        self.assertEqual(
            [item["id"] for item in inicial["comentarios"]],
            [comentario.pk for comentario in comentarios[5:]],
        )
        self.assertEqual(anterior.status_code, 200)
        self.assertEqual(
            [item["id"] for item in anterior.json()["comentarios"]],
            [comentario.pk for comentario in comentarios[:5]],
        )
        self.assertEqual(
            TareaLectura.objects.get(
                tarea=self.tarea, usuario=self.lector
            ).comentario_leido_hasta_id,
            cursor_inicial,
        )