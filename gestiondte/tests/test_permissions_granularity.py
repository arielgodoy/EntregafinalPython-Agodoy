import importlib

from django.contrib.auth.models import User
from django.apps import apps
from django.test import Client, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from access_control.services.empresa_activa import get_user_navigable_vistas


class DtePermissionGranularityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dte-granularity", password="pass")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self.client = Client()
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    def create_view(self, name):
        return Vista.objects.get_or_create(nombre=name)[0]

    def grant(self, name, **flags):
        return Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.create_view(name),
            **flags,
        )

    def test_dashboard_and_cesiones_are_independent(self):
        self.create_view("Gestión DTE - Control de Cesiones")
        self.grant("Gestión DTE - Dashboard DTE-SII-RPETC", ingresar=True)

        self.assertEqual(self.client.get(reverse("gestion_dte:index")).status_code, 200)
        self.assertEqual(self.client.get(reverse("gestion_dte:cesiones")).status_code, 403)

    def test_lectura_and_cesiones_are_independent(self):
        self.create_view("Gestión DTE - Control de Cesiones")
        self.grant("Gestión DTE - Lectura Automática de Cesiones", ingresar=True)

        self.assertEqual(self.client.get(reverse("gestion_dte:lectura_automatica_cesiones")).status_code, 200)
        self.assertEqual(self.client.get(reverse("gestion_dte:cesiones")).status_code, 403)

    def test_cesiones_and_lectura_are_independent_in_control_direction(self):
        self.grant("Gestión DTE - Control de Cesiones", ingresar=True)
        self.create_view("Gestión DTE - Lectura Automática de Cesiones")

        self.assertEqual(self.client.get(reverse("gestion_dte:cesiones")).status_code, 200)
        self.assertEqual(self.client.get(reverse("gestion_dte:lectura_automatica_cesiones")).status_code, 403)

    def test_certificados_remain_independent(self):
        self.grant("Gestión DTE - Certificados PFX-DTE", ingresar=True)
        self.create_view("Gestión DTE - Control de Cesiones")

        self.assertEqual(self.client.get(reverse("gestion_dte:certificados")).status_code, 200)
        self.assertEqual(self.client.get(reverse("gestion_dte:cesiones")).status_code, 403)

    def test_sidebar_shows_all_dte_items_with_partial_permissions(self):
        self.grant("Gestión DTE - Dashboard DTE-SII-RPETC", ingresar=True)
        response = self.client.get(reverse("gestion_dte:index"))

        self.assertContains(response, 'data-key="menu.gestion_dte.index"')
        self.assertContains(response, 'data-key="menu.gestion_dte.cesiones"')
        self.assertContains(response, 'data-key="menu.gestion_dte.lectura_automatica"')
        self.assertContains(response, 'data-key="menu.gestion_dte.certificados"')

    def test_sidebar_shows_all_dte_items_without_any_dte_permission(self):
        response = self.client.get(reverse("gestion_dte:index"))

        self.assertContains(response, 'data-key="menu.gestion_dte.index"', status_code=403)
        self.assertContains(response, 'data-key="menu.gestion_dte.cesiones"', status_code=403)
        self.assertContains(response, 'data-key="menu.gestion_dte.lectura_automatica"', status_code=403)
        self.assertContains(response, 'data-key="menu.gestion_dte.certificados"', status_code=403)

    def test_without_ingresar_each_dte_route_returns_403_with_access_request(self):
        routes = (
            "gestion_dte:index",
            "gestion_dte:cesiones",
            "gestion_dte:lectura_automatica_cesiones",
            "gestion_dte:certificados",
        )
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 403)
                self.assertContains(response, "accessRequestModal", status_code=403)
                self.assertContains(response, 'name="vista_nombre"', status_code=403)
                self.assertContains(response, 'name="empresa_id"', status_code=403)
                self.assertContains(response, "access.request.button", status_code=403)

    def test_company_change_keeps_certificate_visible_but_backend_changes_access(self):
        empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa 02")
        self.grant("Gestión DTE - Certificados PFX-DTE", ingresar=True)

        response = self.client.get(reverse("gestion_dte:certificados"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-key="menu.gestion_dte.certificados"')

        session = self.client.session
        session["empresa_id"] = empresa_b.id
        session.save()
        response = self.client.get(reverse("gestion_dte:certificados"))
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, 'data-key="menu.gestion_dte.certificados"', status_code=403)

    def test_conceptual_sidebar_and_backend_split(self):
        for name in (
            "Gestión DTE - Dashboard DTE-SII-RPETC",
            "Gestión DTE - Control de Cesiones",
            "Gestión DTE - Lectura Automática de Cesiones",
            "Gestión DTE - Certificados PFX-DTE",
        ):
            self.create_view(name)
        for name in (
            "Gestión DTE - Dashboard DTE-SII-RPETC",
            "Gestión DTE - Control de Cesiones",
            "Gestión DTE - Lectura Automática de Cesiones",
        ):
            self.grant(name, ingresar=True)

        dashboard_response = self.client.get(reverse("gestion_dte:index"))
        self.assertEqual(dashboard_response.status_code, 200)
        for key in (
            "menu.gestion_dte.index",
            "menu.gestion_dte.cesiones",
            "menu.gestion_dte.lectura_automatica",
            "menu.gestion_dte.certificados",
        ):
            self.assertContains(dashboard_response, f'data-key="{key}"')

        self.assertEqual(self.client.get(reverse("gestion_dte:cesiones")).status_code, 200)
        self.assertEqual(self.client.get(reverse("gestion_dte:lectura_automatica_cesiones")).status_code, 200)
        self.assertEqual(self.client.get(reverse("gestion_dte:certificados")).status_code, 403)

    def test_migration_copies_all_flags_without_changing_original(self):
        control = self.create_view("Gestión DTE - Control de Cesiones")
        historical = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=control,
            ingresar=True,
            crear=True,
            modificar=False,
            eliminar=False,
            autorizar=True,
            supervisor=False,
        )
        migration = importlib.import_module("access_control.migrations.0009_split_gestion_dte_vistas")
        migration.forwards(apps, None)

        for name in (
            "Gestión DTE - Dashboard DTE-SII-RPETC",
            "Gestión DTE - Lectura Automática de Cesiones",
        ):
            copied = Permiso.objects.get(usuario=self.user, empresa=self.empresa, vista__nombre=name)
            self.assertEqual(
                [getattr(copied, flag) for flag in migration.PERMISSION_FLAGS],
                [getattr(historical, flag) for flag in migration.PERMISSION_FLAGS],
            )
        historical.refresh_from_db()
        self.assertTrue(historical.ingresar)
        self.assertTrue(historical.crear)
        self.assertTrue(historical.autorizar)

    def test_migration_does_not_overwrite_existing_dashboard_permission(self):
        control = self.create_view("Gestión DTE - Control de Cesiones")
        dashboard = self.create_view("Gestión DTE - Dashboard DTE-SII-RPETC")
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=control,
            ingresar=True,
            crear=True,
            autorizar=True,
        )
        existing = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=dashboard,
            ingresar=False,
            crear=False,
            modificar=True,
            eliminar=True,
            autorizar=False,
            supervisor=True,
        )
        migration = importlib.import_module("access_control.migrations.0009_split_gestion_dte_vistas")
        migration.forwards(apps, None)

        existing.refresh_from_db()
        self.assertFalse(existing.ingresar)
        self.assertTrue(existing.modificar)
        self.assertTrue(existing.eliminar)
        self.assertTrue(existing.supervisor)

    def test_migration_does_not_overwrite_existing_lectura_permission(self):
        control = self.create_view("Gestión DTE - Control de Cesiones")
        lectura = self.create_view("Gestión DTE - Lectura Automática de Cesiones")
        Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=control,
            ingresar=True,
            crear=True,
            autorizar=True,
        )
        existing = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=lectura,
            ingresar=False,
            crear=True,
            modificar=False,
            eliminar=True,
            autorizar=False,
            supervisor=True,
        )
        migration = importlib.import_module("access_control.migrations.0009_split_gestion_dte_vistas")
        migration.forwards(apps, None)

        existing.refresh_from_db()
        self.assertFalse(existing.ingresar)
        self.assertTrue(existing.crear)
        self.assertTrue(existing.eliminar)
        self.assertTrue(existing.supervisor)

    def test_migration_does_not_create_destinations_without_control_permission(self):
        control = self.create_view("Gestión DTE - Control de Cesiones")
        migration = importlib.import_module("access_control.migrations.0009_split_gestion_dte_vistas")
        migration.forwards(apps, None)

        self.assertFalse(Permiso.objects.filter(
            usuario=self.user,
            empresa=self.empresa,
            vista__nombre="Gestión DTE - Dashboard DTE-SII-RPETC",
        ).exists())
        self.assertFalse(Permiso.objects.filter(
            usuario=self.user,
            empresa=self.empresa,
            vista__nombre="Gestión DTE - Lectura Automática de Cesiones",
        ).exists())

    def test_migration_sets_route_names_for_all_four_vistas(self):
        migration = importlib.import_module("access_control.migrations.0009_split_gestion_dte_vistas")
        migration.forwards(apps, None)

        self.assertEqual(
            dict(Vista.objects.filter(nombre__in=migration.VIEWS).values_list("nombre", "route_name")),
            migration.VIEWS,
        )

    def test_new_vistas_are_eligible_for_initial_view(self):
        expected_routes = {
            "Gestión DTE - Dashboard DTE-SII-RPETC": "gestion_dte:index",
            "Gestión DTE - Control de Cesiones": "gestion_dte:cesiones",
            "Gestión DTE - Lectura Automática de Cesiones": "gestion_dte:lectura_automatica_cesiones",
            "Gestión DTE - Certificados PFX-DTE": "gestion_dte:certificados",
        }
        for name, route_name in expected_routes.items():
            vista = self.create_view(name)
            vista.route_name = route_name
            vista.save(update_fields=["route_name"])
            self.grant(name, ingresar=True)

        navigable = get_user_navigable_vistas(self.user)
        self.assertEqual(
            {vista.nombre: vista.route_name for vista in navigable},
            expected_routes,
        )