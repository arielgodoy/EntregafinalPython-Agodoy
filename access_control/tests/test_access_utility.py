from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, PerfilAcceso, UsuarioPerfilEmpresa, Vista
from access_control.services.access_utility import (
    ACCESS_UTILITY_VISTA_NAME,
    apply_additive_permissions,
    get_scope_vistas,
)
from access_control.services.permissions import (
    SIDEBAR_GLOBAL_ITEMS,
    SIDEBAR_GROUPS,
    SIDEBAR_VIEW_NAMES,
    get_sidebar_visible_items,
)


class AccessUtilityTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user(username="actor", password="pass")
        self.target = User.objects.create_user(username="target", password="pass")
        self.inactive_target = User.objects.create_user(
            username="inactive", password="pass", is_active=False
        )
        self.empresa_activa = Empresa.objects.create(codigo="01", descripcion="Activa")
        self.empresa_objetivo = Empresa.objects.create(codigo="02", descripcion="Objetivo")
        self.utilitario, _ = Vista.objects.get_or_create(
            nombre=ACCESS_UTILITY_VISTA_NAME,
            defaults={"route_name": "access_control:utilitario_acceso"},
        )
        self.sidebar_vistas = {
            nombre: Vista.objects.get_or_create(nombre=nombre)[0]
            for nombre in set(SIDEBAR_VIEW_NAMES.values())
            if nombre != ACCESS_UTILITY_VISTA_NAME
        }
        self.api_vista = Vista.objects.get(nombre="APIs - Inicio")
        self.target_validity_vista = next(
            vista for vista in self.sidebar_vistas.values()
            if vista != self.api_vista
        )
        self.gestion_dte_vistas = [
            vista
            for vista in self.sidebar_vistas.values()
            if vista.nombre.startswith("Gestión DTE -")
        ]
        self.global_vista = Vista.objects.filter(nombre=SIDEBAR_VIEW_NAMES["account_email"]).first()
        self.actor_target_permission = Permiso.objects.create(
            usuario=self.actor,
            empresa=self.empresa_activa,
            vista=self.utilitario,
            ingresar=True,
        )
        self.actor_target_permission_b = Permiso.objects.create(
            usuario=self.actor,
            empresa=self.empresa_objetivo,
            vista=self.utilitario,
            modificar=True,
        )
        Permiso.objects.create(
            usuario=self.target,
            empresa=self.empresa_objetivo,
            vista=self.target_validity_vista,
            ingresar=True,
        )
        Permiso.objects.create(
            usuario=self.inactive_target,
            empresa=self.empresa_objetivo,
            vista=self.target_validity_vista,
            ingresar=True,
        )
        self.client.force_login(self.actor)
        session = self.client.session
        session["empresa_id"] = self.empresa_activa.id
        session.save()

    def _url(self):
        return reverse("access_control:utilitario_acceso")

    def _post(self, *, usuario=None, empresa=None, alcance="apis", action="confirm", **flags):
        data = {
            "usuario": (usuario or self.target).id,
            "empresa": (empresa or self.empresa_objetivo).id,
            "alcance": alcance,
            "action": action,
        }
        data.update({field: "on" for field, value in flags.items() if value})
        if flags.get("confirm_sensitive"):
            data["confirm_sensitive"] = "on"
        return self.client.post(self._url(), data)

    def _permission(self, usuario, empresa, vista):
        return Permiso.objects.filter(usuario=usuario, empresa=empresa, vista=vista).first()

    def test_seed_creates_canonical_view_idempotently(self):
        Vista.objects.filter(nombre=ACCESS_UTILITY_VISTA_NAME).delete()
        call_command("seed_vistas")
        call_command("seed_vistas")
        vista = Vista.objects.get(nombre=ACCESS_UTILITY_VISTA_NAME)
        self.assertEqual(vista.route_name, "access_control:utilitario_acceso")
        self.assertEqual(Vista.objects.filter(nombre=ACCESS_UTILITY_VISTA_NAME).count(), 1)

    def test_sidebar_mapping_and_visibility_use_canonical_view(self):
        self.assertIn("access_utility", SIDEBAR_GROUPS["access"])
        self.assertEqual(
            SIDEBAR_VIEW_NAMES["access_utility"],
            ACCESS_UTILITY_VISTA_NAME,
        )
        self.actor_target_permission.ver = True
        self.actor_target_permission.save(update_fields=["ver"])
        visible = get_sidebar_visible_items(self.actor, self.empresa_activa.id)
        self.assertIn("access_utility", visible)
        self.assertIn("access", visible)

    def test_v_false_hides_utility_and_parent(self):
        visible = get_sidebar_visible_items(self.actor, self.empresa_activa.id)
        self.assertNotIn("access_utility", visible)
        self.assertNotIn("access", visible)

    def test_superuser_visibility_does_not_authorize_backend(self):
        self.actor.is_superuser = True
        self.actor.save(update_fields=["is_superuser"])
        self.actor_target_permission.ingresar = False
        self.actor_target_permission_b.modificar = False
        self.actor_target_permission.save(update_fields=["ingresar"])
        self.actor_target_permission_b.save(update_fields=["modificar"])

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 403)
        response = self._post(ver=True)
        self.assertEqual(response.status_code, 403)

    def test_get_without_ingresar_returns_403_without_creating_empty_permission(self):
        self.actor_target_permission.delete()
        before = Permiso.objects.count()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Permiso.objects.count(), before)
        self.assertFalse(
            Permiso.objects.filter(
                usuario=self.actor,
                empresa=self.empresa_activa,
                vista=self.utilitario,
            ).exists()
        )

    def test_get_with_ingresar_returns_dashboard(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UTILITARIO DE ACCESO")
        self.assertContains(response, "Asignar permisos masivos")

    def test_post_without_modificar_in_target_company_returns_403(self):
        self.actor_target_permission_b.delete()
        before = Permiso.objects.count()
        response = self._post(ver=True)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Permiso.objects.count(), before)

    def test_required_fields_and_at_least_one_flag(self):
        response = self.client.post(self._url(), {"action": "preview"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Este campo es obligatorio", status_code=400)

        response = self._post(action="preview")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "al menos un permiso VICMEAS", status_code=400)

    def test_inactive_user_is_rejected(self):
        response = self._post(usuario=self.inactive_target, ver=True)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "inactivo", status_code=400)

    def test_preview_does_not_write_and_recalculates_scope_backend(self):
        before = Permiso.objects.count()
        response = self._post(action="preview", alcance="apis", ver=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Permiso.objects.count(), before)
        self.assertContains(response, "Vistas afectadas")
        self.assertContains(response, "1")

    def test_preview_renders_visible_confirmation_form(self):
        response = self._post(action="preview", alcance="gestion_dte", ver=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Confirmar asignación")
        self.assertContains(response, 'name="action" value="confirm"')
        self.assertContains(response, f'name="empresa" value="{self.empresa_objetivo.id}"')
        self.assertContains(response, f'name="usuario" value="{self.target.id}"')
        self.assertContains(response, 'name="alcance" value="gestion_dte"')
        self.assertContains(response, 'name="ver" value="on"')

    def test_action_missing_returns_explicit_400(self):
        data = {
            "usuario": self.target.id,
            "empresa": self.empresa_objetivo.id,
            "alcance": "apis",
            "ver": "on",
        }
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "acción válida", status_code=400)

    def test_all_scope_with_missing_catalog_returns_clear_400(self):
        Vista.objects.filter(
            nombre__in=["Tareas - Listado", "Configuración - Conexiones MySQL"]
        ).delete()
        before = Permiso.objects.count()
        response = self._post(action="preview", alcance="all", ver=True)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Faltan Vistas catalogadas", status_code=400)
        self.assertEqual(Permiso.objects.count(), before)

    def test_gestion_dte_preview_does_not_write(self):
        before = Permiso.objects.count()
        response = self._post(action="preview", alcance="gestion_dte", ver=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vistas afectadas")
        self.assertEqual(Permiso.objects.count(), before)

    def test_gestion_dte_confirm_writes_selected_flag(self):
        response = self._post(action="confirm", alcance="gestion_dte", ver=True)
        self.assertEqual(response.status_code, 200)
        for vista in self.gestion_dte_vistas:
            permiso = self._permission(self.target, self.empresa_objetivo, vista)
            self.assertIsNotNone(permiso)
            self.assertTrue(permiso.ver)

    def test_library_confirm_updates_seven_sidebar_views_and_preserves_icmeas(self):
        library_vistas = get_scope_vistas("library")
        self.assertEqual(len(library_vistas), 7)
        preserved = Permiso.objects.create(
            usuario=self.target,
            empresa=self.empresa_objetivo,
            vista=library_vistas[0],
            ingresar=True,
            modificar=True,
        )

        response = self._post(action="confirm", alcance="library", ver=True)

        self.assertEqual(response.status_code, 200)
        for vista in library_vistas:
            permiso = self._permission(self.target, self.empresa_objetivo, vista)
            self.assertIsNotNone(permiso)
            self.assertTrue(permiso.ver)
        preserved.refresh_from_db()
        self.assertTrue(preserved.ingresar)
        self.assertTrue(preserved.modificar)
        self.assertFalse(preserved.crear)
        self.assertFalse(preserved.eliminar)
        self.assertFalse(preserved.autorizar)
        self.assertFalse(preserved.supervisor)

    def test_api_scope_resolves_only_api_view(self):
        vistas = get_scope_vistas("apis")
        self.assertEqual([vista.nombre for vista in vistas], ["APIs - Inicio"])

    def test_gestion_dte_scope_resolves_only_its_children(self):
        vistas = get_scope_vistas("gestion_dte")
        self.assertEqual(
            {vista.id for vista in vistas},
            {vista.id for vista in self.gestion_dte_vistas},
        )

    def test_all_scope_excludes_globals_and_parents(self):
        vistas = get_scope_vistas("all")
        names = {vista.nombre for vista in vistas}
        expected_children = {
            SIDEBAR_VIEW_NAMES[item_key]
            for children in SIDEBAR_GROUPS.values()
            for item_key in children
            if item_key not in SIDEBAR_GLOBAL_ITEMS
            and SIDEBAR_VIEW_NAMES[item_key]
            not in {
                SIDEBAR_VIEW_NAMES[global_item]
                for global_item in SIDEBAR_GLOBAL_ITEMS
                if global_item in SIDEBAR_VIEW_NAMES
            }
        }
        self.assertEqual(names, expected_children)
        self.assertNotIn(self.global_vista.nombre, names)
        self.assertNotIn("Control de Acceso", names)
        self.assertNotIn("APIs", names)

    def test_group_operation_does_not_create_parent_or_other_group_permissions(self):
        response = self._post(alcance="gestion_dte", ver=True)
        self.assertEqual(response.status_code, 200)
        for vista in self.gestion_dte_vistas:
            self.assertTrue(self._permission(self.target, self.empresa_objetivo, vista).ver)
        self.assertFalse(
            Permiso.objects.filter(
                usuario=self.target,
                empresa=self.empresa_objetivo,
                vista=self.api_vista,
            ).exists()
        )
        self.assertFalse(
            Permiso.objects.filter(
                usuario=self.target,
                empresa=self.empresa_objetivo,
                vista__nombre__in=["Control de Acceso", "APIs"],
            ).exists()
        )

    def test_v_only_creates_selected_flag_and_rest_false(self):
        response = self._post(ver=True)
        self.assertEqual(response.status_code, 200)
        permiso = self._permission(self.target, self.empresa_objetivo, self.api_vista)
        self.assertTrue(permiso.ver)
        self.assertFalse(permiso.ingresar)
        self.assertFalse(permiso.crear)
        self.assertFalse(permiso.modificar)
        self.assertFalse(permiso.eliminar)
        self.assertFalse(permiso.autorizar)
        self.assertFalse(permiso.supervisor)

    def test_v_and_i_create_both_flags(self):
        response = self._post(ver=True, ingresar=True)
        self.assertEqual(response.status_code, 200)
        permiso = self._permission(self.target, self.empresa_objetivo, self.api_vista)
        self.assertTrue(permiso.ver)
        self.assertTrue(permiso.ingresar)
        self.assertFalse(permiso.modificar)

    def test_existing_permission_preserves_unselected_flags_and_never_resets_true(self):
        permiso = Permiso.objects.create(
            usuario=self.target,
            empresa=self.empresa_objetivo,
            vista=self.api_vista,
            ingresar=True,
            modificar=True,
            autorizar=True,
        )
        response = self._post(ver=True)
        self.assertEqual(response.status_code, 200)
        permiso.refresh_from_db()
        self.assertTrue(permiso.ver)
        self.assertTrue(permiso.ingresar)
        self.assertTrue(permiso.modificar)
        self.assertTrue(permiso.autorizar)
        self.assertFalse(permiso.crear)

    def test_other_company_is_untouched(self):
        other = Permiso.objects.create(
            usuario=self.target,
            empresa=self.empresa_activa,
            vista=self.api_vista,
            ingresar=True,
        )
        response = self._post(ver=True)
        self.assertEqual(response.status_code, 200)
        other.refresh_from_db()
        self.assertFalse(other.ver)
        self.assertTrue(other.ingresar)

    def test_a_requires_supervisor_and_confirmation(self):
        response = self._post(autorizar=True)
        self.assertEqual(response.status_code, 403)
        self.actor_target_permission_b.supervisor = True
        self.actor_target_permission_b.save(update_fields=["supervisor"])
        response = self._post(autorizar=True)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "permisos sensibles", status_code=400)
        response = self._post(autorizar=True, confirm_sensitive=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self._permission(self.target, self.empresa_objetivo, self.api_vista).autorizar)

    def test_s_requires_supervisor(self):
        response = self._post(supervisor=True)
        self.assertEqual(response.status_code, 403)
        self.actor_target_permission_b.supervisor = True
        self.actor_target_permission_b.save(update_fields=["supervisor"])
        response = self._post(supervisor=True, confirm_sensitive=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self._permission(self.target, self.empresa_objetivo, self.api_vista).supervisor)

    def test_transaction_rolls_back_all_created_permissions_on_error(self):
        vistas = self.gestion_dte_vistas[:2]
        original_create = Permiso.objects.create
        calls = {"count": 0}

        def create_then_fail(**kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("forced rollback")
            return original_create(**kwargs)

        with self.assertRaises(RuntimeError):
            with patch.object(Permiso.objects, "create", side_effect=create_then_fail):
                apply_additive_permissions(
                    usuario=self.target,
                    empresa=self.empresa_objetivo,
                    vistas=vistas,
                    selected_fields=("ver",),
                )
        self.assertFalse(Permiso.objects.filter(
            usuario=self.target,
            empresa=self.empresa_objetivo,
            vista__in=vistas,
        ).exists())

    def test_result_summary_reports_created_updated_and_unchanged(self):
        response = self._post(ver=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Permisos creados: 1")
        response = self._post(ver=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sin cambios: 1")

    def test_valid_users_are_active_union_of_assignments_and_permissions(self):
        profile = PerfilAcceso.objects.create(nombre="Perfil")
        assigned = User.objects.create_user(username="assigned", password="pass")
        UsuarioPerfilEmpresa.objects.create(
            usuario=assigned,
            empresa=self.empresa_objetivo,
            perfil=profile,
            asignado_por=self.actor,
        )
        from access_control.services.permissions import get_valid_users_for_empresa

        users = get_valid_users_for_empresa(self.empresa_objetivo, active_only=True)
        self.assertIn(self.target, users)
        self.assertIn(assigned, users)
        self.assertNotIn(self.inactive_target, users)
