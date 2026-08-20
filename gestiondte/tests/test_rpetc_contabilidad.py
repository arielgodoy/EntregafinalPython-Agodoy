from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from gestiondte.services.rpetc_contabilidad import (
    ContabilidadLegacyError,
    normalizar_folio_legacy,
    normalizar_rut_legacy,
    obtener_estados_contables_cesiones,
)


class LegacyCursor:
    description = [
        ("rutctacte",), ("tipodocumento",), ("numerodocumento",), ("monto",),
        ("dh",), ("fecha",), ("fechadocumento",), ("fechavencimiento",),
        ("glosacontable",), ("creadopor",), ("fechacreacion",), ("horacreacion",),
    ]

    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self, rows):
        self.cursor_obj = LegacyCursor(rows)
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


class FakeCesion:
    def __init__(self, pk=1, tipo_doc="33", folio_doc="2587"):
        self.pk = pk
        self.tipo_doc = tipo_doc
        self.folio_doc = folio_doc
        self.cedente_rut = "76376142"
        self.cedente_dv = "8"
        self.cesionario_rut = "76682670"
        self.cesionario_dv = "9"
        self.monto_total = Decimal("1764799")
        self.monto_cesion = Decimal("1764799")


class RPETCLegacyServiceTest(SimpleTestCase):
    def test_normaliza_rut_y_folio(self):
        self.assertEqual(normalizar_rut_legacy("76.376.142", "8"), "0763761428")
        self.assertEqual(normalizar_rut_legacy("07762388", "k"), "007762388K")
        self.assertEqual(normalizar_rut_legacy("", "8"), None)
        self.assertEqual(normalizar_folio_legacy("2587", "FC"), "0000002587")
        self.assertIsNone(normalizar_folio_legacy("2587", "OT"))

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_batch_contabilizada_pagada_y_sql_parametrizado(self, connect, config):
        rows = [
            ("0763761428", "FC", "0000002587", 1764799.0, "H", None, None, None, "CONTABILIZACION FAE", "u", None, None),
            ("0766826709", "FC", "0000002587", 1764799.0, "D", None, None, None, "CANCELA DOCUMENTO", "u", None, None),
        ]
        connection = FakeConnection(rows)
        connect.return_value = connection
        config.return_value = SimpleNamespace(
            host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1"
        )
        cesion = FakeCesion()
        result = obtener_estados_contables_cesiones("09", [cesion])
        self.assertEqual(result[1]["contabilizacion"]["estado"], "CONTABILIZADA")
        self.assertEqual(result[1]["pago"]["estado"], "PAGADA")
        self.assertTrue(result[1]["contabilizacion"]["monto_coincide"])
        self.assertEqual(connection.cursor_obj.params.count("0000002587"), 2)
        self.assertNotIn("LIKE", connection.cursor_obj.sql.upper())
        self.assertIn("eltit_conta09", connection.cursor_obj.sql)
        connect.assert_called_once()
        self.assertTrue(connection.closed)

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_multiples_movimientos_y_monto_discrepante_revisan(self, connect, config):
        rows = [
            ("0763761428", "FC", "0000002587", 1.0, "H", None, None, None, "a", "u", None, None),
            ("0763761428", "FC", "0000002587", 2.0, "H", None, None, None, "b", "u", None, None),
        ]
        connect.return_value = FakeConnection(rows)
        config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
        cesion = FakeCesion()
        result = obtener_estados_contables_cesiones("09", [cesion])
        self.assertEqual(result[1]["contabilizacion"]["estado"], "REVISAR")
        self.assertEqual(result[1]["contabilizacion"]["cantidad_movimientos"], 2)

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_tipo_no_soportado_no_consulta(self, connect, config):
        config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
        cesion = FakeCesion(tipo_doc="61")
        result = obtener_estados_contables_cesiones("21", [cesion])
        self.assertEqual(result[1]["contabilizacion"]["estado"], "TIPO_NO_SOPORTADO")
        self.assertEqual(result[1]["pago"]["estado"], "TIPO_NO_SOPORTADO")
        connect.assert_not_called()

    def test_codigo_empresa_invalido(self):
        with self.assertRaises(ContabilidadLegacyError):
            obtener_estados_contables_cesiones("9;DROP", [FakeCesion()])
