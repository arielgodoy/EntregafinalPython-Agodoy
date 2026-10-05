from contextlib import nullcontext
import inspect
import re
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.db.backends.mysql.base import DatabaseWrapper
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from settings.models import SettingsMySQLConnection
from tareas.models import TareaConnectionRole
from tareas.services.base_tareas_schema import (
    BaseTareasSchemaInstallError,
    EXPECTED_OPERATIONAL_MODELS,
    SCHEMA_PATH,
    build_base_tareas_schema_statements,
    get_operational_models,
    install_base_tareas_schema,
)


class BaseTareasSchemaInventoryTests(SimpleTestCase):
    class _PreviewCursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *args, **kwargs):
            return None

        def fetchone(self):
            return ("8.0.36", "", "InnoDB", 0, 0, 1)

        def close(self):
            return None

    class _PreviewDbApi:
        encoders = {}

        def escape(self, value, mapping=None):
            if value is None:
                return "NULL"
            if isinstance(value, bool):
                return "1" if value else "0"
            if isinstance(value, (int, float)):
                return str(value)
            return "'" + str(value).replace("'", "''") + "'"

        def cursor(self, *args, **kwargs):
            return BaseTareasSchemaInventoryTests._PreviewCursor()

    def _mysql_preview_connection(self):
        connection = DatabaseWrapper(
            {"ENGINE": "django.db.backends.mysql", "NAME": "preview", "OPTIONS": {}},
            "preview",
        )
        connection.connection = self._PreviewDbApi()
        return connection

    def test_bootstrap_has_no_gestiondte_runtime_dependency(self):
        from tareas.services import base_tareas_schema

        self.assertNotIn("gestiondte", inspect.getsource(base_tareas_schema))

    def test_operational_inventory_has_expected_models_and_excludes_roles(self):
        models = get_operational_models()

        self.assertEqual(len(models), 38)
        self.assertEqual(
            {model.__name__ for model in models},
            set(EXPECTED_OPERATIONAL_MODELS),
        )
        self.assertNotIn(TareaConnectionRole, models)

    @patch("tareas.services.base_tareas_schema.DatabaseSchemaEditor")
    def test_schema_builder_keeps_internal_and_removes_external_foreign_keys(
        self, schema_editor_class
    ):
        editor = MagicMock()
        editor.collected_sql = [
            'CREATE TABLE "tareas_tarea" ("id" bigint NOT NULL)',
            'ALTER TABLE "tareas_tarea" ADD CONSTRAINT "internal" '
            'FOREIGN KEY ("todo_origen_id") REFERENCES "tareas_todo" ("id")',
            'ALTER TABLE "tareas_tarea" ADD CONSTRAINT "external" '
            'FOREIGN KEY ("empresa_id") REFERENCES "access_control_empresa" ("id")',
        ]
        schema_editor_class.return_value.__enter__.return_value = editor

        statements = build_base_tareas_schema_statements(MagicMock())

        self.assertIn(
            'CREATE TABLE IF NOT EXISTS "tareas_tarea" ("id" bigint NOT NULL)',
            statements,
        )
        self.assertTrue(any('REFERENCES "tareas_todo"' in item for item in statements))
        self.assertFalse(any('access_control_empresa' in item for item in statements))
        self.assertNotIn("tareas_tareaconnectionrole", " ".join(statements))

    def test_schema_builder_rejects_destructive_sql(self):
        editor = MagicMock()
        editor.collected_sql = ['DROP TABLE tareas_tarea']
        with patch(
            "tareas.services.base_tareas_schema.DatabaseSchemaEditor"
        ) as schema_editor_class:
            schema_editor_class.return_value.__enter__.return_value = editor
            with self.assertRaises(BaseTareasSchemaInstallError):
                build_base_tareas_schema_statements(MagicMock())

    def test_frozen_sql_contains_only_operational_mysql_objects(self):
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        sql_without_comments = "\n".join(
            line for line in sql.splitlines() if not line.lstrip().startswith("--")
        )
        statements = [
            item.strip() for item in sql_without_comments.split(";") if item.strip()
        ]
        upper = [item.upper() for item in statements]

        self.assertEqual(
            (
                sum(item.startswith("CREATE TABLE") for item in upper),
                any("TAREAS_REPROGRAMACION_CAUSAS" in item for item in upper),
                "TAREAS_TAREACONNECTIONROLE" not in sql.upper(),
                "AUTH_USER" not in sql.upper(),
                "ACCESS_CONTROL_EMPRESA" not in sql.upper(),
                "ORGANIZACION_" not in sql.upper(),
                "PROVEEDORES_" not in sql.upper(),
                sum("FOREIGN KEY" in item.upper() for item in statements),
                sum("CREATE INDEX" in item.upper() for item in statements),
                sum("CHECK" in item.upper() for item in statements),
                sum("UNIQUE" in item.upper() for item in statements),
                not any(word in sql.upper() for word in ("DROP", "TRUNCATE", "DELETE")),
                not bool(re.search(
                    r"ALTER\s+TABLE\b.*\b(?:DROP|MODIFY|CHANGE|RENAME)\b",
                    sql,
                    re.IGNORECASE | re.DOTALL,
                )),
            ),
            (39, True, True, True, True, True, True, 46, 115, 11, 21, True, True),
        )

    def test_mysql_preview_shape_matches_frozen_sql(self):
        preview = build_base_tareas_schema_statements(
            self._mysql_preview_connection()
        )
        frozen = SCHEMA_PATH.read_text(encoding="utf-8")
        frozen = "\n".join(
            line for line in frozen.splitlines() if not line.lstrip().startswith("--")
        )
        frozen = [item.strip() for item in frozen.split(";") if item.strip()]

        def shape(statements):
            upper = [item.upper() for item in statements]
            return (
                sum(item.startswith("CREATE TABLE") for item in upper),
                sum("CREATE INDEX" in item for item in upper),
                sum("FOREIGN KEY" in item for item in upper),
                sum("CHECK" in item for item in upper),
                sum("UNIQUE" in item for item in upper),
            )

        self.assertEqual(shape(preview), shape(frozen))


class BaseTareasSchemaServiceTests(SimpleTestCase):
    def _mysql_context(self):
        connection = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        connection.cursor.return_value = cursor
        return connection, cursor

    @patch("tareas.services.base_tareas_schema._read_frozen_schema_statements")
    @patch("tareas.services.base_tareas_schema.open_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_connection")
    def test_install_resolves_base_role_and_commits_statements(
        self, get_connection, get_mysql_connection, open_connection, read_schema
    ):
        connection, cursor = self._mysql_context()
        get_connection.return_value = {
            "type": "MYSQL_CONFIG",
            "database_name": "tareas",
        }
        get_mysql_connection.return_value = object()
        open_connection.return_value = nullcontext(connection)
        read_schema.return_value = [
            "CREATE TABLE IF NOT EXISTS tareas_tarea (id BIGINT NOT NULL)"
        ]

        processed = install_base_tareas_schema()

        self.assertEqual(processed, 1)
        get_connection.assert_called_once_with("BASE_TAREAS")
        open_connection.assert_called_once()
        self.assertEqual(cursor.execute.call_args_list[-1].args[0], read_schema.return_value[0])
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()

    @patch("tareas.services.base_tareas_schema.get_tarea_connection")
    def test_django_base_role_is_rejected_without_opening_mysql(self, get_connection):
        get_connection.return_value = {"type": "DJANGO", "alias": "default"}

        with self.assertRaises(BaseTareasSchemaInstallError):
            install_base_tareas_schema()

    @patch("tareas.services.base_tareas_schema._read_frozen_schema_statements")
    @patch("tareas.services.base_tareas_schema.open_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_connection")
    def test_sql_failure_rolls_back_and_sanitizes_error(
        self, get_connection, get_mysql_connection, open_connection, read_schema
    ):
        connection, cursor = self._mysql_context()
        cursor.execute.side_effect = RuntimeError("password=secret")
        get_connection.return_value = {
            "type": "MYSQL_CONFIG",
            "database_name": "tareas",
        }
        get_mysql_connection.return_value = object()
        open_connection.return_value = nullcontext(connection)
        read_schema.return_value = [
            "CREATE TABLE IF NOT EXISTS tareas_tarea (id BIGINT NOT NULL)"
        ]

        with self.assertRaises(BaseTareasSchemaInstallError) as raised:
            install_base_tareas_schema()

        self.assertNotIn("password", str(raised.exception).lower())
        connection.rollback.assert_called_once_with()
        connection.commit.assert_not_called()

    @patch("tareas.services.base_tareas_schema._read_frozen_schema_statements")
    @patch("tareas.services.base_tareas_schema.open_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_connection")
    def test_second_run_skips_existing_tables_indexes_and_constraints(
        self, get_connection, get_mysql_connection, open_connection, read_schema
    ):
        connection, cursor = self._mysql_context()
        cursor.fetchone.return_value = (1,)
        get_connection.return_value = {
            "type": "MYSQL_CONFIG",
            "database_name": "tareas",
        }
        get_mysql_connection.return_value = object()
        open_connection.return_value = nullcontext(connection)
        read_schema.return_value = [
            "CREATE TABLE IF NOT EXISTS `tareas_tarea` (`id` BIGINT)",
            "CREATE INDEX `idx_tarea` ON `tareas_tarea` (`id`)",
            "ALTER TABLE `tareas_tarea` ADD CONSTRAINT `fk_tarea` "
            "FOREIGN KEY (`id`) REFERENCES `tareas_tarea` (`id`)",
        ]

        processed = install_base_tareas_schema()

        self.assertEqual(processed, 3)
        self.assertEqual(cursor.execute.call_count, 3)
        connection.commit.assert_called_once_with()

    @patch("tareas.services.base_tareas_schema._read_frozen_schema_statements")
    @patch("tareas.services.base_tareas_schema.open_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_connection")
    def test_partial_schema_creates_only_missing_object(
        self, get_connection, get_mysql_connection, open_connection, read_schema
    ):
        connection, cursor = self._mysql_context()
        cursor.fetchone.side_effect = [(1,), None]
        get_connection.return_value = {
            "type": "MYSQL_CONFIG",
            "database_name": "tareas",
        }
        get_mysql_connection.return_value = object()
        open_connection.return_value = nullcontext(connection)
        read_schema.return_value = [
            "CREATE TABLE IF NOT EXISTS `tareas_tarea` (`id` BIGINT)",
            "CREATE INDEX `idx_tarea` ON `tareas_tarea` (`id`)",
        ]

        install_base_tareas_schema()

        self.assertEqual(
            cursor.execute.call_args_list[-1].args[0],
            read_schema.return_value[1],
        )
        connection.commit.assert_called_once_with()


class BaseTareasSchemaViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="base-tareas-schema-user",
            password="pass",
        )
        self.active_company = Empresa.objects.create(
            codigo="09",
            descripcion="Empresa activa",
        )
        self.catalog_company = Empresa.objects.create(
            codigo="00",
            descripcion="Empresa Base",
        )
        self.vista = Vista.objects.create(
            nombre="Tareas - Conexiones SQL",
            route_name="tareas:conexiones_sql",
        )
        self.connection = SettingsMySQLConnection.objects.create(
            empresa=self.catalog_company,
            nombre_logico="mysqldjango",
            host="mysql.example.test",
            user="user",
            password="secret",
            db_name="system",
            is_active=True,
        )
        TareaConnectionRole.objects.create(
            role="BASE_TAREAS",
            source_type="MYSQL_CONFIG",
            mysql_connection=self.connection,
            database_name="tareas",
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.active_company.id
        session.save()

    def _grant(self, **flags):
        return Permiso.objects.create(
            usuario=self.user,
            empresa=self.active_company,
            vista=self.vista,
            **flags,
        )

    def test_button_requires_mysql_base_role_and_supervisor(self):
        self._grant(ver=True, ingresar=True)
        without_supervisor = self.client.get(reverse("tareas:conexiones_sql"))
        self.assertNotContains(without_supervisor, "Crear estructura Base Tareas")

        Permiso.objects.filter(
            usuario=self.user,
            empresa=self.active_company,
            vista=self.vista,
        ).update(supervisor=True)
        with_supervisor = self.client.get(reverse("tareas:conexiones_sql"))
        self.assertContains(with_supervisor, "Crear estructura Base Tareas")
        self.assertContains(with_supervisor, "tareas")

    def test_button_hidden_for_django_base_role(self):
        self._grant(ver=True, ingresar=True, supervisor=True)
        role = TareaConnectionRole.objects.get(role="BASE_TAREAS")
        role.source_type = "DJANGO"
        role.django_alias = "default"
        role.mysql_connection = None
        role.database_name = None
        role.save()

        response = self.client.get(reverse("tareas:conexiones_sql"))

        self.assertNotContains(response, "Crear estructura Base Tareas")

    @patch("tareas.views.install_base_tareas_schema")
    def test_endpoint_is_post_only_and_requires_supervisor(self, install):
        self._grant(ver=True, ingresar=True)
        url = reverse("tareas:base_tareas_schema_install")

        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url).status_code, 403)
        install.assert_not_called()

        Permiso.objects.filter(
            usuario=self.user,
            empresa=self.active_company,
            vista=self.vista,
        ).update(supervisor=True)
        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        install.assert_called_once_with()
