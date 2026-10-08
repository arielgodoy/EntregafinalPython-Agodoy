import json
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from django.db import DatabaseError, IntegrityError
from django.db.backends.base.base import BaseDatabaseWrapper
from django.test import SimpleTestCase

from common.database_classification import DatabaseClassification
from gestiondte.models import CesionRPETC, TareaRPETC
from gestiondte.services.connection_roles import (
    GestionDTERoleNotFoundError,
)
from gestiondte.services.rpetc_repository import (
    RPETCCesionRecord,
    RPETCRepository,
    RPETCRepositoryConfigurationError,
    _to_database_value,
)
from settings.models import SettingsMySQLConnection


def _django_repository(alias="DB_sistema"):
    with patch(
        "gestiondte.services.rpetc_repository.get_gestiondte_connection",
        return_value={"type": "DJANGO", "alias": alias},
    ), patch(
        "gestiondte.services.rpetc_repository.get_database_classification",
        return_value=DatabaseClassification.SYSTEM,
    ):
        return RPETCRepository()


def _mysql_repository(engine=SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL):
    config = SimpleNamespace(pk=17, is_active=True, engine=engine)
    resolved = {
        "type": "MYSQL_CONFIG",
        "connection_id": config.pk,
        "database_name": "gestiondte",
    }
    with patch(
        "gestiondte.services.rpetc_repository.get_gestiondte_connection",
        return_value=resolved,
    ), patch(
        "gestiondte.services.rpetc_repository.get_gestiondte_mysql_connection",
        return_value=config,
    ):
        return RPETCRepository()


@contextmanager
def _opened(connection):
    yield connection


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.lastrowid = None
        self.rowcount = 1
        self._result = None

    def execute(self, sql, params=()):
        self.connection.statements.append((sql, params))
        if self.connection.results:
            result = self.connection.results.pop(0)
            if isinstance(result, BaseException):
                raise result
            self._result, self.lastrowid = result
        else:
            self._result = None
            self.lastrowid = None
        if self.connection.rowcounts:
            self.rowcount = self.connection.rowcounts.pop(0)

    def fetchone(self):
        return self._result

    def close(self):
        self.connection.closed_cursors += 1


class FakeConnection:
    def __init__(self, results=(), rowcounts=()):
        self.results = list(results)
        self.rowcounts = list(rowcounts)
        self.statements = []
        self.closed_cursors = 0
        self.begin = MagicMock()
        self.commit = MagicMock()
        self.rollback = MagicMock()

    def cursor(self):
        return FakeCursor(self)


class FakeMySQLIntegrityError(Exception):
    pass


class RPETCRepositoryResolutionTests(SimpleTestCase):
    @patch("gestiondte.services.rpetc_repository.get_gestiondte_connection")
    def test_role_absence_fails_closed(self, resolver):
        resolver.side_effect = GestionDTERoleNotFoundError("serverbasedte ausente")

        with self.assertRaises(GestionDTERoleNotFoundError):
            RPETCRepository()

    @patch(
        "gestiondte.services.rpetc_repository.get_gestiondte_connection",
        return_value={"type": "DJANGO", "alias": "default"},
    )
    def test_default_alias_is_rejected_before_any_operation(self, resolver):
        with self.assertRaisesRegex(RPETCRepositoryConfigurationError, "default"):
            RPETCRepository()

        resolver.assert_called_once_with("serverbasedte")

    @patch(
        "gestiondte.services.rpetc_repository.get_gestiondte_connection",
        return_value={"type": "DJANGO", "alias": "legacy"},
    )
    @patch(
        "gestiondte.services.rpetc_repository.get_database_classification",
        return_value=DatabaseClassification.LEGACY,
    )
    def test_non_system_alias_is_rejected(self, classification, resolver):
        with self.assertRaises(RPETCRepositoryConfigurationError):
            RPETCRepository()

        classification.assert_called_once_with("legacy")
        resolver.assert_called_once_with("serverbasedte")

    @patch(
        "gestiondte.services.rpetc_repository.get_gestiondte_connection",
        return_value={"type": "DJANGO", "alias": "DB_sistema"},
    )
    @patch(
        "gestiondte.services.rpetc_repository.get_database_classification",
        return_value=DatabaseClassification.SYSTEM,
    )
    def test_explicit_nondefault_system_alias_is_accepted(self, _classification, _resolver):
        repository = RPETCRepository()

        self.assertEqual(repository._django_alias, "DB_sistema")

    @patch(
        "gestiondte.services.rpetc_repository.get_gestiondte_connection",
        return_value={
            "type": "MYSQL_CONFIG",
            "connection_id": 17,
            "database_name": "gestiondte",
        },
    )
    @patch(
        "gestiondte.services.rpetc_repository.get_gestiondte_mysql_connection",
    )
    def test_inactive_mysql_config_fails_closed(self, get_mysql_connection, _resolver):
        get_mysql_connection.return_value = SimpleNamespace(
            pk=17,
            is_active=False,
            engine=SettingsMySQLConnection.ENGINE_LEGACY_PYMYSQL,
        )

        with self.assertRaises(RPETCRepositoryConfigurationError):
            RPETCRepository()

    @patch(
        "gestiondte.services.rpetc_repository.get_gestiondte_connection",
        return_value={
            "type": "MYSQL_CONFIG",
            "connection_id": 17,
            "database_name": "gestiondte",
        },
    )
    @patch(
        "gestiondte.services.rpetc_repository.get_gestiondte_mysql_connection",
    )
    def test_unsupported_mysql_engine_fails_closed(self, get_mysql_connection, _resolver):
        get_mysql_connection.return_value = SimpleNamespace(
            pk=17,
            is_active=True,
            engine=SettingsMySQLConnection.ENGINE_API_REMOTA,
        )

        with self.assertRaises(RPETCRepositoryConfigurationError):
            RPETCRepository()

    @patch(
        "gestiondte.services.rpetc_repository.get_gestiondte_connection",
        return_value={
            "type": "MYSQL_CONFIG",
            "connection_id": 17,
            "database_name": None,
        },
    )
    @patch(
        "gestiondte.services.rpetc_repository.get_gestiondte_mysql_connection",
    )
    def test_missing_database_name_fails_closed(self, get_mysql_connection, _resolver):
        get_mysql_connection.return_value = SimpleNamespace(
            pk=17,
            is_active=True,
            engine=SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
        )

        with self.assertRaises(RPETCRepositoryConfigurationError):
            RPETCRepository()

    @patch(
        "gestiondte.services.rpetc_repository.get_gestiondte_connection",
        return_value={
            "type": "MYSQL_CONFIG",
            "connection_id": 18,
            "database_name": "gestiondte",
        },
    )
    @patch(
        "gestiondte.services.rpetc_repository.get_gestiondte_mysql_connection",
    )
    def test_connection_changed_during_resolution_fails_closed(
        self, get_mysql_connection, _resolver
    ):
        get_mysql_connection.return_value = SimpleNamespace(
            pk=17,
            is_active=True,
            engine=SettingsMySQLConnection.ENGINE_DJANGO_MYSQL,
        )

        with self.assertRaises(RPETCRepositoryConfigurationError):
            RPETCRepository()


class RPETCRepositoryDjangoTests(SimpleTestCase):
    @patch("gestiondte.services.rpetc_repository.transaction.atomic")
    @patch("gestiondte.services.rpetc_repository.TareaRPETC.objects")
    def test_task_upsert_uses_alias_and_company_code(self, task_manager, atomic):
        atomic.return_value = nullcontext()
        task = SimpleNamespace(pk=12, id_tarea="rp-1", empresa_id="09")
        task_manager.using.return_value.update_or_create.return_value = (task, True)
        repository = _django_repository()
        empresa = SimpleNamespace(codigo="09", _state=SimpleNamespace(db="default"))

        with repository.unit_of_work() as work:
            result = work.upsert_tarea(
                "rp-1",
                {"empresa": empresa, "estado": "TERMINADO"},
            )

        atomic.assert_called_once_with(using="DB_sistema")
        task_manager.using.assert_called_once_with("DB_sistema")
        task_manager.using.return_value.update_or_create.assert_called_once_with(
            id_tarea="rp-1",
            defaults={"empresa_id": "09", "estado": "TERMINADO"},
        )
        self.assertEqual((result.pk, result.empresa_id, result.created), (12, "09", True))

    @patch("gestiondte.services.rpetc_repository.CesionRPETC.objects")
    def test_lookup_and_create_cesion_use_same_alias(self, cesion_manager):
        existing = CesionRPETC(pk=4, id_cesion="c-1", estado_cesion="Vigente")
        cesion_manager.using.return_value.filter.return_value.first.return_value = existing
        cesion_manager.using.return_value.create.return_value = existing
        work = _django_repository().unit_of_work

        with patch(
            "gestiondte.services.rpetc_repository.transaction.atomic",
            return_value=nullcontext(),
        ):
            with work() as repository:
                found = repository.find_cesion({"id_cesion": "c-1"})
                created = repository.create_cesion({"id_cesion": "c-1"})

            assert found is not None
            self.assertEqual(found.pk, 4)
            self.assertIs(found.instance, existing)
        self.assertEqual(created.pk, 4)
        self.assertEqual(
            cesion_manager.using.call_args_list,
            [call("DB_sistema"), call("DB_sistema")],
        )

    @patch("gestiondte.services.rpetc_repository.CesionRPETC.objects")
    def test_cesion_update_preserves_update_fields_and_timestamp(self, cesion_manager):
        instance = MagicMock(spec=CesionRPETC)
        instance.pk = 4
        instance.estado_cesion = "Revocada"
        instance.actualizada_en = "saved-time"
        record = RPETCCesionRecord(
            pk=4,
            instance=instance,
            values={"estado_cesion": "Vigente"},
        )
        with patch(
            "gestiondte.services.rpetc_repository.transaction.atomic",
            return_value=nullcontext(),
        ):
            with _django_repository().unit_of_work() as repository:
                repository.update_cesion(record, {"estado_cesion": "Revocada"})

        instance.save.assert_called_once_with(
            using="DB_sistema",
            update_fields=["estado_cesion", "actualizada_en"],
        )

    @patch("gestiondte.services.rpetc_repository.CesionRPETCHistorial.objects")
    @patch("gestiondte.services.rpetc_repository.TareaCesionRPETC.objects")
    def test_history_and_link_use_ids_and_only_creation_defaults(
        self, link_manager, history_manager
    ):
        link_manager.using.return_value.get_or_create.return_value = (
            SimpleNamespace(pk=31),
            False,
        )
        with patch(
            "gestiondte.services.rpetc_repository.transaction.atomic",
            return_value=nullcontext(),
        ):
            with _django_repository().unit_of_work() as repository:
                repository.create_historial(4, "Vigente", None, 12)
                link_id, created = repository.get_or_create_vinculo(
                    12,
                    4,
                    {"rol_consulta": "DEUDOR", "fila_origen": 3},
                )

        history_manager.using.return_value.create.assert_called_once_with(
            cesion_id=4,
            estado="Vigente",
            estado_anterior=None,
            tarea_origen_id=12,
        )
        link_manager.using.return_value.get_or_create.assert_called_once_with(
            tarea_id=12,
            cesion_id=4,
            defaults={"rol_consulta": "DEUDOR", "fila_origen": 3},
        )
        self.assertEqual((link_id, created), (31, False))


class RPETCRepositoryMysqlTests(SimpleTestCase):
    def _run_with_connection(self, connection, operation):
        repository = _mysql_repository()
        with patch(
            "gestiondte.services.rpetc_repository.open_mysql_connection",
            side_effect=lambda *_args, **_kwargs: _opened(connection),
        ) as opener:
            result = operation(repository)
        opener.assert_called_once()
        return result

    def test_dbapi_unit_of_work_commits_once_on_success(self):
        connection = FakeConnection()

        self._run_with_connection(
            connection,
            lambda repository: self._complete_unit_of_work(repository),
        )

        connection.begin.assert_called_once_with()
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()

    def _complete_unit_of_work(self, repository):
        with repository.unit_of_work():
            return None

    def test_dbapi_unit_of_work_rolls_back_and_propagates_failure(self):
        connection = FakeConnection()

        def fail(repository):
            with repository.unit_of_work():
                raise IntegrityError("write failed")

        with self.assertRaises(IntegrityError):
            self._run_with_connection(connection, fail)

        connection.begin.assert_called_once_with()
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()

    def test_open_failure_propagates_without_default_fallback(self):
        repository = _mysql_repository()
        with patch(
            "gestiondte.services.rpetc_repository.open_mysql_connection",
            side_effect=RuntimeError("connection unavailable"),
        ) as opener:
            with self.assertRaisesRegex(RuntimeError, "connection unavailable"):
                with repository.unit_of_work():
                    self.fail("unreachable")

        opener.assert_called_once()

    def test_mysql_django_wrapper_uses_its_alias_transaction(self):
        wrapper = MagicMock(spec=BaseDatabaseWrapper)
        wrapper.alias = "mysql_runtime_test"
        wrapper.vendor = "mysql"
        atomic = MagicMock(return_value=nullcontext())
        with patch(
            "gestiondte.services.rpetc_repository.open_mysql_connection",
            side_effect=lambda *_args, **_kwargs: _opened(wrapper),
        ), patch(
            "gestiondte.services.rpetc_repository.transaction.atomic",
            atomic,
        ):
            with _mysql_repository(
                SettingsMySQLConnection.ENGINE_DJANGO_MYSQL
            ).unit_of_work():
                pass

        atomic.assert_called_once_with(using="mysql_runtime_test")

    def test_upsert_existing_task_updates_same_row_and_company_code(self):
        connection = FakeConnection(results=[((17,), None)])
        with patch(
            "gestiondte.services.rpetc_repository.open_mysql_connection",
            side_effect=lambda *_args, **_kwargs: _opened(connection),
        ):
            with _mysql_repository().unit_of_work() as repository:
                task = repository.upsert_tarea(
                    "rp-1",
                    {
                        "empresa": SimpleNamespace(codigo="09"),
                        "estado": "TERMINADO",
                    },
                )

        self.assertEqual((task.pk, task.created), (17, False))
        self.assertIn("`empresa_codigo` = %s", connection.statements[1][0])
        self.assertIn("09", connection.statements[1][1])
        self.assertIn("`id_tarea` = %s", connection.statements[0][0])
        self.assertEqual(connection.commit.call_count, 1)

    @patch(
        "gestiondte.services.rpetc_repository._pymysql_integrity_error_type",
        return_value=FakeMySQLIntegrityError,
    )
    def test_upsert_recovers_a_concurrent_unique_insert(self, _error_type):
        connection = FakeConnection(
            results=[
                (None, None),
                FakeMySQLIntegrityError(1062, "duplicate"),
                ((17,), None),
            ]
        )
        with patch(
            "gestiondte.services.rpetc_repository.open_mysql_connection",
            side_effect=lambda *_args, **_kwargs: _opened(connection),
        ):
            with _mysql_repository().unit_of_work() as repository:
                task = repository.upsert_tarea(
                    "rp-1",
                    {"empresa_id": "09", "estado": "TERMINADO"},
                )

        self.assertEqual((task.pk, task.created), (17, False))
        self.assertIn("UPDATE", connection.statements[3][0])

    def test_upsert_new_task_inserts_company_code_and_auto_timestamps(self):
        connection = FakeConnection(results=[(None, None), (None, 23)])
        with patch(
            "gestiondte.services.rpetc_repository.open_mysql_connection",
            side_effect=lambda *_args, **_kwargs: _opened(connection),
        ):
            with _mysql_repository().unit_of_work() as repository:
                task = repository.upsert_tarea(
                    "rp-2",
                    {"empresa_id": "10", "estado": "TERMINADO"},
                )

        insert_sql, params = connection.statements[1]
        self.assertIn("`empresa_codigo`", insert_sql)
        self.assertIn("consultada_en", insert_sql)
        self.assertIn("actualizada_en", insert_sql)
        self.assertIn("10", params)
        self.assertEqual((task.pk, task.created), (23, True))

    def test_lookup_uses_model_identity_and_returns_mapped_record(self):
        row = []
        expected = {
            "id": 8,
            "id_cesion": "c-8",
            "estado_cesion": "Vigente",
            "deudor_rut": "123",
            "deudor_dv": "4",
            "tipo_doc": "33",
            "folio_doc": "001",
        }
        for field in CesionRPETC._meta.concrete_fields:
            row.append(expected.get(field.attname))
        connection = FakeConnection(results=[(tuple(row), None)])
        with patch(
            "gestiondte.services.rpetc_repository.open_mysql_connection",
            side_effect=lambda *_args, **_kwargs: _opened(connection),
        ):
            with _mysql_repository().unit_of_work() as repository:
                cesion = repository.find_cesion(
                    {
                        "id_cesion": "c-8",
                        "deudor_rut": "123",
                        "deudor_dv": "4",
                        "tipo_doc": "33",
                        "folio_doc": "001",
                    }
                )

        assert cesion is not None
        self.assertEqual(cesion.pk, 8)
        self.assertEqual(cesion.estado_cesion, "Vigente")
        self.assertIn("ORDER BY", connection.statements[0][0])
        self.assertEqual(connection.statements[0][1], ("c-8", "123", "4", "33", "001"))

    def test_create_update_history_and_link_use_one_connection(self):
        connection = FakeConnection(
            results=[
                (None, 41),
                (None, None),
                (None, 50),
                ((31,), None),
                (None, None),
                (None, 32),
            ]
        )
        with patch(
            "gestiondte.services.rpetc_repository.open_mysql_connection",
            side_effect=lambda *_args, **_kwargs: _opened(connection),
        ):
            with _mysql_repository().unit_of_work() as repository:
                cesion = repository.create_cesion(
                    {"id_cesion": "c-1", "estado_cesion": "Vigente"}
                )
                repository.update_cesion(cesion, {"estado_cesion": "Revocada"})
                repository.create_historial(41, "Revocada", "Vigente", 12)
                existing_id, existing_created = repository.get_or_create_vinculo(
                    12, 41, {"rol_consulta": "DEUDOR", "fila_origen": 3}
                )
                new_id, new_created = repository.get_or_create_vinculo(
                    12, 42, {"rol_consulta": "CEDENTE", "fila_origen": 4}
                )

        self.assertEqual(cesion.pk, 41)
        self.assertEqual(cesion.estado_cesion, "Revocada")
        self.assertEqual((existing_id, existing_created), (31, False))
        self.assertEqual((new_id, new_created), (32, True))
        self.assertEqual(connection.begin.call_count, 1)
        self.assertEqual(connection.commit.call_count, 1)
        self.assertEqual(connection.rollback.call_count, 0)
        self.assertEqual(connection.closed_cursors, 5)
        self.assertIn("`tarea_origen_id`", connection.statements[2][0])

    @patch(
        "gestiondte.services.rpetc_repository._pymysql_integrity_error_type",
        return_value=FakeMySQLIntegrityError,
    )
    def test_link_get_or_create_recovers_a_concurrent_unique_insert(self, _error_type):
        connection = FakeConnection(
            results=[
                (None, None),
                FakeMySQLIntegrityError(1062, "duplicate"),
                ((31,), None),
            ]
        )
        with patch(
            "gestiondte.services.rpetc_repository.open_mysql_connection",
            side_effect=lambda *_args, **_kwargs: _opened(connection),
        ):
            with _mysql_repository().unit_of_work() as repository:
                link_id, created = repository.get_or_create_vinculo(
                    12,
                    41,
                    {"rol_consulta": "DEUDOR", "fila_origen": 3},
                )

        self.assertEqual((link_id, created), (31, False))
        self.assertIn("FOR UPDATE", connection.statements[2][0])

    def test_update_missing_cesion_raises_and_rolls_back(self):
        connection = FakeConnection(
            results=[(None, None), (None, None)],
            rowcounts=[0, 0],
        )
        with patch(
            "gestiondte.services.rpetc_repository.open_mysql_connection",
            side_effect=lambda *_args, **_kwargs: _opened(connection),
        ):
            with self.assertRaisesRegex(DatabaseError, "no encontró"):
                with _mysql_repository().unit_of_work() as repository:
                    repository.update_cesion(
                        RPETCCesionRecord(pk=41, values={}),
                        {"estado_cesion": "Revocada"},
                    )

        connection.rollback.assert_called_once_with()
        connection.commit.assert_not_called()

    def test_datetime_and_json_values_are_bound_as_mysql_values(self):
        aware = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        with patch(
            "gestiondte.services.rpetc_repository.timezone.get_default_timezone",
            return_value=timezone.utc,
        ):
            datetime_value = _to_database_value(
                TareaRPETC._meta.get_field("consultada_en"),
                aware,
            )
        json_value = _to_database_value(
            TareaRPETC._meta.get_field("parametros"),
            {"periodo": ["2026-10-01", "2026-10-08"]},
        )

        self.assertEqual(datetime_value, aware.replace(tzinfo=None))
        self.assertEqual(
            json.loads(json_value),
            {"periodo": ["2026-10-01", "2026-10-08"]},
        )
