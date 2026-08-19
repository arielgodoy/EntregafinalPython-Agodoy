"""
Diagnóstico estricto del JWT generado para API-RPETC SII.
Solo lectura. NO modifica nada. NO implementa JWE.
Ejecutar: python tools/sii_jwt_diagnostic.py [empresa_codigo]
"""
import os
import sys
import base64
import json
import time
import datetime

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
import django
django.setup()

from gestiondte.models import CertificadoSII
from gestiondte.utils.maestro import get_maestroempresa_by_codigo
from gestiondte.services.sii_auth import (
    SII_TOKEN_URL, _rut_sin_dv, _build_jwt,
)
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates

SEP = "=" * 70


def _b64url_decode(s: str) -> bytes:
    pad = s + '=' * (-len(s) % 4)
    return base64.urlsafe_b64decode(pad)


def diagnosticar_jwt(empresa_codigo: str):
    print(SEP)
    print(f"DIAGNÓSTICO JWT — empresa={empresa_codigo}")
    print(f"Hora UTC: {datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S')}")
    print(SEP)

    # 1. Cargar certificado
    cert_obj = CertificadoSII.objects.filter(empresa_codigo=empresa_codigo, activo=True).first()
    if not cert_obj:
        print("ERROR: No hay CertificadoSII activo para esta empresa.")
        return

    empresa = get_maestroempresa_by_codigo(empresa_codigo)
    rutenviasii_raw = str((empresa or {}).get('rutenviasii') or '').strip()
    rut_sin_dv = _rut_sin_dv(rutenviasii_raw)

    plain_password = cert_obj.get_password()
    try:
        with open(cert_obj.archivo.path, 'rb') as fh:
            pfx_data = fh.read()
        pwd_bytes = plain_password.encode() if plain_password else None
        private_key, x509_cert, _ = load_key_and_certificates(pfx_data, pwd_bytes)
        plain_password = None
    except Exception as e:
        plain_password = None
        print(f"ERROR al cargar PFX: {type(e).__name__}")
        return

    cert_der = x509_cert.public_bytes(serialization.Encoding.DER)

    # 2. Verificar que private_key corresponde al cert público (coincidencia de módulo RSA)
    print("\n[COINCIDENCIA clave privada ↔ certificado]")
    try:
        pub_from_cert = x509_cert.public_key()
        pub_from_priv = private_key.public_key()
        # Comparar módulo RSA (números enteros, no material de clave)
        match = (pub_from_cert.public_numbers().n == pub_from_priv.public_numbers().n)
        print(f"  Coinciden (módulo RSA): {'Sí' if match else 'NO ← PROBLEMA'}")
    except Exception as e:
        print(f"  Error al comparar: {type(e).__name__}")

    # 3. Construir JWT usando la misma función de producción
    jwt_token = _build_jwt(private_key, cert_der, rut_sin_dv, SII_TOKEN_URL)
    private_key = None  # limpiar

    parts = jwt_token.split('.')
    print(f"\n[ESTRUCTURA JWT]")
    print(f"  Número de segmentos : {len(parts)}  (esperado: 3)")
    print(f"  Longitud header_b64 : {len(parts[0])} chars")
    print(f"  Longitud payload_b64: {len(parts[1])} chars")
    print(f"  Longitud sig_b64    : {len(parts[2])} chars")

    # 4. Inspeccionar header
    hdr = json.loads(_b64url_decode(parts[0]))
    print(f"\n[HEADER]")
    print(f"  Claves presentes    : {list(hdr.keys())}")
    print(f"  alg                 : {hdr.get('alg')}")
    print(f"  typ                 : {hdr.get('typ')} {'← presente (no en manual)' if 'typ' in hdr else ''}")
    print(f"  kid presente        : {'kid' in hdr}")
    print(f"  jku presente        : {'jku' in hdr}")
    print(f"  x5c presente        : {'x5c' in hdr}")

    x5c_val = hdr.get('x5c')
    if x5c_val and isinstance(x5c_val, list) and x5c_val:
        x5c_str = x5c_val[0]
        print(f"\n[x5c ANÁLISIS]")
        print(f"  Es lista con 1 elemento    : {len(x5c_val) == 1}")
        print(f"  Longitud del string x5c    : {len(x5c_str)} chars")
        print(f"  Contiene '-----BEGIN'      : {'-----BEGIN' in x5c_str} {'← PROBLEMA (PEM no DER)' if '-----BEGIN' in x5c_str else ''}")
        _has_newline = '\n' in x5c_str or chr(10) in x5c_str
        print(f"  Contiene saltos de línea   : {_has_newline} {'← PROBLEMA' if _has_newline else ''}")
        print(f"  Contiene padding '='       : {'=' in x5c_str}")
        print(f"  Contiene chars '-' o '_'   : {'-' in x5c_str or '_' in x5c_str} {'← PROBLEMA: Base64URL, no Base64 estándar' if ('-' in x5c_str or '_' in x5c_str) else ''}")
        # Verificar que es Base64 estándar decodificable y coincide con cert DER
        try:
            decoded = base64.b64decode(x5c_str)
            matches_der = (decoded == cert_der)
            print(f"  Decodificable (Base64 std) : Sí")
            print(f"  Coincide con DER real      : {'Sí' if matches_der else 'NO ← PROBLEMA'}")
        except Exception as e:
            print(f"  Decodificable              : NO — {type(e).__name__} ← PROBLEMA")
    else:
        print("  x5c ausente o formato incorrecto ← PROBLEMA")

    # 5. Inspeccionar payload
    pay = json.loads(_b64url_decode(parts[1]))
    print(f"\n[PAYLOAD]")
    print(f"  Claves presentes : {list(pay.keys())}")
    aio_val = pay.get('aio')
    exp_val = pay.get('exp')
    aud_val = pay.get('aud')
    print(f"  aio              : {aio_val!r}  tipo={type(aio_val).__name__}")
    print(f"  aud              : {aud_val!r}")
    print(f"  aud == SII_URL   : {aud_val == SII_TOKEN_URL}")
    exp_dt = datetime.datetime.utcfromtimestamp(exp_val) if exp_val else None
    delta = (exp_val or 0) - int(time.time())
    print(f"  exp              : {exp_val!r}  tipo={type(exp_val).__name__}")
    print(f"  exp UTC          : {exp_dt.strftime('%Y-%m-%dT%H:%M:%S') if exp_dt else 'N/A'}")
    print(f"  exp delta_seg    : {delta}")

    # 6. Verificar firma localmente con la clave pública del mismo cert
    print(f"\n[VERIFICACIÓN LOCAL DE FIRMA]")
    try:
        pub_key = x509_cert.public_key()
        signing_input = f"{parts[0]}.{parts[1]}".encode()
        sig_bytes = _b64url_decode(parts[2])
        pub_key.verify(sig_bytes, signing_input, padding.PKCS1v15(), hashes.SHA256())
        print(f"  Firma válida (local)       : Sí")
    except Exception as e:
        print(f"  Firma válida (local)       : NO — {type(e).__name__} ← PROBLEMA")

    # 7. Librería utilizada
    print(f"\n[LIBRERÍA]")
    print(f"  Construcción JWT    : manual (json + base64urlsafe + cryptography PKCS1v15)")
    print(f"  PyJWT en uso        : No")
    try:
        import jwt as _jwt
        print(f"  PyJWT instalado     : Sí (versión {getattr(_jwt, '__version__', 'desconocida')})")
    except ImportError:
        print(f"  PyJWT instalado     : No")

    # 8. Resumen de conformidad con manual RPETC v3.0
    print(f"\n[RESUMEN CONFORMIDAD con manual API-RPETC v3.0]")
    issues = []
    if hdr.get('alg') != 'RS256':
        issues.append(f"alg incorrecto: {hdr.get('alg')}")
    if 'x5c' not in hdr:
        issues.append("x5c ausente en header")
    if 'typ' in hdr:
        issues.append("typ presente en header (manual no lo documenta)")
    if x5c_val and isinstance(x5c_val, list):
        x5c_s = x5c_val[0]
        if '-' in x5c_s or '_' in x5c_s:
            issues.append("x5c usa Base64URL en vez de Base64 estándar")
        if '-----BEGIN' in x5c_s:
            issues.append("x5c contiene cabecera PEM")
        if chr(10) in x5c_s:
            issues.append("x5c contiene saltos de línea")
    if not isinstance(pay.get('exp'), int):
        issues.append(f"exp no es integer: {type(pay.get('exp')).__name__}")
    if not isinstance(pay.get('aio'), str):
        issues.append(f"aio no es string: {type(pay.get('aio')).__name__}")
    if pay.get('aud') != SII_TOKEN_URL:
        issues.append(f"aud no coincide con endpoint: {pay.get('aud')}")
    if len(parts) != 3:
        issues.append(f"JWT tiene {len(parts)} segmentos (esperado 3)")
    if issues:
        for i in issues:
            print(f"  ⚠ {i}")
    else:
        print(f"  Sin diferencias detectadas — JWT conforme al manual")

    print(f"\n{SEP}")


if __name__ == '__main__':
    codigo = sys.argv[1] if len(sys.argv) > 1 else '09'
    diagnosticar_jwt(codigo)
