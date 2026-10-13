import ast
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

from django import forms
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.migrations import (
    AddField,
    AddConstraint,
    AlterField,
    CreateModel,
    DeleteModel,
    RemoveField,
    RunPython,
    RunSQL,
)
from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from evaluaciones.forms import EvaluacionConnectionRoleForm
from evaluaciones.models import EvaluacionConnectionRole
from evaluaciones.services import connection_roles
from settings.models import SettingsMySQLConnection
from settings.services.mysql_connections import MySQLConnectionOpenError


def _choice_values(form, field_name):
    field = form.fields[field_name]
    if not isinstance(field, forms.ChoiceField):
        raise AssertionError(f"{field_name} is not a ChoiceField")
    return {choice[0] for choice in field.choices if choice[0]}


class EvaluacionConnectionRoleModelTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 1")
        self.connection = self._create_connection()

    def _create_connection(self, **overrides):
        values = {
            "empresa": self.empresa,
            "nombre_logico": f"mysql-{SettingsMySQLConnection.objects.count()}",
            "engine": SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
            "host": "127.0.0.1",
            "port": 3306,
            "user": "user",
            "password": "not-used-in-tests",
            "db_name": "legacy_db",
            "is_active": True,
        }
        values.update(overrides)
        return SettingsMySQLConnection.objects.create(**values)

    def test_exactly_four_global_roles_are_declared(self):
        self.assertEqual(
            {choice[0] for choice in EvaluacionConnectionRole.ROLE_CHOICES},
            {
                "BASE_EVALUACIONES",
                "AUDITORIA_EVALUACIONES",
                "LEGACY_MYSQL",
                "LEGACY_AUDITORIA",
            },
        )
        self.assertNotIn("empresa", {
            field.name for field in EvaluacionConnectionRole._meta.fields
        })

    def test_roles_can_share_a_settings_connection(self):
        base = EvaluacionConnectionRole(
            role="BASE_EVALUACIONES",
            mysql_connection=self.connection,
            database_name="eval_operacional",
        )
        audit = EvaluacionConnectionRole(
            role="AUDITORIA_EVALUACIONES",
            mysql_connection=self.connection,
            database_name="eval_auditoria",
        )

        base.full_clean()
        audit.full_clean()
        base.save()
        audit.save()
        self.assertEqual(base.mysql_connection, audit.mysql_connection)

    def test_role_is_globally_unique(self):
        EvaluacionConnectionRole.objects.create(
            role="BASE_EVALUACIONES",
            mysql_connection=self.connection,
            database_name="eval_operacional",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                EvaluacionConnectionRole.objects.create(
                    role="BASE_EVALUACIONES",
                    mysql_connection=self.connection,
                    database_name="eval_operacional_2",
                )

    def test_invalid_role_is_rejected(self):
        role = EvaluacionConnectionRole(
            role="TAREAS",
            mysql_connection=self.connection,
            database_name="eval_operacional",
        )

        with self.assertRaises(ValidationError):
            role.full_clean()

    def test_connection_is_required_and_must_be_active(self):
        missing = EvaluacionConnectionRole(
            role="BASE_EVALUACIONES",
            database_name="eval_operacional",
        )
        with self.assertRaises(ValidationError):
            missing.full_clean()

        self.connection.is_active = False
        inactive = EvaluacionConnectionRole(
            role="LEGACY_MYSQL",
            mysql_connection=self.connection,
        )
        with self.assertRaises(ValidationError):
            inactive.full_clean()

    def test_only_supported_sql_engines_are_allowed(self):
        remote = self._create_connection(
            nombre_logico="remote",
            engine=SettingsMySQLConnection.ENGINE_API_REMOTA,
        )
        role = EvaluacionConnectionRole(
            role="LEGACY_MYSQL",
            mysql_connection=remote,
        )

        with self.assertRaises(ValidationError):
            role.full_clean()

    def test_django_source_is_valid_for_base_and_audit_roles(self):
        for role_name in (
            "BASE_EVALUACIONES",
            "AUDITORIA_EVALUACIONES",
        ):
            with self.subTest(role=role_name):
                role = EvaluacionConnectionRole(
                    role=role_name,
                    source_type=EvaluacionConnectionRole.SOURCE_DJANGO,
                    django_alias="default",
                    database_name="must_be_cleared",
                )

                role.full_clean()

                self.assertIsNone(role.mysql_connection)
                self.assertIsNone(role.database_name)

    def test_legacy_roles_reject_django_source(self):
        for role_name in (
            "LEGACY_MYSQL",
            "LEGACY_AUDITORIA",
        ):
            with self.subTest(role=role_name):
                role = EvaluacionConnectionRole(
                    role=role_name,
                    source_type=EvaluacionConnectionRole.SOURCE_DJANGO,
                    django_alias="default",
                )

                with self.assertRaises(ValidationError):
                    role.full_clean()

    def test_django_source_rejects_unknown_and_legacy_aliases(self):
        for alias in ("not_configured", "dinamica"):
            with self.subTest(alias=alias):
                role = EvaluacionConnectionRole(
                    role="BASE_EVALUACIONES",
                    source_type=EvaluacionConnectionRole.SOURCE_DJANGO,
                    django_alias=alias,
                )

                with self.assertRaises(ValidationError) as raised:
                    role.full_clean()

                self.assertIn("django_alias", raised.exception.message_dict)

    def test_django_and_mysql_sources_are_mutually_exclusive(self):
        role = EvaluacionConnectionRole(
            role="BASE_EVALUACIONES",
            source_type=EvaluacionConnectionRole.SOURCE_DJANGO,
            django_alias="default",
            mysql_connection=self.connection,
        )

        with self.assertRaises(ValidationError) as raised:
            role.full_clean()

        self.assertIn("mysql_connection", raised.exception.message_dict)

    def test_database_name_is_validated_and_legacy_roles_cannot_override_it(self):
        for database_name in ("bad-name", "1database", "db name", "x" * 65):
            with self.subTest(database_name=database_name):
                role = EvaluacionConnectionRole(
                    role="AUDITORIA_EVALUACIONES",
                    mysql_connection=self.connection,
                    database_name=database_name,
                )
                with self.assertRaises(ValidationError):
                    role.full_clean()

        legacy = EvaluacionConnectionRole(
            role="LEGACY_AUDITORIA",
            mysql_connection=self.connection,
            database_name="not-the-settings-db",
        )
        with self.assertRaises(ValidationError):
            legacy.full_clean()


class EvaluacionesConnectionMigrationTests(SimpleTestCase):
    def test_incremental_migration_preserves_mysql_fields_without_data_operations(self):
        migration_modules = dict(settings.MIGRATION_MODULES)
        migration_modules.pop("evaluaciones", None)
        migration_modules["evaluaciones"] = "evaluaciones.migrations"
        with override_settings(MIGRATION_MODULES=migration_modules):
            loader = MigrationLoader(None)

        migration = loader.disk_migrations[
            (
                "evaluaciones",
                "0007_remove_evaluacionconnectionrole_eval_conn_role_source_chk_and_more",
            )
        ]
        operation_types = tuple(
            isinstance(
                operation,
                (CreateModel, DeleteModel, RemoveField, RunPython, RunSQL),
            )
            for operation in migration.operations
        )

        self.assertIn(
            ("evaluaciones", "0006_evaluacionconnectionrole"),
            migration.dependencies,
        )
        self.assertIn(
            ("settings", "0007_settingsmysqlconnection"),
            migration.dependencies,
        )
        self.assertNotIn(
            ("settings", "0008_userpreferences_vista_inicial"),
            migration.dependencies,
        )
        self.assertFalse(any(operation_types))
        self.assertEqual(
            sum(isinstance(operation, AddConstraint) for operation in migration.operations),
            2,
        )
        self.assertEqual(
            {
                operation.name
                for operation in migration.operations
                if isinstance(operation, (AddField, AlterField))
            },
            {"django_alias", "source_type"},
        )
        self.assertTrue(
            all(
                getattr(operation, "model_name", None)
                == "evaluacionconnectionrole"
                for operation in migration.operations
            )
        )


class EvaluacionesConnectionResolverTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 1")
        self.connection = SettingsMySQLConnection.objects.create(
            empresa=self.empresa,
            nombre_logico="eval-central",
            engine=SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
            host="127.0.0.1",
            port=3306,
            user="user",
            password="not-used-in-tests",
            db_name="legacy_database",
            is_active=True,
        )

    def _create_role(
        self,
        role,
        database_name=None,
        *,
        source_type=EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG,
        django_alias=None,
    ):
        return EvaluacionConnectionRole.objects.create(
            role=role,
            source_type=source_type,
            django_alias=django_alias,
            mysql_connection=(
                self.connection
                if source_type == EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG
                else None
            ),
            database_name=database_name,
        )

    def test_each_role_resolves_to_the_configured_database(self):
        expected = {
            "BASE_EVALUACIONES": "evaluaciones",
            "AUDITORIA_EVALUACIONES": "evaluaciones_auditoria",
            "LEGACY_MYSQL": "legacy_database",
            "LEGACY_AUDITORIA": "legacy_database",
        }
        for role, database_name in expected.items():
            with self.subTest(role=role):
                self._create_role(
                    role,
                    database_name
                    if role in EvaluacionConnectionRole.DATABASE_CONFIGURABLE_ROLES
                    else None,
                )
                context = connection_roles.resolve_operational_backend(role)
                self.assertEqual(context.logical_role, role)
                self.assertEqual(
                    context.backend_type,
                    EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG,
                )
                self.assertEqual(context.database_name, database_name)
                resolved_connection = context.mysql_connection
                self.assertIsNotNone(resolved_connection)
                self.assertEqual(resolved_connection, self.connection)
                self.assertIsNone(context.django_alias)
                self.assertFalse(hasattr(context, "password"))

    def test_database_override_does_not_mutate_settings_configuration(self):
        self._create_role("BASE_EVALUACIONES", "evaluaciones")

        context = connection_roles.resolve_operational_backend("BASE_EVALUACIONES")
        self.connection.refresh_from_db()

        self.assertEqual(context.database_name, "evaluaciones")
        self.assertEqual(self.connection.db_name, "legacy_database")

    def test_django_alias_resolution_is_explicit_and_not_defaulted(self):
        self._create_role(
            "BASE_EVALUACIONES",
            source_type=EvaluacionConnectionRole.SOURCE_DJANGO,
            django_alias="reporting",
        )
        catalog = (
            {
                "alias": "reporting",
                "vendor": "postgresql",
                "classification": "SYSTEM",
            },
        )

        with patch(
            "evaluaciones.services.connection_roles.get_system_database_catalog",
            return_value=catalog,
        ):
            context = connection_roles.resolve_operational_backend(
                "BASE_EVALUACIONES"
            )

        self.assertEqual(context.backend_type, "DJANGO")
        self.assertEqual(context.django_alias, "reporting")
        self.assertEqual(context.vendor, "postgresql")
        self.assertIsNone(context.mysql_connection)
        self.assertIsNone(context.database_name)

    def test_unknown_and_legacy_aliases_fail_closed(self):
        for alias in ("not_configured", "dinamica"):
            with self.subTest(alias=alias):
                self._create_role(
                    "BASE_EVALUACIONES",
                    source_type=EvaluacionConnectionRole.SOURCE_DJANGO,
                    django_alias=alias,
                )
                with patch(
                    "evaluaciones.services.connection_roles.get_system_database_catalog",
                    return_value=(),
                ):
                    with self.assertRaises(
                        connection_roles.EvaluacionesConnectionAliasUnavailableError
                    ):
                        connection_roles.resolve_operational_backend(
                            "BASE_EVALUACIONES"
                        )
                EvaluacionConnectionRole.objects.filter(
                    role="BASE_EVALUACIONES"
                ).delete()

    def test_missing_or_unknown_roles_fail_without_fallback(self):
        with self.assertRaises(
            connection_roles.EvaluacionesConnectionRoleNotFoundError
        ):
            connection_roles.resolve_operational_backend("BASE_EVALUACIONES")
        with self.assertRaises(
            connection_roles.EvaluacionesConnectionRoleNotFoundError
        ):
            connection_roles.resolve_operational_backend("default")

    def test_status_does_not_open_physical_connections(self):
        self._create_role("BASE_EVALUACIONES", "evaluaciones")

        with patch(
            "evaluaciones.services.connection_roles.open_mysql_connection"
        ) as open_connection:
            status = connection_roles.get_evaluaciones_connection_status()

        self.assertEqual(status["roles"][0]["status"], "configured")
        self.assertEqual(status["missing_roles"], [
            "AUDITORIA_EVALUACIONES",
            "LEGACY_MYSQL",
            "LEGACY_AUDITORIA",
        ])
        open_connection.assert_not_called()

    def test_django_status_does_not_open_physical_connections(self):
        self._create_role(
            "BASE_EVALUACIONES",
            source_type=EvaluacionConnectionRole.SOURCE_DJANGO,
            django_alias="reporting",
        )
        catalog = (
            {
                "alias": "reporting",
                "vendor": "sqlite",
                "classification": "SYSTEM",
            },
        )

        with patch(
            "evaluaciones.services.connection_roles.get_system_database_catalog",
            return_value=catalog,
        ), patch(
            "evaluaciones.services.connection_roles.open_mysql_connection"
        ) as open_mysql:
            status = connection_roles.get_evaluaciones_connection_status()

        self.assertEqual(status["roles"][0]["status"], "configured")
        self.assertEqual(status["roles"][0]["metadata"]["alias"], "reporting")
        open_mysql.assert_not_called()

    def test_django_open_wrapper_uses_only_the_selected_alias(self):
        self._create_role(
            "BASE_EVALUACIONES",
            source_type=EvaluacionConnectionRole.SOURCE_DJANGO,
            django_alias="reporting",
        )
        catalog = (
            {
                "alias": "reporting",
                "vendor": "sqlite",
                "classification": "SYSTEM",
            },
        )
        opened_connection = object()

        with patch(
            "evaluaciones.services.connection_roles.get_system_database_catalog",
            return_value=catalog,
        ), patch(
            "evaluaciones.services.connection_roles.connections"
        ) as django_connections, patch(
            "evaluaciones.services.connection_roles.open_mysql_connection"
        ) as open_mysql:
            django_connections.__getitem__.return_value = opened_connection
            with connection_roles.open_evaluaciones_connection(
                "BASE_EVALUACIONES"
            ) as actual:
                self.assertIs(actual, opened_connection)

        django_connections.__getitem__.assert_called_once_with("reporting")
        open_mysql.assert_not_called()

    def test_inactive_connection_is_reported_invalid(self):
        role = self._create_role("LEGACY_MYSQL")
        self.connection.is_active = False
        self.connection.save(update_fields=("is_active",))

        status = connection_roles.get_evaluaciones_connection_status()

        self.assertIn("LEGACY_MYSQL", status["invalid_roles"])

    def test_open_wrapper_delegates_to_settings_context_manager(self):
        role = self._create_role("BASE_EVALUACIONES", "evaluaciones")
        opened = object()
        with patch(
            "evaluaciones.services.connection_roles.open_mysql_connection",
            return_value=nullcontext(opened),
        ) as open_connection:
            with connection_roles.open_evaluaciones_connection(
                "BASE_EVALUACIONES"
            ) as actual:
                self.assertIs(actual, opened)

        open_connection.assert_called_once_with(
            role.mysql_connection,
            database_name="evaluaciones",
        )

    def test_connection_role_form_offers_sources_only_for_database_roles(self):
        base_form = EvaluacionConnectionRoleForm(
            instance=EvaluacionConnectionRole(role="BASE_EVALUACIONES"),
            role="BASE_EVALUACIONES",
        )
        audit_form = EvaluacionConnectionRoleForm(
            instance=EvaluacionConnectionRole(role="AUDITORIA_EVALUACIONES"),
            role="AUDITORIA_EVALUACIONES",
        )
        legacy_form = EvaluacionConnectionRoleForm(
            instance=EvaluacionConnectionRole(role="LEGACY_MYSQL"),
            role="LEGACY_MYSQL",
        )

        expected_sources = {"DJANGO", "MYSQL_CONFIG"}
        for form in (base_form, audit_form):
            self.assertEqual(
                _choice_values(form, "source_type"),
                expected_sources,
            )
            self.assertIn("django_alias", form.fields)
        self.assertFalse(legacy_form.show_source_selector)
        self.assertTrue(legacy_form.fields["source_type"].widget.is_hidden)
        self.assertTrue(legacy_form.fields["django_alias"].widget.is_hidden)
        self.assertEqual(
            _choice_values(legacy_form, "source_type"),
            {"MYSQL_CONFIG"},
        )

    def test_connection_role_form_clears_stale_fields_when_switching_sources(self):
        mysql_role = self._create_role("BASE_EVALUACIONES", "eval_database")
        to_django = EvaluacionConnectionRoleForm(
            {
                "source_type": "DJANGO",
                "django_alias": "default",
                "mysql_connection": "",
                "database_name": "",
            },
            instance=mysql_role,
            role="BASE_EVALUACIONES",
        )

        self.assertTrue(to_django.is_valid(), to_django.errors)
        django_role = to_django.save()
        self.assertEqual(django_role.source_type, "DJANGO")
        self.assertEqual(django_role.django_alias, "default")
        self.assertIsNone(django_role.mysql_connection)
        self.assertIsNone(django_role.database_name)

        to_mysql = EvaluacionConnectionRoleForm(
            {
                "source_type": "MYSQL_CONFIG",
                "django_alias": "",
                "mysql_connection": str(self.connection.pk),
                "database_name": "eval_database",
            },
            instance=django_role,
            role="BASE_EVALUACIONES",
        )

        self.assertTrue(to_mysql.is_valid(), to_mysql.errors)
        mysql_role = to_mysql.save()
        self.assertEqual(mysql_role.source_type, "MYSQL_CONFIG")
        self.assertIsNone(mysql_role.django_alias)
        self.assertEqual(mysql_role.mysql_connection, self.connection)
        self.assertEqual(mysql_role.database_name, "eval_database")

    def test_resolver_has_no_private_application_imports(self):
        tree = ast.parse(Path(connection_roles.__file__).read_text(encoding="utf-8"))
        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)

        forbidden_apps = (
            "tareas",
            "gestiondte",
            "biblioteca",
            "control_de_proyectos",
            "control_operacional",
        )
        self.assertFalse(
            any(
                module == app or module.startswith(f"{app}.")
                for module in imported_modules
                for app in forbidden_apps
            )
        )


class EvaluacionesConnectionViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="evaluaciones-admin")
        self.empresa = Empresa.objects.create(codigo="01", descripcion="Empresa 1")
        self.otra_empresa = Empresa.objects.create(codigo="02", descripcion="Empresa 2")
        self.vista = Vista.objects.create(
            nombre="Evaluaciones - Importar Personas",
            route_name="evaluaciones:importar_personas",
        )
        self.connection_vista = Vista.objects.create(
            nombre="Evaluaciones - Conexiones Sql",
            route_name="evaluaciones:connection_roles",
        )
        self.permission = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            ver=True,
            ingresar=True,
            supervisor=True,
        )
        self.connection_permission = Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.connection_vista,
            ver=True,
            ingresar=True,
            modificar=True,
            supervisor=False,
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.pk
        session.save()
        self.connection = self._create_connection(self.empresa, "eval-primary")
        self.global_connection = self._create_connection(
            self.otra_empresa, "shared-legacy"
        )

    @staticmethod
    def _create_connection(empresa, nombre_logico):
        return SettingsMySQLConnection.objects.create(
            empresa=empresa,
            nombre_logico=nombre_logico,
            engine=SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
            host="127.0.0.1",
            port=3306,
            user="user",
            password="not-used-in-tests",
            db_name="legacy_database",
            is_active=True,
        )

    def test_configuration_screen_lists_all_four_roles_and_global_connections(self):
        response = self.client.get(reverse("evaluaciones:connection_roles"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-connection-role="BASE_EVALUACIONES"')
        self.assertContains(response, 'data-connection-role="AUDITORIA_EVALUACIONES"')
        self.assertContains(response, 'data-connection-role="LEGACY_MYSQL"')
        self.assertContains(response, 'data-connection-role="LEGACY_AUDITORIA"')
        self.assertContains(response, 'data-role-source-type="true"', count=2)
        self.assertContains(response, 'data-role-django-alias="true"', count=2)
        self.assertContains(response, "evaluaciones/js/connection_roles.js")
        self.assertContains(response, "02 - Empresa 2 / shared-legacy")
        self.assertNotContains(response, "not-used-in-tests")

    def test_role_can_be_bound_to_central_connection_from_another_company(self):
        response = self.client.post(
            reverse("evaluaciones:connection_roles"),
            {
                "role": "BASE_EVALUACIONES",
                "source_type": "MYSQL_CONFIG",
                "mysql_connection": self.global_connection.pk,
                "database_name": "evaluaciones",
            },
        )

        self.assertEqual(response.status_code, 302)
        role = EvaluacionConnectionRole.objects.get(role="BASE_EVALUACIONES")
        self.assertEqual(role.mysql_connection, self.global_connection)
        self.assertEqual(role.database_name, "evaluaciones")

    def test_django_configuration_is_saved_for_base_role(self):
        response = self.client.post(
            reverse("evaluaciones:connection_roles"),
            {
                "role": "BASE_EVALUACIONES",
                "source_type": "DJANGO",
                "django_alias": "default",
                "mysql_connection": "",
                "database_name": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        role = EvaluacionConnectionRole.objects.get(role="BASE_EVALUACIONES")
        self.assertEqual(role.source_type, "DJANGO")
        self.assertEqual(role.django_alias, "default")
        self.assertIsNone(role.mysql_connection)
        self.assertIsNone(role.database_name)

    def test_legacy_role_rejects_django_submission(self):
        response = self.client.post(
            reverse("evaluaciones:connection_roles"),
            {
                "role": "LEGACY_MYSQL",
                "source_type": "DJANGO",
                "django_alias": "default",
                "mysql_connection": self.connection.pk,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            EvaluacionConnectionRole.objects.filter(role="LEGACY_MYSQL").exists()
        )

    def test_invalid_database_name_does_not_save_role(self):
        response = self.client.post(
            reverse("evaluaciones:connection_roles"),
            {
                "role": "BASE_EVALUACIONES",
                "source_type": "MYSQL_CONFIG",
                "mysql_connection": self.connection.pk,
                "database_name": "invalid-name",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            EvaluacionConnectionRole.objects.filter(
                role="BASE_EVALUACIONES"
            ).exists()
        )

    def test_probe_uses_safe_query_and_central_connection_wrapper(self):
        self._create_role_for_probe()
        cursor = MagicMock()
        connection = MagicMock()
        connection.cursor.return_value = cursor

        with patch(
            "evaluaciones.views.open_evaluaciones_connection",
            return_value=nullcontext(connection),
        ):
            response = self.client.post(
                reverse("evaluaciones:connection_probe"),
                {"role": "BASE_EVALUACIONES"},
            )

        self.assertEqual(response.status_code, 302)
        cursor.execute.assert_called_once_with("SELECT 1")
        cursor.close.assert_called_once_with()

    def test_probe_uses_selected_django_alias(self):
        self.connection_permission.supervisor = True
        self.connection_permission.save(update_fields=["supervisor"])
        EvaluacionConnectionRole.objects.create(
            role="BASE_EVALUACIONES",
            source_type=EvaluacionConnectionRole.SOURCE_DJANGO,
            django_alias="reporting",
        )
        alias_connection = MagicMock()
        alias_cursor = MagicMock()
        alias_connection.cursor.return_value = alias_cursor
        catalog = (
            {
                "alias": "reporting",
                "vendor": "sqlite",
                "classification": "SYSTEM",
            },
        )

        with patch(
            "evaluaciones.services.connection_roles.get_system_database_catalog",
            return_value=catalog,
        ), patch(
            "evaluaciones.services.connection_roles.connections"
        ) as django_connections, patch(
            "evaluaciones.services.connection_roles.open_mysql_connection"
        ) as open_mysql:
            django_connections.__getitem__.return_value = alias_connection
            response = self.client.post(
                reverse("evaluaciones:connection_probe"),
                {"role": "BASE_EVALUACIONES"},
            )

        self.assertEqual(response.status_code, 302)
        django_connections.__getitem__.assert_called_once_with("reporting")
        alias_cursor.execute.assert_called_once_with("SELECT 1")
        alias_cursor.close.assert_called_once_with()
        open_mysql.assert_not_called()

    def test_probe_handles_central_open_errors_without_exposing_them(self):
        self._create_role_for_probe()
        with patch(
            "evaluaciones.views.open_evaluaciones_connection",
            side_effect=MySQLConnectionOpenError("safe failure"),
        ):
            response = self.client.post(
                reverse("evaluaciones:connection_probe"),
                {"role": "BASE_EVALUACIONES"},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No se pudo validar la conexión SQL.")
        self.assertNotContains(response, "safe failure")

    def test_connection_screen_requires_its_own_ingresar_permission(self):
        self.connection_permission.ingresar = False
        self.connection_permission.save(update_fields=["ingresar"])
        permission_count = Permiso.objects.count()

        response = self.client.get(reverse("evaluaciones:connection_roles"))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Permiso.objects.count(), permission_count)

    def test_unauthorized_role_changes_are_rejected(self):
        self.connection_permission.modificar = False
        self.connection_permission.save(update_fields=["modificar"])

        response = self.client.post(
            reverse("evaluaciones:connection_roles"),
            {
                "role": "BASE_EVALUACIONES",
                "source_type": "MYSQL_CONFIG",
                "mysql_connection": self.connection.pk,
                "database_name": "evaluaciones",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            EvaluacionConnectionRole.objects.filter(
                role="BASE_EVALUACIONES"
            ).exists()
        )

    def test_import_permission_does_not_grant_connection_administration(self):
        self.connection_permission.delete()

        response = self.client.get(reverse("evaluaciones:connection_roles"))

        self.assertEqual(response.status_code, 403)

    def test_connection_permission_does_not_grant_person_import_access(self):
        self.permission.delete()

        response = self.client.get(reverse("evaluaciones:importar_personas"))

        self.assertEqual(response.status_code, 403)

    def test_connection_link_uses_its_view_visibility_not_import_supervisor(self):
        self.permission.supervisor = False
        self.permission.save(update_fields=["supervisor"])

        response = self.client.get(reverse("evaluaciones:importar_personas"))

        self.assertContains(response, "Configurar conexiones SQL")

        self.connection_permission.ver = False
        self.connection_permission.save(update_fields=["ver"])
        self.permission.supervisor = True
        self.permission.save(update_fields=["supervisor"])

        response = self.client.get(reverse("evaluaciones:importar_personas"))

        self.assertNotContains(response, "Configurar conexiones SQL")

    def test_probe_requires_supervisor_on_connection_view(self):
        self.connection_permission.supervisor = False
        self.connection_permission.save(update_fields=["supervisor"])
        self._create_role_for_probe()
        self.connection_permission.supervisor = False
        self.connection_permission.save(update_fields=["supervisor"])

        page = self.client.get(reverse("evaluaciones:connection_roles"))
        self.assertNotContains(page, "Probar conexión técnica")

        response = self.client.post(
            reverse("evaluaciones:connection_probe"),
            {"role": "BASE_EVALUACIONES"},
        )

        self.assertEqual(response.status_code, 403)

    def _create_role_for_probe(self):
        self.connection_permission.supervisor = True
        self.connection_permission.save(update_fields=["supervisor"])
        return EvaluacionConnectionRole.objects.create(
            role="BASE_EVALUACIONES",
            mysql_connection=self.connection,
            database_name="evaluaciones",
        )
