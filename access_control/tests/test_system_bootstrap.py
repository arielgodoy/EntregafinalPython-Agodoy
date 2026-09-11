from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.db import transaction
from django.test import TestCase

from access_control.models import Empresa, Permiso, Vista
from access_control.services.permissions import SIDEBAR_GROUPS, SIDEBAR_VIEW_NAMES, VICMEAS_FIELDS
from access_control.services.system_bootstrap import (
    BootstrapInconsistency,
    initialize_system_for_user,
)


class SystemBootstrapTests(TestCase):
    topbar_view_name = "Notificaciones - Topbar"

    def test_empty_installation_creates_base_catalog_user_and_complete_permissions(self):
        initialize_system_for_user(username="administrador", password="Strong-pass-123")

        self.assertEqual(Empresa.objects.filter(codigo="00").count(), 1)
        expected_names = [SIDEBAR_VIEW_NAMES[key] for key in SIDEBAR_GROUPS["access"]]
        self.assertTrue(set(expected_names).issubset(set(Vista.objects.values_list("nombre", flat=True))))
        user = User.objects.get(username="administrador")
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        permisos = Permiso.objects.filter(usuario=user, vista__nombre__in=expected_names)
        self.assertEqual(permisos.count(), len(expected_names))
        for permiso in permisos:
            self.assertTrue(all(getattr(permiso, field) for field in VICMEAS_FIELDS))
        topbar = Vista.objects.get(nombre=self.topbar_view_name)
        self.assertEqual(topbar.route_name, "notificaciones:topbar")
        self.assertTrue(
            Permiso.objects.filter(
                usuario=user,
                empresa__codigo="00",
                vista=topbar,
                ingresar=True,
            ).exists()
        )

    def test_topbar_is_required_system_and_legacy_route_stays_out_of_ambiguous(self):
        topbar = Vista.objects.create(nombre=self.topbar_view_name)
        ambiguous = Vista.objects.create(nombre="Sistema sin ruta")
        application = Vista.objects.create(
            nombre="Biblioteca negocio",
            route_name="biblioteca:listar_propiedades",
        )

        summary = initialize_system_for_user(username="admin", password="Strong-pass-123")

        self.assertIsNone(topbar.refresh_from_db())
        self.assertIsNone(topbar.route_name)
        self.assertIn(self.topbar_view_name, summary.bootstrap_view_names)
        self.assertNotIn(self.topbar_view_name, summary.ambiguous_view_names)
        self.assertIn(ambiguous.nombre, summary.ambiguous_view_names)
        self.assertIn(application.nombre, summary.application_view_names)

    def test_existing_user_without_topbar_permission_receives_only_missing_permission(self):
        user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="old-password",
        )
        initialize_system_for_user(username="admin")
        topbar = Vista.objects.get(nombre=self.topbar_view_name)
        Permiso.objects.filter(usuario=user, vista=topbar).delete()
        permission_count = Permiso.objects.filter(usuario=user).count()

        summary = initialize_system_for_user(username="admin")

        user.refresh_from_db()
        permiso = Permiso.objects.get(
            usuario=user,
            empresa__codigo="00",
            vista=topbar,
        )
        self.assertTrue(all(getattr(permiso, field) for field in VICMEAS_FIELDS))
        self.assertEqual(summary.permissions_created, 1)
        self.assertEqual(Permiso.objects.filter(usuario=user).count(), permission_count + 1)
        self.assertTrue(user.check_password("old-password"))

    def test_existing_complete_topbar_permission_is_unchanged(self):
        initialize_system_for_user(username="admin", password="Strong-pass-123")
        user = User.objects.get(username="admin")
        before_count = Permiso.objects.filter(usuario=user).count()

        summary = initialize_system_for_user(username="admin")

        self.assertEqual(summary.permissions_created, 0)
        self.assertEqual(summary.permissions_updated, 0)
        self.assertEqual(summary.permissions_unchanged, summary.permissions_processed)
        self.assertEqual(Permiso.objects.filter(usuario=user).count(), before_count)

    def test_dry_run_reports_missing_topbar_permission_without_writing(self):
        initialize_system_for_user(username="admin", password="Strong-pass-123")
        user = User.objects.get(username="admin")
        topbar = Vista.objects.get(nombre=self.topbar_view_name)
        Permiso.objects.filter(usuario=user, vista=topbar).delete()
        counts_before = (
            Empresa.objects.count(),
            Vista.objects.count(),
            User.objects.count(),
            Permiso.objects.count(),
        )

        summary = initialize_system_for_user(username="admin", dry_run=True)

        self.assertEqual(summary.permissions_created, 1)
        self.assertEqual(
            (
                Empresa.objects.count(),
                Vista.objects.count(),
                User.objects.count(),
                Permiso.objects.count(),
            ),
            counts_before,
        )
        self.assertFalse(Permiso.objects.filter(usuario=user, vista=topbar).exists())

    def test_topbar_bootstrap_does_not_modify_other_company_or_user(self):
        other_user = User.objects.create_superuser(
            username="other",
            email="other@example.com",
            password="other-password",
        )
        other_company = Empresa.objects.create(codigo="01", descripcion="Otra")
        topbar = Vista.objects.create(nombre=self.topbar_view_name)
        other_permission = Permiso.objects.create(
            usuario=other_user,
            empresa=other_company,
            vista=topbar,
            ver=False,
            ingresar=False,
        )

        initialize_system_for_user(username="admin", password="Strong-pass-123")

        other_permission.refresh_from_db()
        self.assertFalse(other_permission.ver)
        self.assertFalse(other_permission.ingresar)
        self.assertEqual(
            Permiso.objects.filter(usuario=other_user, empresa=other_company).count(),
            1,
        )

    def test_second_execution_is_idempotent_for_topbar(self):
        initialize_system_for_user(username="admin", password="Strong-pass-123")
        first_count = Vista.objects.filter(nombre=self.topbar_view_name).count()

        summary = initialize_system_for_user(username="admin")

        self.assertEqual(Vista.objects.filter(nombre=self.topbar_view_name).count(), first_count)
        self.assertEqual(summary.permissions_created, 0)
        self.assertEqual(summary.permissions_updated, 0)

    def test_repeated_and_multiple_users_reuse_company_and_views(self):
        initialize_system_for_user(username="administrador", password="Strong-pass-123")
        initialize_system_for_user(username="administrador")
        initialize_system_for_user(username="ariel", password="Strong-pass-123")
        initialize_system_for_user(username="soporte1", password="Strong-pass-123")

        self.assertEqual(Empresa.objects.filter(codigo="00").count(), 1)
        expected_names = [SIDEBAR_VIEW_NAMES[key] for key in SIDEBAR_GROUPS["access"]]
        self.assertEqual(Vista.objects.filter(nombre__in=expected_names).count(), len(expected_names))
        self.assertEqual(User.objects.filter(is_superuser=True).count(), 3)
        self.assertEqual(
            Permiso.objects.filter(usuario__is_superuser=True, vista__nombre__in=expected_names).count(),
            3 * len(expected_names),
        )

    def test_application_views_are_not_added_to_bootstrap_catalog(self):
        application_names = {
            name for key, name in SIDEBAR_VIEW_NAMES.items() if key not in SIDEBAR_GROUPS["access"]
        }
        before = set(Vista.objects.filter(nombre__in=application_names).values_list("nombre", flat=True))
        initialize_system_for_user(username="admin", password="Strong-pass-123")
        after = set(Vista.objects.filter(nombre__in=application_names).values_list("nombre", flat=True))
        self.assertEqual(after, before)

    def test_namespaced_system_views_are_included_and_application_views_excluded(self):
        system_view = Vista.objects.create(
            nombre="Sistema soporte", route_name="notificaciones:mis_notificaciones"
        )
        application_view = Vista.objects.create(
            nombre="Biblioteca negocio", route_name="biblioteca:listar_propiedades"
        )

        summary = initialize_system_for_user(username="admin", password="Strong-pass-123")

        user = User.objects.get(username="admin")
        self.assertTrue(Permiso.objects.filter(usuario=user, vista=system_view, ver=True).exists())
        self.assertFalse(Permiso.objects.filter(usuario=user, vista=application_view).exists())
        self.assertIn(application_view.nombre, summary.application_view_names)
        self.assertIn(system_view, Vista.objects.filter(id__in=Permiso.objects.filter(usuario=user).values("vista_id")))
        self.assertGreaterEqual(summary.system_views_count, 1)

    def test_null_and_unnamespaced_views_are_reported_ambiguous_and_omitted(self):
        null_view = Vista.objects.create(nombre="Sistema sin ruta")
        unnamespaced_view = Vista.objects.create(nombre="Chat legado", route_name="chat_inbox")

        summary = initialize_system_for_user(username="admin", password="Strong-pass-123")

        user = User.objects.get(username="admin")
        self.assertIn(null_view.nombre, summary.ambiguous_view_names)
        self.assertIn(unnamespaced_view.nombre, summary.ambiguous_view_names)
        self.assertFalse(Permiso.objects.filter(usuario=user, vista=null_view).exists())
        self.assertFalse(Permiso.objects.filter(usuario=user, vista=unnamespaced_view).exists())

    def test_url_namespace_alias_is_classified_by_declaring_application(self):
        application_view = Vista.objects.create(
            nombre="Gestion DTE catalogada", route_name="gestion_dte:index"
        )

        summary = initialize_system_for_user(username="admin", password="Strong-pass-123")

        user = User.objects.get(username="admin")
        self.assertIn(application_view.nombre, summary.application_view_names)
        self.assertFalse(Permiso.objects.filter(usuario=user, vista=application_view).exists())

    def test_existing_users_and_permissions_are_additive(self):
        user = User.objects.create_user(username="admin", password="old-password")
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=["is_staff", "is_superuser"])
        empresa = Empresa.objects.create(codigo="00", descripcion="Original")
        vista = Vista.objects.create(nombre=SIDEBAR_VIEW_NAMES[SIDEBAR_GROUPS["access"][0]])
        Permiso.objects.create(usuario=user, empresa=empresa, vista=vista, ver=True, ingresar=True)

        summary = initialize_system_for_user(username="admin")

        empresa.refresh_from_db()
        permiso = Permiso.objects.get(usuario=user, empresa=empresa, vista=vista)
        self.assertEqual(empresa.descripcion, "Original")
        self.assertTrue(permiso.ver)
        self.assertTrue(permiso.ingresar)
        self.assertTrue(all(getattr(permiso, field) for field in VICMEAS_FIELDS))
        self.assertTrue(summary.user_reused)

    def test_existing_normal_user_is_blocked(self):
        User.objects.create_user(username="normal", password="password")
        with self.assertRaises(BootstrapInconsistency):
            initialize_system_for_user(username="normal", password="unused")

    def test_existing_superuser_without_staff_is_blocked(self):
        User.objects.create_user(username="inconsistent", password="password", is_superuser=True)
        with self.assertRaises(BootstrapInconsistency):
            initialize_system_for_user(username="inconsistent")

    def test_existing_superuser_command_reuses_without_credentials(self):
        user = User.objects.create_superuser(username="existing", email="existing@example.com", password="old-password")
        output = StringIO()
        with patch("builtins.input", side_effect=AssertionError), patch("getpass.getpass", side_effect=AssertionError):
            call_command("inicializar_sistema", "existing", stdout=output)
        user.refresh_from_db()
        self.assertTrue(user.check_password("old-password"))
        self.assertIn("reutilizado", output.getvalue())

    def test_duplicate_base_company_is_reported(self):
        with patch("access_control.services.system_bootstrap.Empresa.objects.filter") as filter_mock:
            filter_mock.return_value.count.return_value = 2
            with self.assertRaises(BootstrapInconsistency):
                initialize_system_for_user(username="admin", password="Strong-pass-123")

    def test_internal_failure_rolls_back_all_bootstrap_writes(self):
        with patch(
            "access_control.services.system_bootstrap.ensure_system_vistas",
            side_effect=RuntimeError("simulated failure"),
        ):
            with self.assertRaises(RuntimeError):
                initialize_system_for_user(username="rollback", password="Strong-pass-123")
        self.assertFalse(Empresa.objects.filter(codigo="00").exists())
        self.assertFalse(User.objects.filter(username="rollback").exists())

    def test_dry_run_does_not_write_or_prompt_password(self):
        output = StringIO()
        initial_counts = (Empresa.objects.count(), Vista.objects.count(), User.objects.count(), Permiso.objects.count())
        with patch("builtins.input", side_effect=AssertionError), patch("getpass.getpass", side_effect=AssertionError):
            call_command("inicializar_sistema", "pruebaadmin", "--dry-run", stdout=output)
        self.assertIn("DRY-RUN", output.getvalue())
        self.assertEqual(
            (Empresa.objects.count(), Vista.objects.count(), User.objects.count(), Permiso.objects.count()),
            initial_counts,
        )

    def test_password_confirmation_and_password_are_not_output(self):
        output = StringIO()
        with patch("builtins.input", side_effect=["admin@example.com", "Nombre", "Apellido"]), patch(
            "getpass.getpass", side_effect=["Secret-pass-123", "Secret-pass-123"]
        ):
            call_command("inicializar_sistema", "admin", stdout=output)
        self.assertNotIn("Secret-pass-123", output.getvalue())

    def test_password_confirmation_mismatch_does_not_write(self):
        output = StringIO()
        with patch("builtins.input", side_effect=["admin@example.com", "Nombre", "Apellido"]), patch(
            "getpass.getpass", side_effect=["Secret-pass-123", "different-password"]
        ):
            with self.assertRaises(CommandError):
                call_command("inicializar_sistema", "admin", stdout=output)
        self.assertFalse(User.objects.filter(username="admin").exists())

    def test_bootstrap_does_not_modify_other_company_or_user_permissions(self):
        other_user = User.objects.create_user(username="other", password="password")
        other_company = Empresa.objects.create(codigo="01", descripcion="Otra")
        other_view = Vista.objects.create(nombre="Vista externa")
        permission = Permiso.objects.create(
            usuario=other_user, empresa=other_company, vista=other_view, ingresar=True
        )
        initialize_system_for_user(username="admin", password="Strong-pass-123")
        permission.refresh_from_db()
        self.assertTrue(permission.ingresar)
        self.assertFalse(permission.crear)
        self.assertEqual(Permiso.objects.filter(usuario=other_user, empresa=other_company).count(), 1)

    def test_transaction_rolls_back_on_failure(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                initialize_system_for_user(username="rollback", password="Strong-pass-123")
                raise RuntimeError("test rollback")
        self.assertFalse(User.objects.filter(username="rollback").exists())
        self.assertFalse(Empresa.objects.filter(codigo="00").exists())