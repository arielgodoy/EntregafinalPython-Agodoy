"""
Herramienta de diagnóstico OAuth SII — solo lectura, sin modificar datos.
Ejecutar con: python tools/sii_oauth_diagnostic.py

Imprime un informe estructurado con datos de diagnóstico seguros.
NUNCA imprime tokens, contraseñas, JWT completo ni claves privadas.
"""
import os
import sys
import logging
import json
import base64
import time
import datetime

# Configurar logging a nivel INFO para capturar mensajes de sii_auth
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s %(name)s: %(message)s',
)

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
import django
django.setup()

from gestiondte.models import CertificadoSII
from gestiondte.utils.maestro import get_maestroempresa_by_codigo
from gestiondte.services.sii_auth import (
    SII_TOKEN_URL, SII_SCOPES, JWT_LIFETIME_SECONDS,
    _rut_sin_dv, _build_jwt, _extract_rut_from_cert, SiiAuthError,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
import requests


SEP = "=" * 70


def _b64url_decode_safe(s):
    pad = s + '=' * (-len(s) % 4)
    return base64.urlsafe_b64decode(pad)


def diagnosticar(empresa_codigo: str):
    print(SEP)
    print(f"DIAGNÓSTICO OAUTH SII — empresa={empresa_codigo}")
    print(f"Hora UTC inicio: {datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S')}")
    print(SEP)

    # 1. Certificado
    cert_obj = CertificadoSII.objects.filter(empresa_codigo=empresa_codigo, activo=True).first()
    if not cert_obj:
        print(f"ERROR: No existe CertificadoSII activo para empresa={empresa_codigo}")
        return

    print(f"\n[CERTIFICADO]")
    print(f"  PK             : {cert_obj.pk}")
    print(f"  Titular        : {cert_obj.titular}")
    print(f"  rut_titular    : {cert_obj.rut_titular}")
    print(f"  Estado vigencia: {cert_obj.estado_vigencia}")
    print(f"  valido_hasta   : {cert_obj.valido_hasta}")

    # 2. Empresa legacy
    empresa = get_maestroempresa_by_codigo(empresa_codigo)
    print(f"\n[EMPRESA LEGACY maestroempresas]")
    if empresa:
        print(f"  nombre       : {empresa.get('nombre')}")
        print(f"  rut          : {empresa.get('rut')}")
        print(f"  rutenviasii  : {empresa.get('rutenviasii')}")
    else:
        print(f"  ERROR: No se encontró la empresa en maestroempresas")
        return

    rutenviasii_raw = str(empresa.get('rutenviasii') or '').strip()

    print(f"\n[AIO / RUT AUTENTICADOR]")
    print(f"  rutenviasii original : {rutenviasii_raw}")

    if not rutenviasii_raw:
        print("  ERROR: rutenviasii inválido, no se puede continuar.")
        return

    # 3. Cargar PFX
    plain_password = cert_obj.get_password()
    try:
        with open(cert_obj.archivo.path, 'rb') as fh:
            pfx_data = fh.read()
        pwd_bytes = plain_password.encode() if plain_password else None
        private_key, x509_cert, _ = load_key_and_certificates(pfx_data, pwd_bytes)
        plain_password = None
        cert_der = x509_cert.public_bytes(serialization.Encoding.DER)
        print(f"\n[PFX] cargado OK — DER len={len(cert_der)}")
    except Exception as e:
        plain_password = None
        print(f"\n[PFX] ERROR al cargar: {type(e).__name__}")
        return

    # Extraer aio desde certificado X.509 (mismo flujo que el servicio)
    rut_cert_raw = _extract_rut_from_cert(x509_cert)
    if rut_cert_raw:
        rut_sin_dv = _rut_sin_dv(rut_cert_raw)
        print(f"  RUT desde cert X.509 : {rut_cert_raw}")
        print(f"  aio (del cert, sin DV): {rut_sin_dv}  ← fuente usada")
    else:
        rut_sin_dv = _rut_sin_dv(rutenviasii_raw)
        print(f"  RUT desde cert X.509 : no encontrado — usando rutenviasii")
        print(f"  aio (rutenviasii)    : {rut_sin_dv}  ← fuente usada")

    if not rut_sin_dv or not rut_sin_dv.lstrip('0').isdigit():
        print("  ERROR: aio inválido, no se puede continuar.")
        return

    # 4. Construir JWT y analizar su contenido (sin mostrarlo completo)
    jwt_token = _build_jwt(private_key, cert_der, rut_sin_dv, SII_TOKEN_URL)
    private_key = None

    parts = jwt_token.split('.')
    hdr = json.loads(_b64url_decode_safe(parts[0]))
    pay = json.loads(_b64url_decode_safe(parts[1]))
    now_ts = int(time.time())
    exp_ts = pay.get('exp', 0)
    exp_dt = datetime.datetime.utcfromtimestamp(exp_ts)
    delta = exp_ts - now_ts
    x5c_len = len(hdr.get('x5c', [''])[0]) if hdr.get('x5c') else 0

    print(f"\n[JWT — solo metadatos, sin valor completo]")
    print(f"  alg            : {hdr.get('alg')}")
    print(f"  x5c presente   : {bool(hdr.get('x5c'))}")
    print(f"  x5c longitud   : {x5c_len} chars")
    print(f"  aud            : {pay.get('aud')}")
    print(f"  aio            : {pay.get('aio')}")
    print(f"  iss            : {pay.get('iss')}")
    print(f"  exp UTC        : {exp_dt.strftime('%Y-%m-%dT%H:%M:%S')}")
    print(f"  exp delta_seg  : {delta}")
    print(f"  aud == url     : {pay.get('aud') == SII_TOKEN_URL}")

    # 5. Request
    print(f"\n[REQUEST]")
    print(f"  URL                      : {SII_TOKEN_URL}")
    print(f"  Authorization Basic      : Sí (presente)")
    print(f"  Content-Type             : application/x-www-form-urlencoded (automático por requests)")
    print(f"  grant_type               : cert_credentials")
    print(f"  campo JWT                : jwt")
    print(f"  scope                    : {SII_SCOPES}")

    # 6. Llamada real al SII
    print(f"\n[RESPUESTA SII]")
    from django.conf import settings as _s
    _basic = getattr(_s, 'SII_RPETC_BASIC_AUTH', '') or getattr(_s, 'SII_OAUTH_BASIC_AUTH', 'cmljYXJkbzpyaWNhcmRv')
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
        jwt_token = None
    except Exception as e:
        print(f"  ERROR de red: {type(e).__name__}: {e}")
        return

    print(f"  HTTP status   : {resp.status_code}")
    print(f"  Content-Type  : {resp.headers.get('Content-Type', 'desconocido')}")

    # Intentar parsear como JSON
    try:
        data = resp.json()
        campo_nombres = list(data.keys())
        _safe_keys = {'error', 'error_description', 'message', 'mensaje', 'codigo', 'status', 'detail', 'token_type', 'scope', 'expires_in'}
        _secret_keys = {'access_token', 'refresh_token', 'id_token', 'jwt'}
        print(f"  Campos recibidos         : {campo_nombres}")
        for k in _safe_keys:
            if k in data:
                print(f"  {k:25s}: {str(data[k])[:200]}")
        for k in _secret_keys:
            presente = k in data and bool(data[k])
            print(f"  {k:25s}: presente={presente}")
    except Exception:
        _preview = resp.text[:1000] if resp.text else '(vacío)'
        print(f"  Respuesta no es JSON. Preview (máx 1000 chars):")
        print(f"  {_preview}")

    print(f"\n[FIN DIAGNÓSTICO] empresa={empresa_codigo}")
    print(SEP)


if __name__ == '__main__':
    codigo = sys.argv[1] if len(sys.argv) > 1 else '09'
    diagnosticar(codigo)
