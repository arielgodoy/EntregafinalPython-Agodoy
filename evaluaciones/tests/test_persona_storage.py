from contextlib import contextmanager
import ast
from copy import deepcopy
import re
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from django.db import connections
from django.test import SimpleTestCase

from evaluaciones.models import Persona
from evaluaciones.services import persona_storage
from evaluaciones.services.persona_importer import (
    PersonaImportServiceError,
    importar_personas_desde_api_interna,
)
from evaluaciones.services.connection_roles import (
    EvaluacionesConnectionInactiveError,
    EvaluacionesConnectionRoleNotFoundError,
)
from evaluaciones.services.persona_storage import (
    DjangoPersonaStorage,
    PersonaStorageError,
    open_persona_storage,
)
from settings.services.mysql_connections import MySQLConnectionOpenError


def _employee_payload(person_id: int, full_name: str = "Ana Pérez") -> dict:
    return {
        "person_id": person_id,
        "full_name": full_name,
        "first_name": "Ana",
        "surname": "Pérez",
        "second_surname": "Gómez",
        "email": "ana@example.com",
        "birthday": "1989-12-01",
        "active_since": "2024-03-14",
        "created_at": "2025-03-07T15:56:12.444-03:00",
        "progressive_vacations_start": "2037-03-14",
    }


def _one_page(*employees: dict) -> dict:
    return {"pagination": {"next": None}, "data": list(employees)}


class _MemoryDatabase:
    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.next_id = 1
        self.snapshot = None
        self.statements: list[str] = []
        self.batch_sizes: list[int] = []
        self.connections = []
        self.fail_update = False
        self.cursor_close_count = 0


class _MemoryMySQLConnection:
    def __init__(self, database: _MemoryDatabase):
        self.database = database
        self.closed = False
        database.connections.append(self)

    def begin(self):
        self.database.snapshot = deepcopy(self.database.rows)

    def commit(self):
        self.database.snapshot = None

    def rollback(self):
        if self.database.snapshot is not None:
            self.database.rows = self.database.snapshot
            self.database.snapshot = None

    def cursor(self):
        return _MemoryCursor(self.database)

    def close(self):
        self.closed = True


class _MemoryCursor:
    def __init__(self, database: _MemoryDatabase):
        self.database = database
        self.rows = []
        self.closed = False

    def execute(self, query: str, params=()):
        self.database.statements.append(query)
        if query.startswith("SELECT COUNT(*)"):
            self.rows = [(len(self.database.rows),)]
            return

        columns = _selected_columns(query)
        if " WHERE `person_id` IN " in query:
            wanted_ids = set(params)
            self.rows = [
                tuple(row.get(column) for column in columns)
                for row in self.database.rows.values()
                if row["person_id"] in wanted_ids
            ]
            return

        if " ORDER BY " in query:
            limit = params[0]
            rows = sorted(
                self.database.rows.values(),
                key=lambda row: (-row["anio"], -row["mes"], row["full_name"]),
            )
            self.rows = [
                tuple(row.get(column) for column in columns)
                for row in rows[:limit]
            ]
            return

        raise AssertionError(f"Unexpected SQL in test double: {query}")

    def executemany(self, query: str, parameter_rows):
        self.database.statements.append(query)
        parameter_rows = list(parameter_rows)
        self.database.batch_sizes.append(len(parameter_rows))

        if query.startswith("INSERT INTO "):
            columns = _insert_columns(query)
            for params in parameter_rows:
                row = dict(zip(columns, params))
                if any(
                    existing["person_id"] == row["person_id"]
                    for existing in self.database.rows.values()
                ):
                    raise RuntimeError("duplicate person_id")
                row["id"] = self.database.next_id
                self.database.rows[self.database.next_id] = row
                self.database.next_id += 1
            return

        if query.startswith("UPDATE "):
            assignments = query.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
            columns = re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)` = %s", assignments)
            identity_column = re.search(r"WHERE `([A-Za-z_][A-Za-z0-9_]*)` = %s", query)
            if identity_column is None:
                raise AssertionError("Missing identity column in update.")
            for params in parameter_rows:
                row = self.database.rows[params[-1]]
                row.update(zip(columns, params[:-1]))
                if self.database.fail_update:
                    raise RuntimeError("simulated driver failure")
            return

        raise AssertionError(f"Unexpected SQL in test double: {query}")

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def close(self):
        self.closed = True
        self.database.cursor_close_count += 1


def _selected_columns(query: str) -> list[str]:
    select = query.split(" FROM ", 1)[0][len("SELECT ") :]
    return re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", select)


def _insert_columns(query: str) -> list[str]:
    match = re.search(r"\((.*?)\) VALUES", query)
    if match is None:
        raise AssertionError("Missing columns in insert.")
    return re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", match.group(1))


class DjangoPersonaStorageTests(SimpleTestCase):
    def test_orm_operations_use_the_selected_alias(self):
        storage = DjangoPersonaStorage("system_test")
        manager = Mock()
        manager.using.return_value.filter.return_value = []
        manager.using.return_value.bulk_create.return_value = []
        manager.using.return_value.bulk_update.return_value = 1

        with patch.object(Persona, "objects", manager):
            self.assertEqual(storage.existing_by_person_id([123]), {})
            storage.bulk_create([Persona(person_id=123)], batch_size=200)
            storage.bulk_update([Persona(pk=1)], ["full_name"], batch_size=200)

        self.assertEqual(manager.using.call_count, 3)
        self.assertTrue(
            all(call.args == ("system_test",) for call in manager.using.call_args_list)
        )

    def test_list_and_count_use_the_selected_alias(self):
        storage = DjangoPersonaStorage("system_test")
        manager = Mock()
        queryset = MagicMock()
        manager.using.return_value = queryset
        queryset.all.return_value.order_by.return_value.__getitem__.return_value = []
        queryset.count.return_value = 0

        with patch.object(Persona, "objects", manager):
            self.assertEqual(storage.list_people(5000), [])
            self.assertEqual(storage.count(), 0)

        self.assertEqual(manager.using.call_count, 2)
        self.assertTrue(
            all(call.args == ("system_test",) for call in manager.using.call_args_list)
        )

    def test_atomic_uses_the_selected_alias(self):
        storage = DjangoPersonaStorage("system_test")
        with patch(
            "evaluaciones.services.persona_storage.transaction.atomic"
        ) as atomic:
            atomic.return_value.__enter__.return_value = None
            with storage.atomic():
                pass
        atomic.assert_called_once_with(using="system_test")

    def test_connection_factory_rejects_default_alias(self):
        @contextmanager
        def use_default(_role):
            yield connections["default"]

        with patch.object(persona_storage, "open_evaluaciones_connection", use_default):
            with self.assertRaises(PersonaStorageError):
                with open_persona_storage():
                    self.fail("default must not be used as the operational destination")

    def test_connection_factory_uses_selected_django_alias(self):
        @contextmanager
        def use_system_test(role):
            self.assertEqual(role, "BASE_EVALUACIONES")
            yield connections["system_test"]

        with patch.object(
            persona_storage,
            "open_evaluaciones_connection",
            use_system_test,
        ):
            with open_persona_storage() as storage:
                self.assertIsInstance(storage, DjangoPersonaStorage)
                self.assertEqual(storage.alias, "system_test")

    def test_storage_module_does_not_import_other_business_apps(self):
        with open(persona_storage.__file__, encoding="utf-8") as module_file:
            tree = ast.parse(module_file.read())

        imports = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        imports.extend(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        self.assertFalse(
            any(
                name == "tareas"
                or name.startswith("tareas.")
                or name == "gestiondte"
                or name.startswith("gestiondte.")
                for name in imports
            )
        )


class MySQLPersonaStorageTests(TestCase):
    def setUp(self):
        self.database = _MemoryDatabase()

    @contextmanager
    def _open_connection(self, role):
        self.assertEqual(role, "BASE_EVALUACIONES")
        connection = _MemoryMySQLConnection(self.database)
        try:
            yield connection
        finally:
            connection.close()

    def _run_import(self, payload):
        with patch.object(
            persona_storage,
            "open_evaluaciones_connection",
            self._open_connection,
        ), patch("api.services.buk_api.fetch_active_employees") as fetch, patch(
            "api.services.buk_api.fetch_buk_url"
        ) as fetch_next:
            fetch.return_value = payload
            result = importar_personas_desde_api_interna("2026-03-07", True)
            fetch.assert_called_once()
            fetch_next.assert_not_called()
        return result

    def test_mysql_config_creates_updates_by_person_id_and_preserves_counts(self):
        created = self._run_import(_one_page(_employee_payload(100, "Nombre Inicial")))
        self.assertEqual((created.creados, created.actualizados, created.omitidos), (1, 0, 0))
        self.assertEqual(len(self.database.rows), 1)
        stored = next(iter(self.database.rows.values()))
        self.assertEqual(stored["person_id"], 100)
        self.assertEqual(stored["full_name"], "Nombre Inicial")

        updated = self._run_import(_one_page(_employee_payload(100, "Nombre Nuevo")))
        self.assertEqual((updated.creados, updated.actualizados, updated.omitidos), (0, 1, 0))
        self.assertEqual(len(self.database.rows), 1)
        stored = next(iter(self.database.rows.values()))
        self.assertEqual(stored["full_name"], "Nombre Nuevo")
        self.assertEqual(stored["mes"], 3)
        self.assertEqual(stored["anio"], 2026)
        self.assertTrue(all(connection.closed for connection in self.database.connections))
        self.assertTrue(all(statement.startswith(("SELECT", "INSERT", "UPDATE")) for statement in self.database.statements))

    def test_duplicate_person_ids_keep_last_payload_without_duplicate_rows(self):
        result = self._run_import(
            _one_page(
                _employee_payload(100, "Primero"),
                _employee_payload(100, "Último"),
            )
        )
        self.assertEqual((result.creados, result.omitidos), (1, 1))
        self.assertEqual(len(self.database.rows), 1)
        self.assertEqual(next(iter(self.database.rows.values()))["full_name"], "Último")

    def test_mysql_config_writes_are_batched(self):
        employees = [_employee_payload(person_id) for person_id in range(1, 202)]
        result = self._run_import(_one_page(*employees))

        self.assertEqual(result.creados, 201)
        self.assertEqual(sorted(self.database.batch_sizes), [1, 200])

    def test_mysql_config_rolls_back_and_closes_after_driver_error(self):
        self._run_import(_one_page(_employee_payload(100, "Antes")))
        self.database.fail_update = True

        with self.assertRaises(PersonaImportServiceError) as raised:
            self._run_import(_one_page(_employee_payload(100, "Después")))

        self.assertEqual(
            raised.exception.message_key,
            "evaluaciones.personas.import.error.db",
        )
        self.assertEqual(next(iter(self.database.rows.values()))["full_name"], "Antes")
        self.assertTrue(all(connection.closed for connection in self.database.connections))
        self.assertGreater(self.database.cursor_close_count, 0)

    def test_mysql_config_listing_uses_same_backend_and_returns_count(self):
        self._run_import(_one_page(_employee_payload(100, "Persona de prueba")))
        with patch.object(
            persona_storage,
            "open_evaluaciones_connection",
            self._open_connection,
        ):
            personas, count = persona_storage.list_personas()

        self.assertEqual(count, 1)
        self.assertEqual(personas[0].person_id, 100)
        self.assertEqual(personas[0].full_name, "Persona de prueba")
        self.assertTrue(all(connection.closed for connection in self.database.connections))

    def test_resolution_and_connection_failures_are_controlled_without_writes(self):
        for error in (
            EvaluacionesConnectionRoleNotFoundError("role missing"),
            EvaluacionesConnectionInactiveError("inactive"),
            MySQLConnectionOpenError(
                "user=import_user password=do-not-leak host=internal-db"
            ),
        ):
            with self.subTest(error=type(error).__name__):
                with patch.object(
                    persona_storage,
                    "open_evaluaciones_connection",
                    side_effect=error,
                ), patch(
                    "api.services.buk_api.fetch_active_employees",
                    return_value=_one_page(_employee_payload(100)),
                ):
                    with self.assertRaises(PersonaImportServiceError) as raised:
                        importar_personas_desde_api_interna("2026-03-07", True)

                self.assertEqual(
                    raised.exception.message_key,
                    "evaluaciones.personas.import.error.db",
                )
                self.assertNotIn("inactive", str(raised.exception))
                self.assertNotIn("do-not-leak", str(raised.exception))
                self.assertNotIn("internal-db", str(raised.exception))
                self.assertNotIn("import_user", str(raised.exception))
                self.assertEqual(self.database.rows, {})

    def test_mysql_config_failure_rolls_back_partial_batch(self):
        self._run_import(
            _one_page(
                _employee_payload(100, "Antes 1"),
                _employee_payload(101, "Antes 2"),
            )
        )
        self.database.fail_update = True
        with patch.object(
            persona_storage,
            "open_evaluaciones_connection",
            self._open_connection,
        ), patch(
            "api.services.buk_api.fetch_active_employees",
            return_value=_one_page(
                _employee_payload(100, "Después 1"),
                _employee_payload(101, "Después 2"),
            ),
        ):
            with self.assertRaises(PersonaImportServiceError):
                importar_personas_desde_api_interna("2026-03-07", True)

        self.assertEqual(
            [row["full_name"] for row in self.database.rows.values()],
            ["Antes 1", "Antes 2"],
        )
        self.assertTrue(all(connection.closed for connection in self.database.connections))
