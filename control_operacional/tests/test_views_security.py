from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from access_control.services.access_utility import resolve_scope_vistas
from access_control.services.permissions import get_sidebar_visible_items
from control_operacional.views import (
    AckAlertaView,
    AlertasOperacionalesView,
    DashboardView,
)


class ControlOperacionalViewsSecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="operational-views")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self.dashboard = Vista.objects.create(
            nombre="Control Operacional - Dashboard",
            route_name="control_operacional:dashboard",
        )
        self.alertas = Vista.objects.create(
            nombre="Control Operacional - Alertas",
            route_name="control_operacional:alertas_operacionales",
        )
        self.legacy_ack = Vista.objects.create(
            nombre="Control Operacional - Reconocer alerta",
            route_name="control_operacional:ack_alerta",
        )

    def test_views_use_two_surfaces_and_ack_reuses_alertas(self):
        self.assertEqual(DashboardView.vista_nombre, self.dashboard.nombre)
        self.assertEqual(DashboardView.permiso_requerido, "ingresar")
        self.assertEqual(AlertasOperacionalesView.vista_nombre, self.alertas.nombre)
        self.assertEqual(AlertasOperacionalesView.permiso_requerido, "ingresar")
        self.assertEqual(AckAlertaView.vista_nombre, self.alertas.nombre)
        self.assertEqual(AckAlertaView.permiso_requerido, "ingresar")

    def test_scope_contains_only_canonical_surfaces(self):
        legacy_permission = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.legacy_ack,
            ingresar=True,
        )
        before_permissions = Permiso.objects.count()

        resolution = resolve_scope_vistas("control_operacional")

        self.assertEqual(
            set(resolution.requested_leaf_names),
            {self.dashboard.nombre, self.alertas.nombre},
        )
        self.assertEqual(
            {vista.nombre for vista in resolution.vistas},
            {self.dashboard.nombre, self.alertas.nombre},
        )
        self.assertEqual(resolution.missing_names, ())
        self.assertEqual(resolution.conflicts, ())
        self.assertEqual(Permiso.objects.count(), before_permissions)
        self.assertEqual(legacy_permission.vista_id, self.legacy_ack.id)
        self.assertNotIn(self.legacy_ack, resolution.vistas)

    def test_sidebar_uses_view_name_and_only_ver_controls_visibility(self):
        dashboard_permission = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.dashboard,
            ver=True,
            ingresar=False,
        )
        alertas_permission = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.alertas,
            ver=True,
            ingresar=False,
        )

        visible = get_sidebar_visible_items(
            self.user,
            self.empresa.id,
            materialize_permissions=False,
        )
        self.assertIn("operational_dashboard", visible)
        self.assertIn("operational_alerts", visible)

        dashboard_permission.ver = False
        dashboard_permission.ingresar = True
        dashboard_permission.save(update_fields=["ver", "ingresar"])
        alertas_permission.ver = False
        alertas_permission.ingresar = True
        alertas_permission.save(update_fields=["ver", "ingresar"])

        visible = get_sidebar_visible_items(
            self.user,
            self.empresa.id,
            materialize_permissions=False,
        )
        self.assertNotIn("operational_dashboard", visible)
        self.assertNotIn("operational_alerts", visible)
