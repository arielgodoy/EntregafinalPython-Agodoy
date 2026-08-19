"""
Servicio de autenticación OAuth con el SII usando certificado PFX/P12.

Flujo: cargar PFX → construir JWT RS256 firmado → solicitar access_token.
NO persiste tokens. NO implementa consultas RPETC/DTE.
NUNCA registra ni devuelve secretos (password, clave privada, tokens).
"""
import base64
import json
import logging
import time

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

logger = logging.getLogger(__name__)

SII_TOKEN_URL = "https://api.sii.cl/oauthsii-v1-ms/extauth/v1/token"
SII_SCOPES = "RTC_TAR RTC_PRO_RES RTC_PRO_TOD RTC_PRO_PER RTC_PRO_EST"
JWT_LIFETIME_SECONDS = 600


class SiiAuthError(Exception):
    """Error controlado retornado al caller; no expone secretos."""
    def __init__(self, message: str, http_status: int | None = None):
        super().__init__(message)
        self.http_status = http_status


def _rut_sin_dv(rut: str | None) -> str:
    """Extrae la parte numérica del RUT sin dígito verificador."""
    if not rut:
        return ""
    # Soporta "12345678-9", "12.345.678-9", etc.
    rut = rut.strip().replace(".", "").replace(" ", "")
    if "-" in rut:
        return rut.split("-")[0]
    return rut[:-1] if rut else rut


def _extract_rut_from_cert(cert) -> str | None:
    """Lee el RUT desde subjectAltName OtherName OID 1.3.6.1.4.1.8321.1 (E-CERTCHILE)."""
    try:
        from cryptography import x509 as _x509
        _RUT_OID = _x509.ObjectIdentifier("1.3.6.1.4.1.8321.1")
        san = cert.extensions.get_extension_for_oid(
            _x509.ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        )
        for name in san.value:
            if isinstance(name, _x509.OtherName) and name.type_id == _RUT_OID:
                raw = name.value  # DER bytes: \x16\x0a + string bytes
                if len(raw) >= 2 and raw[0] == 0x16:  # IA5String tag
                    length = raw[1]
                    return raw[2:2 + length].decode('ascii').strip()
                return raw.decode('ascii', errors='replace').strip()
    except Exception:
        pass
    return None


def _build_jwt(private_key, cert_der: bytes, rut_sin_dv: str, audience: str) -> str:
    """Construye y firma el JWT RS256 según especificación SII."""
    now = int(time.time())

    header = {
        "alg": "RS256",
        "x5c": base64.b64encode(cert_der).decode(),
    }
    payload = {
        "aio": rut_sin_dv,
        "exp": now + JWT_LIFETIME_SECONDS,
        "aud": audience,
    }

    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()

    from cryptography.hazmat.primitives.asymmetric import padding
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header_b64}.{payload_b64}.{_b64url(signature)}"


def probar_autenticacion_sii(certificado_sii, *, _incluir_access_token=False) -> dict:
    """
    Autentica contra el SII con el certificado PFX dado y retorna resultado seguro.

    Usa maestroempresas.rutenviasii como RUT autenticador (campo aio del JWT).
    NO persiste tokens. NO implementa consultas RPETC/DTE.
    """
    empresa_codigo = certificado_sii.empresa_codigo

    # — Validar precondiciones —
    from django.utils import timezone
    if not certificado_sii.activo:
        raise SiiAuthError("El certificado no está activo para esta empresa.")

    if certificado_sii.valido_hasta and timezone.now() > certificado_sii.valido_hasta:
        raise SiiAuthError("El certificado está vencido.")

    if not certificado_sii.archivo or not certificado_sii.archivo.name:
        raise SiiAuthError("No hay archivo de certificado asociado.")

    try:
        pfx_path = certificado_sii.archivo.path
    except Exception:
        raise SiiAuthError("No se puede acceder al archivo del certificado.")

    import os
    if not os.path.exists(pfx_path):
        raise SiiAuthError("El archivo del certificado no existe en disco.")

    plain_password = certificado_sii.get_password()
    if plain_password is None and certificado_sii.password_encrypted:
        raise SiiAuthError("No se pudo descifrar la contraseña del certificado.")

    # — Cargar PFX —
    try:
        with open(pfx_path, "rb") as fh:
            pfx_data = fh.read()
        pwd_bytes = plain_password.encode() if plain_password else None
        private_key, cert, _ = load_key_and_certificates(pfx_data, pwd_bytes)
    except Exception:
        # No loggear excepción completa para no exponer paths
        logger.warning("sii_auth: fallo al cargar PFX para empresa=%s", empresa_codigo)
        raise SiiAuthError("No se pudo abrir el certificado PFX. Verifique el archivo y la contraseña.")
    finally:
        plain_password = None  # limpiar inmediatamente de memoria

    # — Extraer DER del certificado X.509 —
    try:
        cert_der = cert.public_bytes(serialization.Encoding.DER)
    except Exception:
        logger.warning("sii_auth: error extrayendo DER para empresa=%s", empresa_codigo)
        raise SiiAuthError("No se pudo extraer el certificado X.509 del PFX.")

    # — Obtener rutenviasii desde maestroempresas (fuente principal de aio) —
    from gestiondte.utils.maestro import get_maestroempresa_by_codigo
    empresa_data = get_maestroempresa_by_codigo(empresa_codigo)
    rutenviasii_raw = (empresa_data or {}).get('rutenviasii') or ''
    rutenviasii_raw = str(rutenviasii_raw).strip()

    # — Determinar aio: RUT del certificado X.509 (conserva cero inicial) —
    rut_cert_raw = _extract_rut_from_cert(cert)  # ej. "07762388-4"
    if rut_cert_raw:
        rut_sin_dv = _rut_sin_dv(rut_cert_raw)  # "07762388" (cero inicial conservado)
        # Validar coincidencia con rutenviasii normalizando ambos (lstrip '0')
        rut_sin_dv_norm = rut_sin_dv.lstrip('0')
        rutenviasii_sin_dv_norm = _rut_sin_dv(rutenviasii_raw).lstrip('0')
        if rutenviasii_sin_dv_norm and rut_sin_dv_norm != rutenviasii_sin_dv_norm:
            raise SiiAuthError(
                "El RUT configurado en rutenviasii no coincide con el RUT contenido en el certificado."
            )
        logger.info(
            "sii_auth: aio desde cert X.509 empresa=%s aio=%s coincide_rutenviasii=%s",
            empresa_codigo, rut_sin_dv, rut_sin_dv_norm == rutenviasii_sin_dv_norm,
        )
    else:
        raise SiiAuthError("El certificado no contiene un RUT X.509 utilizable para aio.")

    if not rut_sin_dv or not rut_sin_dv.lstrip('0').isdigit():
        raise SiiAuthError("No se pudo determinar el RUT del titular para construir el JWT.")

    # — Construir y firmar JWT —
    try:
        jwt_token = _build_jwt(private_key, cert_der, rut_sin_dv, SII_TOKEN_URL)
    except Exception:
        logger.warning("sii_auth: error construyendo JWT para empresa=%s", empresa_codigo)
        raise SiiAuthError("No se pudo construir el JWT de autenticación.")
    finally:
        private_key = None  # limpiar referencia a clave privada

    # — Diagnóstico seguro del JWT antes de enviarlo —
    try:
        import datetime as _dt
        _parts = jwt_token.split('.')
        if len(_parts) == 3:
            _pad = lambda s: s + '=' * (-len(s) % 4)
            _hdr = json.loads(base64.urlsafe_b64decode(_pad(_parts[0])))
            _pay = json.loads(base64.urlsafe_b64decode(_pad(_parts[1])))
            _x5c_value = _hdr.get('x5c') or ''
            _x5c_len = len(_x5c_value)
            _exp_val = _pay.get('exp', 0)
            _exp_dt = _dt.datetime.utcfromtimestamp(_exp_val)
            _delta = _exp_val - int(time.time())
            logger.info(
                "sii_diag: JWT empresa=%s alg=%s x5c_presente=%s x5c_len=%d "
                "aud=%s aio=%s exp_utc=%s exp_delta_seg=%d",
                empresa_codigo,
                _hdr.get('alg'),
                bool(_hdr.get('x5c')),
                _x5c_len,
                _pay.get('aud'),
                _pay.get('aio'),
                _exp_dt.strftime('%Y-%m-%dT%H:%M:%S'),
                _delta,
            )
    except Exception as _e:
        logger.warning("sii_diag: no se pudo inspeccionar JWT empresa=%s error=%s", empresa_codigo, type(_e).__name__)

    # — Diagnóstico del request —
    _form_fields = ["grant_type", "scope", "jwt"]
    logger.info(
        "sii_diag: request empresa=%s url=%s form_fields=%s authorization_basic=Si "
        "grant_type=%s scopes=%s",
        empresa_codigo,
        SII_TOKEN_URL,
        _form_fields,
        "cert_credentials",
        SII_SCOPES,
    )

    # — Solicitar access_token al SII —
    from django.conf import settings as _dj_settings
    _basic = (getattr(_dj_settings, 'SII_RPETC_BASIC_AUTH', '') or '').strip()
    if not _basic:
        raise SiiAuthError("SII_RPETC_BASIC_AUTH no está configurado.")
    try:
        resp = requests.post(
            SII_TOKEN_URL,
            headers={"Authorization": f"Basic {_basic}"},
            data={
                "grant_type": "cert_credentials",
                "jwt": jwt_token,
                "scope": SII_SCOPES,
            },
            timeout=15,
        )
        jwt_token = None  # limpiar JWT tras envío
    except requests.exceptions.Timeout:
        logger.warning("sii_auth: timeout al contactar SII para empresa=%s", empresa_codigo)
        raise SiiAuthError("Timeout al contactar el SII. Reintente más tarde.")
    except requests.exceptions.ConnectionError:
        logger.warning("sii_auth: error de red al contactar SII para empresa=%s", empresa_codigo)
        raise SiiAuthError("Error de red al contactar el SII.")
    except Exception:
        logger.warning("sii_auth: error HTTP inesperado para empresa=%s", empresa_codigo)
        raise SiiAuthError("Error inesperado al solicitar autenticación al SII.")

    # — Interpretar respuesta con diagnóstico seguro —
    http_status = resp.status_code
    content_type = resp.headers.get('Content-Type', 'desconocido')
    logger.info(
        "sii_auth: respuesta SII empresa=%s http_status=%d content_type=%s",
        empresa_codigo,
        http_status,
        content_type,
    )

    if resp.status_code == 200:
        # application/problem+json = error funcional aunque HTTP sea 200
        _ct = (resp.headers.get('Content-Type') or '').lower()
        if 'problem+json' in _ct:
            try:
                _prob = resp.json()
            except Exception:
                _prob = {}
            _safe_prob = {k: str(_prob.get(k, ''))[:200]
                          for k in ('type', 'title', 'status', 'detail', 'instance') if k in _prob}
            logger.warning(
                "sii_diag: problem+json empresa=%s campos=%s valores=%s",
                empresa_codigo, list(_prob.keys()), _safe_prob,
            )
            _detail = _safe_prob.get('detail') or _safe_prob.get('title') or 'Error funcional devuelto por el SII.'
            raise SiiAuthError(f"SII rechazó la solicitud: {_detail}", http_status=http_status)

        try:
            data = resp.json()
        except Exception:
            # No es JSON: loggear contenido truncado de forma segura
            _body_preview = resp.text[:1000] if resp.text else '(vacío)'
            logger.warning(
                "sii_diag: respuesta no-JSON empresa=%s content_type=%s body_preview=%s",
                empresa_codigo, content_type, _body_preview,
            )
            raise SiiAuthError("Respuesta inesperada del SII (no JSON).", http_status=http_status)

        # Campos seguros a loggear con sus valores
        _safe_value_keys = {'error', 'error_description', 'message', 'mensaje', 'codigo', 'status', 'detail'}
        _secret_keys = {'access_token', 'refresh_token', 'id_token', 'jwt'}
        _safe_values = {k: v for k, v in data.items() if k in _safe_value_keys}
        _secret_presence = {k: (k in data and bool(data[k])) for k in _secret_keys}
        safe_fields = list(data.keys())
        token_obtenido = bool(data.get("access_token"))
        logger.info(
            "sii_diag: empresa=%s campos=%s valores_seguros=%s secretos_presentes=%s "
            "access_token_presente=%s token_type=%s",
            empresa_codigo,
            safe_fields,
            _safe_values,
            _secret_presence,
            token_obtenido,
            data.get("token_type"),
        )

        # success = existencia real de access_token con contenido
        if not token_obtenido:
            raise SiiAuthError(
                "El SII respondió HTTP 200 pero no incluyó access_token en la respuesta.",
                http_status=http_status,
            )

        # expires_in: el SII puede enviar timestamp Unix absoluto o segundos relativos
        token_expira = None
        expires_raw = data.get("expires_in")
        if expires_raw:
            try:
                import datetime
                val = int(expires_raw)
                # Heurística: timestamps Unix son > año 2000 (>1_000_000_000)
                if val > 1_000_000_000:
                    token_expira = datetime.datetime.utcfromtimestamp(val)
                else:
                    token_expira = datetime.datetime.utcnow() + datetime.timedelta(seconds=val)
            except Exception:
                pass

        resultado = {
            "success": True,
            "empresa_codigo": empresa_codigo,
            "titular": certificado_sii.titular,
            "rut_titular": certificado_sii.rut_titular,
            "rut_envio_sii": rutenviasii_raw,
            "token_obtenido": True,
            "token_expira": token_expira,
            "error": None,
            "http_status": http_status,
        }
        if _incluir_access_token:
            resultado["access_token"] = data["access_token"]
            resultado["token_type"] = data.get("token_type")
            resultado["scope"] = data.get("scope")
        return resultado
    else:
        # Diagnóstico seguro para HTTP no-200
        content_type_err = resp.headers.get('Content-Type', 'desconocido')
        error_desc = "Autenticación rechazada por el SII."
        _err_safe = {}
        try:
            err_data = resp.json()
            _safe_err_keys = {'error', 'error_description', 'message', 'mensaje', 'codigo', 'status', 'detail'}
            _err_safe = {k: str(v)[:200] for k, v in err_data.items() if k in _safe_err_keys}
            logger.warning(
                "sii_diag: error empresa=%s http_status=%d content_type=%s campos=%s valores_seguros=%s",
                empresa_codigo, http_status, content_type_err,
                list(err_data.keys()), _err_safe,
            )
            if err_data.get("error_description"):
                error_desc = str(err_data["error_description"])[:200]
            elif err_data.get("error"):
                error_desc = str(err_data["error"])[:200]
        except Exception:
            _body_preview = resp.text[:500] if resp.text else '(vacío)'
            logger.warning(
                "sii_diag: respuesta-error no-JSON empresa=%s http_status=%d content_type=%s body=%s",
                empresa_codigo, http_status, content_type_err, _body_preview,
            )

        logger.warning(
            "sii_auth: autenticación fallida empresa=%s http_status=%d",
            empresa_codigo,
            http_status,
        )
        raise SiiAuthError(error_desc, http_status=http_status)


def obtener_access_token_sii(certificado_sii) -> dict:
    """Obtiene el token para un servicio interno sin duplicar el flujo OAuth.

    El token solo se entrega al consumidor interno en memoria y nunca se registra.
    """
    resultado = probar_autenticacion_sii(certificado_sii, _incluir_access_token=True)
    return {
        "access_token": resultado["access_token"],
        "token_type": resultado.get("token_type"),
        "scope": resultado.get("scope"),
        "http_status": resultado["http_status"],
    }
