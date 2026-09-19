from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from access_control.services.access_utility import resolve_scope_vistas
from access_control.services.permissions import (
    SIDEBAR_DEFINITION_KEYS,
    get_sidebar_visible_items,
)
from access_control.services.view_catalog import ensure_declared_views_catalog, get_legacy_views_for_app
from access_control.services.view_registry import definitions_for_app
from access_control.services.view_registry_audit import audit_app


class ControlOperacionalVicmeasTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="operational-vicmeas")
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

    def test_registry_defines_two_real_surfaces_and_exact_bindings(self):
        definitions = definitions_for_app("control_operacional")

        self.assertEqual(
            {definition.key for definition in definitions},
            {"control_operacional.dashboard", "control_operacional.alertas"},
        )
        alerts = next(definition for definition in definitions if definition.key.endswith("alertas"))
        self.assertEqual(
            {(binding.route_name, binding.methods, binding.permiso_requerido) for binding in alerts.routes},
            {
                ("control_operacional:alertas_operacionales", ("GET",), "ingresar"),
                ("control_operacional:ack_alerta", ("GET", "POST"), "ingresar"),
            },
        )

    def test_audit_has_no_issues_and_covers_recognition_action(self):
        result = audit_app("control_operacional")

        self.assertEqual(result.issues, ())
        self.assertEqual(
            {(route.route_name, route.method, route.vista_nombre, route.permiso_requerido) for route in result.protected_routes},
            {
                ("control_operacional:dashboard", "GET", "Control Operacional - Dashboard", "ingresar"),
                ("control_operacional:alertas_operacionales", "GET", "Control Operacional - Alertas", "ingresar"),
                ("control_operacional:ack_alerta", "GET", "Control Operacional - Alertas", "ingresar"),
                ("control_operacional:ack_alerta", "POST", "Control Operacional - Alertas", "ingresar"),
            },
        )

    def test_scope_uses_two_canonical_surfaces_without_copying_legacy_permission(self):
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
            {"Control Operacional - Dashboard", "Control Operacional - Alertas"},
        )
        self.assertEqual(
            {vista.nombre for vista in resolution.vistas},
            {self.dashboard.nombre, self.alertas.nombre},
        )
        self.assertEqual(resolution.missing_names, ())
        self.assertEqual(resolution.conflicts, ())
        self.assertEqual(Permiso.objects.count(), before_permissions)
        self.assertFalse(
            Permiso.objects.filter(
                usuario=self.user,
                empresa=self.empresa,
                vista__in=(self.dashboard, self.alertas),
            ).exists()
        )
        self.assertEqual(legacy_permission.vista_id, self.legacy_ack.id)

    def test_sidebar_uses_definition_keys_and_only_ver_controls_visibility(self):
        self.assertEqual(
            SIDEBAR_DEFINITION_KEYS["operational_dashboard"],
            "control_operacional.dashboard",
        )
        self.assertEqual(
            SIDEBAR_DEFINITION_KEYS["operational_alerts"],
            "control_operacional.alertas",
        )
        permission = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.dashboard,
            ver=True,
            ingresar=False,
            modificar=False,
        )

        visible = get_sidebar_visible_items(
            self.user,
            self.empresa.id,
            materialize_permissions=False,
        )

        self.assertIn("operational_dashboard", visible)
        self.assertNotIn("operational_alerts", visible)
        permission.ver = False
        permission.ingresar = True
        permission.save(update_fields=["ver", "ingresar"])
        visible = get_sidebar_visible_items(
            self.user,
            self.empresa.id,
            materialize_permissions=False,
        )
        self.assertNotIn("operational_dashboard", visible)

    def test_catalog_reuses_canonical_rows_and_reports_ack_as_legacy(self):
        before_views = tuple(Vista.objects.values_list("id", "nombre", "route_name"))
        result = ensure_declared_views_catalog(
            app="control_operacional",
            dry_run=True,
        )

        self.assertEqual(result.created, 0)
        self.assertEqual(result.existing, 2)
        self.assertEqual(result.updated, 0)
        self.assertEqual(result.conflicts, ())
        self.assertEqual(
            {item.nombre for item in result.legacy},
            {self.legacy_ack.nombre},
        )
        self.assertEqual(
            {report.reemplazo_canonico_sugerido for report in result.legacy_reports},
            {"Control Operacional - Alertas"},
        )
        self.assertEqual(
            tuple(Vista.objects.values_list("id", "nombre", "route_name")),
            before_views,
        )

    def test_legacy_reporting_preserves_history_and_marks_blocker(self):
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.legacy_ack,
            ingresar=True,
        )

        report = get_legacy_views_for_app("control_operacional")[0]

        self.assertEqual(report.vista, self.legacy_ack)
        self.assertEqual(report.permisos.count, 1)
        self.assertFalse(report.safe_to_delete)
        self.assertIn("permisos históricos", report.blockers)
