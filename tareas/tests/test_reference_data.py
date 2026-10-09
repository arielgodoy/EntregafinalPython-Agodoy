from contextlib import nullcontext
from copy import deepcopy
from importlib import import_module
from pathlib import Path
import json
import re
from unittest.mock import patch

from django.test import SimpleTestCase

from tareas.services.base_tareas_schema import (
    BaseTareasSchemaInstallError,
    install_base_tareas_schema,
)
from tareas.services.connection_roles import TareaConnectionRoleNotFoundError
from tareas.services.reference_data import (
    BASE_DELAY_CAUSES,
    BaseTareasCauseConflict,
    BaseTareasReferenceDataError,
    ensure_base_tareas_reference_data,
    ensure_mysql_delay_causes,
)


class ReferenceConnection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []
        self.results = []
        self.commits = 0
        self.rollbacks = 0
        self.inserts = 0
        self.fail_at = None
        self.engine = "InnoDB"
        self.tables = set()

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def close(self):
        pass

    def commit(self):
        self.commits += 1

    def rollback(self):
        if hasattr(self, "snapshot"):
            self.rows = deepcopy(self.snapshot)
        self.rollbacks += 1

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        self.results = []
        if sql.startswith("SELECT ENGINE"):
            self.results = [(self.engine,)]
        elif sql == "START TRANSACTION":
            self.snapshot = deepcopy(self.rows)
        elif sql.startswith("SELECT codigo"):
            self.results = [
                row for row in self.rows
                if row[0].casefold() == params[0].casefold()
                or row[1].casefold() == params[1].casefold()
            ]
        elif sql.startswith("INSERT INTO tareas_causaatraso"):
            self.inserts += 1
            if self.inserts == self.fail_at:
                raise RuntimeError("simulated confidential driver failure")
            self.rows.append(tuple(params))
        elif sql.startswith("SELECT 1 FROM information_schema.tables"):
            self.results = [(1,)] if params[1] in self.tables else []
        elif sql.startswith("SELECT TABLE_NAME, TABLE_TYPE, ENGINE, TABLE_COLLATION"):
            self.results = [
                (table, "BASE TABLE", self.engine, "utf8mb4_unicode_ci")
                for table in params[1:]
                if table in self.tables
            ]
        elif sql.startswith("SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, EXTRA"):
            self.results = [
                (table, "id", "BIGINT", "YES", "")
                for table in params[1:]
                if table in self.tables
            ]
        elif sql.startswith("SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME"):
            self.results = []
        elif sql.startswith("SELECT TABLE_NAME, CONSTRAINT_NAME, COLUMN_NAME"):
            self.results = []
        elif sql.startswith("CREATE TABLE IF NOT EXISTS tareas_causaatraso"):
            self.tables.add("tareas_causaatraso")
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.results[0] if self.results else None

    def fetchall(self):
        return self.results


class ReferenceDataTests(SimpleTestCase):
    def test_canonical_rows_match_frozen_migration_exactly(self):
        migration = import_module(
            "tareas.migrations.0009_causaatraso_tarea_fecha_asignacion_and_more"
        )
        self.assertEqual(BASE_DELAY_CAUSES, migration.CAUSAS_ATRASO)
        self.assertEqual(len(BASE_DELAY_CAUSES), 6)

    def test_empty_catalog_creates_exact_official_rows(self):
        connection = ReferenceConnection()
        self.assertEqual(ensure_mysql_delay_causes(connection), 6)
        self.assertEqual(connection.rows, list(BASE_DELAY_CAUSES))
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)

    def test_second_execution_does_not_duplicate(self):
        connection = ReferenceConnection()
        ensure_mysql_delay_causes(connection)
        self.assertEqual(ensure_mysql_delay_causes(connection), 0)
        self.assertEqual(connection.rows, list(BASE_DELAY_CAUSES))
        self.assertEqual(connection.inserts, 6)

    def test_complete_catalog_unchanged_including_extra_rows(self):
        rows = (*BASE_DELAY_CAUSES, ("CUSTOM", "Custom cause"))
        connection = ReferenceConnection(rows)
        self.assertEqual(ensure_mysql_delay_causes(connection), 0)
        self.assertEqual(connection.rows, list(rows))
        self.assertEqual(connection.inserts, 0)

    def test_partial_catalog_completes_only_missing(self):
        connection = ReferenceConnection(BASE_DELAY_CAUSES[:2])
        self.assertEqual(ensure_mysql_delay_causes(connection), 4)
        self.assertEqual(connection.rows, list(BASE_DELAY_CAUSES))

    def test_incompatible_code_aborts_entire_seed_with_official_code(self):
        code = BASE_DELAY_CAUSES[-1][0]
        connection = ReferenceConnection([(code, "Incompatible")])
        with self.assertLogs("tareas.services.reference_data", level="ERROR"):
            with self.assertRaises(BaseTareasCauseConflict) as raised:
                ensure_mysql_delay_causes(connection)
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(connection.rows, [(code, "Incompatible")])
        self.assertEqual(connection.inserts, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_name_or_case_collision_is_not_silently_overwritten(self):
        for row in (
            ("OTHER", BASE_DELAY_CAUSES[0][1]),
            (BASE_DELAY_CAUSES[0][0].lower(), BASE_DELAY_CAUSES[0][1]),
        ):
            with self.subTest(row=row):
                connection = ReferenceConnection([row])
                with self.assertLogs("tareas.services.reference_data", level="ERROR"):
                    with self.assertRaises(BaseTareasCauseConflict):
                        ensure_mysql_delay_causes(connection)
                self.assertEqual(connection.rows, [row])
                self.assertEqual(connection.inserts, 0)

    def test_intermediate_failure_rolls_back_all_inserts_and_sanitizes(self):
        connection = ReferenceConnection()
        connection.fail_at = 3
        with self.assertLogs("tareas.services.reference_data", level="ERROR"):
            with self.assertRaises(BaseTareasReferenceDataError) as raised:
                ensure_mysql_delay_causes(connection)
        self.assertNotIn("confidential", str(raised.exception))
        self.assertEqual(connection.rows, [])
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_nontransactional_catalog_rejected_without_inserts(self):
        connection = ReferenceConnection()
        connection.engine = "MyISAM"
        with self.assertRaises(BaseTareasReferenceDataError):
            ensure_mysql_delay_causes(connection)
        self.assertEqual(connection.inserts, 0)

    def test_only_reference_table_written_without_ids_or_external_tables(self):
        connection = ReferenceConnection()
        ensure_mysql_delay_causes(connection)
        writes = [(sql, params) for sql, params in connection.calls
                  if sql.startswith("INSERT")]
        self.assertEqual(len(writes), 6)
        for sql, params in writes:
            self.assertEqual(
                sql, "INSERT INTO tareas_causaatraso (codigo, nombre) VALUES (%s,%s)"
            )
            self.assertIn(params, BASE_DELAY_CAUSES)

    @patch("tareas.services.reference_data.open_mysql_connection")
    @patch("tareas.services.reference_data.get_tarea_mysql_connection")
    @patch("tareas.services.reference_data.get_tarea_connection")
    def test_public_entry_resolves_base_role_without_company(self, resolve, config, opened):
        connection = ReferenceConnection()
        resolve.return_value = {"type": "MYSQL_CONFIG", "database_name": "tareas"}
        opened.return_value = nullcontext(connection)
        self.assertEqual(ensure_base_tareas_reference_data(), 6)
        resolve.assert_called_once_with("BASE_TAREAS")
        config.assert_called_once_with("BASE_TAREAS")
        opened.assert_called_once_with(config.return_value, database_name="tareas")

    @patch("tareas.services.reference_data.open_mysql_connection")
    @patch("tareas.services.reference_data.get_tarea_connection")
    def test_no_fallback_on_django_or_missing_configuration(self, resolve, opened):
        resolve.return_value = {"type": "DJANGO", "alias": "default"}
        with self.assertRaises(BaseTareasReferenceDataError):
            ensure_base_tareas_reference_data()
        resolve.side_effect = TareaConnectionRoleNotFoundError("missing")
        with self.assertLogs("tareas.services.reference_data", level="ERROR"):
            with self.assertRaises(BaseTareasReferenceDataError):
                ensure_base_tareas_reference_data()
        opened.assert_not_called()

    @patch("tareas.services.base_tareas_schema._read_frozen_schema_statements")
    @patch("tareas.services.base_tareas_schema.open_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_connection")
    def test_structure_bootstrap_twice_keeps_cardinality(self, resolve, config, opened, schema):
        connection = ReferenceConnection()
        resolve.return_value = {"type": "MYSQL_CONFIG", "database_name": "tareas"}
        opened.side_effect = lambda *args, **kwargs: nullcontext(connection)
        schema.return_value = [
            "CREATE TABLE IF NOT EXISTS tareas_causaatraso (id BIGINT)"
        ]
        self.assertEqual(install_base_tareas_schema(), 1)
        self.assertEqual(install_base_tareas_schema(), 1)
        self.assertEqual(connection.rows, list(BASE_DELAY_CAUSES))
        self.assertEqual(connection.inserts, 6)
        self.assertEqual(sum(sql.startswith("CREATE") for sql, _ in connection.calls), 1)
        self.assertEqual(connection.commits, 4)

    @patch("tareas.services.base_tareas_schema._read_frozen_schema_statements")
    @patch("tareas.services.base_tareas_schema.open_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_connection")
    def test_bootstrap_conflict_reports_failure_not_success(self, resolve, config, opened, schema):
        connection = ReferenceConnection([(BASE_DELAY_CAUSES[0][0], "Wrong name")])
        resolve.return_value = {"type": "MYSQL_CONFIG", "database_name": "tareas"}
        opened.return_value = nullcontext(connection)
        schema.return_value = ["CREATE TABLE IF NOT EXISTS tareas_causaatraso (id BIGINT)"]
        with self.assertLogs("tareas.services.reference_data", level="ERROR"):
            with self.assertRaisesMessage(BaseTareasSchemaInstallError, BASE_DELAY_CAUSES[0][0]):
                install_base_tareas_schema()
        self.assertEqual(connection.inserts, 0)
        self.assertEqual(connection.rollbacks, 1)


class ReprogrammingTranslationTests(SimpleTestCase):
    def test_all_reprogramming_keys_exist_once_in_both_catalogs(self):
        root = Path(__file__).resolve().parents[2]
        keys = set()
        for path in (root / "tareas" / "templates" / "tareas").glob("*.html"):
            keys.update(re.findall(r'data-key="(tareas\.reprogramming\.[^"]+)"',
                                   path.read_text(encoding="utf-8")))
        self.assertEqual(len(keys), 23)
        for language in ("sp", "en"):
            text = (root / "static" / "lang" / f"{language}.json").read_text(encoding="utf-8")
            pairs = json.loads(text, object_pairs_hook=list)
            catalog = dict(pairs)
            for key in keys:
                with self.subTest(language=language, key=key):
                    self.assertEqual(sum(name == key for name, _ in pairs), 1)
                    self.assertTrue(catalog[key].strip())
