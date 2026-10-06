from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import sqlite3
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from proveedores.models import Proveedor
from tareas.models import Cotizacion, RondaCotizacion, Tarea, TareaConnectionRole
from tareas.services import quotation_storage
from tareas.services.quotation_storage import (
    DjangoQuotationStorage,
    MySQLQuotationStorage,
    QuotationStorageError,
)
from tareas.services.quotations import (
    add_quotation_document,
    create_quotation,
    create_quotation_round,
    get_latest_quotation_round,
    has_quotation_process,
    update_quotation_status,
)
from tareas.tests.factories import create_empresa, create_tarea, create_user


class ControlledMySQL:
    def __init__(self, task, round_row=None, quotation_row=None):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.commands = []
        self.db.executescript(
            """
            CREATE TABLE tareas_tarea (id INTEGER PRIMARY KEY, empresa_id INTEGER);
            CREATE TABLE tareas_rondacotizacion (
                id INTEGER PRIMARY KEY AUTOINCREMENT, tarea_id INTEGER,
                numero INTEGER, minimo_cotizaciones INTEGER, estado TEXT,
                fecha_apertura TEXT, fecha_cierre TEXT,
                UNIQUE(tarea_id, numero));
            CREATE TABLE tareas_cotizacion (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ronda_id INTEGER,
                proveedor_id INTEGER, version INTEGER, monto NUMERIC,
                vigente INTEGER, estado TEXT, fecha_cotizacion TEXT,
                observaciones TEXT);
            CREATE TABLE tareas_documentocotizacion (
                id INTEGER PRIMARY KEY AUTOINCREMENT, cotizacion_id INTEGER,
                formato_archivo TEXT, archivo TEXT, url TEXT, usuario_id INTEGER,
                fecha TEXT);
            """
        )
        self.db.execute(
            "INSERT INTO tareas_tarea VALUES (?,?)",
            (task.pk, task.empresa_id),
        )
        if round_row:
            self.db.execute(
                "INSERT INTO tareas_rondacotizacion "
                "(id,tarea_id,numero,minimo_cotizaciones,estado,fecha_apertura,fecha_cierre) "
                "VALUES (?,?,?,?,?,?,?)",
                round_row,
            )
        if quotation_row:
            self.db.execute(
                "INSERT INTO tareas_cotizacion "
                "(id,ronda_id,proveedor_id,version,monto,vigente,estado,fecha_cotizacion,observaciones) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                quotation_row,
            )

    def cursor(self):
        return self

    def close(self):
        pass

    def execute(self, sql, params=()):
        self.commands.append((sql, tuple(params)))
        statement = sql.replace("%s", "?").replace(" FOR UPDATE", "")
        if statement == "START TRANSACTION":
            statement = "BEGIN"
        values = tuple(
            str(value) if isinstance(value, Decimal)
            else value.isoformat() if hasattr(value, "isoformat")
            else value
            for value in params
        )
        cursor = self.db.execute(statement, values)
        self.description = cursor.description
        self.lastrowid = cursor.lastrowid
        self._rows = cursor.fetchall()

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()


class QuotationBackendParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        TareaConnectionRole.objects.update_or_create(
            role="BASE_TAREAS",
            defaults={"source_type": "DJANGO", "django_alias": "default"},
        )
        cls.company = create_empresa(codigo="Q135D")
        cls.user = create_user(username="quotation-parity-user")
        cls.provider = Proveedor.objects.create(nombre="Canonical provider")
        cls.task = create_tarea(cls.company, cls.user, titulo="Quotation parity")

    def setUp(self):
        self.mysql = ControlledMySQL(self.task)
        self.addCleanup(self.mysql.db.close)
        self.mysql_patch = patch.object(
            quotation_storage,
            "open_mysql_connection",
            self.open_mysql,
        )
        self.mysql_patch.start()
        self.addCleanup(self.mysql_patch.stop)

    @contextmanager
    def open_mysql(self, *args, **kwargs):
        yield self.mysql

    @contextmanager
    def configured_mysql(self):
        source = {"type": "MYSQL_CONFIG", "database_name": "quotation_test"}
        with patch.object(quotation_storage, "get_tarea_connection", return_value=source):
            with patch.object(
                quotation_storage,
                "get_tarea_mysql_connection",
                return_value=object(),
            ):
                yield

    def test_resolver_selects_configured_django_alias(self):
        with patch.object(quotation_storage, "get_tarea_connection", return_value={
            "type": "DJANGO", "alias": "default",
        }):
            self.assertIsInstance(quotation_storage.resolve_quotation_storage(), DjangoQuotationStorage)

    def test_mysql_round_quotation_status_and_document_operations(self):
        with self.configured_mysql():
            self.assertFalse(has_quotation_process(self.task))
            first = create_quotation_round(tarea=self.task, minimo_cotizaciones=1)
            self.assertEqual(first.number, 1)
            self.assertTrue(has_quotation_process(self.task))
            self.assertEqual(get_latest_quotation_round(self.task).id, first.id)

            quote = create_quotation(
                ronda=first,
                version=1,
                monto=Decimal("125.50"),
                fecha_cotizacion=date(2026, 10, 1),
                proveedor=self.provider,
            )
            self.assertEqual(quote.provider_id, self.provider.pk)
            self.assertEqual(quote.amount, Decimal("125.50"))

            updated = update_quotation_status(
                cotizacion=quote,
                estado=Cotizacion.Estado.SELECCIONADA,
            )
            self.assertEqual(updated.state, Cotizacion.Estado.SELECCIONADA)

            document = add_quotation_document(
                cotizacion=updated,
                formato_archivo="PDF",
                usuario=self.user,
                url="https://example.test/quotation.pdf",
            )
            self.assertEqual(document.quotation_id, quote.id)
            self.assertEqual(document.user_id, self.user.pk)
            self.assertEqual(document.url, "https://example.test/quotation.pdf")

            table_writes = "\n".join(sql for sql, _ in self.mysql.commands)
            self.assertIn("INSERT INTO tareas_rondacotizacion", table_writes)
            self.assertIn("INSERT INTO tareas_cotizacion", table_writes)
            self.assertIn("UPDATE tareas_cotizacion", table_writes)
            self.assertIn("INSERT INTO tareas_documentocotizacion", table_writes)

    def test_mysql_storage_keeps_external_provider_and_user_references_as_ids(self):
        with self.configured_mysql():
            round_data = create_quotation_round(tarea=self.task)
            quote = create_quotation(
                ronda=round_data,
                version=1,
                monto=Decimal("10"),
                fecha_cotizacion=date(2026, 10, 1),
                proveedor=self.provider,
            )
            add_quotation_document(
                cotizacion=quote,
                formato_archivo="PDF",
                usuario=self.user,
                url="https://example.test/external.pdf",
            )
        operational_sql = "\n".join(sql for sql, _ in self.mysql.commands)
        self.assertNotIn("proveedores_proveedor", operational_sql)
        self.assertNotIn("auth_user", operational_sql)
        self.assertEqual(Proveedor.objects.count(), 1)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_mysql_same_pk_reads_and_updates_operational_quote_only(self):
        default_round = create_quotation_round(tarea=self.task)
        default_quote = create_quotation(
            ronda=default_round,
            version=1,
            monto=Decimal("11.00"),
            fecha_cotizacion=date(2026, 10, 1),
            proveedor=self.provider,
        )
        self.mysql.db.execute(
            "INSERT INTO tareas_rondacotizacion "
            "(id,tarea_id,numero,minimo_cotizaciones,estado,fecha_apertura,fecha_cierre) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                default_round.pk, self.task.pk, default_round.numero,
                default_round.minimo_cotizaciones, default_round.estado,
                default_round.fecha_apertura.isoformat(), None,
            ),
        )
        self.mysql.db.execute(
            "INSERT INTO tareas_cotizacion "
            "(id,ronda_id,proveedor_id,version,monto,vigente,estado,fecha_cotizacion,observaciones) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                default_quote.pk, default_round.pk, self.provider.pk, 1,
                "99.00", 1, Cotizacion.Estado.RECIBIDA, "2026-10-01", "MYSQL B",
            ),
        )
        with self.configured_mysql():
            mysql_round = get_latest_quotation_round(self.task)
            self.assertEqual(mysql_round.id, default_round.pk)
            self.assertEqual(mysql_round.minimum, default_round.minimo_cotizaciones)
            result = update_quotation_status(
                cotizacion=default_quote,
                estado=Cotizacion.Estado.DESCARTADA,
            )
            self.assertEqual(result.state, Cotizacion.Estado.DESCARTADA)

        default_quote.refresh_from_db()
        self.assertEqual(default_quote.estado, Cotizacion.Estado.RECIBIDA)
        self.assertEqual(default_quote.monto, Decimal("11.00"))
        row = self.mysql.db.execute(
            "SELECT monto,estado FROM tareas_cotizacion WHERE id=?",
            (default_quote.pk,),
        ).fetchone()
        self.assertEqual(Decimal(str(row[0])), Decimal("99"))
        self.assertEqual(row[1], Cotizacion.Estado.DESCARTADA)

    def test_missing_invalid_and_unresolvable_backend_fail_without_default_access(self):
        for error in (
            quotation_storage.TareaConnectionError("not configured"),
            RuntimeError("invalid configuration"),
        ):
            with patch.object(quotation_storage, "get_tarea_connection", side_effect=error):
                with patch.object(
                    Tarea.objects,
                    "using",
                    side_effect=AssertionError("operational default fallback"),
                ):
                    with self.assertRaises(QuotationStorageError):
                        create_quotation_round(tarea=self.task)

    def test_mysql_missing_round_rolls_back_and_does_not_create_default_rows(self):
        before_rounds = RondaCotizacion.objects.count()
        with self.configured_mysql():
            with self.assertRaises(quotation_storage.QuotationNotFound):
                create_quotation(
                    ronda=999999,
                    version=1,
                    monto=Decimal("10"),
                    fecha_cotizacion=date(2026, 10, 1),
                    proveedor=self.provider,
                )
        self.assertEqual(RondaCotizacion.objects.count(), before_rounds)
        self.assertEqual(Cotizacion.objects.count(), 0)

    def test_mysql_document_file_is_compensated_when_operational_insert_fails(self):
        class FakeStorage:
            def __init__(self):
                self.deleted = []

            def save(self, name, uploaded, **kwargs):
                return name

            def delete(self, name):
                self.deleted.append(name)

        fake_storage = FakeStorage()
        with self.configured_mysql():
            with patch.object(quotation_storage, "default_storage", fake_storage):
                with self.assertRaises(quotation_storage.QuotationNotFound):
                    add_quotation_document(
                        cotizacion=999999,
                        formato_archivo="PDF",
                        usuario=self.user,
                        archivo=SimpleUploadedFile("quote.pdf", b"PDF"),
                    )
        self.assertEqual(fake_storage.deleted, ["tareas/cotizaciones/quote.pdf"])
