from contextlib import contextmanager
from datetime import date, datetime, timezone as datetime_timezone
from decimal import Decimal
import sqlite3
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from access_control.models import Empresa
from tareas.models import EvaluacionSimilitud, Tarea, TareaConnectionRole
from tareas.services import similarity_storage
from tareas.services.connection_roles import BackendContext
from tareas.services.similarity import (
    confirm_similarity,
    evaluate_task_similarity,
    get_similarity_threshold,
    set_similarity_threshold,
)
from tareas.services.connection_roles import TareaConnectionRoleNotFoundError
from tareas.services.similarity_storage import (
    DjangoSimilarityStorage,
    MySQLSimilarityStorage,
    SimilarityStorageError,
    resolve_similarity_storage,
)


class _SQLiteCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, params=()):
        sql = sql.replace("%s", "?").replace(" FOR UPDATE", "")
        values = tuple(
            value.isoformat() if hasattr(value, "isoformat") else value
            for value in params
        )
        self.cursor.execute(sql, values)

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class _SQLiteConnection:
    def __init__(self):
        self.database = sqlite3.connect(":memory:", isolation_level=None)
        self.database.executescript(
            """
            CREATE TABLE tareas_tarea (
                id INTEGER PRIMARY KEY, empresa_id INTEGER, correlativo TEXT,
                titulo TEXT, descripcion TEXT, prioridad TEXT, estado TEXT,
                anulada INTEGER, tipo_ambito TEXT, local_id INTEGER,
                departamento_id INTEGER, todo_origen_id INTEGER,
                tarea_origen_id INTEGER
            );
            CREATE TABLE tareas_evaluacionsimilitud (
                id INTEGER PRIMARY KEY AUTOINCREMENT, tarea_id INTEGER,
                tarea_candidata_id INTEGER, porcentaje NUMERIC,
                umbral_aplicado NUMERIC, supera_umbral INTEGER, decision TEXT,
                confirmada_por_id INTEGER, confirmada_at TEXT, created_at TEXT,
                UNIQUE(tarea_id,tarea_candidata_id)
            );
            CREATE TABLE tareas_umbralsimilitudempresa (
                id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER UNIQUE,
                porcentaje NUMERIC, actualizado_por_id INTEGER, actualizado_at TEXT
            );
            """
        )

    def cursor(self):
        return _SQLiteCursor(self.database.cursor())

    def begin(self):
        self.database.execute("BEGIN")

    def commit(self):
        self.database.commit()

    def rollback(self):
        self.database.rollback()

    def close(self):
        self.database.close()


class SimilarityBackendParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        TareaConnectionRole.objects.update_or_create(
            role="BASE_TAREAS",
            defaults={"source_type": "DJANGO", "django_alias": "default"},
        )
        cls.company = Empresa.objects.create(
            codigo="S135F",
            descripcion="Similarity backend parity",
        )
        cls.user = User.objects.create_user(username="similarity-parity-user")
        cls.task = Tarea.objects.create(
            empresa=cls.company,
            creada_por=cls.user,
            titulo="Default task content",
            descripcion="Default task description",
            correlativo="A135F01",
            estado=Tarea.Estado.BORRADOR,
            fecha_tope=date(2026, 10, 1),
        )
        cls.candidate = Tarea.objects.create(
            empresa=cls.company,
            creada_por=cls.user,
            titulo="Default candidate content",
            descripcion="Default candidate description",
            correlativo="A135F02",
            estado=Tarea.Estado.ACTIVA,
            fecha_tope=date(2026, 10, 1),
        )
        cls.evaluation = EvaluacionSimilitud.objects.create(
            tarea=cls.task,
            tarea_candidata=cls.candidate,
            porcentaje=Decimal("10.00"),
            umbral_aplicado=Decimal("80.00"),
            supera_umbral=False,
        )

    def setUp(self):
        self.connection = _SQLiteConnection()
        self.addCleanup(self.connection.close)
        self.connection.database.executemany(
            "INSERT INTO tareas_tarea VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    self.task.pk, self.company.pk, "B135F01", "Operational issue",
                    "Operational description", Tarea.Prioridad.URGENTE,
                    Tarea.Estado.BORRADOR, 0, "", None, None, None, None,
                ),
                (
                    self.candidate.pk, self.company.pk, "A135F02",
                    "Operational issue", "Operational description",
                    Tarea.Prioridad.CRITICA, Tarea.Estado.ACTIVA, 0, "",
                    None, None, None, None,
                ),
            ],
        )
        self.connection.database.execute(
            "INSERT INTO tareas_evaluacionsimilitud "
            "(id,tarea_id,tarea_candidata_id,porcentaje,umbral_aplicado,"
            "supera_umbral,decision,confirmada_por_id,confirmada_at,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                self.evaluation.pk, self.task.pk, self.candidate.pk,
                "20.00", "80.00", 0,
                EvaluacionSimilitud.Decision.PENDIENTE, None, None,
                datetime.now(datetime_timezone.utc).isoformat(),
            ),
        )
        self.mysql_patch = patch.object(
            similarity_storage,
            "open_mysql_connection",
            self.open_mysql_connection,
        )
        self.mysql_patch.start()
        self.addCleanup(self.mysql_patch.stop)

    @contextmanager
    def open_mysql_connection(self, *args, **kwargs):
        yield self.connection

    @contextmanager
    def configured_mysql(self):
        context = BackendContext(
            logical_role="BASE_TAREAS", backend_type="MYSQL_CONFIG",
            mysql_connection=object(), database_name="similarity_test",
        )
        with patch.object(similarity_storage, "resolve_operational_backend", return_value=context):
            yield

    def test_resolver_uses_configured_django_alias(self):
        with patch.object(
            similarity_storage,
            "resolve_operational_backend",
            return_value=BackendContext(
                logical_role="BASE_TAREAS", backend_type="DJANGO", django_alias="default",
            ),
        ):
            self.assertIsInstance(resolve_similarity_storage(), DjangoSimilarityStorage)

    def test_resolver_selects_mysql_configured_storage(self):
        with self.configured_mysql():
            self.assertIsInstance(resolve_similarity_storage(), MySQLSimilarityStorage)

    def test_mysql_same_pk_updates_the_operational_evaluation_only(self):
        with self.configured_mysql():
            results = evaluate_task_similarity(tarea=self.task, threshold=80)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].porcentaje, Decimal("100.00"))
            self.assertEqual(results[0].pk, self.evaluation.pk)
            self.assertEqual(results[0].tarea_candidata.correlativo, "A135F02")
            self.assertEqual(
                results[0].tarea_candidata.prioridad,
                Tarea.Prioridad.CRITICA,
            )
            self.connection.database.execute(
                "UPDATE tareas_evaluacionsimilitud "
                "SET tarea_id=?,tarea_candidata_id=?,porcentaje=?,"
                "decision=?,confirmada_por_id=NULL,confirmada_at=NULL WHERE id=?",
                (
                    self.candidate.pk,
                    self.task.pk,
                    "25.00",
                    EvaluacionSimilitud.Decision.PENDIENTE,
                    self.evaluation.pk,
                ),
            )
            confirm_similarity(
                evaluacion=self.evaluation,
                decision=EvaluacionSimilitud.Decision.MISMO_PROBLEMA,
                actor=self.user,
            )

        row = self.connection.database.execute(
            "SELECT porcentaje,decision FROM tareas_evaluacionsimilitud WHERE id=?",
            (self.evaluation.pk,),
        ).fetchone()
        self.assertEqual(
            (Decimal(str(row[0])), row[1]),
            (Decimal("25"), EvaluacionSimilitud.Decision.MISMO_PROBLEMA),
        )
        origin_id = self.connection.database.execute(
            "SELECT tarea_origen_id FROM tareas_tarea WHERE id=?",
            (self.candidate.pk,),
        ).fetchone()[0]
        self.assertEqual(origin_id, self.task.pk)
        self.evaluation.refresh_from_db()
        self.task.refresh_from_db()
        self.assertEqual(self.evaluation.porcentaje, Decimal("10.00"))
        self.assertEqual(
            self.evaluation.decision,
            EvaluacionSimilitud.Decision.PENDIENTE,
        )
        self.assertIsNone(self.task.tarea_origen_id)

    def test_mysql_threshold_is_stored_in_configured_backend(self):
        with self.configured_mysql():
            self.assertEqual(
                get_similarity_threshold(self.company),
                Decimal("80.00"),
            )
            configuration = set_similarity_threshold(
                empresa=self.company,
                porcentaje=Decimal("75.00"),
                actor=self.user,
            )
            self.assertEqual(configuration.porcentaje, Decimal("75.00"))
            self.assertEqual(
                get_similarity_threshold(self.company),
                Decimal("75.00"),
            )
        self.assertFalse(
            self.company.__class__.objects.filter(
                pk=self.company.pk,
                umbral_similitud__isnull=False,
            ).exists()
        )

    def test_missing_role_fails_closed_without_using_default_storage(self):
        with patch.object(
            similarity_storage,
            "resolve_operational_backend",
            side_effect=TareaConnectionRoleNotFoundError("missing"),
        ):
            with self.assertRaises(SimilarityStorageError):
                evaluate_task_similarity(tarea=self.task, threshold=80)

        with self.configured_mysql():
            self.connection.database.execute(
                "DELETE FROM tareas_evaluacionsimilitud WHERE id=?",
                (self.evaluation.pk,),
            )
            with self.assertRaises(SimilarityStorageError):
                confirm_similarity(
                    evaluacion=self.evaluation,
                    decision=EvaluacionSimilitud.Decision.DISTINTO_PROBLEMA,
                    actor=self.user,
                )
        self.evaluation.refresh_from_db()
        self.assertEqual(
            self.evaluation.decision,
            EvaluacionSimilitud.Decision.PENDIENTE,
        )
