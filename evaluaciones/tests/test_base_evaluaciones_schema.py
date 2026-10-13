from contextlib import nullcontext
from datetime import datetime, timezone
from time import time as current_time
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import signing
from django.db.utils import OperationalError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from access_control.models import Empresa, Permiso, Vista
from evaluaciones.models import EvaluacionConnectionRole, Persona
from evaluaciones.services.connection_roles import SUPPORTED_MYSQL_ENGINES
from evaluaciones.services import base_evaluaciones_schema as schema
from settings.models import SettingsMySQLConnection


def compatible_snapshot(*, table_exists=True):
    statement = schema._read_frozen_statement()
    expected = schema._expected_schema(statement)
    actual = {
        "tables": {},
        "columns": {},
        "indexes": [],
        "checks": set(),
        "unenforced_checks": set(),
    }
    if table_exists:
        actual["tables"][schema.TABLE_NAME] = {
            "type": "BASE TABLE",
            "engine": schema.EXPECTED_ENGINE,
            "collation": schema.EXPECTED_COLLATION,
        }
        actual["columns"] = {
            name: field.copy() for name, field in expected["columns"].items()
        }
        actual["indexes"] = [
            {
                "name": "PRIMARY",
                "unique": True,
                "columns": expected["primary"],
            },
            {
                "name": "person_id",
                "unique": True,
                "columns": ("person_id",),
            },
        ]
        actual["checks"] = set(expected["checks"])
    return {
        "expected": expected,
        "actual": actual,
        "server_version": "8.0.36",
    }


class ReadOnlyCursor:
    def __init__(
        self,
        *,
        server_row=("8.0.36", "MySQL Community Server - GPL", "evaluaciones"),
        failing_sql_fragment=None,
        failure=None,
        check_rows=(),
    ):
        self.calls = []
        self.rows = []
        self.one = None
        self.server_row = server_row
        self.failing_sql_fragment = failing_sql_fragment
        self.failure = failure
        self.check_rows = check_rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.calls.append((query, params))
        if self.failing_sql_fragment and self.failing_sql_fragment in query:
            raise self.failure
        if "SELECT VERSION()" in query:
            self.one = self.server_row
        elif "INFORMATION_SCHEMA.CHECK_CONSTRAINTS" in query:
            self.rows = list(self.check_rows)
        else:
            self.one = None
            self.rows = []

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.rows

    def close(self):
        return None


class ReadOnlyConnection:
    def __init__(self, **cursor_options):
        self.query_cursor = ReadOnlyCursor(**cursor_options)
        self.executed_ddl = []
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.query_cursor

    def close(self):
        self.closed = True

    def commit(self):
        self.committed = True

    def rollback(self):
        return None


class TrackingConnectionContext:
    def __init__(self, connection=None, enter_error=None):
        self.connection = connection
        self.enter_error = enter_error
        self.closed = False

    def __enter__(self):
        if self.enter_error:
            raise self.enter_error
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True
        self.connection.close()
        return False


class BaseEvaluacionesSchemaServiceTests(SimpleTestCase):
    @staticmethod
    def _preview_with_connection_context(connection_context):
        target = {
            "connection_config": SimpleNamespace(pk=9),
            "connection_id": 9,
            "connection_updated_at": "2026-01-01T00:00:00+00:00",
            "database_name": "evaluaciones",
        }
        with (
            patch.object(schema, "_resolve_target", return_value=target),
            patch.object(
                schema,
                "open_mysql_connection",
                return_value=connection_context,
            ),
        ):
            return schema.preview_base_evaluaciones_schema()

    def test_frozen_sql_has_one_explicit_persona_table(self):
        statement = schema._read_frozen_statement()
        expected = schema._expected_schema(statement)

        self.assertEqual(expected["table"], "evaluaciones_persona")
        self.assertEqual(len(expected["columns"]), len(Persona._meta.local_fields))
        self.assertEqual(expected["primary"], ("id",))
        self.assertEqual(expected["unique"], {("person_id",)})
        self.assertEqual(
            expected["checks"],
            {"mes>=0", "anio>=0"},
        )
        self.assertEqual(expected["engine"], "InnoDB")
        self.assertEqual(expected["charset"], "utf8mb4")
        self.assertEqual(expected["collation"], "utf8mb4_unicode_ci")
        self.assertNotIn("evaluacionconnectionrole", statement.lower())

    def test_frozen_sql_matches_django_mysql_schema_editor(self):
        statements = schema.build_base_evaluaciones_schema_statements("8.0.36")

        self.assertEqual(len(statements), 1)
        self.assertTrue(statements[0].startswith("CREATE TABLE `evaluaciones_persona`"))
        self.assertIn(
            "ENGINE=InnoDB DEFAULT CHARACTER SET=utf8mb4 "
            "COLLATE=utf8mb4_unicode_ci",
            statements[0],
        )

    def test_frozen_sql_matches_django_mariadb_schema_editor(self):
        statements = schema.build_base_evaluaciones_schema_statements(
            "10.11.13-MariaDB-ubu2004"
        )

        self.assertEqual(len(statements), 1)
        self.assertEqual(statements[0], schema._read_frozen_statement())
        self.assertEqual(
            schema._expected_schema(statements[0])["checks"],
            {"mes>=0", "anio>=0"},
        )

    def test_product_specific_minimum_versions_are_enforced(self):
        self.assertEqual(schema._parse_mysql_version("8.0.16"), (8, 0, 16))
        self.assertEqual(schema._parse_mysql_version("8.4.2-commercial"), (8, 4, 2))
        self.assertEqual(
            schema._parse_mysql_version("10.11.13-MariaDB-ubu2004"),
            (10, 11, 13),
        )
        self.assertEqual(
            schema._parse_mysql_version("10.5.0-MariaDB"),
            (10, 5, 0),
        )
        for version in (
            "8.0.15",
            "5.7.44",
            "5.1.73",
            "10.4.99-MariaDB",
            "unknown",
        ):
            with self.subTest(version=version):
                with self.assertRaises(schema.BaseEvaluacionesSchemaInstallError):
                    schema._parse_mysql_version(version)

    def test_server_product_must_match_version_and_comment(self):
        self.assertEqual(
            schema._validate_server_product(
                "10.11.13-MariaDB-ubu2004",
                "mariadb.org binary distribution",
            ),
            "mariadb",
        )
        self.assertEqual(
            schema._validate_server_product(
                "8.0.36",
                "MySQL Community Server - GPL",
            ),
            "mysql",
        )
        for version, comment in (
            ("10.11.13-MariaDB", "MySQL Community Server - GPL"),
            ("8.0.36", "mariadb.org binary distribution"),
            ("8.0.36", "Percona Server"),
        ):
            with self.subTest(version=version, comment=comment):
                with self.assertRaises(schema.BaseEvaluacionesSchemaInstallError):
                    schema._validate_server_product(version, comment)

    def test_mariadb_check_metadata_is_compared_without_enforced_column(self):
        connection = ReadOnlyConnection(
            server_row=(
                "10.11.13-MariaDB-ubu2004",
                "mariadb.org binary distribution",
                "evaluaciones",
            ),
            check_rows=(
                ("CHECK", "`mes` >= 0"),
                ("CHECK", "`anio` >= 0"),
            ),
        )

        snapshot = schema._collect_snapshot(connection, "evaluaciones")

        check_query = next(
            query
            for query, _params in connection.query_cursor.calls
            if "INFORMATION_SCHEMA.CHECK_CONSTRAINTS" in query
        )
        self.assertNotIn("ENFORCED", check_query.upper())
        self.assertEqual(
            snapshot["actual"]["checks"],
            {"mes>=0", "anio>=0"},
        )
        self.assertEqual(snapshot["actual"]["unenforced_checks"], set())

    def test_mysql_check_metadata_still_validates_enforced_state(self):
        connection = ReadOnlyConnection(
            check_rows=(
                ("CHECK", "`mes` >= 0", "YES"),
                ("CHECK", "`anio` >= 0", "NO"),
            )
        )

        snapshot = schema._collect_snapshot(connection, "evaluaciones")

        check_query = next(
            query
            for query, _params in connection.query_cursor.calls
            if "INFORMATION_SCHEMA.CHECK_CONSTRAINTS" in query
        )
        self.assertIn("cc.ENFORCED", check_query)
        self.assertEqual(snapshot["actual"]["checks"], {"mes>=0"})
        self.assertEqual(
            snapshot["actual"]["unenforced_checks"],
            {"anio>=0"},
        )

    def test_api_remote_engine_remains_outside_supported_installer_engines(self):
        self.assertNotIn(
            SettingsMySQLConnection.ENGINE_API_REMOTA,
            SUPPORTED_MYSQL_ENGINES,
        )

    def test_comparator_classifies_missing_table(self):
        result = schema._compare_snapshot(compatible_snapshot(table_exists=False))

        self.assertEqual(result["missing"], ["evaluaciones_persona"])
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(
            result["tables"][0]["classification"],
            "PENDIENTE_CREACION",
        )

    def test_comparator_accepts_compatible_table(self):
        result = schema._compare_snapshot(compatible_snapshot())

        self.assertEqual(result["existing"], ["evaluaciones_persona"])
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["conflicts"], [])

    def test_comparator_rejects_column_engine_collation_and_index_conflicts(self):
        mutations = (
            ("columns", "person_id", "type", "varchar(20)", "COLUMN_TYPE_MISMATCH"),
            ("columns", "email", "nullable", "NO", "NULLABILITY_MISMATCH"),
        )
        for section, name, key, value, expected_issue in mutations:
            with self.subTest(issue=expected_issue):
                snapshot = compatible_snapshot()
                snapshot["actual"][section][name][key] = value
                result = schema._compare_snapshot(snapshot)
                self.assertIn(expected_issue, result["conflicts"][0]["issues"])

        for key, value, expected_issue in (
            ("engine", "MyISAM", "ENGINE_MISMATCH"),
            ("collation", "utf8mb4_general_ci", "COLLATION_MISMATCH"),
        ):
            with self.subTest(issue=expected_issue):
                snapshot = compatible_snapshot()
                snapshot["actual"]["tables"][schema.TABLE_NAME][key] = value
                result = schema._compare_snapshot(snapshot)
                self.assertIn(expected_issue, result["conflicts"][0]["issues"])

        snapshot = compatible_snapshot()
        snapshot["actual"]["indexes"] = [
            index
            for index in snapshot["actual"]["indexes"]
            if index["name"] != "person_id"
        ]
        result = schema._compare_snapshot(snapshot)
        self.assertIn("UNIQUE_INDEX_MISMATCH", result["conflicts"][0]["issues"])

    def test_comparator_rejects_extra_columns_and_check_constraints(self):
        snapshot = compatible_snapshot()
        snapshot["actual"]["columns"]["extra"] = {
            "type": "int",
            "nullable": "YES",
            "auto_increment": False,
        }
        snapshot["actual"]["checks"].clear()

        result = schema._compare_snapshot(snapshot)

        self.assertIn("COLUMN_SET_MISMATCH", result["conflicts"][0]["issues"])
        self.assertIn("CHECK_CONSTRAINT_MISMATCH", result["conflicts"][0]["issues"])

        snapshot = compatible_snapshot()
        snapshot["actual"]["unenforced_checks"] = set(
            snapshot["actual"]["checks"]
        )
        snapshot["actual"]["checks"].clear()
        result = schema._compare_snapshot(snapshot)
        self.assertIn(
            "CHECK_CONSTRAINT_NOT_ENFORCED",
            result["conflicts"][0]["issues"],
        )

    def test_preview_uses_read_only_metadata_queries_only(self):
        target = {
            "connection_config": SimpleNamespace(
                pk=9,
                db_name="central_catalog_database",
            ),
            "connection_id": 9,
            "connection_updated_at": "2026-01-01T00:00:00+00:00",
            "database_name": "evaluaciones",
        }
        connection = ReadOnlyConnection()
        context = SimpleNamespace(
            backend_type=EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG,
            mysql_connection=SimpleNamespace(
                pk=9,
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            database_name="evaluaciones",
        )
        with (
            patch.object(schema, "_resolve_target", return_value=target),
            patch.object(schema, "resolve_operational_backend", return_value=context),
            patch.object(
                schema,
                "open_mysql_connection",
                return_value=nullcontext(connection),
            ) as open_connection,
            patch.object(
                schema,
                "build_base_evaluaciones_schema_statements",
                return_value=[schema._read_frozen_statement()],
            ),
            patch.object(schema, "_collect_snapshot", wraps=schema._collect_snapshot),
        ):
            result = schema.preview_base_evaluaciones_schema()

        self.assertEqual(result["missing"], ["evaluaciones_persona"])
        self.assertEqual(result["server_version"], "8.0.36")
        open_connection.assert_called_once_with(
            target["connection_config"],
            database_name="evaluaciones",
        )
        self.assertTrue(connection.query_cursor.calls)
        self.assertTrue(
            all(query.lstrip().upper().startswith("SELECT") for query, _ in connection.query_cursor.calls)
        )
        self.assertFalse(connection.committed)
        self.assertEqual(connection.executed_ddl, [])

    def test_real_connection_open_failure_keeps_open_error_and_sanitizes_message(self):
        open_error = schema.MySQLConnectionOpenError(
            "Access denied for user internal-user at internal-host; password=secret"
        )
        connection_context = TrackingConnectionContext(enter_error=open_error)

        with self.assertRaises(schema.BaseEvaluacionesSchemaInstallError) as raised:
            self._preview_with_connection_context(connection_context)

        self.assertEqual(
            str(raised.exception),
            "No se pudo abrir la conexión de BASE_EVALUACIONES.",
        )
        self.assertNotIn("internal-user", str(raised.exception))
        self.assertNotIn("internal-host", str(raised.exception))
        self.assertNotIn("secret", str(raised.exception))
        self.assertIs(raised.exception.__cause__, open_error)
        self.assertFalse(connection_context.closed)

    def test_version_validation_failure_keeps_its_category_and_closes_connection(self):
        connection = ReadOnlyConnection(
            server_row=("8.0.15", "MySQL Community Server - GPL", "evaluaciones")
        )
        connection_context = TrackingConnectionContext(connection)

        with self.assertRaises(schema.BaseEvaluacionesSchemaInstallError) as raised:
            self._preview_with_connection_context(connection_context)

        self.assertNotEqual(
            str(raised.exception),
            "No se pudo abrir la conexión de BASE_EVALUACIONES.",
        )
        self.assertEqual(len(connection.query_cursor.calls), 1)
        self.assertIn("SELECT VERSION()", connection.query_cursor.calls[0][0])
        self.assertTrue(connection_context.closed)
        self.assertTrue(connection.closed)
        self.assertFalse(connection.committed)

    def test_metadata_read_failure_keeps_inspection_category_and_closes_connection(self):
        driver_error = OperationalError(
            "Access denied for user internal-user at internal-host; password=secret"
        )
        connection = ReadOnlyConnection(
            failing_sql_fragment="INFORMATION_SCHEMA.COLUMNS",
            failure=driver_error,
        )
        connection_context = TrackingConnectionContext(connection)

        with self.assertLogs(schema.__name__, level="DEBUG") as diagnostic_logs:
            with self.assertRaises(
                schema.BaseEvaluacionesSchemaInstallError
            ) as raised:
                self._preview_with_connection_context(connection_context)

        self.assertEqual(
            str(raised.exception),
            "No se pudo inspeccionar la estructura Base Evaluaciones.",
        )
        self.assertIs(raised.exception.__cause__, driver_error)
        self.assertTrue(connection_context.closed)
        self.assertTrue(connection.closed)
        self.assertFalse(connection.committed)
        self.assertEqual(connection.executed_ddl, [])
        diagnostic_output = "\n".join(diagnostic_logs.output)
        self.assertIn("OperationalError", diagnostic_output)
        self.assertIn("mysql_error_code=None", diagnostic_output)
        self.assertNotIn("internal-user", diagnostic_output)
        self.assertNotIn("internal-host", diagnostic_output)
        self.assertNotIn("secret", diagnostic_output)
        self.assertTrue(
            all(
                query.lstrip().upper().startswith("SELECT")
                for query, _ in connection.query_cursor.calls
            )
        )

    def test_wrong_selected_database_keeps_validation_error_and_closes_connection(self):
        connection = ReadOnlyConnection(
            server_row=("8.0.36", "MySQL Community Server - GPL", "otra_base")
        )
        connection_context = TrackingConnectionContext(connection)

        with self.assertRaises(schema.BaseEvaluacionesSchemaInstallError) as raised:
            self._preview_with_connection_context(connection_context)

        self.assertEqual(
            str(raised.exception),
            "La conexión no abrió la base efectiva de BASE_EVALUACIONES.",
        )
        self.assertTrue(connection_context.closed)
        self.assertTrue(connection.closed)
        self.assertFalse(connection.committed)
        self.assertEqual(connection.executed_ddl, [])

    def test_sql_driver_error_is_not_reported_as_an_open_failure(self):
        driver_error = OperationalError(
            1045,
            "Access denied for user internal-user at internal-host; password=secret",
        )
        connection = ReadOnlyConnection(
            failing_sql_fragment="SELECT VERSION()",
            failure=driver_error,
        )
        connection_context = TrackingConnectionContext(connection)

        with self.assertLogs(schema.__name__, level="DEBUG") as diagnostic_logs:
            with self.assertRaises(
                schema.BaseEvaluacionesSchemaInstallError
            ) as raised:
                self._preview_with_connection_context(connection_context)

        self.assertEqual(
            str(raised.exception),
            "No se pudo inspeccionar la estructura Base Evaluaciones.",
        )
        self.assertIs(raised.exception.__cause__, driver_error)
        self.assertNotIn("internal-user", str(raised.exception))
        self.assertNotIn("internal-host", str(raised.exception))
        self.assertNotIn("secret", str(raised.exception))
        self.assertTrue(connection_context.closed)
        self.assertTrue(connection.closed)
        self.assertFalse(connection.committed)
        self.assertEqual(connection.executed_ddl, [])
        diagnostic_output = "\n".join(diagnostic_logs.output)
        self.assertIn("OperationalError", diagnostic_output)
        self.assertIn("mysql_error_code=1045", diagnostic_output)
        self.assertNotIn("internal-user", diagnostic_output)
        self.assertNotIn("internal-host", diagnostic_output)
        self.assertNotIn("secret", diagnostic_output)

    def test_django_role_is_rejected_without_opening_connection(self):
        context = SimpleNamespace(
            backend_type=EvaluacionConnectionRole.SOURCE_DJANGO,
            mysql_connection=None,
            database_name=None,
        )
        with (
            patch.object(schema, "resolve_operational_backend", return_value=context),
            patch.object(schema, "open_mysql_connection") as open_connection,
        ):
            with self.assertRaises(schema.BaseEvaluacionesSchemaInstallError):
                schema.preview_base_evaluaciones_schema()
        open_connection.assert_not_called()

    def test_install_rejects_changed_destination_before_opening_connection(self):
        context = SimpleNamespace(
            backend_type=EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG,
            mysql_connection=SimpleNamespace(
                pk=12,
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            database_name="other_database",
        )
        with (
            patch.object(schema, "resolve_operational_backend", return_value=context),
            patch.object(schema, "open_mysql_connection") as open_connection,
        ):
            with self.assertRaises(schema.BaseEvaluacionesSchemaInstallError):
                schema.install_base_evaluaciones_schema(
                    expected_fingerprint="fingerprint",
                    expected_missing=("evaluaciones_persona",),
                    expected_connection_id=12,
                    expected_connection_updated_at="2026-01-01T00:00:00+00:00",
                    expected_database_name="evaluaciones",
                )
        open_connection.assert_not_called()

    def test_install_rejects_changed_schema_before_executing_ddl(self):
        target = {
            "connection_config": SimpleNamespace(pk=12),
            "connection_id": 12,
            "connection_updated_at": "2026-01-01T00:00:00+00:00",
            "database_name": "evaluaciones",
        }
        connection = ReadOnlyConnection()
        context = SimpleNamespace(
            backend_type=EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG,
            mysql_connection=SimpleNamespace(
                pk=12,
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            database_name="evaluaciones",
        )
        missing = compatible_snapshot(table_exists=False)
        changed = compatible_snapshot()
        with (
            patch.object(schema, "resolve_operational_backend", return_value=context),
            patch.object(
                schema,
                "open_mysql_connection",
                return_value=nullcontext(connection),
            ),
            patch.object(schema, "_collect_snapshot", return_value=changed),
            patch.object(
                schema,
                "build_base_evaluaciones_schema_statements",
                return_value=[schema._read_frozen_statement()],
            ),
        ):
            with self.assertRaises(schema.BaseEvaluacionesSchemaInstallError):
                schema.install_base_evaluaciones_schema(
                    expected_fingerprint=schema._fingerprint(target, missing),
                    expected_missing=("evaluaciones_persona",),
                    expected_connection_id=12,
                    expected_connection_updated_at="2026-01-01T00:00:00+00:00",
                    expected_database_name="evaluaciones",
                )

        self.assertFalse(connection.committed)
        self.assertEqual(connection.query_cursor.calls, [])

    def test_install_executes_only_create_after_matching_preview(self):
        target = {
            "connection_config": SimpleNamespace(pk=12),
            "connection_id": 12,
            "connection_updated_at": "2026-01-01T00:00:00+00:00",
            "database_name": "evaluaciones",
        }
        connection = ReadOnlyConnection()
        context = SimpleNamespace(
            backend_type=EvaluacionConnectionRole.SOURCE_MYSQL_CONFIG,
            mysql_connection=SimpleNamespace(
                pk=12,
                updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            database_name="evaluaciones",
        )
        missing = compatible_snapshot(table_exists=False)
        fingerprint = schema._fingerprint(target, missing)
        statement = schema._read_frozen_statement()
        with (
            patch.object(schema, "resolve_operational_backend", return_value=context),
            patch.object(
                schema,
                "open_mysql_connection",
                return_value=nullcontext(connection),
            ) as open_connection,
            patch.object(schema, "_collect_snapshot", return_value=missing),
            patch.object(
                schema,
                "build_base_evaluaciones_schema_statements",
                return_value=[statement],
            ),
        ):
            created = schema.install_base_evaluaciones_schema(
                expected_fingerprint=fingerprint,
                expected_missing=("evaluaciones_persona",),
                expected_connection_id=12,
                expected_connection_updated_at="2026-01-01T00:00:00+00:00",
                expected_database_name="evaluaciones",
            )

        self.assertEqual(created, 1)
        self.assertTrue(connection.committed)
        open_connection.assert_called_once_with(
            context.mysql_connection,
            database_name="evaluaciones",
        )
        self.assertEqual(
            [query for query, _params in connection.query_cursor.calls],
            [statement],
        )
        self.assertTrue(statement.startswith("CREATE TABLE `evaluaciones_persona`"))


class BaseEvaluacionesSchemaPermissionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="schema-installer")
        self.company = Empresa.objects.create(codigo="01", descripcion="Empresa 01")
        self.view = Vista.objects.create(
            nombre="Evaluaciones - Conexiones Sql",
            route_name="evaluaciones:connection_roles",
        )
        self.permission = Permiso.objects.create(
            usuario=self.user,
            empresa=self.company,
            vista=self.view,
            ingresar=True,
            supervisor=True,
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["empresa_id"] = self.company.pk
        session.save()
        self.url = reverse("evaluaciones:base_evaluaciones_schema_install")

    @staticmethod
    def _connection_status(source_type="MYSQL_CONFIG"):
        roles = []
        for role, label in EvaluacionConnectionRole.ROLE_CHOICES:
            roles.append(
                {
                    "role": role,
                    "label": label,
                    "status": (
                        "configured"
                        if role == EvaluacionConnectionRole.ROLE_BASE_EVALUACIONES
                        else "missing"
                    ),
                    "source_type": source_type if role == EvaluacionConnectionRole.ROLE_BASE_EVALUACIONES else None,
                    "metadata": {},
                }
            )
        return {
            "configured": False,
            "roles": roles,
            "missing_roles": [],
            "invalid_roles": [],
        }

    def test_supervisor_in_non00_company_can_preview(self):
        preview = {
            "missing": ["evaluaciones_persona"],
            "conflicts": [],
            "tables": [{
                "name": "evaluaciones_persona",
                "classification": "PENDIENTE_CREACION",
                "issues": [],
            }],
            "database_name": "evaluaciones",
            "server_version": "8.0.36",
            "connection_id": 12,
            "connection_updated_at": "2026-01-01T00:00:00+00:00",
            "fingerprint": "signed-preview-value",
        }
        with (
            patch(
                "evaluaciones.views.get_evaluaciones_connection_status",
                return_value=self._connection_status(),
            ),
            patch(
                "evaluaciones.views.preview_base_evaluaciones_schema",
                return_value=preview,
            ),
        ):
            response = self.client.post(self.url, {"schema_action": "preview"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Crear estructura Base Evaluaciones")
        self.assertContains(response, "schema_preview_token")
        self.assertContains(response, "name=\"schema_action\" value=\"confirm\"")

    def test_modify_without_supervisor_cannot_preview_or_install(self):
        self.permission.supervisor = False
        self.permission.modificar = True
        self.permission.save(update_fields=["supervisor", "modificar"])
        with (
            patch("evaluaciones.views.preview_base_evaluaciones_schema") as preview,
            patch("evaluaciones.views.install_base_evaluaciones_schema") as install,
        ):
            preview_response = self.client.post(
                self.url, {"schema_action": "preview"}
            )
            install_response = self.client.post(
                self.url,
                {"schema_action": "confirm", "schema_preview_token": "unused"},
            )

        self.assertEqual(preview_response.status_code, 403)
        self.assertEqual(install_response.status_code, 403)
        preview.assert_not_called()
        install.assert_not_called()

    def test_confirm_requires_supervisor_and_calls_service_only_after_signed_token(self):
        token = signing.dumps(
            {
                "role": EvaluacionConnectionRole.ROLE_BASE_EVALUACIONES,
                "connection_id": 12,
                "connection_updated_at": "2026-01-01T00:00:00+00:00",
                "database_name": "evaluaciones",
                "fingerprint": "signed-preview-value",
                "missing": ["evaluaciones_persona"],
            },
            salt="evaluaciones.base_evaluaciones_schema.preview.v1",
            compress=True,
        )
        with patch("evaluaciones.views.install_base_evaluaciones_schema") as install:
            response = self.client.post(
                self.url,
                {
                    "schema_action": "confirm",
                    "schema_preview_token": token,
                },
            )

        self.assertEqual(response.status_code, 302)
        install.assert_called_once()

    def test_expired_signed_token_is_rejected(self):
        with patch(
            "django.core.signing.time.time",
            return_value=current_time() - 700,
        ):
            token = signing.dumps(
                {"role": EvaluacionConnectionRole.ROLE_BASE_EVALUACIONES},
                salt="evaluaciones.base_evaluaciones_schema.preview.v1",
            )
        with (
            patch(
                "evaluaciones.views.get_evaluaciones_connection_status",
                return_value=self._connection_status(),
            ),
            patch("evaluaciones.views.install_base_evaluaciones_schema") as install,
        ):
            response = self.client.post(
                self.url,
                {
                    "schema_action": "confirm",
                    "schema_preview_token": token,
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "expiró o no es válida", status_code=409)
        install.assert_not_called()

    def test_post_requires_csrf_token(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        session = client.session
        session["empresa_id"] = self.company.pk
        session.save()

        response = client.post(self.url, {"schema_action": "preview"})

        self.assertEqual(response.status_code, 403)

    def test_button_requires_supervisor_and_mysql_role(self):
        self.permission.supervisor = False
        self.permission.save(update_fields=["supervisor"])
        with patch(
            "evaluaciones.views.get_evaluaciones_connection_status",
            return_value=self._connection_status(),
        ):
            response = self.client.get(reverse("evaluaciones:connection_roles"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Crear estructura Base Evaluaciones")

        self.permission.supervisor = True
        self.permission.save(update_fields=["supervisor"])
        with patch(
            "evaluaciones.views.get_evaluaciones_connection_status",
            return_value=self._connection_status(source_type="DJANGO"),
        ):
            response = self.client.get(reverse("evaluaciones:connection_roles"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Crear estructura Base Evaluaciones")

    def test_get_is_not_an_installer_operation(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
