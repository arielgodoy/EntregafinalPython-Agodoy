from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from tareas.models import TareaEliminacionOperacion
from tareas.services.base_tareas_schema import (
    BaseTareasSchemaInstallError,
    preview_logical_restoration_schema,
    read_logical_restoration_schema_contract,
)
from tareas.services.deletion_ledger import (
    DeletionLedgerBackendError,
    DeletionLedgerSchemaError,
    _check_mysql_restoration_schema,
)


class _RestorationSchemaCursor:
    def __init__(
        self,
        *,
        selected_database="tareas",
        server_version="10.11.13-MariaDB",
        engine="InnoDB",
        column=("varchar", 32, "YES"),
        unique=True,
        foreign_key=True,
        delete_rule="NO ACTION",
        update_rule="NO ACTION",
    ):
        self.selected_database = selected_database
        self.server_version = server_version
        self.engine = engine
        self.column = column
        self.unique = unique
        self.foreign_key = foreign_key
        self.delete_rule = delete_rule
        self.update_rule = update_rule
        self.statements = []
        self.rows = ()
        self.row = None

    def execute(self, sql, params=()):
        self.statements.append(sql)
        if "SELECT DATABASE()" in sql:
            self.row = (self.selected_database,)
        elif "SELECT VERSION()" in sql:
            self.row = (self.server_version,)
        elif "information_schema.tables" in sql:
            self.row = (self.engine,)
        elif "information_schema.columns" in sql:
            self.row = self.column
        elif "information_schema.statistics" in sql:
            if "SELECT non_unique " in sql:
                self.rows = ((0,),) if self.unique else ()
            else:
                self.rows = (
                    (("tareas_delop_reverses_uniq", 0, "reverses_operation_id"),)
                    if self.unique
                    else ()
                )
        elif "information_schema.key_column_usage" in sql:
            self.rows = (
                (
                    (
                        TareaEliminacionOperacion._meta.db_table,
                        "operation_id",
                        self.delete_rule,
                        self.update_rule,
                    ),
                )
                if self.foreign_key
                else ()
            )

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows

    def close(self):
        return None


class LogicalRestorationSchemaContractTests(SimpleTestCase):
    def _mysql_context(self, *, database_name="tareas", **cursor_options):
        connection_config = SimpleNamespace(
            pk=17,
            updated_at=datetime(2026, 10, 19, tzinfo=timezone.utc),
        )
        context = SimpleNamespace(
            backend_type="MYSQL_CONFIG",
            mysql_connection=connection_config,
            database_name=database_name,
        )
        cursor = _RestorationSchemaCursor(**cursor_options)
        connection = SimpleNamespace(cursor=lambda: cursor)

        @contextmanager
        def open_connection(*args, **kwargs):
            yield connection

        return context, cursor, open_connection

    def test_contract_contains_only_validated_additions(self):
        statements = read_logical_restoration_schema_contract()

        self.assertEqual(len(statements), 5)
        self.assertEqual(statements[0].split("ADD COLUMN", 1)[0].strip(),
                         "ALTER TABLE `tareas_eliminacion_operacion`")
        self.assertTrue(
            any(statement.startswith("CREATE UNIQUE INDEX") for statement in statements)
        )
        self.assertTrue(
            all(statement.startswith(("ALTER TABLE", "CREATE UNIQUE INDEX"))
                for statement in statements)
        )

    def test_contract_rejects_destructive_sql(self):
        with patch(
            "tareas.services.base_tareas_schema.LOGICAL_RESTORATION_SCHEMA_PATH",
            SimpleNamespace(read_text=lambda encoding: "DROP TABLE tareas_tarea;"),
        ):
            with self.assertRaises(BaseTareasSchemaInstallError):
                read_logical_restoration_schema_contract()

    def test_mysql_preview_is_select_only_and_requires_the_expected_schema(self):
        context, cursor, open_connection = self._mysql_context()
        with (
            patch(
                "tareas.services.base_tareas_schema.resolve_operational_backend",
                return_value=context,
            ),
            patch(
                "tareas.services.base_tareas_schema.open_mysql_connection",
                side_effect=open_connection,
            ),
        ):
            result = preview_logical_restoration_schema()

        self.assertEqual(result["status"], "CURRENT")
        self.assertEqual(result["database_name"], "tareas")
        self.assertEqual(result["server_version"], "10.11.13-MariaDB")
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") for sql in cursor.statements))

    def test_mysql_preview_reports_missing_unique_reference(self):
        context, _cursor, open_connection = self._mysql_context(unique=False)
        with (
            patch(
                "tareas.services.base_tareas_schema.resolve_operational_backend",
                return_value=context,
            ),
            patch(
                "tareas.services.base_tareas_schema.open_mysql_connection",
                side_effect=open_connection,
            ),
        ):
            result = preview_logical_restoration_schema()

        self.assertEqual(result["status"], "SCHEMA_UPDATE_REQUIRED")
        self.assertEqual(result["missing"], ("unique:reverses_operation_id",))

    def test_mysql_preview_rejects_cascading_foreign_key(self):
        context, _cursor, open_connection = self._mysql_context(
            delete_rule="CASCADE",
        )
        with (
            patch(
                "tareas.services.base_tareas_schema.resolve_operational_backend",
                return_value=context,
            ),
            patch(
                "tareas.services.base_tareas_schema.open_mysql_connection",
                side_effect=open_connection,
            ),
        ):
            result = preview_logical_restoration_schema()

        self.assertEqual(result["status"], "SCHEMA_UPDATE_REQUIRED")
        self.assertEqual(
            result["missing"],
            ("foreign_key:reverses_operation_id",),
        )

    def test_mysql_preview_rejects_a_different_configured_database_before_open(self):
        context, _cursor, open_connection = self._mysql_context(
            database_name="other_database",
        )
        with (
            patch(
                "tareas.services.base_tareas_schema.resolve_operational_backend",
                return_value=context,
            ),
            patch(
                "tareas.services.base_tareas_schema.open_mysql_connection",
                side_effect=open_connection,
            ) as open_mysql,
        ):
            with self.assertRaises(BaseTareasSchemaInstallError):
                preview_logical_restoration_schema()

        open_mysql.assert_not_called()

    def test_mysql_preview_rejects_a_mismatched_selected_database(self):
        context, _cursor, open_connection = self._mysql_context(
            selected_database="other_database",
        )
        with (
            patch(
                "tareas.services.base_tareas_schema.resolve_operational_backend",
                return_value=context,
            ),
            patch(
                "tareas.services.base_tareas_schema.open_mysql_connection",
                side_effect=open_connection,
            ),
        ):
            with self.assertRaises(BaseTareasSchemaInstallError):
                preview_logical_restoration_schema()

    def test_django_backend_defers_to_its_migration(self):
        context = SimpleNamespace(
            backend_type="DJANGO",
            django_alias="default",
            mysql_connection=None,
            database_name=None,
        )
        with (
            patch(
                "tareas.services.base_tareas_schema.resolve_operational_backend",
                return_value=context,
            ),
            patch(
                "tareas.services.base_tareas_schema.open_mysql_connection",
            ) as open_mysql,
        ):
            result = preview_logical_restoration_schema()

        self.assertEqual(result["status"], "DJANGO_MIGRATIONS")
        self.assertEqual(result["backend"], "DJANGO")
        open_mysql.assert_not_called()

    def test_mysql_ledger_gate_checks_database_column_unique_and_foreign_key(self):
        cursor = _RestorationSchemaCursor()
        connection = SimpleNamespace(cursor=lambda: cursor)

        _check_mysql_restoration_schema(connection, "tareas")

        self.assertTrue(
            all(sql.lstrip().upper().startswith("SELECT") for sql in cursor.statements)
        )
        with self.assertRaises(DeletionLedgerBackendError):
            _check_mysql_restoration_schema(connection, "other_database")

    def test_mysql_ledger_gate_rejects_missing_unique_or_foreign_key(self):
        for options in ({"unique": False}, {"foreign_key": False}):
            cursor = _RestorationSchemaCursor(**options)
            connection = SimpleNamespace(cursor=lambda: cursor)
            with self.assertRaises(DeletionLedgerSchemaError):
                _check_mysql_restoration_schema(connection, "tareas")

    def test_mysql_ledger_gate_rejects_cascading_reference_rules(self):
        cursor = _RestorationSchemaCursor(delete_rule="CASCADE")
        connection = SimpleNamespace(cursor=lambda: cursor)

        with self.assertRaises(DeletionLedgerSchemaError):
            _check_mysql_restoration_schema(connection, "tareas")
