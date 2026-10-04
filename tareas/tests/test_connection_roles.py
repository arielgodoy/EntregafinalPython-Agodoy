from pathlib import Path
import inspect
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from settings.models import SettingsMySQLConnection
from tareas.forms import TareaConnectionRoleForm
from tareas.models import TareaConnectionRole
from tareas.services.connection_roles import (
    TASKS_CONNECTIONS_COMPANY_CODE,
    TareaConnectionAliasUnavailableError,
    TareaConnectionInactiveError,
    TareaConnectionRoleNotFoundError,
    TareaConnectionSourceError,
    get_active_mysql_connection_catalog,
    get_tarea_connection,
)


class TareaConnectionRoleModelTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo=TASKS_CONNECTIONS_COMPANY_CODE, descripcion="Catálogo Tareas")
        self.connection = SettingsMySQLConnection.objects.create(
            empresa=self.empresa,
            nombre_logico="tareas_legacy",
            host="mysql.example.test",
            user="readonly",
            password="secret-no-debe-salir",
            db_name="legacy_tareas",
        )

    def test_exactly_four_global_roles_without_company_field(self):
        self.assertEqual(
            {role for role, _label in TareaConnectionRole.ROLE_CHOICES},
            {"BASE_TAREAS", "AUDITORIA_TAREAS", "LEGACY_MYSQL", "LEGACY_AUDITORIA"},
        )
        self.assertNotIn("empresa", {field.name for field in TareaConnectionRole._meta.fields})

    def test_django_source_is_valid_for_base_role(self):
        role = TareaConnectionRole(
            role="BASE_TAREAS",
            source_type="DJANGO",
            django_alias="default",
        )
        with patch(
            "tareas.services.connection_roles.get_system_database_catalog",
            return_value=({"alias": "default", "vendor": "sqlite", "classification": "SYSTEM"},),
        ):
            role.clean()

    def test_legacy_django_source_is_rejected(self):
        role = TareaConnectionRole(
            role="LEGACY_MYSQL",
            source_type="DJANGO",
            django_alias="default",
        )
        with self.assertRaises(ValidationError) as raised:
            role.full_clean()
        self.assertIn("source_type", raised.exception.message_dict)

    def test_mysql_source_requires_database_name_for_configurable_roles(self):
        role = TareaConnectionRole(
            role="BASE_TAREAS",
            source_type="MYSQL_CONFIG",
            mysql_connection=self.connection,
        )
        with self.assertRaises(ValidationError) as raised:
            role.full_clean()
        self.assertIn("database_name", raised.exception.message_dict)

    def test_legacy_mysql_uses_settings_database_name(self):
        role = TareaConnectionRole(
            role="LEGACY_MYSQL",
            source_type="MYSQL_CONFIG",
            mysql_connection=self.connection,
        )
        role.full_clean()
        self.assertIsNone(role.database_name)

    def test_catalog_company_code_is_centralized(self):
        self.assertEqual(TASKS_CONNECTIONS_COMPANY_CODE, "00")

    def test_role_is_unique(self):
        TareaConnectionRole.objects.create(
            role="LEGACY_MYSQL",
            source_type="MYSQL_CONFIG",
            mysql_connection=self.connection,
        )
        with self.assertRaises(Exception):
            TareaConnectionRole.objects.create(
                role="LEGACY_MYSQL",
                source_type="MYSQL_CONFIG",
                mysql_connection=self.connection,
            )


class TareaConnectionRoleResolverTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(codigo=TASKS_CONNECTIONS_COMPANY_CODE, descripcion="Catálogo resolver")
        self.otra_empresa = Empresa.objects.create(codigo="09", descripcion="Empresa operativa")
        self.connection = SettingsMySQLConnection.objects.create(
            empresa=self.empresa,
            nombre_logico="tareas_legacy",
            host="mysql.example.test",
            user="readonly",
            password="secret-no-debe_salir",
            db_name="legacy_tareas",
        )
        self.foreign_connection = SettingsMySQLConnection.objects.create(
            empresa=self.otra_empresa,
            nombre_logico="otra_empresa",
            host="mysql.example.test",
            user="readonly",
            password="secret-no-debe-salir",
            db_name="legacy_otra_empresa",
        )

    def test_missing_role_does_not_fallback_to_default(self):
        with self.assertRaises(TareaConnectionRoleNotFoundError):
            get_tarea_connection("BASE_TAREAS")

    def test_django_alias_must_be_system(self):
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS",
            source_type="DJANGO",
            django_alias="not_system",
        )
        with patch("tareas.services.connection_roles.get_system_database_catalog", return_value=()):
            with self.assertRaises(TareaConnectionAliasUnavailableError):
                get_tarea_connection("BASE_TAREAS")

    def test_legacy_django_is_rejected_by_resolver(self):
        TareaConnectionRole.objects.create(
            role="LEGACY_MYSQL",
            source_type="DJANGO",
            django_alias="default",
        )
        with patch(
            "tareas.services.connection_roles.get_system_database_catalog",
            return_value=({"alias": "default", "vendor": "sqlite", "classification": "SYSTEM"},),
        ):
            with self.assertRaises(TareaConnectionSourceError):
                get_tarea_connection("LEGACY_MYSQL")

    def test_mysql_resolution_is_global_and_returns_selected_connection(self):
        TareaConnectionRole.objects.create(
            role="LEGACY_MYSQL",
            source_type="MYSQL_CONFIG",
            mysql_connection=self.connection,
        )
        resolved = get_tarea_connection("LEGACY_MYSQL")
        self.assertEqual(resolved["connection_id"], self.connection.pk)
        self.assertEqual(resolved["database_name"], "legacy_tareas")

    def test_resolver_rejects_connection_outside_company_00_catalog(self):
        TareaConnectionRole.objects.create(
            role="LEGACY_MYSQL",
            source_type="MYSQL_CONFIG",
            mysql_connection=self.foreign_connection,
        )
        with self.assertRaises(TareaConnectionSourceError):
            get_tarea_connection("LEGACY_MYSQL")

    def test_resolver_rejects_inactive_company_00_connection(self):
        self.connection.is_active = False
        self.connection.save(update_fields=("is_active",))
        TareaConnectionRole.objects.create(
            role="LEGACY_MYSQL",
            source_type="MYSQL_CONFIG",
            mysql_connection=self.connection,
        )
        with self.assertRaises(TareaConnectionInactiveError):
            get_tarea_connection("LEGACY_MYSQL")

    def test_resolver_scope_is_global_and_accepts_only_role(self):
        self.assertEqual(tuple(inspect.signature(get_tarea_connection).parameters), ("role",))


class TareaConnectionRoleFormTests(TestCase):
    def setUp(self):
        self.catalog_empresa = Empresa.objects.create(codigo="00", descripcion="Catálogo form")
        self.otra_empresa = Empresa.objects.create(codigo="09", descripcion="Empresa form")
        self.connection = SettingsMySQLConnection.objects.create(
            empresa=self.catalog_empresa,
            nombre_logico="tareas_form",
            host="mysql.example.test",
            user="readonly",
            password="secret-no-debe-salir",
            db_name="legacy_tareas",
        )
        self.inactive_connection = SettingsMySQLConnection.objects.create(
            empresa=self.catalog_empresa,
            nombre_logico="tareas_inactive",
            host="mysql.example.test",
            user="readonly",
            password="secret-no-debe-salir",
            db_name="legacy_inactive",
            is_active=False,
        )
        self.foreign_connection = SettingsMySQLConnection.objects.create(
            empresa=self.otra_empresa,
            nombre_logico="tareas_foreign",
            host="mysql.example.test",
            user="readonly",
            password="secret-no-debe-salir",
            db_name="legacy_foreign",
        )

    def test_mysql_catalog_contains_only_active_company_00_connections(self):
        catalog_ids = set(get_active_mysql_connection_catalog().values_list("pk", flat=True))
        self.assertIn(self.connection.pk, catalog_ids)
        self.assertNotIn(self.inactive_connection.pk, catalog_ids)
        self.assertNotIn(self.foreign_connection.pk, catalog_ids)

    def test_form_rejects_manipulated_foreign_connection(self):
        form = TareaConnectionRoleForm(
            data={
                "source_type": "MYSQL_CONFIG",
                "django_alias": "",
                "mysql_connection": str(self.foreign_connection.pk),
                "database_name": "tareas",
            },
            instance=TareaConnectionRole(role="BASE_TAREAS"),
            role="BASE_TAREAS",
        )
        self.assertFalse(form.is_valid())
        self.assertIn("mysql_connection", form.errors)

    def test_legacy_form_only_offers_mysql(self):
        form = TareaConnectionRoleForm(
            instance=TareaConnectionRole(role="LEGACY_MYSQL"),
            role="LEGACY_MYSQL",
        )
        self.assertEqual(
            [value for value, _label in form.fields["source_type"].choices],
            ["MYSQL_CONFIG"],
        )

    def test_form_rejects_legacy_django_post(self):
        form = TareaConnectionRoleForm(
            data={
                "source_type": "DJANGO",
                "django_alias": "default",
                "mysql_connection": "",
            },
            instance=TareaConnectionRole(role="LEGACY_AUDITORIA"),
            role="LEGACY_AUDITORIA",
        )
        self.assertFalse(form.is_valid())
        self.assertIn("source_type", form.errors)


class TareaConnectionRoleViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="connection-user", password="pass")
        self.empresa = Empresa.objects.create(codigo="09", descripcion="Empresa vista")
        self.catalog_empresa = Empresa.objects.create(codigo="00", descripcion="Catálogo vista")
        self.catalog_connection = SettingsMySQLConnection.objects.create(
            empresa=self.catalog_empresa,
            nombre_logico="catalogo_vista",
            host="mysql.example.test",
            user="readonly",
            password="secret-no-debe-salir",
            db_name="legacy_tareas",
        )
        self.vista = Vista.objects.create(
            nombre="Tareas - Conexiones SQL",
            route_name="tareas:conexiones_sql",
        )

    def _activate(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.empresa.id
        session.save()

    def _grant(self, **flags):
        return Permiso.objects.create(
            usuario=self.user,
            empresa=self.empresa,
            vista=self.vista,
            **flags,
        )

    def test_get_requires_ingresar_and_post_requires_modificar(self):
        self._activate()
        self._grant(ver=True, ingresar=True, modificar=False)
        response = self.client.get(reverse("tareas:conexiones_sql"))
        self.assertEqual(response.status_code, 200)
        post_response = self.client.post(reverse("tareas:conexiones_sql"), data={})
        self.assertEqual(post_response.status_code, 403)

    def test_get_renders_four_roles_without_credentials(self):
        self._activate()
        self._grant(ver=True, ingresar=True)
        response = self.client.get(reverse("tareas:conexiones_sql"))
        self.assertEqual(response.status_code, 200)
        for role, _label in TareaConnectionRole.ROLE_CHOICES:
            self.assertContains(response, f'tareas.connection_roles.role.{role}')
        self.assertContains(response, "catalogo_vista")
        self.assertNotContains(response, "secret-no-debe-salir")


class TareaConnectionRoleImportTests(SimpleTestCase):
    def test_connection_role_runtime_has_no_gestiondte_imports(self):
        root = Path(__file__).resolve().parents[1]
        files = [
            root / "models.py",
            root / "forms.py",
            root / "views.py",
            root / "services" / "connection_roles.py",
        ]
        for file_path in files:
            content = file_path.read_text(encoding="utf-8")
            self.assertNotIn("from gestiondte", content)
            self.assertNotIn("import gestiondte", content)
