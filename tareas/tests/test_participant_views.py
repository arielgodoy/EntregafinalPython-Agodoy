from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from tareas.models import Tarea, TareaLectura, TareaParticipante, TareaReasignacion
from tareas.tests.factories import (
    assign_permission, configure_task_storage, create_empresa, create_tarea, create_user,
)


class ParticipantAdministrationViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        configure_task_storage()
        cls.company = create_empresa(codigo="PAV")
        cls.creator = create_user("pav-creator")
        cls.old = create_user("pav-old")
        cls.new = create_user("pav-new")
        cls.reader = create_user("pav-reader")
        for user in (cls.creator, cls.old, cls.reader):
            assign_permission(user, cls.company, "Tareas", ingresar=True, modificar=True)
        assign_permission(cls.new, cls.company, "Membership only", ingresar=True)

    def setUp(self):
        self.task = create_tarea(
            self.company, self.creator, responsable=self.old,
            fecha_tope=timezone.localdate(), titulo="Original",
        )
        self.client.force_login(self.creator)
        session = self.client.session
        session["empresa_id"] = self.company.pk
        session.save()

    def publish(self):
        self.task.publicar(self.creator)

    def url(self, name, *args):
        return reverse(f"tareas:{name}", args=[self.task.pk, *args])

    def edit_data(self, **kwargs):
        data = {
            "titulo": "Updated", "descripcion": "Updated text",
            "prioridad": "NORMAL", "responsable": self.new.pk,
            "fecha_tope": self.task.fecha_tope.isoformat(),
        }
        data.update(kwargs)
        return data

    def test_add_without_target_tareas_permission_role_change_same_row_and_remove(self):
        response = self.client.post(self.url("vincular_participante", self.new.pk))
        self.assertEqual(response.status_code, 200)
        participant = TareaParticipante.objects.get(tarea=self.task, usuario=self.new)
        original = (participant.pk, participant.fecha)
        reading = TareaLectura.objects.get(tarea=self.task, usuario=self.new)
        role_url = self.url("cambiar_rol_participante", self.new.pk)
        self.assertEqual(self.client.post(role_url, {"rol": "INVITADO_OBSERVADOR"}).status_code, 302)
        participant.refresh_from_db()
        self.assertEqual((participant.pk, participant.fecha), original)
        self.assertEqual(participant.rol, "INVITADO_OBSERVADOR")
        self.assertEqual(self.client.post(role_url, {"rol": "INVITADO_OBSERVADOR"}).status_code, 302)
        self.new.is_active = False
        self.new.save(update_fields=["is_active"])
        self.assertEqual(self.client.post(self.url("desvincular_participante", self.new.pk)).status_code, 200)
        self.assertFalse(TareaParticipante.objects.filter(pk=participant.pk).exists())
        self.assertTrue(TareaLectura.objects.filter(pk=reading.pk).exists())

    def test_public_add_rejects_implicit_duplicate_and_historical_role(self):
        for user in (self.creator, self.old):
            with self.subTest(user=user.pk):
                self.assertEqual(self.client.post(self.url("vincular_participante", user.pk)).status_code, 400)
        self.client.post(self.url("vincular_participante", self.new.pk))
        self.assertEqual(self.client.post(self.url("vincular_participante", self.new.pk)).status_code, 409)
        self.client.post(self.url("vincular_participante_detalle"), {"usuario": self.reader.pk, "rol": "SUPERVISOR"})
        self.assertFalse(TareaParticipante.objects.filter(tarea=self.task, usuario=self.reader).exists())

    def test_detail_filters_actual_options_and_hides_locked_controls(self):
        TareaParticipante.objects.create(tarea=self.task, usuario=self.reader)
        response = self.client.get(self.url("detalle_tarea"))
        self.assertEqual(response.status_code, 200)
        options = set(response.context["participante_form"].fields["usuario"].queryset.values_list("pk", flat=True))
        self.assertEqual(options, {self.new.pk})
        self.assertContains(response, self.url("cambiar_rol_participante", self.reader.pk))
        self.task.estado = Tarea.Estado.CERRADA
        self.task.save(update_fields=["estado"])
        response = self.client.get(self.url("detalle_tarea"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["puede_administrar_participantes"])
        self.assertNotContains(response, self.url("administrar_responsable_detalle"))
        self.assertNotContains(response, self.url("cambiar_rol_participante", self.reader.pk))

    def test_published_reason_required_from_detail_and_general_edit(self):
        self.publish()
        self.client.post(self.url("administrar_responsable_detalle"), {"responsable": self.new.pk, "motivo": "  "})
        self.task.refresh_from_db()
        self.assertEqual(self.task.responsable_id, self.old.pk)
        response = self.client.post(self.url("editar_tarea"), self.edit_data(motivo=" "))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-key="tareas.assignment.errors.reason_required"')
        self.task.refresh_from_db()
        self.assertEqual((self.task.titulo, self.task.responsable_id), ("Original", self.old.pk))
        response = self.client.post(self.url("editar_tarea"), self.edit_data(motivo="  Service coverage  "))
        self.assertEqual(response.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual((self.task.titulo, self.task.responsable_id), ("Updated", self.new.pk))
        ledger = TareaReasignacion.objects.get(tarea=self.task)
        self.assertEqual((ledger.responsable_anterior_id, ledger.responsable_nuevo_id, ledger.motivo), (self.old.pk, self.new.pk, "Service coverage"))

    def test_draft_edit_clears_without_null_ledger(self):
        response = self.client.post(self.url("editar_tarea"), self.edit_data(responsable=""))
        self.assertEqual(response.status_code, 302)
        self.task.refresh_from_db()
        self.assertIsNone(self.task.responsable_id)
        self.assertFalse(TareaReasignacion.objects.filter(tarea=self.task).exists())

    def test_noncreator_with_modificar_cannot_edit_or_manage(self):
        self.client.force_login(self.reader)
        session = self.client.session
        session["empresa_id"] = self.company.pk
        session.save()
        for url, data in (
            (self.url("editar_tarea"), self.edit_data()),
            (self.url("administrar_responsable_detalle"), {"responsable": self.new.pk}),
            (self.url("vincular_participante_detalle"), {"usuario": self.new.pk}),
        ):
            with self.subTest(url=url):
                response = self.client.post(url, data)
                self.assertEqual(response.status_code, 403)
                self.assertTemplateUsed(response, "access_control/403_forbidden.html")
        self.assertEqual(self.client.get(self.url("editar_tarea")).status_code, 403)

    def test_closed_and_annulled_reject_all_mutations_and_edit_fk(self):
        for state, annulled in ((Tarea.Estado.CERRADA, False), (Tarea.Estado.ACTIVA, True)):
            self.task.estado = state
            self.task.anulada = annulled
            self.task.save(update_fields=["estado", "anulada"])
            link = TareaParticipante.objects.create(tarea=self.task, usuario=self.new)
            for name, args, data in (
                ("vincular_participante", [self.reader.pk], {}),
                ("desvincular_participante", [self.new.pk], {}),
                ("cambiar_rol_participante", [self.new.pk], {"rol": "INVITADO_OBSERVADOR"}),
                ("administrar_responsable_detalle", [], {"responsable": self.new.pk, "motivo": "Valid reason"}),
            ):
                self.client.post(self.url(name, *args), data)
            response = self.client.post(self.url("editar_tarea"), self.edit_data(motivo="Valid reason"))
            self.assertEqual(response.status_code, 200)
            self.task.refresh_from_db()
            link.refresh_from_db()
            self.assertEqual((self.task.responsable_id, self.task.titulo, link.rol), (self.old.pk, "Original", "PARTICIPANTE"))
            link.delete()

    def test_family_resolver_errors_do_not_lookup_default_tasks(self):
        for error in (RuntimeError("sensitive detail"), ValueError("sensitive detail")):
            with self.subTest(error=type(error).__name__), patch(
                "tareas.services.participant_storage.get_tarea_connection", side_effect=error,
            ), patch("tareas.views.Tarea.objects.get", side_effect=AssertionError("default fallback")):
                response = self.client.post(self.url("vincular_participante", self.new.pk))
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("sensitive", response.content.decode())

    def test_edit_resolver_failure_is_fail_closed(self):
        with patch("tareas.services.task_storage.get_tarea_connection", side_effect=RuntimeError("sensitive detail")):
            response = self.client.post(self.url("editar_tarea"), self.edit_data())
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("sensitive", response.content.decode())
