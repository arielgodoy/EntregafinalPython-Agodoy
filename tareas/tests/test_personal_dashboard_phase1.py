from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from access_control.models import Permiso, Vista
from access_control.services.permissions import get_sidebar_visible_items
from settings.models import UserPreferences
from tareas.models import Hito, MiniTarea, Tarea, TareaParticipante
from tareas.tests.factories import (
    activate_company,
    assign_permission,
    configure_task_storage,
    create_empresa,
    create_tarea,
    create_user,
)
from tareas.views import TareasDashboardPersonalView


class TareasPersonalDashboardPhase1Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        configure_task_storage()
        cls.empresa = create_empresa(codigo="00", descripcion="Empresa Dashboard Personal")
        cls.otra_empresa = create_empresa(codigo="02", descripcion="Empresa fuera de alcance")
        cls.usuario = create_user("dashboard_personal")
        cls.otro_usuario = create_user("dashboard_personal_otro")
        cls.usuario_vacio = create_user("dashboard_personal_vacio")

        assign_permission(
            cls.usuario, cls.empresa, "Tareas - Dashboard personal", ingresar=True
        )
        assign_permission(
            cls.usuario, cls.otra_empresa, "Tareas - Dashboard personal", ingresar=True
        )
        assign_permission(
            cls.otro_usuario, cls.empresa, "Tareas - Dashboard personal", ingresar=True
        )
        assign_permission(
            cls.usuario_vacio, cls.empresa, "Tareas - Dashboard personal", ingresar=True
        )

        today = timezone.localdate()
        now = timezone.now()
        cls.tarea_activa = create_tarea(
            cls.empresa,
            cls.usuario,
            titulo="Tarea activa propia",
            responsable=cls.usuario,
            estado=Tarea.Estado.ACTIVA,
            fecha_publicacion=now,
            fecha_tope=today + timedelta(days=5),
        )
        cls.tarea_gestion = create_tarea(
            cls.empresa,
            cls.usuario,
            titulo="Tarea en gestión propia",
            responsable=cls.usuario,
            estado=Tarea.Estado.GESTION,
            fecha_publicacion=now,
            fecha_tope=today + timedelta(days=5),
        )
        cls.tarea_aprobacion = create_tarea(
            cls.empresa,
            cls.usuario,
            titulo="Tarea pendiente de aprobación",
            responsable=cls.usuario,
            estado=Tarea.Estado.PENDIENTE_APROBACION_CIERRE,
            fecha_publicacion=now,
            fecha_tope=today + timedelta(days=5),
        )
        cls.tarea_cerrada = create_tarea(
            cls.empresa,
            cls.usuario,
            titulo="Tarea cerrada propia",
            responsable=cls.usuario,
            estado=Tarea.Estado.CERRADA,
            fecha_publicacion=now,
            fecha_tope=today - timedelta(days=10),
            fecha_cumplimiento=now,
        )
        cls.tarea_vencida = create_tarea(
            cls.empresa,
            cls.usuario,
            titulo="Tarea vencida propia",
            responsable=cls.usuario,
            estado=Tarea.Estado.ACTIVA,
            fecha_publicacion=now,
            fecha_tope=today - timedelta(days=1),
        )
        cls.tarea_participante = create_tarea(
            cls.empresa,
            cls.otro_usuario,
            titulo="Tarea por participación",
            responsable=cls.otro_usuario,
            estado=Tarea.Estado.ACTIVA,
            fecha_publicacion=now,
            fecha_tope=today + timedelta(days=2),
        )
        TareaParticipante.objects.create(
            tarea=cls.tarea_participante,
            usuario=cls.usuario,
            rol=TareaParticipante.Rol.PARTICIPANTE,
        )
        cls.tarea_ajena = create_tarea(
            cls.empresa,
            cls.otro_usuario,
            titulo="Tarea ajena",
            responsable=cls.otro_usuario,
            estado=Tarea.Estado.ACTIVA,
            fecha_publicacion=now,
            fecha_tope=today + timedelta(days=2),
        )
        cls.tarea_otra_empresa = create_tarea(
            cls.otra_empresa,
            cls.usuario,
            titulo="Tarea de otra empresa",
            responsable=cls.usuario,
            estado=Tarea.Estado.ACTIVA,
            fecha_publicacion=now,
            fecha_tope=today + timedelta(days=2),
        )
        cls.tarea_borrador = create_tarea(
            cls.empresa,
            cls.usuario,
            titulo="Borrador excluido",
            responsable=cls.usuario,
            fecha_tope=today - timedelta(days=2),
        )
        cls.tarea_anulada = create_tarea(
            cls.empresa,
            cls.usuario,
            titulo="Tarea anulada excluida",
            responsable=cls.usuario,
            estado=Tarea.Estado.ACTIVA,
            anulada=True,
            fecha_publicacion=now,
            fecha_tope=today - timedelta(days=2),
        )

        Hito.objects.create(
            tarea=cls.tarea_activa,
            nombre="Hito pendiente personal",
            responsable=cls.usuario,
            cumplimiento=Decimal("25.00"),
            peso=Decimal("1.00"),
        )
        Hito.objects.create(
            tarea=cls.tarea_activa,
            nombre="Hito completado personal",
            responsable=cls.usuario,
            cumplimiento=Decimal("100.00"),
            peso=Decimal("1.00"),
            completado=True,
        )
        Hito.objects.create(
            tarea=cls.tarea_activa,
            nombre="Hito de otro responsable",
            responsable=cls.otro_usuario,
            cumplimiento=Decimal("0.00"),
            peso=Decimal("1.00"),
        )
        Hito.objects.create(
            tarea=cls.tarea_activa,
            nombre="Hito anulado",
            responsable=cls.usuario,
            cumplimiento=Decimal("0.00"),
            peso=Decimal("1.00"),
            anulado=True,
        )
        MiniTarea.objects.create(
            tarea=cls.tarea_activa,
            descripcion="Minitarea pendiente personal",
            persona=cls.usuario,
        )
        MiniTarea.objects.create(
            tarea=cls.tarea_activa,
            descripcion="Minitarea terminada",
            persona=cls.usuario,
            hecho=True,
        )
        MiniTarea.objects.create(
            tarea=cls.tarea_activa,
            descripcion="Minitarea de otra persona",
            persona=cls.otro_usuario,
        )

    def setUp(self):
        self.client.force_login(self.usuario)
        activate_company(self.client, self.empresa)

    def test_requiere_autenticacion_y_permiso_ingresar(self):
        self.client.logout()
        response = self.client.get(reverse("tareas:dashboard_personal"))
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.usuario)
        activate_company(self.client, self.empresa)
        assign_permission(
            self.usuario, self.empresa, "Tareas - Dashboard personal", ingresar=False
        )
        response = self.client.get(reverse("tareas:dashboard_personal"))
        self.assertEqual(response.status_code, 403)

    def test_empresa_02_redirige_antes_de_consultar_datos_personales(self):
        activate_company(self.client, self.otra_empresa)
        with patch("tareas.views.get_personal_dashboard") as dashboard:
            response = self.client.get(reverse("tareas:dashboard_personal"))

        self.assertRedirects(
            response,
            reverse("access_control:seleccionar_empresa"),
            fetch_redirect_response=False,
        )
        dashboard.assert_not_called()

    def test_poblacion_personal_kpis_y_vencimiento(self):
        response = self.client.get(reverse("tareas:dashboard_personal"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tarea activa propia")
        self.assertContains(response, "Tarea por participación")
        self.assertNotContains(response, "Tarea ajena")
        self.assertNotContains(response, "Tarea de otra empresa")
        self.assertNotContains(response, "Borrador excluido")
        self.assertNotContains(response, "Tarea anulada excluida")

        kpis = {
            item["key"]: item["value"]
            for item in response.context["dashboard_kpis"]
        }
        self.assertEqual(kpis["tareas.dashboard.personal.kpi.total_tasks"], 6)
        self.assertEqual(kpis["tareas.dashboard.personal.kpi.active"], 3)
        self.assertEqual(kpis["tareas.dashboard.personal.kpi.management"], 1)
        self.assertEqual(kpis["tareas.dashboard.personal.kpi.pending_approval"], 1)
        self.assertEqual(kpis["tareas.dashboard.personal.kpi.closed"], 1)
        self.assertEqual(kpis["tareas.dashboard.personal.kpi.overdue"], 1)

    def test_hitos_y_minitareas_solo_incluyen_pendientes_asignados(self):
        response = self.client.get(reverse("tareas:dashboard_personal"))

        self.assertContains(response, "Hito pendiente personal")
        self.assertNotContains(response, "Hito completado personal")
        self.assertNotContains(response, "Hito de otro responsable")
        self.assertNotContains(response, "Hito anulado")
        self.assertContains(response, "Minitarea pendiente personal")
        self.assertNotContains(response, "Minitarea terminada")
        self.assertNotContains(response, "Minitarea de otra persona")

        kpis = {
            item["key"]: item["value"]
            for item in response.context["dashboard_kpis"]
        }
        self.assertEqual(
            kpis["tareas.dashboard.personal.kpi.pending_milestones"], 1
        )
        self.assertEqual(
            kpis["tareas.dashboard.personal.kpi.pending_minitasks"], 1
        )

    def test_muestra_cinco_tarjetas_por_estado_sin_alterar_totales(self):
        for index in range(6):
            create_tarea(
                self.empresa,
                self.usuario,
                titulo=f"Tarea adicional {index}",
                responsable=self.usuario,
                estado=Tarea.Estado.ACTIVA,
                fecha_publicacion=timezone.now(),
                fecha_tope=timezone.localdate() + timedelta(days=1),
            )

        response = self.client.get(reverse("tareas:dashboard_personal"))
        active_group = next(
            group
            for group in response.context["dashboard_state_groups"]
            if group["estado"] == Tarea.Estado.ACTIVA
        )

        self.assertEqual(active_group["total"], 9)
        self.assertEqual(len(active_group["tareas"]), 5)
        self.assertTrue(active_group["has_more"])
        visible_card_count = sum(
            min(group["total"], 5)
            for group in response.context["dashboard_state_groups"]
        )
        self.assertEqual(
            response.content.count(b'data-task-card="true"'),
            visible_card_count,
        )
        self.assertContains(response, reverse("tareas:mis_tareas"))

    def test_vista_vacia_muestra_kpis_en_cero_y_mensajes(self):
        self.client.force_login(self.usuario_vacio)
        activate_company(self.client, self.empresa)

        response = self.client.get(reverse("tareas:dashboard_personal"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No tienes tareas asignadas en esta empresa.")
        self.assertContains(response, "No tienes hitos pendientes.")
        self.assertContains(response, "No tienes minitareas pendientes.")
        self.assertTrue(
            all(item["value"] == 0 for item in response.context["dashboard_kpis"])
        )

    def test_enlaces_son_solo_navegacion_y_conserva_la_vista_anterior(self):
        response = self.client.get(reverse("tareas:dashboard_personal"))
        self.assertContains(
            response,
            reverse("tareas:detalle_tarea", args=[self.tarea_activa.pk]),
        )
        self.assertContains(response, reverse("tareas:mis_tareas"))
        self.assertNotContains(
            response,
            reverse("tareas:hitos_tarea", args=[self.tarea_activa.pk]),
        )
        self.assertNotContains(
            response,
            reverse("tareas:completar_tarea", args=[self.tarea_activa.pk]),
        )

        old_response = self.client.get(reverse("tareas:mis_tareas"))
        self.assertEqual(old_response.status_code, 200)
        self.assertContains(
            old_response,
            '<span data-key="tareas.personal.title">Mis tareas y hitos</span>',
        )

    def test_hereda_preferencia_oscura_sin_imponer_tema(self):
        preferences, _ = UserPreferences.objects.get_or_create(user=self.usuario)
        preferences.data_bs_theme = "dark"
        preferences.save(update_fields=["data_bs_theme"])

        response = self.client.get(reverse("tareas:dashboard_personal"))

        self.assertContains(response, '"data-bs-theme": "dark"')
        self.assertNotContains(response, 'data-bs-theme="light"')

    def test_ruta_independiente_y_permisos_iguales_a_la_vista_personal(self):
        self.assertEqual(
            reverse("tareas:dashboard_personal"),
            "/tareas/dashboard/personal/",
        )
        self.assertEqual(reverse("tareas:mis_tareas"), "/tareas/mis-tareas/")
        self.assertEqual(
            TareasDashboardPersonalView.vista_nombre,
            "Tareas - Dashboard personal",
        )
        self.assertEqual(
            TareasDashboardPersonalView.template_name,
            "tareas/dashboard_personal.html",
        )

    def test_seed_registers_dashboard_route_without_granting_permissions(self):
        vista = Vista.objects.get(nombre="Tareas - Dashboard personal")
        vista.route_name = "tareas:mis_tareas"
        vista.save(update_fields=["route_name"])
        permissions_before = Permiso.objects.count()

        call_command("seed_vistas")
        call_command("seed_vistas")

        vista.refresh_from_db()
        self.assertEqual(vista.route_name, "tareas:dashboard_personal")
        self.assertEqual(
            reverse(vista.route_name),
            "/tareas/dashboard/personal/",
        )
        self.assertEqual(
            Vista.objects.filter(nombre="Tareas - Dashboard personal").count(),
            1,
        )
        self.assertEqual(Permiso.objects.count(), permissions_before)

    def test_sidebar_link_uses_existing_visibility_permission(self):
        permission = Permiso.objects.get(
            usuario=self.usuario,
            empresa=self.empresa,
            vista__nombre="Tareas - Dashboard personal",
        )
        permission.ver = True
        permission.ingresar = True
        permission.save(update_fields=["ver", "ingresar"])

        response = self.client.get(reverse("tareas:dashboard_personal"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="{reverse("tareas:dashboard_personal")}"',
        )
        self.assertContains(response, "Dashboard Personal")
        self.assertContains(response, "Mis Hitos y Tareas")
        visible_items = get_sidebar_visible_items(
            self.usuario,
            self.empresa.pk,
            materialize_permissions=False,
        )
        self.assertIn("tasks_dashboard", visible_items)
        self.assertIn("tasks", visible_items)

        permission.ver = False
        permission.save(update_fields=["ver"])
        hidden_response = self.client.get(reverse("tareas:dashboard_personal"))

        self.assertEqual(hidden_response.status_code, 200)
        self.assertNotContains(
            hidden_response,
            f'href="{reverse("tareas:dashboard_personal")}"',
        )
        self.assertNotIn(
            "tasks_dashboard",
            get_sidebar_visible_items(
                self.usuario,
                self.empresa.pk,
                materialize_permissions=False,
            ),
        )

    def test_visibility_permission_does_not_grant_page_access(self):
        permission = Permiso.objects.get(
            usuario=self.usuario,
            empresa=self.empresa,
            vista__nombre="Tareas - Dashboard personal",
        )
        permission.ver = True
        permission.ingresar = False
        permission.save(update_fields=["ver", "ingresar"])

        visible_items = get_sidebar_visible_items(
            self.usuario,
            self.empresa.pk,
            materialize_permissions=False,
        )
        response = self.client.get(reverse("tareas:dashboard_personal"))

        self.assertIn("tasks_dashboard", visible_items)
        self.assertIn("tasks", visible_items)
        self.assertEqual(response.status_code, 403)

    def test_sidebar_visibility_and_access_use_the_active_company(self):
        permission = Permiso.objects.get(
            usuario=self.otro_usuario,
            empresa=self.empresa,
            vista__nombre="Tareas - Dashboard personal",
        )
        permission.ver = True
        permission.save(update_fields=["ver"])

        visible_in_authorized_company = get_sidebar_visible_items(
            self.otro_usuario,
            self.empresa.pk,
            materialize_permissions=False,
        )
        visible_in_other_company = get_sidebar_visible_items(
            self.otro_usuario,
            self.otra_empresa.pk,
            materialize_permissions=False,
        )

        self.assertIn("tasks_dashboard", visible_in_authorized_company)
        self.assertNotIn("tasks_dashboard", visible_in_other_company)
        self.assertNotIn("tasks", visible_in_other_company)

        self.client.force_login(self.otro_usuario)
        activate_company(self.client, self.otra_empresa)
        response = self.client.get(reverse("tareas:dashboard_personal"))
        self.assertEqual(response.status_code, 403)
