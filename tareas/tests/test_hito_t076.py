from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from tareas.forms import HitoForm
from tareas.models import Hito, HitoHistorial, TareaParticipante
from tareas.services.progress import (
    create_milestone,
    delete_milestone_safely,
    reassign_milestone,
    set_milestone_annulled,
    set_weighted_progress_mode,
    update_milestone,
    weighted_progress,
)
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user


class HitoT076Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="76", descripcion="Empresa T076")
        cls.otra_empresa = create_empresa(codigo="77", descripcion="Otra T076")
        cls.manager = create_user("t076_manager")
        cls.owner = create_user("t076_owner")
        cls.new_owner = create_user("t076_new_owner")
        cls.observer = create_user("t076_observer")
        cls.inactive = create_user("t076_inactive")
        cls.inactive.is_active = False
        cls.inactive.save(update_fields=["is_active"])
        for user in [cls.manager, cls.owner, cls.new_owner, cls.observer, cls.inactive]:
            assign_permission(user, cls.empresa, "Tareas - Hitos", ingresar=True)
        assign_permission(
            cls.manager,
            cls.empresa,
            "Tareas - Hitos",
            ingresar=True,
            modificar=True,
        )
        cls.tarea = create_tarea(
            cls.empresa,
            cls.manager,
            titulo="Tarea T076",
            responsable=cls.manager,
        )
        cls.hito = create_milestone(
            cls.tarea,
            "Hito inicial",
            20,
            2,
            responsable=cls.owner,
            actor=cls.manager,
        )

    def test_form_queryset_only_active_users_of_task_company(self):
        form = HitoForm(tarea=self.tarea)
        self.assertIn(self.owner, form.fields["responsable"].queryset)
        self.assertNotIn(self.inactive, form.fields["responsable"].queryset)

    def test_responsable_is_required_and_validated_by_service(self):
        with self.assertRaises(ValidationError):
            create_milestone(self.tarea, "Sin responsable", actor=self.manager)
        with self.assertRaises(ValidationError):
            create_milestone(
                self.tarea,
                "Inactivo",
                responsable=self.inactive,
                actor=self.manager,
            )
        foreign = create_user("t076_foreign")
        assign_permission(foreign, self.otra_empresa, "Tareas - Hitos", ingresar=True)
        with self.assertRaises(ValidationError):
            create_milestone(
                self.tarea,
                "Otra empresa",
                responsable=foreign,
                actor=self.manager,
            )

    def test_responsable_only_changes_own_compliance(self):
        update_milestone(self.hito, self.owner, cumplimiento=40)
        self.hito.refresh_from_db()
        self.assertEqual(self.hito.cumplimiento, Decimal("40.00"))
        self.assertTrue(
            self.hito.historial.filter(
                tipo_evento=HitoHistorial.Evento.CAMBIO_CUMPLIMIENTO,
                usuario=self.owner,
            ).exists()
        )
        with self.assertRaises(ValidationError):
            update_milestone(self.hito, self.owner, nombre="Cambio no permitido")
        with self.assertRaises(ValidationError):
            update_milestone(self.hito, self.owner, peso=4)
        with self.assertRaises(ValidationError):
            reassign_milestone(self.hito, self.owner, self.new_owner, "motivo")

    def test_manager_reassignment_requires_reason_and_is_audited(self):
        with self.assertRaises(ValidationError):
            reassign_milestone(self.hito, self.manager, self.new_owner, "  ")
        reassign_milestone(self.hito, self.manager, self.new_owner, " Cambio de alcance ")
        self.hito.refresh_from_db()
        self.assertEqual(self.hito.responsable, self.new_owner)
        event = self.hito.historial.get(tipo_evento=HitoHistorial.Evento.REASIGNACION)
        self.assertEqual(event.usuario, self.manager)
        self.assertEqual(event.motivo, "Cambio de alcance")

    def test_task_creator_can_manage_without_being_task_or_milestone_responsible(self):
        creator = create_user("t076_creator")
        assign_permission(creator, self.empresa, "Tareas - Hitos", ingresar=True)
        task = create_tarea(
            self.empresa,
            creator,
            titulo="Tarea creador T076",
            responsable=self.owner,
        )
        milestone = create_milestone(
            task,
            "Hito del creador",
            20,
            2,
            responsable=self.new_owner,
            actor=creator,
        )

        update_milestone(milestone, creator, nombre="Hito editado por creador", peso=3)
        reassign_milestone(milestone, creator, self.owner, "Reasignación del creador")
        set_milestone_annulled(milestone, creator, True)
        set_milestone_annulled(milestone, creator, False)

        milestone.refresh_from_db()
        self.assertEqual(milestone.nombre, "Hito editado por creador")
        self.assertEqual(milestone.peso, 3)
        self.assertEqual(milestone.responsable, self.owner)
        self.assertFalse(milestone.anulado)

    def test_authorizer_can_manage_within_task_scope(self):
        authorizer = create_user("t076_authorizer")
        assign_permission(authorizer, self.empresa, "Tareas - Hitos", ingresar=True)
        TareaParticipante.objects.create(
            tarea=self.tarea,
            usuario=authorizer,
            rol=TareaParticipante.Rol.AUTORIZADOR,
        )

        update_milestone(self.hito, authorizer, nombre="Hito autorizado", peso=3)
        reassign_milestone(
            self.hito,
            authorizer,
            self.new_owner,
            "Reasignación del autorizador",
        )
        set_milestone_annulled(self.hito, authorizer, True)
        set_milestone_annulled(self.hito, authorizer, False)

        self.hito.refresh_from_db()
        self.assertEqual(self.hito.nombre, "Hito autorizado")
        self.assertEqual(self.hito.peso, 3)
        self.assertEqual(self.hito.responsable, self.new_owner)
        self.assertFalse(self.hito.anulado)

    def test_invalid_reassignment_is_atomic(self):
        set_weighted_progress_mode(self.tarea)
        self.tarea.avance.refresh_from_db()
        original = {
            "nombre": self.hito.nombre,
            "peso": self.hito.peso,
            "responsable_id": self.hito.responsable_id,
            "cumplimiento": self.hito.cumplimiento,
            "avance": self.tarea.avance.porcentaje,
        }
        history_count = self.hito.historial.count()
        foreign = create_user("t076_atomic_foreign")
        assign_permission(foreign, self.otra_empresa, "Tareas - Hitos", ingresar=True)

        with self.assertRaises(ValidationError):
            reassign_milestone(self.hito, self.manager, foreign, "Cambio inválido")

        self.hito.refresh_from_db()
        self.tarea.avance.refresh_from_db()
        self.assertEqual(self.hito.nombre, original["nombre"])
        self.assertEqual(self.hito.peso, original["peso"])
        self.assertEqual(self.hito.responsable_id, original["responsable_id"])
        self.assertEqual(self.hito.cumplimiento, original["cumplimiento"])
        self.assertEqual(self.tarea.avance.porcentaje, original["avance"])
        self.assertEqual(self.hito.historial.count(), history_count)

    def _hitos_url(self):
        return f"/tareas/{self.tarea.pk}/hitos/"

    def _login_with_company(self, user):
        self.client.force_login(user)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()

    def test_manager_hitos_render_management_controls(self):
        self._login_with_company(self.manager)
        response = self.client.get(self._hitos_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Responsable")
        self.assertContains(response, "Editar")
        self.assertContains(response, "Reasignar")
        self.assertContains(response, "Anular")

        set_milestone_annulled(self.hito, self.manager, True)
        response = self.client.get(self._hitos_url())
        self.assertContains(response, "Reactivar")

    def test_responsible_renders_only_compliance_control(self):
        self._login_with_company(self.owner)
        response = self.client.get(self._hitos_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cumplimiento")
        self.assertNotContains(response, 'name="accion" value="editar_hito"')
        self.assertNotContains(response, 'name="accion" value="reasignar_hito"')
        self.assertNotContains(response, 'name="accion" value="anular_hito"')
        self.assertNotContains(response, 'name="accion" value="eliminar_hito"')

    def test_observer_renders_read_only_hitos(self):
        self._login_with_company(self.observer)
        response = self.client.get(self._hitos_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Responsable")
        self.assertNotContains(response, 'name="accion" value="editar_hito"')
        self.assertNotContains(response, 'name="accion" value="reasignar_hito"')
        self.assertNotContains(response, 'name="accion" value="anular_hito"')
        self.assertNotContains(response, 'name="accion" value="eliminar_hito"')

    def test_responsible_cannot_manipulate_management_post(self):
        self._login_with_company(self.owner)
        original = {
            "nombre": self.hito.nombre,
            "peso": self.hito.peso,
            "responsable_id": self.hito.responsable_id,
            "cumplimiento": self.hito.cumplimiento,
        }

        self.client.post(
            self._hitos_url(),
            data={
                "accion": "editar_hito",
                "hito_id": self.hito.pk,
                "nombre": "Cambio manipulado",
                "peso": "99",
                "responsable": self.new_owner.pk,
                "cumplimiento": "80",
            },
        )
        self.client.post(
            self._hitos_url(),
            data={"accion": "anular_hito", "hito_id": self.hito.pk},
        )

        self.hito.refresh_from_db()
        self.assertEqual(self.hito.nombre, original["nombre"])
        self.assertEqual(self.hito.peso, original["peso"])
        self.assertEqual(self.hito.responsable_id, original["responsable_id"])
        self.assertEqual(self.hito.cumplimiento, original["cumplimiento"])
        self.assertFalse(self.hito.anulado)

    def test_manager_roles_have_precedence_and_observer_is_read_only(self):
        supervisor = create_user("t076_supervisor")
        assign_permission(supervisor, self.empresa, "Tareas - Hitos", ingresar=True)
        TareaParticipante.objects.create(
            tarea=self.tarea,
            usuario=supervisor,
            rol=TareaParticipante.Rol.SUPERVISOR,
        )
        update_milestone(self.hito, supervisor, nombre="Supervisor editó")
        with self.assertRaises(ValidationError):
            update_milestone(self.hito, self.observer, cumplimiento=50)

    def test_annulled_hito_is_excluded_and_reactivated(self):
        set_weighted_progress_mode(self.tarea)
        self.tarea.avance.refresh_from_db()
        self.assertEqual(weighted_progress(self.tarea), Decimal("20.00"))
        set_milestone_annulled(self.hito, self.manager, True)
        self.hito.refresh_from_db()
        self.tarea.avance.refresh_from_db()
        self.assertTrue(self.hito.anulado)
        self.assertEqual(self.tarea.avance.porcentaje, Decimal("0.00"))
        set_milestone_annulled(self.hito, self.manager, False)
        self.hito.refresh_from_db()
        self.tarea.avance.refresh_from_db()
        self.assertFalse(self.hito.anulado)
        self.assertEqual(self.hito.cumplimiento, Decimal("20.00"))
        self.assertEqual(self.tarea.avance.porcentaje, Decimal("20.00"))

    def test_historical_activity_forces_logical_deletion(self):
        update_milestone(self.hito, self.manager, cumplimiento=0)
        result = delete_milestone_safely(self.hito, self.manager)
        self.assertIsNotNone(result)
        self.hito.refresh_from_db()
        self.assertTrue(self.hito.anulado)

    def test_never_active_hito_can_be_physically_deleted(self):
        fresh = create_milestone(
            self.tarea,
            "Borrable",
            responsable=self.owner,
            actor=self.manager,
        )
        delete_milestone_safely(fresh, self.manager)
        self.assertFalse(Hito.objects.filter(pk=fresh.pk).exists())
