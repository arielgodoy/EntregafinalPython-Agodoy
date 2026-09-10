import re
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from access_control.services.permissions import (
    SIDEBAR_GLOBAL_ITEMS,
    SIDEBAR_GROUPS,
    SIDEBAR_VIEW_NAMES,
    get_sidebar_visible_items,
)


class VicmeasSidebarTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="vicmeas-user", password="pass")
        self.empresa_a = Empresa.objects.create(codigo="01", descripcion="Empresa A")
        self.empresa_b = Empresa.objects.create(codigo="02", descripcion="Empresa B")
        self.dte_dashboard, _ = Vista.objects.get_or_create(
            nombre="Gestión DTE - Dashboard DTE-SII-RPETC",
            defaults={"route_name": "gestion_dte:index"},
        )
        self.dte_cesiones, _ = Vista.objects.get_or_create(
            nombre="Gestión DTE - Control de Cesiones",
            defaults={"route_name": "gestion_dte:cesiones"},
        )
        self.operational_dashboard, _ = Vista.objects.get_or_create(
            nombre="Control Operacional - Dashboard",
            defaults={"route_name": "control_operacional:dashboard"},
        )
        self.api_home, _ = Vista.objects.get_or_create(
            nombre="APIs - Inicio",
            defaults={"route_name": "api_home"},
        )

    def _activate(self, empresa):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = empresa.id
        session.save()

    def _permission(self, empresa, vista, *, ver=False, ingresar=False):
        return Permiso.objects.create(
            usuario=self.user,
            empresa=empresa,
            vista=vista,
            ver=ver,
            ingresar=ingresar,
        )

    def test_sidebar_items_have_mapping_or_explicit_classification(self):
        template = Path(__file__).resolve().parents[2] / "templates" / "partials" / "sidebar.html"
        template_keys = set(re.findall(r'"([a-z_]+)" in request\.sidebar_visible_items', template.read_text(encoding="utf-8")))
        declared_keys = set(SIDEBAR_VIEW_NAMES) | set(SIDEBAR_GROUPS) | SIDEBAR_GLOBAL_ITEMS

        self.assertEqual(template_keys, declared_keys)

    def test_sidebar_uses_one_query_for_visible_permissions(self):
        self._permission(self.empresa_a, self.dte_dashboard, ver=True)

        with self.assertNumQueries(1):
            visible = get_sidebar_visible_items(self.user, self.empresa_a.id)

        self.assertIn("gestion_dte_index", visible)
        self.assertIn("gestion_dte", visible)
        self.assertNotIn("library", visible)

    def test_empresa_scope_changes_sidebar_visibility(self):
        self._permission(self.empresa_a, self.dte_dashboard, ver=True)
        self._permission(self.empresa_b, self.dte_dashboard, ver=False)

        self.assertIn("gestion_dte", get_sidebar_visible_items(self.user, self.empresa_a.id))
        self.assertNotIn("gestion_dte", get_sidebar_visible_items(self.user, self.empresa_b.id))

    def test_parent_is_visible_when_any_child_is_visible(self):
        self._permission(self.empresa_a, self.dte_cesiones, ver=True)
        visible = get_sidebar_visible_items(self.user, self.empresa_a.id)

        self.assertIn("gestion_dte", visible)
        self.assertIn("gestion_dte_cesiones", visible)
        self.assertNotIn("gestion_dte_index", visible)

    def test_api_is_a_group_with_one_child_and_existing_view(self):
        template = Path(__file__).resolve().parents[2] / "templates" / "partials" / "sidebar.html"
        template_content = template.read_text(encoding="utf-8")

        self.assertEqual(SIDEBAR_GROUPS["apis"], ("api_home",))
        self.assertNotIn("api_home", SIDEBAR_GROUPS)
        self.assertEqual(SIDEBAR_VIEW_NAMES["api_home"], self.api_home.nombre)
        self.assertEqual(Vista.objects.filter(nombre="APIs - Inicio").count(), 1)
        self.assertEqual(template_content.count("{% url 'api_home' %}"), 1)

    def test_api_v_true_shows_parent_and_documentation_child(self):
        self._permission(self.empresa_a, self.api_home, ver=True)
        visible = get_sidebar_visible_items(self.user, self.empresa_a.id)

        self.assertIn("api_home", visible)
        self.assertIn("apis", visible)

        self._activate(self.empresa_a)
        response = self.client.get(reverse("dashboard:dashboard_general"))
        self.assertContains(response, 'data-key="menu.apis.documentation_test"')
        self.assertContains(response, "Documentación y Prueba")
        self.assertContains(response, f'href="{reverse("api_home")}"')
        self.assertEqual(response.content.count("Documentación y Prueba".encode("utf-8")), 1)

    def test_api_v_false_hides_parent_and_documentation_child(self):
        self._permission(self.empresa_a, self.api_home, ver=False)
        visible = get_sidebar_visible_items(self.user, self.empresa_a.id)

        self.assertNotIn("api_home", visible)
        self.assertNotIn("apis", visible)

        self._activate(self.empresa_a)
        response = self.client.get(reverse("dashboard:dashboard_general"))
        self.assertNotContains(response, "Documentación y Prueba")

    def test_superuser_sees_api_parent_and_child(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])

        visible = get_sidebar_visible_items(self.user, self.empresa_a.id)

        self.assertIn("api_home", visible)
        self.assertIn("apis", visible)

    def test_v_false_i_true_hides_sidebar_but_allows_direct_access(self):
        self._permission(self.empresa_a, self.dte_cesiones, ingresar=True)
        self._activate(self.empresa_a)

        sidebar_response = self.client.get(reverse("dashboard:dashboard_general"))
        direct_response = self.client.get(reverse("gestion_dte:cesiones"))

        self.assertEqual(direct_response.status_code, 200)
        self.assertNotContains(sidebar_response, "menu.gestion_dte")

    def test_v_true_i_false_shows_sidebar_but_denies_direct_access(self):
        self._permission(self.empresa_a, self.dte_cesiones, ver=True)
        self._activate(self.empresa_a)

        sidebar_response = self.client.get(reverse("dashboard:dashboard_general"))
        direct_response = self.client.get(reverse("gestion_dte:cesiones"))

        self.assertContains(sidebar_response, "menu.gestion_dte")
        self.assertEqual(direct_response.status_code, 403)

    def test_superuser_sees_all_sidebar_items_without_ver_permission(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        visible = get_sidebar_visible_items(self.user, self.empresa_a.id)

        self.assertIn("gestion_dte", visible)
        self.assertIn("library", visible)
        self.assertIn("access", visible)

    def test_v_false_i_false_hides_sidebar_and_denies_access(self):
        self._permission(self.empresa_a, self.dte_cesiones)
        self._activate(self.empresa_a)

        sidebar_response = self.client.get(reverse("dashboard:dashboard_general"))
        direct_response = self.client.get(reverse("gestion_dte:cesiones"))

        self.assertNotContains(sidebar_response, "menu.gestion_dte")
        self.assertEqual(direct_response.status_code, 403)

    def test_v_true_i_true_shows_sidebar_and_allows_access(self):
        self._permission(self.empresa_a, self.dte_cesiones, ver=True, ingresar=True)
        self._activate(self.empresa_a)

        sidebar_response = self.client.get(reverse("dashboard:dashboard_general"))
        direct_response = self.client.get(reverse("gestion_dte:cesiones"))

        self.assertContains(sidebar_response, "menu.gestion_dte")
        self.assertEqual(direct_response.status_code, 200)
