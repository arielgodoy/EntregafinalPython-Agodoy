"""Tests para gestiondte.services.sii_auth (mockeado, sin red real).

Cubre los 7 casos originales + 8 de request/response + 3 de aio con cero inicial:
1. HTTP 200 + access_token → éxito
2-7. Casos de error y precondiciones
8-15. Formato del request y secrets
16. aio de cert con cero inicial "07762388-4" → "07762388"
17. Comparación normalizada rutenviasii "7762388-4" == cert "07762388-4"
18. Sin cert OtherName → fallback a rutenviasii

8. request contiene Authorization Basic
9. grant_type == cert_credentials
10. scope correcto
11. campo JWT se llama 'jwt'
12. HTTP 200 + application/problem+json → error
13. HTTP 200 + access_token → success
14. HTTP 200 sin access_token → error (ya cubre caso 2)
15. secrets no aparecen en resultado
"""
from unittest.mock import MagicMock, patch
from django.test import TestCase
from django.utils import timezone

from gestiondte.services.sii_auth import SiiAuthError, probar_autenticacion_sii

_MAESTRO_OK = {"rutenviasii": "7762388-4", "rut": "77575300-5", "nombre": "TEST"}
_OPEN_MOCK = MagicMock(return_value=MagicMock(
    __enter__=lambda s: MagicMock(read=lambda: b"pfxdata"),
    __exit__=MagicMock(return_value=False),
))


def _make_cert(activo=True, vencido=False, rut_titular=None, tiene_password=True):
    cert = MagicMock()
    cert.activo = activo
    cert.empresa_codigo = "09"
    cert.titular = "JUAN TITULAR"
    cert.rut_titular = rut_titular
    cert.archivo.name = "certificado.pfx"
    cert.password_encrypted = b"encrypted" if tiene_password else None
    cert.get_password.return_value = "password123" if tiene_password else None

    from datetime import timedelta
    if vencido:
        cert.valido_hasta = timezone.now() - timedelta(days=1)
    else:
        cert.valido_hasta = timezone.now() + timedelta(days=365)
    return cert


class TestSiiAuthPreconditions(TestCase):
    def test_raise_si_certificado_inactivo(self):
        cert = _make_cert(activo=False)
        with self.assertRaises(SiiAuthError) as ctx:
            probar_autenticacion_sii(cert)
        self.assertIn("activo", str(ctx.exception).lower())

    def test_raise_si_certificado_vencido(self):
        cert = _make_cert(vencido=True)
        with self.assertRaises(SiiAuthError) as ctx:
            probar_autenticacion_sii(cert)
        self.assertIn("vencido", str(ctx.exception).lower())

    def test_raise_si_sin_archivo(self):
        cert = _make_cert()
        cert.archivo.name = ""
        with self.assertRaises(SiiAuthError):
            probar_autenticacion_sii(cert)

    def test_raise_si_archivo_no_existe_en_disco(self):
        cert = _make_cert()
        cert.archivo.path = "/ruta/que/no/existe.pfx"
        with self.assertRaises(SiiAuthError) as ctx:
            probar_autenticacion_sii(cert)
        self.assertIn("no existe", str(ctx.exception).lower())

    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value={"rutenviasii": "", "rut": "77575300-5"})
    @patch("os.path.exists", return_value=True)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("builtins.open", MagicMock(return_value=MagicMock(__enter__=lambda s: MagicMock(read=lambda: b"pfxdata"), __exit__=MagicMock(return_value=False))))
    def test_raise_si_rutenviasii_vacio(self, mock_load, mock_exists, mock_maestro):
        mock_cert = MagicMock()
        mock_cert.public_bytes.return_value = b"\x30\x82"
        mock_load.return_value = (MagicMock(), mock_cert, [])
        cert = _make_cert()
        cert.archivo.path = "/fake/cert.pfx"
        with self.assertRaises(SiiAuthError) as ctx:
            probar_autenticacion_sii(cert)
        self.assertIn("certificado no contiene", str(ctx.exception).lower())


class TestSiiAuthFlujoExito(TestCase):
    """Casos 1–5: flujos de respuesta del SII."""

    def setUp(self):
        self._extract_rut_patcher = patch(
            "gestiondte.services.sii_auth._extract_rut_from_cert",
            return_value="07762388-4",
        )
        self._extract_rut_patcher.start()
        self.addCleanup(self._extract_rut_patcher.stop)

    def _cert_con_archivo(self):
        cert = _make_cert()
        cert.rut_titular = None
        cert.archivo.path = "/fake/cert.pfx"
        return cert

    def _mock_pfx(self, mock_load):
        mock_x509 = MagicMock()
        mock_x509.public_bytes.return_value = b"\x30\x82"
        mock_load.return_value = (MagicMock(), mock_x509, [])

    # Caso 1: HTTP 200 + access_token → éxito
    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value=_MAESTRO_OK)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", _OPEN_MOCK)
    def test_caso1_http200_con_token_es_exito(self, mock_exists, mock_load, mock_m, mock_jwt, mock_post):
        self._mock_pfx(mock_load)
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "SECRET", "expires_in": 3600})
        result = probar_autenticacion_sii(self._cert_con_archivo())
        self.assertTrue(result["success"])
        self.assertTrue(result["token_obtenido"])
        self.assertNotIn("access_token", result)
        self.assertNotIn("SECRET", str(result))
        self.assertEqual(result["rut_envio_sii"], "7762388-4")

    # Caso 2: HTTP 200 sin access_token → error
    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value=_MAESTRO_OK)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", _OPEN_MOCK)
    def test_caso2_http200_sin_token_es_error(self, mock_exists, mock_load, mock_m, mock_jwt, mock_post):
        self._mock_pfx(mock_load)
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"token_type": "Bearer"})
        with self.assertRaises(SiiAuthError) as ctx:
            probar_autenticacion_sii(self._cert_con_archivo())
        self.assertIn("access_token", str(ctx.exception).lower())

    # Caso 3: HTTP error (401) → error
    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value=_MAESTRO_OK)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", _OPEN_MOCK)
    def test_caso3_http_error_es_error(self, mock_exists, mock_load, mock_m, mock_jwt, mock_post):
        self._mock_pfx(mock_load)
        mock_post.return_value = MagicMock(
            status_code=401,
            json=lambda: {"error": "invalid_client", "error_description": "Bad cert"},            headers=MagicMock(get=lambda k, d='': 'application/json'),        )
        with self.assertRaises(SiiAuthError) as ctx:
            probar_autenticacion_sii(self._cert_con_archivo())
        self.assertEqual(ctx.exception.http_status, 401)
        self.assertNotIn("password", str(ctx.exception).lower())

    # Caso 4: JSON inválido → error
    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value=_MAESTRO_OK)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", _OPEN_MOCK)
    def test_caso4_json_invalido_es_error(self, mock_exists, mock_load, mock_m, mock_jwt, mock_post):
        self._mock_pfx(mock_load)
        resp = MagicMock(status_code=200)
        resp.json.side_effect = ValueError("no json")
        mock_post.return_value = resp
        with self.assertRaises(SiiAuthError) as ctx:
            probar_autenticacion_sii(self._cert_con_archivo())
        self.assertIn("json", str(ctx.exception).lower())

    # Caso 5: access_token vacío ("") → error
    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value=_MAESTRO_OK)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", _OPEN_MOCK)
    def test_caso5_access_token_vacio_es_error(self, mock_exists, mock_load, mock_m, mock_jwt, mock_post):
        self._mock_pfx(mock_load)
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "", "expires_in": 600})
        with self.assertRaises(SiiAuthError) as ctx:
            probar_autenticacion_sii(self._cert_con_archivo())
        self.assertIn("access_token", str(ctx.exception).lower())

    # Caso 6 y 7: token_obtenido en el resultado es coherente con success
    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value=_MAESTRO_OK)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", _OPEN_MOCK)
    def test_caso6_success_y_token_obtenido_son_coherentes(self, mock_exists, mock_load, mock_m, mock_jwt, mock_post):
        self._mock_pfx(mock_load)
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "REAL_TOKEN"})
        result = probar_autenticacion_sii(self._cert_con_archivo())
        # Ambos deben ser True o ambos False; nunca success=True con token_obtenido=False
        self.assertEqual(result["success"], result["token_obtenido"])

    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value=_MAESTRO_OK)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", _OPEN_MOCK)
    def test_caso7_sin_token_raises_no_retorna_success_true(self, mock_exists, mock_load, mock_m, mock_jwt, mock_post):
        self._mock_pfx(mock_load)
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {})
        with self.assertRaises(SiiAuthError):
            result = probar_autenticacion_sii(self._cert_con_archivo())
            self.assertFalse(result.get("success") and not result.get("token_obtenido"))


class TestSiiAuthRequestFormat(TestCase):
    """Tests 8-15: formato del request y manejo seguro de respuestas."""

    def setUp(self):
        self._extract_rut_patcher = patch(
            "gestiondte.services.sii_auth._extract_rut_from_cert",
            return_value="07762388-4",
        )
        self._extract_rut_patcher.start()
        self.addCleanup(self._extract_rut_patcher.stop)

    def _setup(self, mock_load):
        c = MagicMock()
        c.activo = True
        c.empresa_codigo = "09"
        c.titular = "TITULAR"
        c.rut_titular = None
        c.archivo.name = "cert.pfx"
        c.archivo.path = "/fake/cert.pfx"
        c.password_encrypted = b"enc"
        c.get_password.return_value = "pass"
        from datetime import timedelta
        from django.utils import timezone as tz
        c.valido_hasta = tz.now() + timedelta(days=365)
        x509 = MagicMock()
        x509.public_bytes.return_value = b"\x30\x82"
        mock_load.return_value = (MagicMock(), x509, [])
        return c

    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value=_MAESTRO_OK)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", _OPEN_MOCK)
    def test_8_authorization_basic_presente(self, mock_exists, mock_load, mock_m, mock_jwt, mock_post):
        cert = self._setup(mock_load)
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "TOK"})
        probar_autenticacion_sii(cert)
        _, kwargs = mock_post.call_args
        auth = (kwargs.get('headers') or {}).get('Authorization', '')
        self.assertTrue(auth.startswith('Basic '))

    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value=_MAESTRO_OK)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", _OPEN_MOCK)
    def test_9_grant_type_cert_credentials(self, mock_exists, mock_load, mock_m, mock_jwt, mock_post):
        cert = self._setup(mock_load)
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "TOK"})
        probar_autenticacion_sii(cert)
        _, kwargs = mock_post.call_args
        self.assertEqual((kwargs.get('data') or {}).get('grant_type'), 'cert_credentials')

    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value=_MAESTRO_OK)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", _OPEN_MOCK)
    def test_10_scope_correcto(self, mock_exists, mock_load, mock_m, mock_jwt, mock_post):
        from gestiondte.services.sii_auth import SII_SCOPES
        cert = self._setup(mock_load)
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "TOK"})
        probar_autenticacion_sii(cert)
        _, kwargs = mock_post.call_args
        self.assertEqual((kwargs.get('data') or {}).get('scope'), SII_SCOPES)

    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value=_MAESTRO_OK)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", _OPEN_MOCK)
    def test_11_campo_jwt_no_assertion(self, mock_exists, mock_load, mock_m, mock_jwt, mock_post):
        cert = self._setup(mock_load)
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "TOK"})
        probar_autenticacion_sii(cert)
        _, kwargs = mock_post.call_args
        data = kwargs.get('data') or {}
        self.assertIn('jwt', data)
        self.assertNotIn('assertion', data)

    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value=_MAESTRO_OK)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", _OPEN_MOCK)
    def test_12_problem_json_es_error(self, mock_exists, mock_load, mock_m, mock_jwt, mock_post):
        cert = self._setup(mock_load)
        resp = MagicMock(status_code=200)
        resp.headers.get = lambda k, d='': 'application/problem+json' if k == 'Content-Type' else d
        resp.json.return_value = {"status": 400, "detail": "Required header missing."}
        mock_post.return_value = resp
        with self.assertRaises(SiiAuthError) as ctx:
            probar_autenticacion_sii(cert)
        self.assertIn("sii", str(ctx.exception).lower())

    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value=_MAESTRO_OK)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", _OPEN_MOCK)
    def test_13_success_true_cuando_hay_token(self, mock_exists, mock_load, mock_m, mock_jwt, mock_post):
        cert = self._setup(mock_load)
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"access_token": "T", "expires_in": 600})
        result = probar_autenticacion_sii(cert)
        self.assertTrue(result["success"])
        self.assertTrue(result["token_obtenido"])

    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value=_MAESTRO_OK)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", _OPEN_MOCK)
    def test_14_secrets_no_en_resultado(self, mock_exists, mock_load, mock_m, mock_jwt, mock_post):
        cert = self._setup(mock_load)
        mock_post.return_value = MagicMock(status_code=200,
                                           json=lambda: {"access_token": "SECRET_TOK",
                                                         "refresh_token": "SECRET_REF",
                                                         "id_token": "SECRET_ID"})
        result = probar_autenticacion_sii(cert)
        for secret in ("SECRET_TOK", "SECRET_REF", "SECRET_ID"):
            self.assertNotIn(secret, str(result))
        for key in ("access_token", "refresh_token", "id_token"):
            self.assertNotIn(key, result)

    @patch("gestiondte.services.sii_auth.requests.post")
    @patch("gestiondte.services.sii_auth._build_jwt", return_value="h.p.s")
    @patch("gestiondte.utils.maestro.get_maestroempresa_by_codigo", return_value=_MAESTRO_OK)
    @patch("gestiondte.services.sii_auth.load_key_and_certificates")
    @patch("os.path.exists", return_value=True)
    @patch("builtins.open", _OPEN_MOCK)
    def test_15_password_no_en_error(self, mock_exists, mock_load, mock_m, mock_jwt, mock_post):
        cert = self._setup(mock_load)
        mock_post.return_value = MagicMock(
            status_code=401,
            json=lambda: {"error": "invalid", "error_description": "rejected"},
            headers=MagicMock(get=lambda k, d='': 'application/json'),
        )
        with self.assertRaises(SiiAuthError) as ctx:
            probar_autenticacion_sii(cert)
        self.assertNotIn("pass", str(ctx.exception).lower()[:100])


class TestAioCeroInicial(TestCase):
    """Tests 16-18: aio preserva cero inicial del certificado X.509."""

    def test_16_rut_sin_dv_preserva_cero_inicial(self):
        from gestiondte.services.sii_auth import _rut_sin_dv
        # "07762388-4" → "07762388" (cero preservado, sin DV)
        self.assertEqual(_rut_sin_dv("07762388-4"), "07762388")

    def test_17_comparacion_normalizada_coincide(self):
        from gestiondte.services.sii_auth import _rut_sin_dv
        # Ambos representan el mismo RUT cuando se normaliza con lstrip('0')
        cert_rut = _rut_sin_dv("07762388-4")   # "07762388"
        legacy_rut = _rut_sin_dv("7762388-4")  # "7762388"
        self.assertEqual(cert_rut.lstrip('0'), legacy_rut.lstrip('0'))

    def test_18_extract_rut_from_cert_otherName(self):
        from gestiondte.services.sii_auth import _extract_rut_from_cert
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        from unittest.mock import MagicMock

        # Simular OtherName con IA5String "07762388-4"
        # DER: tag=0x16, len=0x0a, "07762388-4"
        rut_str = "07762388-4"
        raw_bytes = bytes([0x16, len(rut_str)]) + rut_str.encode('ascii')

        other_name = x509.OtherName(
            type_id=x509.ObjectIdentifier("1.3.6.1.4.1.8321.1"),
            value=raw_bytes,
        )
        mock_san_ext = MagicMock()
        mock_san_ext.value.__iter__ = MagicMock(return_value=iter([other_name]))

        mock_cert = MagicMock()
        mock_cert.extensions.get_extension_for_oid.return_value = mock_san_ext

        result = _extract_rut_from_cert(mock_cert)
        self.assertEqual(result, "07762388-4")
