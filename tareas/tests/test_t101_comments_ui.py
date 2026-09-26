from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from pathlib import Path

from tareas.models import Tarea
from tareas.services.assignment import add_participant
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user


class T101CommentsUiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="T101", descripcion="Empresa T101")
        cls.participante = create_user(username="t101-participante")
        cls.no_vinculado = create_user(username="t101-no-vinculado")
        cls.solo_lectura = create_user(username="t101-lector")
        cls.admin = create_user(username="t101-admin")
        cls.sin_ingresar = create_user(username="t101-sin-ingresar")
        assign_permission(cls.participante, cls.empresa, "Tareas", ingresar=True, modificar=True)
        assign_permission(cls.solo_lectura, cls.empresa, "Tareas", ingresar=True)
        assign_permission(cls.no_vinculado, cls.empresa, "Tareas", ingresar=True)
        assign_permission(
            cls.admin,
            cls.empresa,
            "Tareas",
            ingresar=True,
            modificar=True,
            supervisor=True,
        )

    def login_as(self, usuario):
        self.client.force_login(usuario)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    def make_task(self, estado=Tarea.Estado.ACTIVA, anulada=False):
        tarea = create_tarea(
            self.empresa,
            self.participante,
            responsable=self.participante,
        )
        add_participant(tarea, self.participante, actor=self.participante)
        tarea.estado = estado
        tarea.anulada = anulada
        tarea.fecha_publicacion = timezone.now() if estado != Tarea.Estado.BORRADOR else None
        tarea.save(update_fields=["estado", "anulada", "fecha_publicacion"])
        return tarea

    def get_detail(self, tarea, usuario=None):
        self.login_as(usuario or self.participante)
        return self.client.get(reverse("tareas:detalle_tarea", args=[tarea.pk]))

    def test_active_participant_gets_card_composer_urls_asset_and_csrf(self):
        tarea = self.make_task()

        response = self.get_detail(tarea)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="tarea-comentarios"')
        self.assertContains(response, 'data-can-comment="true"')
        self.assertContains(response, 'data-feed-url="/tareas/%s/comentarios/"' % tarea.pk)
        self.assertContains(response, 'data-read-url="/tareas/%s/comentarios/leer/"' % tarea.pk)
        self.assertContains(response, 'data-create-url="/tareas/%s/comentarios/crear/"' % tarea.pk)
        self.assertContains(response, 'data-edit-url-template="/tareas/%s/comentarios/0/editar/"' % tarea.pk)
        self.assertContains(response, 'tareas/js/task_comments.js')
        self.assertContains(response, 'tareas/css/tarea_detalle.css')
        self.assertContains(response, 'tareas/css/task_comments.css')
        self.assertContains(response, 'class="row g-4 align-items-start"')
        self.assertContains(response, 'class="col-12 task-detail-main"')
        self.assertContains(response, 'class="col-12 task-detail-comments"')
        self.assertNotContains(response, 'card shadow-sm rounded mt-4 task-comments')
        self.assertNotContains(response, 'offset-lg-2')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_unlinked_reader_gets_comment_card_without_composer(self):
        tarea = self.make_task()

        response = self.get_detail(tarea, self.no_vinculado)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="tarea-comentarios"')
        self.assertContains(response, 'data-can-comment="false"')
        self.assertNotContains(response, 'data-comments-composer')
        self.assertContains(response, 'task_comments.js')

    def test_read_only_participant_gets_card_without_composer(self):
        tarea = self.make_task()
        add_participant(tarea, self.solo_lectura, actor=self.participante)

        response = self.get_detail(tarea, self.solo_lectura)

        self.assertContains(response, 'id="tarea-comentarios"')
        self.assertContains(response, 'data-can-comment="false"')
        self.assertNotContains(response, 'data-comments-composer')
        self.assertContains(response, 'data-comments-csrf')

    def test_creator_responsible_with_permissions_gets_mutable_card_without_row(self):
        tarea = create_tarea(
            self.empresa,
            self.admin,
            responsable=self.admin,
            estado=Tarea.Estado.ACTIVA,
            fecha_publicacion=timezone.now(),
        )

        response = self.get_detail(tarea, self.admin)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="tarea-comentarios"')
        self.assertContains(response, 'data-can-comment="true"')
        self.assertContains(response, 'data-can-supervise="true"')
        self.assertContains(response, 'data-comments-composer')
        self.assertFalse(tarea.participantes.filter(usuario=self.admin).exists())

    def test_user_without_ingresar_cannot_access_comment_card(self):
        tarea = self.make_task()

        response = self.get_detail(tarea, self.sin_ingresar)

        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, 'id="tarea-comentarios"', status_code=403)

    def test_draft_closed_and_annulled_are_read_only(self):
        scenarios = (
            (Tarea.Estado.BORRADOR, False),
            (Tarea.Estado.CERRADA, False),
            (Tarea.Estado.ACTIVA, True),
        )
        for estado, anulada in scenarios:
            with self.subTest(estado=estado, anulada=anulada):
                tarea = self.make_task(estado=estado, anulada=anulada)
                response = self.get_detail(tarea)
                self.assertContains(response, 'id="tarea-comentarios"')
                self.assertContains(response, 'data-can-comment="false"')
                self.assertNotContains(response, 'data-comments-composer')
                self.assertContains(response, 'data-comments-csrf')

    def test_operational_states_render_composer_for_modifier(self):
        for estado in (
            Tarea.Estado.ACTIVA,
            Tarea.Estado.GESTION,
            Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
        ):
            with self.subTest(estado=estado):
                tarea = self.make_task(estado=estado)
                response = self.get_detail(tarea)
                self.assertContains(response, 'data-comments-composer')
                self.assertContains(response, 'data-can-comment="true"')

    def test_badge_and_dom_behaviors_are_exposed_by_app_local_script(self):
        script = open("tareas/static/tareas/js/task_comments.js", encoding="utf-8").read()

        self.assertIn('return count >= 10 ? "9+" : String(count);', script)
        self.assertIn("feed.scrollTop", script)
        self.assertIn("feed.prepend", script)
        self.assertIn("data-comments-csrf", script)
        self.assertNotIn("form.innerHTML", script)

    def test_conversational_renderer_preserves_scoped_visual_contract(self):
        script = Path("tareas/static/tareas/js/task_comments.js").read_text(encoding="utf-8")
        stylesheet = Path("tareas/static/tareas/css/task_comments.css").read_text(encoding="utf-8")
        detail_stylesheet = Path("tareas/static/tareas/css/tarea_detalle.css").read_text(encoding="utf-8")

        self.assertIn("task-comments__message--own", script)
        self.assertIn("task-comments__message--other", script)
        self.assertIn("currentUserId", script)
        self.assertIn("comment.autor && comment.autor.id", script)
        self.assertIn("String(comment.autor && comment.autor.id) === root.dataset.currentUserId", script)
        self.assertIn("task-comments__message--tombstone", script)
        self.assertIn("task-comments__avatar", script)
        self.assertIn("avatar_url", script)
        self.assertIn("avatarImage.addEventListener(\"error\"", script)
        self.assertIn("task-comments__avatar img", stylesheet)
        self.assertIn("overflow-y: auto", stylesheet)
        self.assertIn("max-height: calc(100vh - 21rem)", stylesheet)
        self.assertIn("task-comments > .card-body", stylesheet)
        self.assertIn("feed.scrollTop = beforeTop + feed.scrollHeight - beforeHeight", script)
        self.assertNotIn("window.scrollTo", script)
        self.assertNotIn("window.scrollBy", script)
        self.assertIn("task-comments__date-separator", script)
        self.assertIn("data-bs-toggle", script)
        self.assertIn("ri-more-2-fill", script)
        self.assertIn("task-comments__author", script)
        self.assertIn("task-comments__date", script)
        self.assertIn("task-comments__history", script)
        self.assertIn('version.evento === "EDITADO"', script)
        self.assertIn('tareas.comments.history', script)
        self.assertIn('version.evento === "EDITADO"', script)
        self.assertNotIn('textContent = "History"', script)
        self.assertIn("task-detail__card", detail_stylesheet)
        self.assertIn("task-detail__dates", detail_stylesheet)
        self.assertIn("task-detail__config", detail_stylesheet)
        self.assertIn("task-detail__actions", detail_stylesheet)
        self.assertIn("flex: 0 0 75%", detail_stylesheet)
        self.assertIn("flex: 0 0 25%", detail_stylesheet)
        self.assertIn("task-comments__actions", script)
        self.assertIn("task-comments__message--own", stylesheet)
        self.assertIn("task-comments__message--other", stylesheet)
        self.assertIn("task-comments__composer", stylesheet)
        self.assertIn("--task-chat-own-bg", stylesheet)
        self.assertIn("--task-chat-other-bg", stylesheet)
        self.assertIn('[data-bs-theme="dark"] .task-comments', stylesheet)
        self.assertIn("max-width: 82%", stylesheet)
        self.assertIn("max-width: 92%", stylesheet)
        self.assertNotIn("position: fixed", stylesheet)

    def test_create_appends_canonical_comment_without_replacing_feed(self):
        script = Path("tareas/static/tareas/js/task_comments.js").read_text(encoding="utf-8")
        create_start = script.index("postForm(root.dataset.createUrl, form)")
        create_end = script.index("}).catch", create_start)
        create_handler = script[create_start:create_end]

        self.assertIn("appendComment(root, result.data.comentario)", create_handler)
        self.assertNotIn("return loadComments(root, root.dataset.feedUrl);", create_handler)
        self.assertIn("feed.appendChild(renderComment(root, comment));", script)
        self.assertIn("nombre_archivo", script)
        self.assertIn("attachment.nombre_archivo || attachment.tipo", script)

    def test_incremental_polling_contract_is_visibility_aware_and_idempotent(self):
        script = Path("tareas/static/tareas/js/task_comments.js").read_text(encoding="utf-8")

        self.assertIn("10000", script)
        self.assertIn("setTimeout", script)
        self.assertIn("visibilitychange", script)
        self.assertIn("document.hidden", script)
        self.assertIn("after_id=", script)
        self.assertIn("_commentsPollingInFlight", script)
        self.assertIn("appendPolledComments", script)
        self.assertIn("if (feed.querySelector('[data-comment-id=\"' + comment.id + '\"]')) return false;", script)

    def test_dynamic_action_contract_matches_rendered_markup(self):
        tarea = self.make_task()
        response = self.get_detail(tarea)
        html = response.content.decode()
        script = Path("tareas/static/tareas/js/task_comments.js").read_text(encoding="utf-8")

        self.assertIn('data-comments-edit-form', html)
        self.assertIn('data-comments-reason-form', html)
        self.assertIn('data-comments-edit-files', html)
        self.assertIn('return template.replace("/0/", "/" + id + "/");', script)
        self.assertIn('event.target.closest("[data-comment-action]")', script)
        self.assertIn('edit.dataset.commentAction = "edit";', script)
        self.assertIn('visibility.dataset.commentAction = comment.oculto ? "restore" : "hide";', script)
        self.assertIn('if (comment.editado)', script)
        self.assertIn('if (comment.oculto)', script)
        self.assertIn('tareas.comments.hidden_state', script)
        self.assertIn("syncComment(root, result.data.comentario);", script)
        self.assertIn('document.querySelector("[data-comments-edit-form]")', script)
        self.assertIn('document.querySelector("[data-comments-reason-form]")', script)
        self.assertNotIn('root.parentElement.querySelector("[data-comments-', script)
