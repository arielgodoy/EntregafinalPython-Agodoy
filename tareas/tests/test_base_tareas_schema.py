from contextlib import nullcontext
from datetime import datetime, timezone
import inspect
import re
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from django.contrib.auth.models import User
from django.core import signing
from django.db.backends.mysql.base import DatabaseWrapper
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from django.template.loader import render_to_string

from access_control.models import Empresa, Permiso, Vista
from settings.models import SettingsMySQLConnection
from tareas.models import TareaConnectionRole
from tareas.services.base_tareas_schema import (
    BaseTareasSchemaInstallError,
    EXPECTED_OPERATIONAL_MODELS,
    SCHEMA_PATH,
    _compare_schema_snapshot,
    _schema_fingerprint,
    build_base_tareas_schema_statements,
    complete_base_tareas_reference_data,
    get_operational_models,
    install_base_tareas_schema,
    preview_base_tareas_schema,
)
from tareas.services.reference_data import (
    BASE_DELAY_CAUSES,
    inspect_mysql_delay_causes,
)
from tareas.views import (
    _BASE_TAREAS_SEED_PREVIEW_SALT,
    BaseTareasSchemaInstallView,
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


class BaseTareasSchemaBasicTests(SimpleTestCase):
    def test_schema_comparator_classifies_missing_tables(self):
        snapshot = {
            "expected": {
                "tables": {
                    "tareas_tarea": {
                        "columns": {},
                        "primary": (),
                        "unique": set(),
                        "ordinary": set(),
                    }
                },
                "foreign_keys": set(),
            },
            "actual": {
                "tables": {},
                "columns": {},
                "indexes": {},
                "foreign_keys": set(),
            },
        }

        result = _compare_schema_snapshot(snapshot, "tareas")

        self.assertEqual(result["missing"], ["tareas_tarea"])
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["tables"][0]["classification"], "PENDIENTE_CREACION")

    def test_schema_comparator_blocks_column_type_mismatch(self):
        snapshot = {
            "expected": {
                "tables": {
                    "tareas_tarea": {
                        "columns": {
                            "id": {
                                "type": "bigint",
                                "nullable": "NO",
                                "auto_increment": False,
                            }
                        },
                        "primary": ("id",),
                        "unique": set(),
                        "ordinary": set(),
                    }
                },
                "foreign_keys": set(),
            },
            "actual": {
                "tables": {
                    "tareas_tarea": {
                        "type": "BASE TABLE",
                        "engine": "InnoDB",
                        "collation": "utf8mb4_unicode_ci",
                    }
                },
                "columns": {
                    "tareas_tarea": {
                        "id": {
                            "type": "int",
                            "nullable": "NO",
                            "auto_increment": False,
                        }
                    }
                },
                "indexes": {"tareas_tarea": []},
                "foreign_keys": set(),
            },
        }

        result = _compare_schema_snapshot(snapshot, "tareas")

        self.assertEqual(result["existing"], [])
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertIn("COLUMN_TYPE_MISMATCH", result["conflicts"][0]["issues"])


class BaseTareasSchemaComparatorPureTests(SimpleTestCase):
    def _snapshot(self, *, actual=None, expected=None):
        expected = expected or {
            "tareas_tarea": {
                "columns": {
                    "id": {
                        "type": "bigint",
                        "nullable": "NO",
                        "auto_increment": False,
                    },
                    "nombre": {
                        "type": "varchar(100)",
                        "nullable": "YES",
                        "auto_increment": False,
                    },
                },
                "primary": ("id",),
                "unique": {("nombre",)},
                "ordinary": {("nombre",)},
            }
        }
        actual = actual or {
            "tables": {
                "tareas_tarea": {
                    "type": "BASE TABLE",
                    "engine": "InnoDB",
                    "collation": "utf8mb4_unicode_ci",
                }
            },
            "columns": {
                "tareas_tarea": {
                    "id": {
                        "type": "bigint",
                        "nullable": "NO",
                        "auto_increment": False,
                    },
                    "nombre": {
                        "type": "varchar(100)",
                        "nullable": "YES",
                        "auto_increment": False,
                    },
                }
            },
            "indexes": {
                "tareas_tarea": [
                    {"name": "PRIMARY", "unique": True, "columns": ("id",)},
                    {"name": "nombre_unique", "unique": True, "columns": ("nombre",)},
                    {"name": "nombre_idx", "unique": False, "columns": ("nombre",)},
                ]
            },
            "foreign_keys": set(),
        }
        return {
            "expected": {
                "tables": expected,
                "foreign_keys": set(),
            },
            "actual": actual,
        }

    def _issues(self, snapshot):
        return set(_compare_schema_snapshot(snapshot, "tareas")["conflicts"][0]["issues"])

    def test_compatible_table(self):
        result = _compare_schema_snapshot(self._snapshot(), "tareas")
        self.assertEqual(result["existing"], ["tareas_tarea"])
        self.assertEqual(result["conflicts"], [])

    def test_nullability_column_and_primary_key_mismatches(self):
        snapshot = self._snapshot()
        snapshot["actual"]["columns"]["tareas_tarea"]["nombre"]["nullable"] = "NO"
        del snapshot["actual"]["columns"]["tareas_tarea"]["id"]
        snapshot["actual"]["indexes"]["tareas_tarea"][0]["columns"] = ("nombre",)
        issues = self._issues(snapshot)
        self.assertIn("NULLABILITY_MISMATCH", issues)
        self.assertIn("COLUMN_SET_MISMATCH", issues)
        self.assertIn("PRIMARY_KEY_MISMATCH", issues)

    def test_type_engine_and_collation_mismatches(self):
        snapshot = self._snapshot()
        snapshot["actual"]["columns"]["tareas_tarea"]["nombre"]["type"] = "text"
        snapshot["actual"]["tables"]["tareas_tarea"]["engine"] = "MyISAM"
        snapshot["actual"]["tables"]["tareas_tarea"]["collation"] = "latin1_swedish_ci"
        issues = self._issues(snapshot)
        self.assertIn("COLUMN_TYPE_MISMATCH", issues)
        self.assertIn("ENGINE_MISMATCH", issues)
        self.assertIn("COLLATION_MISMATCH", issues)

    def test_missing_normal_index_and_unique_block(self):
        snapshot = self._snapshot()
        snapshot["actual"]["indexes"]["tareas_tarea"] = [
            {"name": "PRIMARY", "unique": True, "columns": ("id",)}
        ]
        issues = self._issues(snapshot)
        self.assertIn("INDEX_MISSING", issues)
        self.assertIn("UNIQUE_CONSTRAINT_MISSING", issues)

    def test_missing_internal_foreign_key_blocks(self):
        snapshot = self._snapshot(
            expected={
                "tareas_padre": {
                    "columns": {
                        "id": {
                            "type": "bigint",
                            "nullable": "NO",
                            "auto_increment": False,
                        }
                    },
                    "primary": ("id",),
                    "unique": set(),
                    "ordinary": set(),
                },
                "tareas_tarea": {
                    "columns": {
                        "id": {
                            "type": "bigint",
                            "nullable": "NO",
                            "auto_increment": False,
                        },
                        "padre_id": {
                            "type": "bigint",
                            "nullable": "NO",
                            "auto_increment": False,
                        },
                    },
                    "primary": ("id",),
                    "unique": set(),
                    "ordinary": set(),
                },
            }
        )
        snapshot["expected"]["foreign_keys"] = {
            ("tareas_tarea", ("padre_id",), "tareas_padre", ("id",))
        }
        snapshot["actual"]["tables"]["tareas_padre"] = snapshot["actual"]["tables"]["tareas_tarea"].copy()
        snapshot["actual"]["columns"]["tareas_padre"] = {
            "id": {
                "type": "bigint",
                "nullable": "NO",
                "auto_increment": False,
            }
        }
        snapshot["actual"]["indexes"]["tareas_padre"] = [
            {"name": "PRIMARY", "unique": True, "columns": ("id",)}
        ]
        snapshot["actual"]["columns"]["tareas_tarea"]["padre_id"] = {
            "type": "bigint",
            "nullable": "NO",
            "auto_increment": False,
        }
        snapshot["actual"]["indexes"]["tareas_tarea"] = [
            {"name": "PRIMARY", "unique": True, "columns": ("id",)}
        ]
        result = _compare_schema_snapshot(snapshot, "tareas")
        conflict = next(item for item in result["conflicts"] if item["name"] == "tareas_tarea")
        self.assertIn("FOREIGN_KEY_MISMATCH", conflict["issues"])

    def test_unexpected_external_foreign_key_blocks(self):
        snapshot = self._snapshot()
        snapshot["actual"]["foreign_keys"] = {
            (
                "tareas_tarea",
                ("empresa_id",),
                "core",
                "empresa",
                ("id",),
            )
        }
        issues = self._issues(snapshot)
        self.assertIn("CROSS_DATABASE_FOREIGN_KEY", issues)

    def test_fingerprint_is_stable_deterministic_and_changes_structurally(self):
        snapshot = self._snapshot()
        first = _schema_fingerprint("tareas", 1, snapshot)
        second = _schema_fingerprint("tareas", 1, self._snapshot())
        self.assertEqual(first, second)
        snapshot["actual"]["tables"]["tareas_tarea"]["engine"] = "MyISAM"
        self.assertNotEqual(first, _schema_fingerprint("tareas", 1, snapshot))


class BaseTareasReferenceDataPreviewTests(SimpleTestCase):
    class _Cursor:
        def __init__(self, rows):
            self.rows = rows
            self.statements = []

        def execute(self, sql, params=()):
            self.statements.append((sql, params))

        def fetchone(self):
            return ("InnoDB",)

        def fetchall(self):
            return self.rows

        def close(self):
            return None

    class _Connection:
        def __init__(self, rows):
            self.cursor_instance = BaseTareasReferenceDataPreviewTests._Cursor(rows)

        def cursor(self):
            return self.cursor_instance

    def test_inspector_classifies_complete_and_incomplete_without_writes(self):
        connection = self._Connection(BASE_DELAY_CAUSES)

        complete, missing_count = inspect_mysql_delay_causes(connection)

        self.assertTrue(complete)
        self.assertEqual(missing_count, 0)
        self.assertEqual(
            [sql.split(None, 1)[0].upper() for sql, _params in connection.cursor_instance.statements],
            ["SELECT", "SELECT"],
        )

        partial_connection = self._Connection(BASE_DELAY_CAUSES[:-1])
        complete, missing_count = inspect_mysql_delay_causes(partial_connection)
        self.assertFalse(complete)
        self.assertEqual(missing_count, 1)

    def test_preview_reports_seed_state_and_never_runs_seed(self):
        config = SimpleNamespace(
            pk=7,
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        with patch(
            "tareas.services.base_tareas_schema.get_tarea_connection",
            return_value={
                "type": "MYSQL_CONFIG",
                "connection_id": 7,
                "database_name": "tareas",
            },
        ), patch(
            "tareas.services.base_tareas_schema.get_tarea_mysql_connection",
            return_value=config,
        ), patch(
            "tareas.services.base_tareas_schema.open_mysql_connection",
            return_value=nullcontext(MagicMock()),
        ), patch(
            "tareas.services.base_tareas_schema._fetch_schema_snapshot",
            return_value={"snapshot": True},
        ), patch(
            "tareas.services.base_tareas_schema._compare_schema_snapshot",
            side_effect=[
                {
                    "tables": [],
                    "existing": ["tareas_causaatraso"],
                    "missing": [],
                    "conflicts": [],
                },
                {
                    "tables": [],
                    "existing": ["tareas_causaatraso"],
                    "missing": [],
                    "conflicts": [],
                },
            ],
        ), patch(
            "tareas.services.base_tareas_schema._schema_fingerprint",
            return_value="stable-fingerprint",
        ), patch(
            "tareas.services.base_tareas_schema.inspect_mysql_delay_causes",
            side_effect=[(False, 2), (True, 0)],
        ) as inspect_seed, patch(
            "tareas.services.base_tareas_schema.ensure_mysql_delay_causes"
        ) as ensure_seed:
            incomplete_result = preview_base_tareas_schema()
            complete_result = preview_base_tareas_schema()

        self.assertFalse(incomplete_result["reference_data_complete"])
        self.assertEqual(incomplete_result["reference_data_missing_count"], 2)
        self.assertTrue(complete_result["reference_data_complete"])
        self.assertEqual(complete_result["reference_data_missing_count"], 0)
        self.assertEqual(inspect_seed.call_count, 2)
        ensure_seed.assert_not_called()
        self.assertEqual(incomplete_result["connection_id"], 7)
        self.assertEqual(
            incomplete_result["connection_updated_at"],
            config.updated_at.isoformat(),
        )
        self.assertEqual(incomplete_result["fingerprint"], "stable-fingerprint")


class BaseTareasSeedServiceTests(SimpleTestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            pk=7,
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.connection = MagicMock()
        self.source = {
            "type": "MYSQL_CONFIG",
            "connection_id": 7,
            "database_name": "tareas",
        }

    def _patch_target(self):
        patches = [
            patch(
                "tareas.services.base_tareas_schema.get_tarea_connection",
                return_value=self.source,
            ),
            patch(
                "tareas.services.base_tareas_schema.get_tarea_mysql_connection",
                return_value=self.config,
            ),
            patch(
                "tareas.services.base_tareas_schema.open_mysql_connection",
                return_value=nullcontext(self.connection),
            ),
            patch(
                "tareas.services.base_tareas_schema._fetch_schema_snapshot",
                return_value={"snapshot": True},
            ),
            patch(
                "tareas.services.base_tareas_schema._compare_schema_snapshot",
                return_value={"missing": [], "conflicts": []},
            ),
            patch(
                "tareas.services.base_tareas_schema._schema_fingerprint",
                return_value="signed-fingerprint",
            ),
        ]
        return patches

    def test_changed_connection_configuration_blocks_seed(self):
        with patch(
            "tareas.services.base_tareas_schema.get_tarea_connection",
            return_value=self.source,
        ), patch(
            "tareas.services.base_tareas_schema.get_tarea_mysql_connection",
            return_value=self.config,
        ), patch(
            "tareas.services.base_tareas_schema.open_mysql_connection"
        ) as open_connection:
            with self.assertRaises(BaseTareasSchemaInstallError):
                complete_base_tareas_reference_data(
                    expected_connection_id=8,
                    expected_connection_updated_at=self.config.updated_at.isoformat(),
                    expected_database_name="tareas",
                    expected_fingerprint="signed-fingerprint",
                )
        open_connection.assert_not_called()

    def test_incompatible_or_missing_schema_blocks_seed(self):
        for plan in ({"missing": ["tareas"], "conflicts": []},
                     {"missing": [], "conflicts": [{"name": "tareas"}]}):
            patches = self._patch_target()
            with patches[0], patches[1], patches[2], patches[3], patch(
                "tareas.services.base_tareas_schema._compare_schema_snapshot",
                return_value=plan,
            ), patches[5], patch(
                "tareas.services.base_tareas_schema.ensure_mysql_delay_causes"
            ) as ensure_seed:
                with self.assertRaises(BaseTareasSchemaInstallError):
                    complete_base_tareas_reference_data(
                        expected_connection_id=7,
                        expected_connection_updated_at=self.config.updated_at.isoformat(),
                        expected_database_name="tareas",
                        expected_fingerprint="signed-fingerprint",
                    )
                ensure_seed.assert_not_called()

    def test_seed_complete_is_idempotent_and_incomplete_uses_existing_seed(self):
        patches = self._patch_target()
        for complete, expected_count in ((True, 0), (False, 3)):
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patch(
                "tareas.services.base_tareas_schema.inspect_mysql_delay_causes",
                return_value=(complete, 0 if complete else 3),
            ), patch(
                "tareas.services.base_tareas_schema.ensure_mysql_delay_causes",
                return_value=3,
            ) as ensure_seed:
                inserted = complete_base_tareas_reference_data(
                    expected_connection_id=7,
                    expected_connection_updated_at=self.config.updated_at.isoformat(),
                    expected_database_name="tareas",
                    expected_fingerprint="signed-fingerprint",
                )
                self.assertEqual(inserted, expected_count)
                self.assertEqual(ensure_seed.called, not complete)


class BaseTareasSeedViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.config = SimpleNamespace(
            pk=7,
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        self.payload = {
            "role": "BASE_TAREAS",
            "connection_id": 7,
            "connection_updated_at": self.config.updated_at.isoformat(),
            "database_name": "tareas",
            "fingerprint": "schema-fingerprint",
            "reference_data_complete": False,
        }

    def _post_seed(self, token):
        request = self.factory.post(
            "/tareas/conexiones-sql/base-schema/",
            {
                "schema_action": "seed",
                "seed_preview_token": token,
            },
        )
        with patch("tareas.views.messages.success"), patch(
            "tareas.views.messages.info"
        ), patch("tareas.views.messages.error"), patch(
            "tareas.views.get_tarea_connection",
            return_value={"type": "MYSQL_CONFIG", "database_name": "tareas"},
        ), patch(
            "tareas.views.get_tarea_mysql_connection",
            return_value=self.config,
        ):
            return BaseTareasSchemaInstallView().post(request)

    def test_valid_seed_token_invokes_revalidating_service(self):
        token = signing.dumps(self.payload, salt=_BASE_TAREAS_SEED_PREVIEW_SALT)
        with patch(
            "tareas.views.complete_base_tareas_reference_data",
            return_value=2,
        ) as complete_seed:
            response = self._post_seed(token)
        self.assertEqual(response.status_code, 302)
        complete_seed.assert_called_once_with(
            expected_connection_id=7,
            expected_connection_updated_at=self.config.updated_at.isoformat(),
            expected_database_name="tareas",
            expected_fingerprint="schema-fingerprint",
        )

    def test_invalid_and_expired_seed_tokens_do_not_call_seed(self):
        with patch(
            "tareas.views.complete_base_tareas_reference_data"
        ) as complete_seed:
            invalid_response = self._post_seed("not-a-signed-token")
            self.assertEqual(invalid_response.status_code, 302)
            with patch(
                "tareas.views.signing.loads",
                side_effect=signing.SignatureExpired("expired"),
            ):
                expired_response = self._post_seed("expired-token")
        self.assertEqual(expired_response.status_code, 302)
        complete_seed.assert_not_called()

    def test_changed_database_blocks_seed_token(self):
        token = signing.dumps(
            {**self.payload, "database_name": "other"},
            salt=_BASE_TAREAS_SEED_PREVIEW_SALT,
        )
        with patch(
            "tareas.views.complete_base_tareas_reference_data"
        ) as complete_seed:
            response = self._post_seed(token)
        self.assertEqual(response.status_code, 302)
        complete_seed.assert_not_called()


class BaseTareasSchemaPreviewTemplateTests(SimpleTestCase):
    def _render_preview(self, preview, schema_token=None, seed_token=None):
        return render_to_string(
            "tareas/tarea_conexiones_sql.html",
            {
                "role_forms": [],
                "connection_status": {"roles": []},
                "can_install_base_tareas": True,
                "base_tareas_database_name": "tareas",
                "schema_preview": preview,
                "schema_preview_token": schema_token,
                "seed_preview_token": seed_token,
                "csrf_token": "test-csrf-token",
            },
        )

    def test_complete_schema_and_seed_hide_actions(self):
        html = self._render_preview(
            {
                "tables": [],
                "missing": [],
                "conflicts": [],
                "reference_data_complete": True,
            }
        )
        self.assertIn("Todas las tablas ya existen y son compatibles.", html)
        self.assertIn("Los datos base también están completos.", html)
        self.assertNotIn("Confirmar creación", html)
        self.assertNotIn("Completar datos base", html)

    def test_complete_schema_with_incomplete_seed_shows_seed_only(self):
        html = self._render_preview(
            {
                "tables": [],
                "missing": [],
                "conflicts": [],
                "reference_data_complete": False,
            },
            seed_token="signed-seed-token",
        )
        self.assertIn("Faltan datos base.", html)
        self.assertIn("Completar datos base", html)
        self.assertNotIn("Confirmar creación", html)

    def test_missing_schema_shows_structural_confirm_only(self):
        html = self._render_preview(
            {
                "tables": [],
                "missing": ["tareas_a"],
                "conflicts": [],
                "reference_data_complete": None,
            },
            schema_token="signed-schema-token",
        )
        self.assertIn("Confirmar creación", html)
        self.assertNotIn("Completar datos base", html)

    def test_conflict_hides_both_actions(self):
        html = self._render_preview(
            {
                "tables": [],
                "missing": [],
                "conflicts": [{"name": "tareas_a"}],
                "reference_data_complete": None,
            },
            seed_token="must-not-show",
        )
        self.assertIn("Se detectaron tablas incompatibles.", html)
        self.assertNotIn("Confirmar creación", html)
        self.assertNotIn("Completar datos base", html)


class BaseTareasSchemaServiceTests(SimpleTestCase):
    def _mysql_context(self):
        connection = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        def execute(sql, params=()):
            if sql.startswith("SELECT ENGINE"):
                cursor.fetchone.side_effect = None
                cursor.fetchone.return_value = ("InnoDB",)
        cursor.execute.side_effect = execute
        connection.cursor.return_value = cursor
        return connection, cursor

    @patch("tareas.services.base_tareas_schema.open_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_connection")
    def test_confirm_rejects_changed_configuration_before_opening(
        self,
        get_connection,
        get_mysql_connection,
        open_connection,
    ):
        config = SimpleNamespace(
            pk=7,
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        get_connection.return_value = {
            "type": "MYSQL_CONFIG",
            "connection_id": 7,
            "database_name": "tareas",
        }
        get_mysql_connection.return_value = config

        with self.assertRaises(BaseTareasSchemaInstallError):
            install_base_tareas_schema(
                expected_fingerprint="signed-fingerprint",
                expected_missing=("tareas_tarea",),
                expected_connection_id=7,
                expected_connection_updated_at="2026-01-02T00:00:00+00:00",
                expected_database_name="tareas",
            )

        open_connection.assert_not_called()

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

        with patch(
            "tareas.services.base_tareas_schema._fetch_schema_snapshot",
            return_value={},
        ), patch(
            "tareas.services.base_tareas_schema._compare_schema_snapshot",
            return_value={"missing": ["tareas_tarea"], "conflicts": []},
        ), patch(
            "tareas.services.base_tareas_schema.ensure_mysql_delay_causes",
            side_effect=lambda _connection: self.assertEqual(
                connection.commit.call_count,
                1,
            ),
        ) as ensure_seed:
            processed = install_base_tareas_schema()

        self.assertEqual(processed, 1)
        get_connection.assert_called_once_with("BASE_TAREAS")
        open_connection.assert_called_once()
        self.assertIn(read_schema.return_value[0], [
            call.args[0] for call in cursor.execute.call_args_list
        ])
        ensure_seed.assert_called_once_with(connection)
        self.assertEqual(connection.commit.call_count, 1)
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

        with patch(
            "tareas.services.base_tareas_schema._fetch_schema_snapshot",
            return_value={},
        ), patch(
            "tareas.services.base_tareas_schema._compare_schema_snapshot",
            return_value={"missing": ["tareas_tarea"], "conflicts": []},
        ), self.assertRaises(BaseTareasSchemaInstallError) as raised:
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

        with patch(
            "tareas.services.base_tareas_schema._fetch_schema_snapshot",
            return_value={},
        ), patch(
            "tareas.services.base_tareas_schema._compare_schema_snapshot",
            return_value={"missing": [], "conflicts": []},
        ):
            processed = install_base_tareas_schema()

        self.assertEqual(processed, 3)
        self.assertFalse(any(
            call.args[0].startswith(("CREATE TABLE", "CREATE INDEX", "ALTER TABLE"))
            for call in cursor.execute.call_args_list
        ))
        self.assertEqual(connection.commit.call_count, 2)

    @patch("tareas.services.base_tareas_schema._read_frozen_schema_statements")
    @patch("tareas.services.base_tareas_schema.open_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_mysql_connection")
    @patch("tareas.services.base_tareas_schema.get_tarea_connection")
    def test_partial_schema_creates_only_missing_object(
        self, get_connection, get_mysql_connection, open_connection, read_schema
    ):
        connection, cursor = self._mysql_context()
        cursor.fetchone.return_value = None
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

        with patch(
            "tareas.services.base_tareas_schema._fetch_schema_snapshot",
            return_value={},
        ), patch(
            "tareas.services.base_tareas_schema._compare_schema_snapshot",
            return_value={"missing": ["tareas_tarea"], "conflicts": []},
        ):
            install_base_tareas_schema()

        executed = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertIn(read_schema.return_value[0], executed)
        self.assertIn(read_schema.return_value[1], executed)
        self.assertEqual(connection.commit.call_count, 2)


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

    @patch("tareas.views.preview_base_tareas_schema")
    @patch("tareas.views.install_base_tareas_schema")
    def test_endpoint_is_post_only_and_requires_supervisor(self, install, preview):
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
        preview.return_value = {
            "tables": [],
            "existing": [],
            "missing": [],
            "conflicts": [],
            "fingerprint": "fingerprint",
        }
        response = self.client.post(url, {"schema_action": "preview"})

        self.assertEqual(response.status_code, 200)
        preview.assert_called_once_with()
        install.assert_not_called()
