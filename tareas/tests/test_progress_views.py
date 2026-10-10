from decimal import Decimal
from dataclasses import replace
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from settings.models import SettingsMySQLConnection

from tareas.models import Avance, Hito, Tarea, TareaConnectionRole
from tareas.tests.factories import assign_permission, create_empresa, create_tarea, create_user
from tareas.services.detail_storage import (
    DjangoTaskDetailStorage, TaskDetailSections, TaskDetailMilestoneHistory,
)
from tareas.services.milestone_storage import (
    CreateMilestoneCommand, UpdateMilestoneCommand, DeleteMilestoneCommand,
    UpdateManualProgressCommand, SetWeightedProgressModeCommand, MilestoneNotFound,
)
from tareas.services.task_storage import TaskStorageError


class ProgressViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="00")
        cls.otra_empresa = create_empresa(codigo="02")
        cls.usuario = create_user(username="progress-view-user")
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS", source_type="DJANGO", django_alias="default"
        )
        assign_permission(cls.usuario, cls.empresa, "Tareas - Hitos", ingresar=True, crear=True, modificar=True)
        cls.tarea = create_tarea(
            cls.empresa,
            cls.usuario,
            titulo="Tarea progreso",
            responsable=cls.usuario,
        )
        cls.tarea_externa = create_tarea(cls.otra_empresa, cls.usuario, titulo="Tarea externa")

    def setUp(self):
        self.client.login(username="progress-view-user", password="password-prueba")
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    def test_login_requerido(self):
        self.client.logout()
        response = self.client.get(reverse("tareas:hitos_tarea", args=[self.tarea.pk]))
        self.assertEqual(response.status_code, 302)

    def test_get_muestra_hitos_y_avance_de_la_empresa(self):
        Hito.objects.create(tarea=self.tarea, nombre="Plan", peso=2, responsable=self.usuario)
        response = self.client.get(reverse("tareas:hitos_tarea", args=[self.tarea.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Plan")
        self.assertContains(response, "Hitos y avance")
        self.assertContains(response, "Cumplimiento (%)")
        self.assertContains(response, "Peso del hito (%)")

    def test_detalle_embeds_hitos_with_hitos_permission(self):
        assign_permission(self.usuario, self.empresa, "Tareas", ingresar=True)
        response = self.client.get(reverse("tareas:detalle_tarea", args=[self.tarea.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="tarea-pane-hitos"')
        self.assertContains(response, "Configurar avance manual")
        self.assertContains(response, "Crear hito")

    def test_detalle_hitos_tab_requires_hitos_permission(self):
        usuario = create_user(username="progress-detail-reader")
        assign_permission(usuario, self.empresa, "Tareas", ingresar=True)
        self.client.logout()
        self.client.login(username="progress-detail-reader", password="password-prueba")
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()
        response = self.client.get(reverse("tareas:detalle_tarea", args=[self.tarea.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="tarea-pane-hitos"')

    def test_post_crea_hito_mediante_servicio(self):
        response = self.client.post(
            reverse("tareas:hitos_tarea", args=[self.tarea.pk]),
            {
                "accion": "hito",
                "nombre": "Ejecución",
                "responsable": self.usuario.pk,
                "cumplimiento": "25",
                "peso": "2",
            },
        )
        self.assertRedirects(response, reverse("tareas:hitos_tarea", args=[self.tarea.pk]))
        self.assertTrue(Hito.objects.filter(tarea=self.tarea, nombre="Ejecución").exists())

    def test_post_desde_detalle_vuelve_al_tab_hitos(self):
        response = self.client.post(
            reverse("tareas:hitos_tarea", args=[self.tarea.pk]),
            {
                "accion": "hito",
                "nombre": "Desde detalle",
                "responsable": self.usuario.pk,
                "cumplimiento": "0",
                "peso": "1",
                "next": "detalle",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"{reverse('tareas:detalle_tarea', args=[self.tarea.pk])}#tarea-pane-hitos",
        )
        self.assertTrue(Hito.objects.filter(tarea=self.tarea, nombre="Desde detalle").exists())

    def test_post_configura_avance_manual_y_ponderado(self):
        self.client.post(
            reverse("tareas:hitos_tarea", args=[self.tarea.pk]),
            {"accion": "manual", "porcentaje": "42.50"},
        )
        avance = Avance.objects.get(tarea=self.tarea)
        self.assertEqual(avance.porcentaje, Decimal("42.50"))
        self.client.post(
            reverse("tareas:hitos_tarea", args=[self.tarea.pk]),
            {"accion": "ponderado", "confirmar": "on"},
        )
        avance.refresh_from_db()
        self.assertEqual(avance.modo, Avance.Modo.PONDERADO)

    def test_otra_empresa_no_es_accesible(self):
        response = self.client.get(reverse("tareas:hitos_tarea", args=[self.tarea_externa.pk]))
        self.assertEqual(response.status_code, 404)


class MySQLMilestoneHttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.empresa = create_empresa(codigo="00")
        cls.user = create_user("mysql-hito-http")
        assign_permission(
            cls.user, cls.empresa, "Tareas - Hitos",
            ingresar=True, crear=True, modificar=True, eliminar=True,
        )
        cls.task = create_tarea(cls.empresa, cls.user, responsable=cls.user)
        cls.milestone = Hito.objects.create(
            tarea=cls.task, responsable=cls.user, nombre="DTO MySQL Hito", peso=1,
        )
        cls.detail = DjangoTaskDetailStorage("default").get_task_detail(
            task_id=cls.task.pk, empresa_id=cls.empresa.pk,
            sections=TaskDetailSections(milestones=True, mini_tasks=False, links=False),
        )
        catalog = cls.empresa
        mysql = SettingsMySQLConnection.objects.create(
            empresa=catalog, nombre_logico="hito-http-test",
            host="mysql.example.test", user="fixture", db_name="tareas", is_active=True,
        )
        TareaConnectionRole.objects.update_or_create(
            role="BASE_TAREAS",
            defaults={
                "source_type": "MYSQL_CONFIG", "django_alias": None,
                "mysql_connection": mysql, "database_name": "tareas",
            },
        )

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()
        self.storage = Mock()
        self.storage.detail.return_value = self.detail
        self.storage.history.return_value = ()
        self.resolver = patch(
            "tareas.views.resolve_milestone_storage", return_value=self.storage,
        )
        self.resolved = self.resolver.start()
        self.addCleanup(self.resolver.stop)
        self.url = reverse("tareas:hitos_tarea", args=[self.task.pk])

    def test_mysql_get_uses_dto_without_legacy_guard_or_operational_orm(self):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url)
        self.assertContains(response, "DTO MySQL Hito")
        self.storage.detail.assert_called_once_with(
            task_id=self.task.pk, empresa_id=self.empresa.pk, actor_id=self.user.pk,
        )
        self.storage.history.assert_called_once_with(
            task_id=self.task.pk, empresa_id=self.empresa.pk,
            actor_id=self.user.pk, milestone_id=self.milestone.pk,
        )
        self.resolved.assert_called_once()
        operational = ('"tareas_tarea"', '"tareas_hito"', '"tareas_avance"')
        self.assertFalse(any(
            table in query["sql"] for query in queries for table in operational
        ))

    def test_mysql_completed_dto_renders_read_only_completion_and_history(self):
        milestone = replace(
            self.detail.milestones[0], completado=True, cumplimiento=Decimal("100"),
            completado_por_username=self.user.username, resena_cierre="Canonical review",
        )
        self.storage.detail.return_value = replace(self.detail, milestones=(milestone,))
        response = self.client.get(self.url)
        self.assertContains(response, "Canonical review")
        self.assertContains(response, f'id="verCumplimientoHitoModal-{milestone.pk}"')
        self.assertNotContains(response, f'id="editarHitoModal-{milestone.pk}"')

    def test_history_event_labels_use_literal_translation_keys(self):
        labels = (
            ("CREACION", "tareas.milestones.created"),
            ("CAMBIO_NOMBRE", "tareas.milestones.history.name_changed"),
            ("CAMBIO_CUMPLIMIENTO", "tareas.milestones.history.compliance_changed"),
            ("CAMBIO_PESO", "tareas.milestones.history.weight_changed"),
            ("REASIGNACION", "tareas.milestones.history.reassigned"),
            ("ANULACION", "tareas.milestones.cancelled"),
            ("REACTIVACION", "tareas.milestones.history.reactivated"),
            ("COMPLETADO", "tareas.milestones.completed"),
        )
        self.storage.history.return_value = tuple(
            TaskDetailMilestoneHistory(
                index, event, self.user.pk, self.user.username, None, {}, {}, "",
            )
            for index, (event, _key) in enumerate(labels, 1)
        )
        response = self.client.get(self.url)
        content = response.content.decode()
        start = content.index(f'id="historialHitoModal-{self.milestone.pk}"')
        modal = content[start:content.index('id="eliminarHitoModal-', start)]
        for event, key in labels:
            self.assertIn(f'data-key="{key}"', modal)
            self.assertNotIn(event, modal)

    def test_mysql_embedded_detail_renders_same_dto_without_history_reads(self):
        assign_permission(self.user, self.empresa, "Tareas", ingresar=True)
        detail_storage = Mock()
        detail_storage.get_task_detail.return_value = self.detail
        with patch("tareas.views.resolve_detail_storage", return_value=detail_storage):
            response = self.client.get(reverse("tareas:detalle_tarea", args=[self.task.pk]))
        self.assertContains(response, "DTO MySQL Hito")
        self.assertContains(response, 'id="tarea-pane-hitos"')
        self.assertEqual(response.context["hitos"][0].pk, self.milestone.pk)
        self.assertEqual(response.context["hitos"][0].historial, ())
        self.storage.history.assert_not_called()
        call = detail_storage.get_task_detail.call_args.kwargs
        self.assertEqual(call["empresa_id"], self.empresa.pk)
        self.assertTrue(call["sections"].milestones)

    def test_mysql_closed_and_effectively_annulled_are_read_only(self):
        for state, annulled in (("CERRADA", False), ("PENDIENTE_APROBACION_CIERRE", False), ("ACTIVA", True)):
            with self.subTest(state=state, annulled=annulled):
                self.storage.detail.return_value = replace(
                    self.detail, core=replace(self.detail.core, estado=state),
                    hierarchy=replace(self.detail.hierarchy, effectively_annulled=annulled),
                )
                response = self.client.get(self.url)
                self.assertContains(response, "DTO MySQL Hito")
                self.assertFalse(response.context["puede_crear_hito"])
                self.assertFalse(response.context["puede_modificar_avance"])
                self.assertFalse(response.context["hitos"][0].puede_actualizar)
                self.assertFalse(response.context["hitos"][0].puede_eliminar)
                self.assertNotContains(response, 'name="accion" value="manual"')
                self.assertNotContains(response, 'name="accion" value="ponderado"')

    def test_mysql_read_only_permission_hides_both_progress_forms(self):
        assign_permission(self.user, self.empresa, "Tareas - Hitos", ingresar=True)
        response = self.client.get(self.url)
        self.assertContains(response, "DTO MySQL Hito")
        self.assertNotContains(response, 'name="accion" value="manual"')
        self.assertNotContains(response, 'name="accion" value="ponderado"')

    def test_mysql_posts_dispatch_commands_with_session_scope_and_prg(self):
        cases = (
            ({"accion": "hito", "nombre": "Create", "responsable": self.user.pk, "cumplimiento": "0", "peso": "1"}, CreateMilestoneCommand),
            ({"accion": "editar_hito", "hito_id": self.milestone.pk, "nombre": "Edit", "cumplimiento": "20", "peso": "2"}, UpdateMilestoneCommand),
            ({"accion": "manual", "porcentaje": "12"}, UpdateManualProgressCommand),
            ({"accion": "ponderado"}, SetWeightedProgressModeCommand),
            ({"accion": "eliminar_hito", "hito_id": self.milestone.pk}, DeleteMilestoneCommand),
        )
        for payload, command_type in cases:
            with self.subTest(command=command_type.__name__):
                response = self.client.post(self.url, {
                    **payload, "empresa_id": self.empresa.pk + 100, "next": "detalle",
                })
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].endswith("#tarea-pane-hitos"))
                command = self.storage.execute.call_args.args[0]
                self.assertIsInstance(command, command_type)
                self.assertEqual(command.empresa_id, self.empresa.pk)
                self.assertEqual(command.task_id, self.task.pk)
                self.assertEqual(command.actor_id, self.user.pk)
        self.milestone.refresh_from_db()
        self.assertEqual(self.milestone.nombre, "DTO MySQL Hito")
        self.assertFalse(Avance.objects.filter(tarea=self.task).exists())

    def test_mysql_missing_action_permission_returns_403_before_storage(self):
        assign_permission(self.user, self.empresa, "Tareas - Hitos", ingresar=True)
        for action, payload in (
            ("hito", {"nombre": "Denied", "responsable": self.user.pk, "cumplimiento": "0", "peso": "1"}),
            ("manual", {"porcentaje": "10"}),
            ("eliminar_hito", {"hito_id": self.milestone.pk}),
        ):
            with self.subTest(action=action):
                response = self.client.post(self.url, {"accion": action, **payload})
                self.assertEqual(response.status_code, 403)
                self.assertTemplateUsed(response, "access_control/403_forbidden.html")
                self.assertEqual(response.context["vista_nombre"], "Tareas - Hitos")
        self.resolved.assert_not_called()
        self.storage.execute.assert_not_called()

    def test_mysql_configuration_and_execution_fail_closed_503(self):
        self.resolved.side_effect = TaskStorageError("sanitized")
        self.assertEqual(self.client.get(self.url).status_code, 503)
        self.storage.detail.assert_not_called()
        self.resolved.side_effect = None
        self.storage.execute.side_effect = TaskStorageError("sanitized")
        response = self.client.post(self.url, {"accion": "manual", "porcentaje": "10"})
        self.assertEqual(response.status_code, 503)
        self.assertNotContains(response, "sanitized", status_code=503)

    def test_mysql_validation_error_rerenders_bound_form_without_write(self):
        self.storage.execute.side_effect = ValidationError("tareas.messages.generic_error")
        response = self.client.post(self.url, {"accion": "manual", "porcentaje": "10"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["manual_form"].errors)
        self.assertFalse(Avance.objects.filter(tarea=self.task).exists())

    def test_mysql_canonical_denial_and_missing_scope_are_controlled(self):
        self.storage.execute.side_effect = PermissionDenied
        response = self.client.post(self.url, {"accion": "manual", "porcentaje": "10"})
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "access_control/403_forbidden.html")
        self.assertEqual(response.context["vista_nombre"], "Tareas - Hitos")
        self.storage.detail.side_effect = MilestoneNotFound
        self.assertEqual(self.client.get(self.url).status_code, 404)
