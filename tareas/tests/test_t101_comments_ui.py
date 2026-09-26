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
        self.assertIn("scrollIntoView", script)
        self.assertIn("feed.prepend", script)
        self.assertIn("data-comments-csrf", script)
        self.assertNotIn("form.innerHTML", script)

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
        self.assertIn('document.querySelector("[data-comments-edit-form]")', script)
        self.assertIn('document.querySelector("[data-comments-reason-form]")', script)
        self.assertNotIn('root.parentElement.querySelector("[data-comments-', script)
