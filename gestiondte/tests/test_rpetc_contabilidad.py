from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from gestiondte.services.rpetc_contabilidad import (
    ContabilidadLegacyError,
    normalizar_folio_legacy,
    normalizar_rut_legacy,
    obtener_estados_contables_cesiones,
)
from gestiondte.views import _rpetc_pagos_pendientes_ids


class LegacyCursor:
    description = [
        ("rutctacte",), ("tipodocumento",), ("numerodocumento",), ("monto",),
        ("dh",), ("fecha",), ("fechadocumento",), ("fechavencimiento",),
        ("glosacontable",), ("creadopor",), ("fechacreacion",), ("horacreacion",), ("tipo",), ("codigocuenta",),
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
    def test_rpetc_pagos_pendientes_usa_interseccion_y_no_or(self):
        states = {
            1: {'pagada_factoring': {'estado': 'NO_PAGADA'}, 'pagada_proveedor': {'estado': 'PAGADA_PROVEEDOR'}},
            2: {'pagada_factoring': {'estado': 'REVISAR'}, 'pagada_proveedor': {'estado': 'NO_PAGADA'}},
            3: {'pagada_factoring': {'estado': 'PAGADA_FACTORING'}, 'pagada_proveedor': {'estado': 'NO_PAGADA'}},
            4: {'pagada_factoring': {'estado': 'NO_PAGADA'}, 'pagada_proveedor': {'estado': 'NO_PAGADA'}},
            5: {'pagada_factoring': {'estado': 'NO_DISPONIBLE'}, 'pagada_proveedor': {'estado': 'NO_PAGADA'}},
        }
        self.assertEqual(_rpetc_pagos_pendientes_ids(states, sin_pago_factoring=True, sin_pago_proveedor=False), {1, 2, 4})
        self.assertEqual(_rpetc_pagos_pendientes_ids(states, sin_pago_factoring=False, sin_pago_proveedor=True), {2, 3, 4, 5})
        self.assertEqual(_rpetc_pagos_pendientes_ids(states, sin_pago_factoring=True, sin_pago_proveedor=True), {2, 4})

    def test_proveedor_usa_monto_total_y_no_monto_cesion(self):
        cesion = FakeCesion()
        cesion.monto_total = Decimal("1764799")
        cesion.monto_cesion = Decimal("999000")
        rows = [("0763761428", "FC", "0000002587", 1764799.0, "D", None, None, None, "CANCELA DOCUMENTO", "u", None, None, "DB", "23100026")]
        with patch("gestiondte.services.rpetc_contabilidad._config_legacy") as config, patch("gestiondte.services.rpetc_contabilidad.pymysql.connect") as connect:
            connect.return_value = FakeConnection(rows)
            config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
            result = obtener_estados_contables_cesiones("09", [cesion])
        self.assertEqual(result[1]["pagada_proveedor"]["estado"], "PAGADA_PROVEEDOR")

    def test_proveedor_2383_con_diferencia_conserva_pago(self):
        cesion = FakeCesion(folio_doc="2383")
        cesion.monto_total = Decimal("3122579")
        cesion.monto_cesion = Decimal("3122579")
        rows = [("0763761428", "FC", "0000002383", 3123479.0, "D", None, None, None, "CANCELA DOCUMENTO", "u", None, None, "DB", "23100026")]
        with patch("gestiondte.services.rpetc_contabilidad._config_legacy") as config, patch("gestiondte.services.rpetc_contabilidad.pymysql.connect") as connect:
            connect.return_value = FakeConnection(rows)
            config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
            result = obtener_estados_contables_cesiones("09", [cesion])
        payment = result[1]["pagada_proveedor"]
        self.assertEqual(payment["estado"], "PAGADA_PROVEEDOR_DIFERENCIA")
        self.assertEqual(payment["diferencia_monto"], Decimal("900"))
        self.assertNotEqual(payment["estado"], "NO_PAGADA")

    @patch("gestiondte.services.rpetc_contabilidad._query_factoring_glosa_candidates", return_value=[])
    def test_factoring_con_diferencia_conserva_pago(self, fallback):
        cesion = FakeCesion()
        rows = [("0766826709", "FC", "0000002587", 1764899.0, "D", None, None, None, "pago factoring", "u", None, None, "DB", "23100026")]
        with patch("gestiondte.services.rpetc_contabilidad._config_legacy") as config, patch("gestiondte.services.rpetc_contabilidad.pymysql.connect") as connect:
            connect.return_value = FakeConnection(rows)
            config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
            result = obtener_estados_contables_cesiones("09", [cesion])
        self.assertEqual(result[1]["pagada_factoring"]["estado"], "PAGADA_FACTORING_DIFERENCIA")
        self.assertEqual(result[1]["pagada_factoring"]["diferencia_monto"], Decimal("100"))

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
            ("0763761428", "FC", "0000002587", 1764799.0, "H", None, None, None, "CONTABILIZACION FAE", "u", None, None, "DB", "23100026"),
            ("0766826709", "FC", "0000002587", 1764799.0, "D", None, None, None, "CANCELA DOCUMENTO", "u", None, None, "DB", "23100026"),
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
        self.assertEqual(connection.cursor_obj.params.count("0000002587"), 4)
        self.assertNotIn("LIKE", connection.cursor_obj.sql.upper())
        self.assertIn("eltit_conta09", connection.cursor_obj.sql)
        connect.assert_called_once()
        self.assertTrue(connection.closed)

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_multiples_movimientos_y_monto_discrepante_revisan(self, connect, config):
        rows = [
            ("0763761428", "FC", "0000002587", 1.0, "H", None, None, None, "a", "u", None, None, "DB", "23100026"),
            ("0763761428", "FC", "0000002587", 2.0, "H", None, None, None, "b", "u", None, None, "DB", "23100026"),
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

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_pago_proveedor_excluye_movimiento_ct(self, connect, config):
        rows = [
            ("0763761428", "FC", "0000002587", 1764799.0, "D", None, None, None, "traspaso", "u", None, None, "CT", "23100026"),
            ("0766826709", "FC", "0000002587", 1764799.0, "D", None, None, None, "factoring", "u", None, None, "DB", "23100026"),
        ]
        connect.return_value = FakeConnection(rows)
        config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
        result = obtener_estados_contables_cesiones("09", [FakeCesion()])
        self.assertEqual(result[1]["pagada_factoring"]["estado"], "PAGADA_FACTORING")
        self.assertEqual(result[1]["pagada_proveedor"]["estado"], "NO_PAGADA")
        self.assertEqual(result[1]["pago"]["estado"], "PAGADA")

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_pago_proveedor_se_marca_con_movimiento_no_ct(self, connect, config):
        rows = [("0763761428", "FC", "0000002587", 1764799.0, "D", None, None, None, "pago proveedor", "u", None, None, "DB", "23100026")]
        connect.return_value = FakeConnection(rows)
        config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
        result = obtener_estados_contables_cesiones("09", [FakeCesion()])
        self.assertEqual(result[1]["pagada_proveedor"]["estado"], "PAGADA_PROVEEDOR")

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_fc_2580_contabilizada_factoring_sin_pago_proveedor(self, connect, config):
        rows = [
            ("0763761428", "FC", "0000002580", 1892029.0, "H", None, None, None, "contabilizada", "u", None, None, "DB", "23100026"),
            ("0766826709", "FC", "0000002580", 1892029.0, "D", None, None, None, "factoring", "u", None, None, "DB", "23100026"),
            ("0763761428", "FC", "0000002580", 1892029.0, "D", None, None, None, "traspaso", "u", None, None, "CT", "23100026"),
        ]
        connect.return_value = FakeConnection(rows)
        config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
        cesion = FakeCesion(folio_doc="2580")
        cesion.monto_total = Decimal("1892029")
        cesion.monto_cesion = Decimal("1892029")
        result = obtener_estados_contables_cesiones("09", [cesion])
        self.assertEqual(result[1]["contabilizacion"]["estado"], "CONTABILIZADA")
        self.assertEqual(result[1]["pagada_factoring"]["estado"], "PAGADA_FACTORING")
        self.assertEqual(result[1]["pagada_proveedor"]["estado"], "NO_PAGADA")

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_fc_3142_sin_pagos(self, connect, config):
        connect.return_value = FakeConnection([
            ("0763761428", "FC", "0000003142", 1764799.0, "H", None, None, None, "contabilizada", "u", None, None, "DB", "23100026"),
        ])
        config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
        cesion = FakeCesion(folio_doc="3142")
        result = obtener_estados_contables_cesiones("09", [cesion])
        self.assertEqual(result[1]["contabilizacion"]["estado"], "CONTABILIZADA")
        self.assertEqual(result[1]["pagada_factoring"]["estado"], "NO_PAGADA")
        self.assertEqual(result[1]["pagada_proveedor"]["estado"], "NO_PAGADA")

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_cuentas_iva_y_mercaderias_no_activan_pagos(self, connect, config):
        rows = [
            ("0765197139", "FC", "0000003142", 29678.0, "D", None, None, None, "IVA", "u", None, None, "DB", "11400001"),
            ("0765197139", "FC", "0000003142", 156200.0, "D", None, None, None, "mercaderias", "u", None, None, "DB", "11350001"),
        ]
        connect.return_value = FakeConnection(rows)
        config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
        result = obtener_estados_contables_cesiones("09", [FakeCesion(folio_doc="3142")])
        self.assertEqual(result[1]["pagada_factoring"]["estado"], "NO_PAGADA")
        self.assertEqual(result[1]["pagada_proveedor"]["estado"], "NO_PAGADA")

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_db_con_folio_exacto_activa_factoring(self, connect, config):
        rows = [
            ("0766826709", "DB", "0000002509", 3498155.0, "D", None, None, None, "FAC 2509", "u", None, None, "DB", "23100026"),
        ]
        connect.return_value = FakeConnection(rows)
        config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
        cesion = FakeCesion(folio_doc="2509")
        cesion.monto_cesion = Decimal("3498155")
        result = obtener_estados_contables_cesiones("09", [cesion])
        self.assertEqual(result[1]["pagada_factoring"]["estado"], "PAGADA_FACTORING")

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_db_agrupado_identifica_cuatro_facturas_en_un_batch(self, connect, config):
        folios_y_montos = {
            "2509": Decimal("3498155"),
            "2510": Decimal("1874250"),
            "2511": Decimal("503527"),
            "2512": Decimal("446821"),
        }
        cesiones = [
            FakeCesion(pk=index, folio_doc=folio)
            for index, folio in enumerate(folios_y_montos, start=1)
        ]
        for cesion in cesiones:
            cesion.monto_cesion = folios_y_montos[cesion.folio_doc]
        rows = [
            ("0766826709", "DB", f"000000{folio}", float(monto), "D", None, None, None, "FAC agrupadas", "u", None, None, "DB", "23100026")
            for folio, monto in folios_y_montos.items()
        ]
        connect.return_value = FakeConnection(rows)
        config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
        result = obtener_estados_contables_cesiones("09", cesiones)
        self.assertTrue(all(result[cesion.pk]["pagada_factoring"]["estado"] == "PAGADA_FACTORING" for cesion in cesiones))
        connect.assert_called_once()

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_db_sin_folio_exacto_activa_factoring_por_glosa_3019(self, connect, config):
        rows = [
            ("0766826709", "DB", "0000000109", 2530844.0, "D", None, None, None, "FAC 3019 V/S AM DECO", "u", None, None, "DB", "23100026"),
        ]
        connect.return_value = FakeConnection(rows)
        config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
        cesion = FakeCesion(folio_doc="3019")
        cesion.monto_cesion = Decimal("2530844")
        result = obtener_estados_contables_cesiones("09", [cesion])
        self.assertEqual(result[1]["pagada_factoring"]["estado"], "PAGADA_FACTORING")

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_glosa_requiere_token_numerico_completo(self, connect, config):
        rows = [
            ("0766826709", "DB", "0000000109", 2530844.0, "D", None, None, None, "FAC 13019", "u", None, None, "DB", "23100026"),
            ("0766826709", "DB", "0000000110", 2530844.0, "D", None, None, None, "FAC 30190", "u", None, None, "DB", "23100026"),
            ("0766826709", "DB", "0000000111", 2530844.0, "D", None, None, None, "", "u", None, None, "DB", "23100026"),
        ]
        connect.return_value = FakeConnection(rows)
        config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
        cesion = FakeCesion(folio_doc="3019")
        cesion.monto_cesion = Decimal("2530844")
        result = obtener_estados_contables_cesiones("09", [cesion])
        self.assertEqual(result[1]["pagada_factoring"]["estado"], "NO_PAGADA")

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_glosa_fallback_requiere_rut_monto_cuenta_dh_y_tipo_db(self, connect, config):
        rows = [
            ("0000000000", "DB", "0000000001", 2530844.0, "D", None, None, None, "FAC 3019", "u", None, None, "DB", "23100026"),
            ("0766826709", "DB", "0000000002", 1.0, "D", None, None, None, "FAC 3019", "u", None, None, "DB", "23100026"),
            ("0766826709", "DB", "0000000003", 2530844.0, "D", None, None, None, "FAC 3019", "u", None, None, "DB", "11400001"),
            ("0766826709", "DB", "0000000004", 2530844.0, "H", None, None, None, "FAC 3019", "u", None, None, "DB", "23100026"),
            ("0766826709", "FC", "0000000005", 2530844.0, "D", None, None, None, "FAC 3019", "u", None, None, "FC", "23100026"),
        ]
        connect.return_value = FakeConnection(rows)
        config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
        cesion = FakeCesion(folio_doc="3019")
        cesion.monto_cesion = Decimal("2530844")
        result = obtener_estados_contables_cesiones("09", [cesion])
        self.assertEqual(result[1]["pagada_factoring"]["estado"], "NO_PAGADA")

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_matching_exacto_tiene_prioridad_sobre_glosa(self, connect, config):
        rows = [
            ("0766826709", "DB", "0000003019", 2530844.0, "D", None, None, None, "FAC 9999", "u", None, None, "DB", "23100026"),
            ("0766826709", "DB", "0000000009", 2530844.0, "D", None, None, None, "FAC 3019", "u", None, None, "DB", "23100026"),
        ]
        connect.return_value = FakeConnection(rows)
        config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
        cesion = FakeCesion(folio_doc="3019")
        cesion.monto_cesion = Decimal("2530844")
        result = obtener_estados_contables_cesiones("09", [cesion])
        self.assertEqual(result[1]["pagada_factoring"]["estado"], "PAGADA_FACTORING")
        self.assertEqual(result[1]["pagada_factoring"]["movimientos"][0]["numerodocumento"], "0000003019")

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_glosa_agrupada_identifica_cuatro_facturas_en_un_fallback_batch(self, connect, config):
        folios_y_montos = {
            "2509": Decimal("3498155"),
            "2510": Decimal("1874250"),
            "2511": Decimal("503527"),
            "2512": Decimal("446821"),
        }
        cesiones = [
            FakeCesion(pk=index, folio_doc=folio)
            for index, folio in enumerate(folios_y_montos, start=1)
        ]
        for cesion in cesiones:
            cesion.monto_cesion = folios_y_montos[cesion.folio_doc]
        rows = [
            ("0766826709", "DB", "0000000108", float(monto), "D", None, None, None, "FAC 2511-2510-2512-2509 V/S ACTYON", "u", None, None, "DB", "23100026")
            for monto in folios_y_montos.values()
        ]
        connect.return_value = FakeConnection(rows)
        config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
        result = obtener_estados_contables_cesiones("09", cesiones)
        self.assertTrue(all(result[cesion.pk]["pagada_factoring"]["estado"] == "PAGADA_FACTORING" for cesion in cesiones))
        self.assertEqual(connect.call_count, 2)

    @patch("gestiondte.services.rpetc_contabilidad._config_legacy")
    @patch("gestiondte.services.rpetc_contabilidad.pymysql.connect")
    def test_db_factoring_requiere_rut_cuenta_dh_y_monto(self, connect, config):
        rows = [
            ("0000000000", "DB", "0000002509", 3498155.0, "D", None, None, None, "rut incorrecto", "u", None, None, "DB", "23100026"),
            ("0766826709", "DB", "0000002510", 3498155.0, "D", None, None, None, "monto incorrecto", "u", None, None, "DB", "23100026"),
            ("0766826709", "DB", "0000002511", 3498155.0, "H", None, None, None, "dh incorrecto", "u", None, None, "DB", "23100026"),
            ("0766826709", "DB", "0000002512", 3498155.0, "D", None, None, None, "cuenta incorrecta", "u", None, None, "DB", "11400001"),
        ]
        connect.return_value = FakeConnection(rows)
        config.return_value = SimpleNamespace(host="h", port=3306, user="u", password="p", db_name="eltit_conta", charset="latin1")
        cesiones = [FakeCesion(pk=index, folio_doc=folio) for index, folio in enumerate(("2509", "2510", "2511", "2512"), start=1)]
        result = obtener_estados_contables_cesiones("09", cesiones)
        self.assertTrue(all(result[cesion.pk]["pagada_factoring"]["estado"] != "PAGADA_FACTORING" for cesion in cesiones))

    def test_fallback_error_conserva_exactos_y_marca_pendiente_no_disponible(self):
        exact_cesion = FakeCesion(pk=2509, folio_doc="2509")
        exact_cesion.monto_cesion = Decimal("3498155")
        pending_cesion = FakeCesion(pk=3019, folio_doc="3019")
        pending_cesion.monto_cesion = Decimal("2530844")
        exact_movement = {
            "rutctacte": "0766826709",
            "codigocuenta": "23100026",
            "dh": "D",
            "monto": 3498155,
            "tipodocumento": "DB",
            "numerodocumento": "0000002509",
            "tipo": "DB",
            "glosacontable": "FAC 2509",
        }
        with patch(
            "gestiondte.services.rpetc_contabilidad._query_movimientos",
            return_value=[exact_movement],
        ), patch(
            "gestiondte.services.rpetc_contabilidad._query_factoring_glosa_candidates",
            side_effect=RuntimeError("fallback unavailable"),
        ):
            result = obtener_estados_contables_cesiones("09", [exact_cesion, pending_cesion])

        self.assertEqual(result[2509]["pagada_factoring"]["estado"], "PAGADA_FACTORING")
        self.assertEqual(result[3019]["pagada_factoring"]["estado"], "NO_DISPONIBLE")
        self.assertEqual(result[3019]["pago"]["estado"], "NO_DISPONIBLE")

    def test_fallback_exitoso_registra_observabilidad(self):
        cesion = FakeCesion(folio_doc="3019")
        cesion.monto_cesion = Decimal("2530844")
        movement = {
            "rutctacte": "0766826709",
            "codigocuenta": "23100026",
            "dh": "D",
            "monto": 2530844,
            "tipodocumento": "DB",
            "numerodocumento": "0000000109",
            "tipo": "DB",
            "glosacontable": "FAC 3019 V/S AM DECO",
        }
        with patch(
            "gestiondte.services.rpetc_contabilidad._query_movimientos",
            return_value=[],
        ), patch(
            "gestiondte.services.rpetc_contabilidad._query_factoring_glosa_candidates",
            return_value=[movement],
        ), self.assertLogs("gestiondte.services.rpetc_contabilidad", level="DEBUG") as logs:
            result = obtener_estados_contables_cesiones("09", [cesion])

        output = "\n".join(logs.output)
        self.assertEqual(result[1]["pagada_factoring"]["estado"], "PAGADA_FACTORING")
        self.assertIn("fallback iniciado", output)
        self.assertIn("candidatos SQL: count=1", output)
        self.assertIn("folio_normalized=3019", output)
        self.assertIn("match=True", output)
        self.assertIn("final=PAGADA_FACTORING", output)

    def test_template_distingue_no_pagada_de_no_disponible(self):
        template = (
            Path(__file__).resolve().parents[1] / "templates/gestiondte/cesiones.html"
        ).read_text(encoding="utf-8")
        self.assertIn("NO_PAGADA:'No'", template)
        self.assertIn("NO_DISPONIBLE:'Revisar'", template)
        self.assertIn("st==='REVISAR'||st==='NO_DISPONIBLE'", template)
