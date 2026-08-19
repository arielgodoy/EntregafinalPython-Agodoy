"""
Diagnóstico X.509 del certificado PFX — solo lectura.
Inspecciona Subject, extensiones, OIDs y busca el RUT 7762388 en todos los atributos.
Ejecutar: python tools/sii_cert_diagnostic.py [empresa_codigo]
"""
import os
import sys
import subprocess
import tempfile

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'AppDocs.settings')
import django
django.setup()

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
from cryptography.x509.oid import NameOID, ExtensionOID
from gestiondte.models import CertificadoSII
from gestiondte.utils.maestro import get_maestroempresa_by_codigo

SEP = "=" * 70
RUT_BUSCAR = ["7762388", "7762388-4"]


def _oid_nombre(oid: x509.ObjectIdentifier) -> str:
    """Devuelve el nombre legible del OID si la librería lo conoce."""
    try:
        return oid._name
    except Exception:
        pass
    _known = {
        "2.5.4.3":  "commonName",
        "2.5.4.4":  "surname",
        "2.5.4.5":  "serialNumber",
        "2.5.4.6":  "countryName",
        "2.5.4.7":  "localityName",
        "2.5.4.8":  "stateOrProvinceName",
        "2.5.4.10": "organizationName",
        "2.5.4.11": "organizationalUnitName",
        "2.5.4.41": "name",
        "2.5.4.42": "givenName",
        "2.5.4.65": "pseudonym",
        "1.2.840.113549.1.9.1": "emailAddress",
        "2.16.840.1.101.3.4.2.1": "SHA-256",
        # OIDs personalizados comunes en cert chilenos
        "1.2.840.113549.1.9.2": "unstructuredName",
        "2.16.152.1.2.1.1":    "RUT-Chile (E-CERTCHILE)",
    }
    dotted = oid.dotted_string
    return _known.get(dotted, f"DESCONOCIDO({dotted})")


def _buscar_rut(texto: str) -> list:
    """Retorna lista de RUTs buscados que aparecen en el texto."""
    return [r for r in RUT_BUSCAR if r in str(texto)]


def diagnosticar_certificado(empresa_codigo: str):
    print(SEP)
    print(f"DIAGNÓSTICO X.509 — empresa={empresa_codigo}")
    print(SEP)

    cert_obj = CertificadoSII.objects.filter(empresa_codigo=empresa_codigo, activo=True).first()
    if not cert_obj:
        print("ERROR: No hay CertificadoSII activo.")
        return

    empresa = get_maestroempresa_by_codigo(empresa_codigo)
    rutenviasii = str((empresa or {}).get('rutenviasii') or '').strip()

    plain_password = cert_obj.get_password()
    try:
        with open(cert_obj.archivo.path, 'rb') as fh:
            pfx_data = fh.read()
        pwd_bytes = plain_password.encode() if plain_password else None
        _, x509_cert, chain = load_key_and_certificates(pfx_data, pwd_bytes)
        plain_password = None
    except Exception as e:
        plain_password = None
        print(f"ERROR al cargar PFX: {type(e).__name__}: {e}")
        return

    hallazgos_rut = []  # [(ubicacion, valor)]

    # ── Subject ──────────────────────────────────────────────────────────────
    print("\n[SUBJECT]")
    for attr in x509_cert.subject:
        nombre = _oid_nombre(attr.oid)
        dotted = attr.oid.dotted_string
        valor  = str(attr.value)
        print(f"  {dotted:30s} | {nombre:30s} | {valor}")
        hits = _buscar_rut(valor)
        if hits:
            hallazgos_rut.append((f"Subject/{nombre}({dotted})", valor, hits))

    # ── Issuer ────────────────────────────────────────────────────────────────
    print("\n[ISSUER]")
    for attr in x509_cert.issuer:
        nombre = _oid_nombre(attr.oid)
        dotted = attr.oid.dotted_string
        valor  = str(attr.value)
        print(f"  {dotted:30s} | {nombre:30s} | {valor}")
        hits = _buscar_rut(valor)
        if hits:
            hallazgos_rut.append((f"Issuer/{nombre}({dotted})", valor, hits))

    # ── Datos generales ───────────────────────────────────────────────────────
    print("\n[DATOS GENERALES]")
    print(f"  Serial number  : {x509_cert.serial_number}")
    print(f"  not_before     : {x509_cert.not_valid_before}")
    print(f"  not_after      : {x509_cert.not_valid_after}")
    hits = _buscar_rut(str(x509_cert.serial_number))
    if hits:
        hallazgos_rut.append(("serial_number", str(x509_cert.serial_number), hits))

    # ── Extensiones ──────────────────────────────────────────────────────────
    print("\n[EXTENSIONES X.509]")
    for ext in x509_cert.extensions:
        dotted = ext.oid.dotted_string
        nombre = _oid_nombre(ext.oid)
        print(f"\n  OID    : {dotted}")
        print(f"  Nombre : {nombre}")
        print(f"  Crítica: {ext.critical}")
        try:
            val_str = str(ext.value)
            # Truncar si es demasiado larga pero buscar RUT primero
            hits = _buscar_rut(val_str)
            if hits:
                hallazgos_rut.append((f"Extension/{nombre}({dotted})", val_str[:300], hits))
            print(f"  Valor  : {val_str[:300]}{'...' if len(val_str) > 300 else ''}")
        except Exception as e:
            print(f"  Valor  : (no parseable: {type(e).__name__})")
            # intentar DER raw
            try:
                raw_hex = ext.value.public_bytes().hex() if hasattr(ext.value, 'public_bytes') else '(sin método)'
                hits = _buscar_rut(raw_hex)
                if hits:
                    hallazgos_rut.append((f"Extension/{nombre}({dotted})/raw", raw_hex[:200], hits))
                print(f"  Raw hex: {raw_hex[:200]}")
            except Exception:
                pass

    # ── Buscar RUT en DER completo (por si está en algún atributo no parseado) ─
    print("\n[BÚSQUEDA EN DER COMPLETO]")
    cert_der = x509_cert.public_bytes(serialization.Encoding.DER)
    cert_pem_text = x509_cert.public_bytes(serialization.Encoding.PEM).decode()
    # Buscar en representación textual PEM y en string del DER
    for rut in RUT_BUSCAR:
        in_pem = rut in cert_pem_text
        # intentar buscar bytes UTF-8 en DER
        in_der = rut.encode() in cert_der
        print(f"  '{rut}' en PEM string: {in_pem}  en DER bytes: {in_der}")
        if in_pem or in_der:
            hallazgos_rut.append(("DER/PEM bytes search", rut, [rut]))

    # ── openssl x509 -text (si disponible) ────────────────────────────────────
    print("\n[OPENSSL TEXT — si disponible]")
    try:
        with tempfile.NamedTemporaryFile(suffix='.pem', delete=False) as tf:
            tf.write(x509_cert.public_bytes(serialization.Encoding.PEM))
            tf_path = tf.name
        result = subprocess.run(
            ["openssl", "x509", "-text", "-noout", "-in", tf_path],
            capture_output=True, text=True, timeout=10
        )
        os.unlink(tf_path)
        if result.returncode == 0:
            ossl_out = result.stdout
            # Imprimir sección Subject y extensiones solamente
            for line in ossl_out.splitlines():
                stripped = line.strip()
                if any(k in stripped for k in ('Subject:', 'Issuer:', 'Serial', 'Not Before', 'Not After',
                                                'DNS:', 'Email:', 'URI:', 'IP:', 'RID:', 'othername',
                                                'X509v3', 'Object', '2.16.', '1.2.840', 'Unknown')):
                    print(f"  {stripped}")
            # Buscar RUT en salida completa
            for rut in RUT_BUSCAR:
                if rut in ossl_out:
                    lines_with_rut = [l.strip() for l in ossl_out.splitlines() if rut in l]
                    hallazgos_rut.append(("openssl output", str(lines_with_rut), [rut]))
                    print(f"  ← RUT '{rut}' encontrado en openssl: {lines_with_rut}")
        else:
            print(f"  openssl no disponible o error (rc={result.returncode}): {result.stderr[:200]}")
    except FileNotFoundError:
        print("  openssl no encontrado en PATH")
    except Exception as e:
        print(f"  Error al ejecutar openssl: {type(e).__name__}: {e}")

    # ── Resumen hallazgos ─────────────────────────────────────────────────────
    print(f"\n[BÚSQUEDA RUT esperado: {RUT_BUSCAR}]")
    if hallazgos_rut:
        for ubicacion, valor, hits in hallazgos_rut:
            print(f"  ✓ Encontrado '{hits}' en: {ubicacion}")
            print(f"    Valor: {valor[:150]}")
    else:
        print(f"  ✗ RUT {RUT_BUSCAR} NO encontrado en ningún atributo del certificado")

    print(f"\n[COMPARACIÓN CON SISTEMA LEGACY]")
    print(f"  rutenviasii (maestroempresas) : {rutenviasii}")
    if hallazgos_rut:
        # Buscar coincidencia exacta con rutenviasii
        rut_cert_encontrado = any(rutenviasii in str(v) for _, v, _ in hallazgos_rut)
        print(f"  Coincide con cert X.509       : {'Sí' if rut_cert_encontrado else 'No determinado (ver hallazgos)'}")
    else:
        print(f"  Coincide con cert X.509       : No — RUT no encontrado en certificado")

    print(f"\n{SEP}")


if __name__ == '__main__':
    codigo = sys.argv[1] if len(sys.argv) > 1 else '09'
    diagnosticar_certificado(codigo)
