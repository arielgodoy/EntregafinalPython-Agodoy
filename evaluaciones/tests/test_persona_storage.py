from contextlib import contextmanager
import ast
from copy import deepcopy
import re
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

from django.db import connections
from django.test import SimpleTestCase

from evaluaciones.admin import PersonaAdmin
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


class PersonaPayloadStorageTests(SimpleTestCase):
    def test_json_payload_round_trip_preserves_nested_nulls(self):
        payload = {
            "custom_attributes": [{"name": "future_field", "value": None}],
            "nested": {"optional": None},
            "items": [None, "synthetic"],
        }
        field = Persona._meta.get_field("buk_payload")

        encoded = persona_storage._to_mysql_value(field, payload)
        decoded = persona_storage._from_mysql_value(field, encoded)

        self.assertEqual(decoded, payload)

    def test_person_listing_and_admin_do_not_expose_payload_automatically(self):
        visible_storage_fields = {
            field.name
            for field in persona_storage._persona_fields_without_payload()
        }

        self.assertNotIn("buk_payload", visible_storage_fields)
        self.assertEqual(PersonaAdmin.exclude, ("buk_payload",))


def _employee_payload(person_id: int, full_name: str = "Ana Pérez") -> dict:
    body = str(10_000_000 + person_id)
    total = 0
    factor = 2
    for digit in reversed(body):
        total += int(digit) * factor
        factor = 2 if factor == 7 else factor + 1
    remainder = 11 - total % 11
    check_digit = "0" if remainder == 11 else "K" if remainder == 10 else str(remainder)
    return {
        "person_id": person_id,
        "id": 90_000 + person_id,
        "rut": f"{body[:2]}.{body[2:5]}.{body[5:]}-{check_digit}",
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
        if query.startswith("SELECT DISTINCT "):
            self.rows = sorted(
                {
                    (row["anio"], row["mes"])
                    for row in self.database.rows.values()
                },
                reverse=True,
            )
            return
        if " WHERE `anio` = %s AND `mes` = %s AND `rut_normalizado` IN " in query:
            anio, mes, *wanted_ruts = params
            wanted_ruts = set(wanted_ruts)
            self.rows = [
                tuple(row.get(column) for column in columns)
                for row in self.database.rows.values()
                if row["anio"] == anio
                and row["mes"] == mes
                and row["rut_normalizado"] in wanted_ruts
            ]
            return
        if " WHERE `anio` = %s AND `mes` = %s " in query:
            anio, mes = params
            self.rows = [
                tuple(row.get(column) for column in columns)
                for row in self.database.rows.values()
                if row["anio"] == anio and row["mes"] == mes
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
                    existing["anio"] == row["anio"]
                    and existing["mes"] == row["mes"]
                    and existing["rut_normalizado"] == row["rut_normalizado"]
                    for existing in self.database.rows.values()
                ):
                    raise RuntimeError("duplicate monthly RUT")
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
        queryset = Mock()
        manager.using.return_value = queryset
        queryset.filter.return_value.defer.return_value = []

        with patch.object(Persona, "objects", manager):
            self.assertEqual(
                storage.existing_by_month_and_rut(
                    anio=2026,
                    mes=3,
                    rut_normalizados=[
                        _employee_payload(123)["rut"]
                        .replace(".", "")
                        .replace("-", "")
                    ],
                ),
                {},
            )
            storage.bulk_create([Persona(person_id=123)], batch_size=200)
            storage.bulk_update([Persona(pk=1)], ["full_name"], batch_size=200)

        self.assertEqual(manager.using.call_count, 3)
        self.assertTrue(
            all(call.args == ("system_test",) for call in manager.using.call_args_list)
        )
        queryset.filter.assert_called_once_with(
            anio=2026,
            mes=3,
            rut_normalizado__in=[
                _employee_payload(123)["rut"].replace(".", "").replace("-", "")
            ],
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

    def test_period_queries_use_the_selected_alias_and_exclude_payload(self):
        storage = DjangoPersonaStorage("system_test")
        manager = Mock()
        queryset = MagicMock()
        manager.using.return_value = queryset
        queryset.values_list.return_value.distinct.return_value.order_by.return_value = [
            (2026, 2)
        ]
        queryset.filter.return_value.defer.return_value.order_by.return_value = []

        with patch.object(Persona, "objects", manager):
            periods = storage.list_available_periods()
            people = storage.list_people_for_period(2026, 2)

        self.assertEqual(periods, [(2026, 2)])
        self.assertEqual(people, [])
        self.assertEqual(manager.using.call_count, 2)
        self.assertTrue(
            all(call.args == ("system_test",) for call in manager.using.call_args_list)
        )
        queryset.values_list.assert_called_once_with("anio", "mes")
        queryset.filter.assert_called_once_with(anio=2026, mes=2)
        queryset.filter.return_value.defer.assert_called_once_with("buk_payload")

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

    def _run_import(self, payload, date_value="2026-03-07"):
        with patch.object(
            persona_storage,
            "open_evaluaciones_connection",
            self._open_connection,
        ), patch("api.services.buk_api.fetch_active_employees") as fetch, patch(
            "api.services.buk_api.fetch_buk_url"
        ) as fetch_next:
            fetch.return_value = payload
            result = importar_personas_desde_api_interna(date_value, True)
            fetch.assert_called_once()
            fetch_next.assert_not_called()
        return result

    def test_mysql_config_creates_updates_monthly_rut_and_preserves_counts(self):
        created = self._run_import(_one_page(_employee_payload(100, "Nombre Inicial")))
        self.assertEqual((created.creados, created.actualizados, created.omitidos), (1, 0, 0))
        self.assertEqual(len(self.database.rows), 1)
        stored = next(iter(self.database.rows.values()))
        original_pk = stored["id"]
        self.assertEqual(stored["person_id"], 100)
        self.assertEqual(stored["full_name"], "Nombre Inicial")

        updated_employee = _employee_payload(101, "Nombre Nuevo")
        updated_employee["rut"] = _employee_payload(100)["rut"]
        updated = self._run_import(_one_page(updated_employee))
        self.assertEqual((updated.creados, updated.actualizados, updated.omitidos), (0, 1, 0))
        self.assertEqual(len(self.database.rows), 1)
        stored = next(iter(self.database.rows.values()))
        self.assertEqual(stored["person_id"], 101)
        self.assertEqual(stored["full_name"], "Nombre Nuevo")
        self.assertEqual(stored["mes"], 3)
        self.assertEqual(stored["anio"], 2026)
        self.assertEqual(stored["buk_employee_id"], 90_101)
        self.assertNotEqual(stored["person_id"], stored["buk_employee_id"])
        self.assertEqual(stored["fecha_corte"].isoformat(), "2026-03-07")
        self.assertEqual(stored["id"], original_pk)
        self.assertTrue(all(connection.closed for connection in self.database.connections))
        self.assertTrue(all(statement.startswith(("SELECT", "INSERT", "UPDATE")) for statement in self.database.statements))

    def test_same_rut_in_another_month_inserts_new_snapshot(self):
        employee = _employee_payload(100, "Nombre Marzo")
        first = self._run_import(_one_page(employee))
        next_month = dict(employee)
        next_month["full_name"] = "Nombre Abril"

        second = self._run_import(_one_page(next_month), "2026-04-15")

        self.assertEqual(first.creados, 1)
        self.assertEqual(second.creados, 1)
        self.assertEqual(len(self.database.rows), 2)
        self.assertEqual(
            {(row["anio"], row["mes"]) for row in self.database.rows.values()},
            {(2026, 3), (2026, 4)},
        )
        self.assertEqual(
            {row["full_name"] for row in self.database.rows.values()},
            {"Nombre Marzo", "Nombre Abril"},
        )

    def test_duplicate_monthly_ruts_keep_last_payload_without_duplicate_rows(self):
        first = _employee_payload(100, "Primero")
        duplicate = _employee_payload(101, "Último")
        duplicate["rut"] = first["rut"]
        result = self._run_import(
            _one_page(
                first,
                duplicate,
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

    def test_period_listing_uses_only_requested_period_and_omits_payload(self):
        employee = _employee_payload(100, "Persona de marzo")
        self._run_import(_one_page(employee), "2026-03-07")
        self._run_import(_one_page(employee), "2026-04-15")

        with patch.object(
            persona_storage,
            "open_evaluaciones_connection",
            self._open_connection,
        ):
            periods, selected, people = persona_storage.list_persona_period_data(
                (2026, 3)
            )

        self.assertEqual(periods, [(2026, 4), (2026, 3)])
        self.assertEqual(selected, (2026, 3))
        self.assertEqual([(person.anio, person.mes) for person in people], [(2026, 3)])
        select_statements = [
            statement
            for statement in self.database.statements
            if statement.startswith("SELECT")
        ]
        self.assertTrue(
            all("`buk_payload`" not in statement for statement in select_statements)
        )
        self.assertTrue(
            any(
                "WHERE `anio` = %s AND `mes` = %s" in statement
                for statement in select_statements
            )
        )

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
