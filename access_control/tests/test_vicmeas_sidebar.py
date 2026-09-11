import json
import re
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.template.loader import render_to_string
from django.urls import NoReverseMatch, reverse

from access_control.models import Empresa, Permiso, Vista
from access_control.services.permissions import (
    SIDEBAR_MENU,
    SIDEBAR_GLOBAL_ITEMS,
    SIDEBAR_GROUPS,
    SIDEBAR_VIEW_NAMES,
    filter_sidebar_tree,
    get_descendant_sidebar_keys,
    get_sidebar_access_tree,
    get_sidebar_visible_items,
)


class VicmeasSidebarTests(TestCase):
    @staticmethod
    def _deep_tree(depth, leaf_key="deep_leaf", prefix="level"):
        node = {
            "key": leaf_key,
            "vista": "Control de Acceso - Maestro Usuarios",
            "route_name": "access_control:usuarios_lista",
            "label_key": "menu.access_control.master_users",
            "label": "Maestro Usuarios",
        }
        for level in range(depth, 0, -1):
            node = {
                "key": f"{prefix}_{level}",
                "label_key": f"test.{prefix}_{level}",
                "label": f"Nivel {level}",
                "children": (node,),
            }
        return ({
            "key": "root",
            "label_key": "test.root",
            "label": "Root",
            "children": (node,),
        },)

    @staticmethod
    def _walk_containers(nodes):
        for node in nodes:
            if node.get("children"):
                yield node
                yield from VicmeasSidebarTests._walk_containers(node["children"])

    @staticmethod
    def _walk_nodes(nodes):
        for node in nodes:
            yield node
            if node.get("children"):
                yield from VicmeasSidebarTests._walk_nodes(node["children"])

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

        access_keys = set(get_descendant_sidebar_keys("control_acceso"))
        legacy_declared_keys = declared_keys - access_keys - {"access"}
        self.assertEqual(template_keys, legacy_declared_keys)
        self.assertIn('{% include "partials/sidebar_node.html"', template.read_text(encoding="utf-8"))

    def test_access_tree_has_nine_leaves_and_expected_branch_sizes(self):
        self.assertEqual(len(get_descendant_sidebar_keys("control_acceso")), 9)
        self.assertEqual(len(get_descendant_sidebar_keys("usuarios")), 3)
        self.assertEqual(len(get_descendant_sidebar_keys("permisos")), 5)
        self.assertEqual(get_descendant_sidebar_keys("control_acceso")[3], "access_companies")

    def test_access_leaf_labels_match_canonical_view_names(self):
        expected = {
            "access_invite": ("Invitar Usuario", "Control de Acceso - Invitar Usuario"),
            "access_invitations": ("Invitaciones", "Control de Acceso - Invitaciones"),
            "access_users": ("Maestro Usuarios", "Control de Acceso - Maestro Usuarios"),
            "access_companies": ("Maestro Empresas", "Control de Acceso - Maestro Empresas"),
            "access_views": ("Maestro Vistas", "Control de Acceso - Maestro Vistas"),
            "access_permissions": ("Maestro Permisos", "Control de Acceso - Maestro Permisos"),
            "access_filtered_permissions": ("Permisos Filtrados", "Control de Acceso - Permisos Filtrados"),
            "access_view_permissions": ("Permisos por Vista", "Control de Acceso - Permisos por Vista"),
            "access_utility": ("Utilitario de Acceso", "Control de Acceso - Utilitario de Acceso"),
        }

        def collect_leaves(nodes):
            leaves = {}
            for node in nodes:
                if node.get("children"):
                    leaves.update(collect_leaves(node["children"]))
                else:
                    leaves[node["key"]] = node
            return leaves

        leaves = collect_leaves(SIDEBAR_MENU)

        for key, (label, vista_name) in expected.items():
            self.assertEqual((leaves[key]["label"], leaves[key]["vista"]), (label, vista_name))

    def test_access_branch_containers_have_no_view(self):
        root = SIDEBAR_MENU[0]
        usuarios = root["children"][0]
        permisos = root["children"][2]

        self.assertNotIn("vista", root)
        self.assertNotIn("vista", usuarios)
        self.assertNotIn("vista", permisos)
        self.assertIn("children", usuarios)
        self.assertIn("children", permisos)

    def test_access_tree_contract_and_i18n_keys(self):
        expected_es = {
            "menu.access_control": "Control de Acceso",
            "menu.access_control.users": "Usuarios",
            "menu.access_control.permissions": "Permisos",
            "menu.access_control.invite_user": "Invitar Usuario",
            "menu.access_control.invitations": "Invitaciones",
            "menu.access_control.master_users": "Maestro Usuarios",
            "menu.access_control.master_companies": "Maestro Empresas",
            "menu.access_control.master_views": "Maestro Vistas",
            "menu.access_control.master_permissions": "Maestro Permisos",
            "menu.access_control.filtered_permissions": "Permisos Filtrados",
            "menu.access_control.view_permissions": "Permisos por Vista",
            "menu.access_control.access_utility": "Utilitario de Acceso",
        }
        lang_dir = Path(__file__).resolve().parents[2] / "static" / "lang"
        translations = {
            language: json.loads((lang_dir / f"{language}.json").read_text(encoding="utf-8"))
            for language in ("sp", "en")
        }

        seen_keys = set()
        seen_vistas = set()

        def visit(nodes):
            for node in nodes:
                self.assertNotIn(node["key"], seen_keys)
                seen_keys.add(node["key"])
                self.assertIn(node["label_key"], translations["sp"])
                self.assertIn(node["label_key"], translations["en"])
                self.assertEqual(node["label"], translations["sp"][node["label_key"]])
                if node.get("children"):
                    self.assertNotIn("vista", node)
                    self.assertNotIn("route_name", node)
                    visit(node["children"])
                    continue
                for field in ("vista", "route_name", "label_key", "label"):
                    self.assertIn(field, node)
                self.assertNotIn(node["vista"], seen_vistas)
                seen_vistas.add(node["vista"])
                try:
                    reverse(node["route_name"])
                except NoReverseMatch as error:
                    self.fail(f"Invalid sidebar route {node['route_name']}: {error}")

        visit(SIDEBAR_MENU)
        self.assertEqual(
            {key: translations["sp"][key] for key in expected_es},
            expected_es,
        )

    def test_access_tree_prunes_branches_from_visible_leaves(self):
        visible = {"access_invite"}
        tree = get_sidebar_access_tree(visible)

        self.assertEqual(tree[0]["key"], "control_acceso")
        self.assertEqual(tree[0]["children"][0]["key"], "usuarios")
        self.assertEqual(tree[0]["children"][0]["children"][0]["key"], "access_invite")
        self.assertEqual(len(tree[0]["children"]), 1)

    def test_deep_tree_visible_leaf_keeps_all_ancestors(self):
        tree = filter_sidebar_tree(self._deep_tree(6), {"deep_leaf"})
        nodes = list(self._walk_nodes(tree))

        self.assertEqual(len(nodes), 8)
        self.assertEqual(nodes[-1]["key"], "deep_leaf")

    def test_deep_tree_hidden_leaf_prunes_all_ancestors(self):
        self.assertEqual(filter_sidebar_tree(self._deep_tree(6), set()), ())

    def test_deep_active_leaf_opens_all_ancestors(self):
        tree = filter_sidebar_tree(
            self._deep_tree(6),
            {"deep_leaf"},
            current_route_name="access_control:usuarios_lista",
        )
        containers = list(self._walk_containers(tree))
        leaf = list(self._walk_nodes(tree))[-1]

        self.assertTrue(leaf["active"])
        self.assertTrue(all(node["open"] for node in containers))
        self.assertEqual(
            [node["collapse_id"] for node in containers],
            ["sidebar-root"] + [f"sidebar-level-{level}" for level in range(1, 7)],
        )

    def test_deep_inactive_branch_remains_closed(self):
        tree = filter_sidebar_tree(
            self._deep_tree(6),
            {"deep_leaf"},
            current_route_name="access_control:empresas_lista",
        )
        self.assertTrue(all(not node["open"] for node in self._walk_containers(tree)))
        self.assertFalse(list(self._walk_nodes(tree))[-1]["active"])

    def test_deep_tree_prunes_unrelated_branch(self):
        branch_a = self._deep_tree(6)[0]["children"][0]
        branch_b = self._deep_tree(4, leaf_key="leaf_b", prefix="branch_b")[0]["children"][0]
        tree = ({
            "key": "root",
            "label_key": "test.root",
            "label": "Root",
            "children": (branch_a, branch_b),
        },)

        filtered = filter_sidebar_tree(tree, {"leaf_b"})
        keys = {node["key"] for node in self._walk_nodes(filtered)}

        self.assertNotIn("level_6", keys)
        self.assertIn("leaf_b", keys)

    def test_tree_supports_mixed_depths(self):
        shallow = {"key": "leaf_a", "vista": "A", "route_name": "access_control:usuarios_lista", "label_key": "test.a", "label": "A"}
        medium = self._deep_tree(4, leaf_key="leaf_b", prefix="medium")[0]["children"][0]
        deep = self._deep_tree(7, leaf_key="leaf_c", prefix="deep")[0]["children"][0]
        tree = ({"key": "root", "label_key": "test.root", "label": "Root", "children": (shallow, medium, deep)},)

        filtered = filter_sidebar_tree(tree, {"leaf_a", "leaf_b", "leaf_c"})
        self.assertEqual({node["key"] for node in self._walk_nodes(filtered)}, {"root", "leaf_a", "leaf_b", "leaf_c", "medium_1", "medium_2", "medium_3", "medium_4", "deep_1", "deep_2", "deep_3", "deep_4", "deep_5", "deep_6", "deep_7"})

    def test_collapse_ids_are_unique_at_depth(self):
        tree = filter_sidebar_tree(self._deep_tree(10), {"deep_leaf"})
        ids = [node["collapse_id"] for node in self._walk_containers(tree)]

        self.assertEqual(len(ids), 11)
        self.assertEqual(len(ids), len(set(ids)))

    def test_deep_tree_preserves_label_keys(self):
        tree = filter_sidebar_tree(self._deep_tree(10), {"deep_leaf"})

        self.assertEqual(
            [node["label_key"] for node in self._walk_nodes(tree)],
            ["test.root"] + [f"test.level_{level}" for level in range(1, 11)] + ["menu.access_control.master_users"],
        )

    def test_recursive_template_renders_deep_tree(self):
        tree = filter_sidebar_tree(self._deep_tree(6), {"deep_leaf"})
        rendered = render_to_string("partials/sidebar_node.html", {"node": tree[0]})

        self.assertEqual(rendered.count('class="collapse menu-dropdown'), 7)
        self.assertIn('data-key="test.level_6"', rendered)
        self.assertIn('data-key="menu.access_control.master_users"', rendered)
        self.assertIn('href="/access-control/usuarios/"', rendered)

    def test_ten_level_tree_has_no_hardcoded_depth_limit(self):
        tree = filter_sidebar_tree(self._deep_tree(10), {"deep_leaf"}, current_route_name="access_control:usuarios_lista")

        self.assertEqual(len(list(self._walk_containers(tree))), 11)
        self.assertTrue(all(node["open"] for node in self._walk_containers(tree)))

    def test_superuser_uses_one_permission_query_and_no_bypass(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])

        with self.assertNumQueries(1):
            visible = get_sidebar_visible_items(self.user, self.empresa_a.id)

        self.assertNotIn("access", visible)
        self.assertEqual(get_sidebar_access_tree(visible), ())

    def test_superuser_v_true_shows_vicmeas_leaf(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self._permission(self.empresa_a, self.dte_dashboard, ver=True)

        visible = get_sidebar_visible_items(self.user, self.empresa_a.id)

        self.assertIn("gestion_dte_index", visible)
        self.assertIn("gestion_dte", visible)

    def test_superuser_v_false_hides_vicmeas_leaf(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self._permission(self.empresa_a, self.dte_dashboard, ver=False)

        visible = get_sidebar_visible_items(self.user, self.empresa_a.id)

        self.assertNotIn("gestion_dte_index", visible)
        self.assertNotIn("gestion_dte", visible)

    def test_superuser_without_permission_hides_vicmeas_leaf(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])

        visible = get_sidebar_visible_items(self.user, self.empresa_a.id)

        self.assertNotIn("gestion_dte_index", visible)

    def test_superuser_only_visible_access_utility_keeps_permissions_branch(self):
        utility, _ = Vista.objects.get_or_create(
            nombre="Control de Acceso - Utilitario de Acceso",
        )
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self._permission(self.empresa_a, utility, ver=True)

        tree = get_sidebar_access_tree(
            get_sidebar_visible_items(self.user, self.empresa_a.id)
        )

        self.assertEqual(tree[0]["key"], "control_acceso")
        self.assertEqual(tree[0]["children"][0]["key"], "permisos")
        self.assertEqual(tree[0]["children"][0]["children"][0]["key"], "access_utility")

    def test_global_item_is_visible_for_authenticated_users_without_ver(self):
        self.assertIn("account_email", get_sidebar_visible_items(self.user, self.empresa_a.id))

        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.assertIn("account_email", get_sidebar_visible_items(self.user, self.empresa_a.id))

    def test_superuser_visibility_changes_by_active_company(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self._permission(self.empresa_a, self.dte_dashboard, ver=True)
        self._permission(self.empresa_b, self.dte_dashboard, ver=False)

        self.assertIn("gestion_dte_index", get_sidebar_visible_items(self.user, self.empresa_a.id))
        self.assertNotIn("gestion_dte_index", get_sidebar_visible_items(self.user, self.empresa_b.id))

    def test_active_leaf_opens_all_access_ancestors(self):
        tree = get_sidebar_access_tree(
            {"access_view_permissions"},
            current_route_name="access_control:permisos_por_vista",
        )
        root = tree[0]

        permissions = next(child for child in root["children"] if child["key"] == "permisos")
        active_leaf = next(
            child for child in permissions["children"]
            if child["key"] == "access_view_permissions"
        )

        self.assertTrue(root["open"])
        self.assertTrue(permissions["open"])
        self.assertTrue(active_leaf["active"])

    def test_access_collapse_ids_are_unique_and_deterministic(self):
        tree = get_sidebar_access_tree(set(SIDEBAR_VIEW_NAMES))

        def containers(nodes):
            for node in nodes:
                if node.get("children"):
                    yield node
                    yield from containers(node["children"])

        nodes = list(containers(tree))
        ids = [node["collapse_id"] for node in nodes]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, ["sidebar-control-acceso", "sidebar-usuarios", "sidebar-permisos"])

    def test_filter_sidebar_tree_supports_arbitrary_depth_without_mutation(self):
        source = (
            {
                "key": "one",
                "children": (
                    {"key": "two", "children": ({"key": "three", "children": ({"key": "leaf"},)},)},
                ),
            },
        )

        filtered = filter_sidebar_tree(source, {"leaf"})

        self.assertEqual(filtered[0]["children"][0]["children"][0]["key"], "three")
        self.assertEqual(source[0]["children"][0]["children"][0].get("open"), None)

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

    def test_superuser_needs_v_for_api_parent_and_child(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self._permission(self.empresa_a, self.api_home, ver=True)

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

    def test_superuser_does_not_see_all_sidebar_items_without_ver_permission(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        visible = get_sidebar_visible_items(self.user, self.empresa_a.id)

        self.assertNotIn("gestion_dte", visible)
        self.assertNotIn("library", visible)
        self.assertNotIn("access", visible)

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
