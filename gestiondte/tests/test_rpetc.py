from unittest.mock import MagicMock, call, patch

from django.test import SimpleTestCase

from gestiondte.services.rpetc import (
    RPETCClient,
    RPETCError,
    RPETCNotFoundError,
    RPETCParameterError,
    RPETCRateLimitError,
    RPETCServerError,
    RPETCTaskFailedError,
    RPETCTaskTimeoutError,
    RPETCUnauthorizedError,
    RPETCAuthenticationError,
)
from gestiondte.services.rpetc_parser import parsear_txt_rpetc


class TestRPETCClient(SimpleTestCase):
    def setUp(self):
        self.cert = MagicMock(empresa_codigo="09")
        self.session = MagicMock()
        self.client = RPETCClient(self.cert, session=self.session, sleep=MagicMock())
        self.auth = patch(
            "gestiondte.services.rpetc.obtener_access_token_sii",
            return_value={
                "access_token": "TOKEN",
                "token_type": "Bearer",
                "scope": "RTC_TAR RTC_PRO_EST RTC_PRO_RES",
            },
        )
        self.auth.start()
        self.addCleanup(self.auth.stop)

    def response(self, body, status=200, content_type="application/json", content=b""):
        response = MagicMock()
        response.status_code = status
        response.headers = {"Content-Type": content_type}
        response.json.return_value = body
        response.content = content
        response.text = str(body)
        return response

    def test_crear_tarea_url_params_y_filtros_vacios_omitidos(self):
        self.session.get.return_value = self.response({"idTarea": "t1"})
        result = self.client.crear_tarea_cesiones_deudor(
            "77575300", "5", "01072026", "31072026", "txt"
        )
        self.assertEqual(result["idTarea"], "t1")
        request = self.session.get.call_args
        self.assertIn("/recurso/v1/tarea/77575300-5/cesiones.deudor", request.args[0])
        self.assertEqual(request.kwargs["params"], {
            "desde": "01072026", "hasta": "31072026", "formato": "TXT"
        })
        self.assertEqual(request.kwargs["headers"]["Authorization"], "Bearer TOKEN")

    def test_crear_tarea_incluye_filtros_completos(self):
        self.session.get.return_value = self.response({})
        self.client.crear_tarea_cesiones_deudor(
            "1", "9", "01072026", "01072026", "XML",
            rut_cedente="2", dv_cedente="8",
            rut_cesionario="3", dv_cesionario="7",
        )
        params = self.session.get.call_args.kwargs["params"]
        self.assertEqual(params["rutCedente"], "2")
        self.assertEqual(params["dvCedente"], "8")
        self.assertEqual(params["rutCesionario"], "3")
        self.assertEqual(params["dvCesionario"], "7")

    def test_valida_fechas_formato_y_rango(self):
        for values in (
            ("31022026", "01032026", "TXT"),
            ("02072026", "01072026", "TXT"),
            ("01072026", "02082026", "TXT"),
            ("01072026", "01072026", "CSV"),
        ):
            with self.subTest(values=values):
                with self.assertRaises(RPETCParameterError):
                    self.client.crear_tarea_cesiones_deudor("1", "9", *values)
        self.session.get.assert_not_called()

    def test_estado_preserva_rut_autenticado(self):
        self.session.get.return_value = self.response({"estado": "CREADO"})
        self.client.consultar_estado_tarea("7762388", "4", "t1")
        path = self.session.get.call_args.args[0]
        self.assertIn("/recurso/v1/estado/7762388-4/t1", path)

    def test_polling_normaliza_en_proceso_con_espacio_y_duerme(self):
        self.session.get.side_effect = [
            self.response({"estado": "CREADO"}),
            self.response({"estado": "EN PROCESO"}),
            self.response({"estado": "TERMINADO", "fileSize": 10}),
        ]
        sleep = MagicMock()
        client = RPETCClient(self.cert, session=self.session, sleep=sleep)
        with patch("gestiondte.services.rpetc.obtener_access_token_sii", return_value={"access_token": "T", "token_type": "Bearer", "scope": "RTC_PRO_EST"}):
            result = client.esperar_tarea("1", "9", "t1", intervalo=3, max_intentos=5)
        self.assertEqual(result["estado"], "TERMINADO")
        self.assertEqual(sleep.call_args_list, [call(3), call(3)])

    def test_polling_fallo(self):
        self.session.get.return_value = self.response({
            "estado": "FALLO", "codigoError": 12, "descripcionError": "fallo"
        })
        with self.assertRaises(RPETCTaskFailedError) as error:
            self.client.esperar_tarea("1", "9", "t1")
        self.assertEqual(error.exception.task_state["codigoError"], 12)

    def test_polling_timeout(self):
        self.session.get.return_value = self.response({"estado": "CREADO"})
        with self.assertRaises(RPETCTaskTimeoutError):
            self.client.esperar_tarea("1", "9", "t1", intervalo=0, max_intentos=2)

    def test_descarga_binaria_y_headers(self):
        self.session.get.return_value = self.response(
            {}, content_type="application/octet-stream", content=b"TXT"
        )
        self.session.get.return_value.headers["Content-Disposition"] = 'attachment; filename="t.txt"'
        result = self.client.descargar_resultado_tarea("1", "9", "t1")
        self.assertEqual(result["bytes"], b"TXT")
        self.assertEqual(result["content_type"], "application/octet-stream")
        self.assertIn("filename", result["content_disposition"])

    def test_http_errors_mapeados(self):
        for status, error_type in (
            (400, RPETCError),
            (401, RPETCAuthenticationError),
            (403, RPETCUnauthorizedError),
            (404, RPETCNotFoundError),
            (429, RPETCRateLimitError),
            (500, RPETCServerError),
        ):
            with self.subTest(status=status):
                self.session.get.return_value = self.response({"error": "x"}, status=status)
                with self.assertRaises(error_type) as error:
                    self.client.consultar_estado_tarea("1", "9", "t1")
                self.assertEqual(error.exception.status_code, status)


class TestRPETCParser(SimpleTestCase):
    def test_parsea_metadata_headers_id_cesion_y_registros(self):
        content = (
            "DATOS_CONSULTA;RUT=1-9;TIPO_CONSULTA=DEUDOR;"
            "DESDE_DDMMAAAA=01072026;HASTA_DDMMAAAA=31072026\n"
            "VENDEDOR;ESTADO_CESION;DEUDOR;MAIL_DEUDOR;TIPO_DOC;NOMBRE_DOC;"
            "FOLIO_DOC;FCH_EMIS_DTE;MNT_TOTAL;CEDENTE;RZ_CEDENTE;MAIL_CEDENTE;"
            "CESIONARIO;RZ_CESIONARIO;MAIL_CESIONARIO;FCH_CESION;MNT_CESION;"
            "FCH_VENCIMIENTO;ID_CESION\n"
            "1-9;Cesion Vigente;1-9;;33;Factura;10;2026-07-01;100;"
            "2-8;Cedente;;3-7;Cesionario;;2026-07-02;100;2026-08-01;ABC\n"
            "1-9;Cesion Vigente;1-9;;33;Factura;11;2026-07-01;200;"
            "2-8;Cedente;;3-7;Cesionario;;2026-07-02;200;2026-08-01;DEF\n"
        ).encode()
        parsed = parsear_txt_rpetc(content)
        self.assertEqual(parsed["consulta"]["TIPO_CONSULTA"], "DEUDOR")
        self.assertEqual(len(parsed["columnas"]), 19)
        self.assertIn("ID_CESION", parsed["columnas"])
        self.assertEqual(parsed["cantidad_registros"], 2)
        self.assertEqual(parsed["registros"][0]["ID_CESION"], "ABC")

    def test_parser_usa_cp1252_si_utf8_falla(self):
        content = "DATOS_CONSULTA;TIPO_CONSULTA=DEUDOR\nNOMBRE\nCesion v\xe1lida\n".encode("cp1252")
        parsed = parsear_txt_rpetc(content)
        self.assertEqual(parsed["registros"][0]["NOMBRE"], "Cesion válida")
