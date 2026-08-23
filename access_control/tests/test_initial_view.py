from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from access_control.services.empresa_activa import (
    get_navigable_vistas,
    get_user_initial_view_url,
    get_user_navigable_vistas,
)
from settings.models import UserPreferences


class InitialViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="initial-user", password="pass")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self.initial_vista = Vista.objects.create(
            nombre="Gestión DTE - Control de Cesiones",
            route_name="gestion_dte:cesiones",
        )
        self.users_vista = Vista.objects.create(
            nombre="Control de Acceso - Maestro Usuarios",
        )
        self._grant(self.empresa, self.initial_vista)

    def _grant(self, empresa, vista, **flags):
        return Permiso.objects.create(
            usuario=self.user,
            empresa=empresa,
            vista=vista,
            ingresar=flags.get("ingresar", True),
            modificar=flags.get("modificar", False),
        )

    def _set_active_company(self, empresa=None):
        session = self.client.session
        session["empresa_id"] = (empresa or self.empresa).id
        session.save()

    def test_without_initial_view_redirects_to_dashboard(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": "pass"},
        )

        self.assertRedirects(response, reverse("dashboard:dashboard_general"), fetch_redirect_response=False)

    def test_valid_initial_view_redirects_to_route(self):
        UserPreferences.objects.update_or_create(
            user=self.user,
            defaults={"vista_inicial": self.initial_vista},
        )

        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": "pass"},
        )

        self.assertRedirects(response, reverse("gestion_dte:cesiones"), fetch_redirect_response=False)

    def test_multiple_companies_selects_initial_view(self):
        other_empresa = Empresa.objects.create(codigo="02", descripcion="Empresa 02")
        self._grant(other_empresa, self.initial_vista)
        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": "pass"},
        )
        self.assertRedirects(response, reverse("access_control:seleccionar_empresa"), fetch_redirect_response=False)

        UserPreferences.objects.update_or_create(
            user=self.user,
            defaults={"vista_inicial": self.initial_vista},
        )
        response = self.client.post(
            reverse("access_control:seleccionar_empresa"),
            {"empresa_id": self.empresa.id},
        )

        self.assertRedirects(response, reverse("gestion_dte:cesiones"), fetch_redirect_response=False)

    def test_company_change_keeps_navigation_target_over_initial_view(self):
        other_empresa = Empresa.objects.create(codigo="02", descripcion="Empresa 02")
        self._grant(other_empresa, self.initial_vista)
        UserPreferences.objects.update_or_create(
            user=self.user,
            defaults={"vista_inicial": self.initial_vista},
        )
        self.client.force_login(self.user)
        self._set_active_company(self.empresa)
        target = reverse("dashboard:dashboard_general")
        session = self.client.session
        session["ultima_vista_url"] = target
        session.save()

        response = self.client.post(
            reverse("access_control:seleccionar_empresa"),
            {"empresa_id": other_empresa.id},
        )

        self.assertRedirects(response, target, fetch_redirect_response=False)

    def test_invalid_route_falls_back_to_dashboard(self):
        invalid = Vista.objects.create(
            nombre="Vista obsoleta",
            route_name="missing:route",
        )
        UserPreferences.objects.update_or_create(
            user=self.user,
            defaults={"vista_inicial": invalid},
        )

        self.assertEqual(
            get_user_initial_view_url(self.user),
            reverse("dashboard:dashboard_general"),
        )

    def test_view_requiring_arguments_is_not_eligible(self):
        parameterized = Vista.objects.create(
            nombre="Detalle de proyecto",
            route_name="control_de_proyectos:detalle_proyecto",
        )

        self.assertNotIn(parameterized, get_navigable_vistas())

    def test_user_navigable_vistas_require_ingresar(self):
        permitted = Vista.objects.create(
            nombre="Dashboard permitido",
            route_name="dashboard:dashboard_general",
        )
        denied = Vista.objects.create(
            nombre="Dashboard denegado",
            route_name="dashboard:dashboard_general",
        )
        self._grant(self.empresa, permitted, ingresar=True)
        self._grant(self.empresa, denied, ingresar=False)

        vistas = get_user_navigable_vistas(self.user)

        self.assertIn(permitted, vistas)
        self.assertNotIn(denied, vistas)

    def test_user_navigable_vistas_are_unique_across_companies(self):
        shared = Vista.objects.create(
            nombre="Vista compartida",
            route_name="dashboard:dashboard_general",
        )
        other_empresa = Empresa.objects.create(codigo="02", descripcion="Empresa 02")
        self._grant(self.empresa, shared, ingresar=True)
        self._grant(other_empresa, shared, ingresar=True)

        vistas = get_user_navigable_vistas(self.user)

        self.assertEqual(vistas.count(shared), 1)

    def test_user_navigable_vistas_exclude_missing_route_name(self):
        without_route = Vista.objects.create(nombre="Vista sin ruta")
        self._grant(self.empresa, without_route, ingresar=True)

        self.assertNotIn(without_route, get_user_navigable_vistas(self.user))

    def test_user_table_renders_only_each_users_permitted_initial_views(self):
        permitted = Vista.objects.create(
            nombre="Vista visible en tabla",
            route_name="dashboard:dashboard_general",
        )
        denied = Vista.objects.create(
            nombre="Vista oculta en tabla",
            route_name="dashboard:dashboard_general",
        )
        self._grant(self.empresa, permitted, ingresar=True)
        self._grant(self.empresa, denied, ingresar=False)
        admin = User.objects.create_user(username="admin-list", password="pass")
        Permiso.objects.create(
            usuario=admin,
            empresa=self.empresa,
            vista=self.users_vista,
            ingresar=True,
        )
        self.client.force_login(admin)
        self._set_active_company(self.empresa)

        response = self.client.get(reverse("access_control:usuarios_lista"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, permitted.nombre)
        self.assertNotContains(response, denied.nombre)

    def test_admin_can_update_initial_view(self):
        admin = User.objects.create_user(username="admin", password="pass")
        Permiso.objects.create(
            usuario=admin,
            empresa=self.empresa,
            vista=self.users_vista,
            ingresar=True,
            modificar=True,
        )
        self.client.force_login(admin)
        self._set_active_company(self.empresa)

        response = self.client.post(
            reverse("access_control:actualizar_vista_inicial"),
            {"user_id": self.user.id, "vista_id": self.initial_vista.id},
        )

        self.assertRedirects(response, reverse("access_control:usuarios_lista"), fetch_redirect_response=False)
        self.assertEqual(
            UserPreferences.objects.get(user=self.user).vista_inicial_id,
            self.initial_vista.id,
        )
        self.assertTrue(any(
            message.message == "Vista inicial actualizada correctamente"
            for message in get_messages(response.wsgi_request)
        ))

    def test_admin_cannot_assign_view_without_user_ingresar_permission(self):
        unavailable = Vista.objects.create(
            nombre="Vista no permitida",
            route_name="dashboard:dashboard_general",
        )
        admin = User.objects.create_user(username="admin-restricted", password="pass")
        Permiso.objects.create(
            usuario=admin,
            empresa=self.empresa,
            vista=self.users_vista,
            ingresar=True,
            modificar=True,
        )
        self.client.force_login(admin)
        self._set_active_company(self.empresa)

        response = self.client.post(
            reverse("access_control:actualizar_vista_inicial"),
            {"user_id": self.user.id, "vista_id": unavailable.id},
        )

        self.assertRedirects(response, reverse("access_control:usuarios_lista"), fetch_redirect_response=False)
        self.assertIsNone(UserPreferences.objects.get(user=self.user).vista_inicial_id)

    def test_admin_can_clear_initial_view_with_dashboard(self):
        UserPreferences.objects.update_or_create(
            user=self.user,
            defaults={"vista_inicial": self.initial_vista},
        )
        admin = User.objects.create_user(username="admin-clear", password="pass")
        Permiso.objects.create(
            usuario=admin,
            empresa=self.empresa,
            vista=self.users_vista,
            ingresar=True,
            modificar=True,
        )
        self.client.force_login(admin)
        self._set_active_company(self.empresa)

        self.client.post(
            reverse("access_control:actualizar_vista_inicial"),
            {"user_id": self.user.id, "vista_id": ""},
        )

        self.assertIsNone(UserPreferences.objects.get(user=self.user).vista_inicial_id)

    def test_user_without_admin_permission_is_rejected(self):
        self.client.force_login(self.user)
        self._set_active_company(self.empresa)

        response = self.client.post(
            reverse("access_control:actualizar_vista_inicial"),
            {"user_id": self.user.id, "vista_id": self.initial_vista.id},
        )

        self.assertEqual(response.status_code, 403)

    def test_initial_view_still_runs_normal_functional_permission_check(self):
        UserPreferences.objects.update_or_create(
            user=self.user,
            defaults={"vista_inicial": self.initial_vista},
        )
        self.client.force_login(self.user)
        self._set_active_company(self.empresa)
        Permiso.objects.filter(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.initial_vista,
        ).update(ingresar=False)

        response = self.client.get(reverse("gestion_dte:cesiones"))

        self.assertEqual(response.status_code, 403)
