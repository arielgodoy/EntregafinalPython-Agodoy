from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from tareas.models import Tarea, TareaEliminacionOperacion
from tareas.services.base_tareas_schema import (
    BaseTareasSchemaInstallError,
    preview_logical_deletion_schema,
    read_logical_deletion_schema_contract,
)


class _SchemaCursor:
    def __init__(self, database_name, missing_columns=()):
        self.database_name = database_name
        self.missing_columns = set(missing_columns)
        self.statements = []
        self.rows = ()
        self.row = None

    def execute(self, sql, params=()):
        self.statements.append(sql)
        if "SELECT DATABASE()" in sql:
            self.row = (self.database_name,)
        elif "information_schema.tables" in sql:
            self.rows = tuple(
                (table, "InnoDB")
                for table in params[1:]
            )
        elif "information_schema.columns" in sql:
            required = {
                Tarea._meta.db_table: (
                    "eliminada",
                    "eliminada_en",
                    "eliminada_por_id",
                    "eliminacion_operacion_id",
                ),
                TareaEliminacionOperacion._meta.db_table: ("motivo",),
            }
            self.rows = tuple(
                (table, column)
                for table, columns in required.items()
                for column in columns
                if (table, column) not in self.missing_columns
            )

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows

    def close(self):
        return None


class LogicalDeletionSchemaContractTests(SimpleTestCase):
    def test_sql_contract_contains_only_validated_additions(self):
        statements = read_logical_deletion_schema_contract()

        self.assertEqual(len(statements), 9)
        self.assertTrue(
            all(statement.upper().startswith(("ALTER TABLE", "CREATE INDEX")) for statement in statements)
        )
        self.assertIn("ADD COLUMN `motivo` longtext NULL", statements[-2])

    def test_mysql_preview_reports_missing_additions_without_writing(self):
        connection_config = SimpleNamespace(
            pk=12,
            updated_at=datetime(2026, 10, 17, tzinfo=timezone.utc),
        )
        context = SimpleNamespace(
            backend_type="MYSQL_CONFIG",
            mysql_connection=connection_config,
            database_name="base_tareas",
        )
        cursor = _SchemaCursor(
            "base_tareas",
            missing_columns={(Tarea._meta.db_table, "eliminada")},
        )
        connection = SimpleNamespace(cursor=lambda: cursor)

        @contextmanager
        def opened_connection(*args, **kwargs):
            yield connection

        with (
            patch(
                "tareas.services.base_tareas_schema.resolve_operational_backend",
                return_value=context,
            ),
            patch(
                "tareas.services.base_tareas_schema.open_mysql_connection",
                side_effect=opened_connection,
            ),
        ):
            result = preview_logical_deletion_schema()

        self.assertEqual(result["status"], "SCHEMA_UPDATE_REQUIRED")
        self.assertEqual(
            result["missing_columns"],
            [(Tarea._meta.db_table, "eliminada")],
        )
        self.assertTrue(
            all(statement.startswith("SELECT") for statement in cursor.statements)
        )

    def test_mysql_preview_reports_current_schema(self):
        connection_config = SimpleNamespace(
            pk=12,
            updated_at=datetime(2026, 10, 17, tzinfo=timezone.utc),
        )
        context = SimpleNamespace(
            backend_type="MYSQL_CONFIG",
            mysql_connection=connection_config,
            database_name="base_tareas",
        )
        cursor = _SchemaCursor("base_tareas")
        connection = SimpleNamespace(cursor=lambda: cursor)

        @contextmanager
        def opened_connection(*args, **kwargs):
            yield connection

        with (
            patch(
                "tareas.services.base_tareas_schema.resolve_operational_backend",
                return_value=context,
            ),
            patch(
                "tareas.services.base_tareas_schema.open_mysql_connection",
                side_effect=opened_connection,
            ),
        ):
            result = preview_logical_deletion_schema()

        self.assertEqual(result["status"], "CURRENT")
        self.assertEqual(result["missing_tables"], [])
        self.assertEqual(result["missing_columns"], [])

    def test_contract_rejects_non_additive_sql(self):
        with (
            patch(
                "tareas.services.base_tareas_schema.LOGICAL_DELETION_SCHEMA_PATH",
                SimpleNamespace(
                    read_text=lambda encoding: "DROP TABLE tareas_tarea;"
                ),
            ),
        ):
            with self.assertRaises(BaseTareasSchemaInstallError):
                read_logical_deletion_schema_contract()
