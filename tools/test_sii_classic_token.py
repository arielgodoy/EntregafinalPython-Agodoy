#!/usr/bin/env python3
"""
Diagnóstico aislado del flujo clásico SII (CrSeed → firma XML → GetTokenFromSeed).

Reglas del script:
- No modifica vistas, URLs, templates ni flujo productivo.
- Usa el certificado real almacenado en gestiondte.CertificadoSII.
- No imprime secretos: contraseña, clave privada, token completo ni contenido del PFX.
- El objetivo es diagnosticar exactamente dónde falla la cadena: CrSeed, firma XML o GetTokenFromSeed.
"""

import os
import sys
import re
import traceback
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional, Tuple

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AppDocs.settings")

import django
django.setup()

import requests
from lxml import etree
from signxml import XMLSigner, XMLVerifier
from signxml.algorithms import (
    SignatureMethod,
    DigestAlgorithm,
    SignatureConstructionMethod,
    CanonicalizationMethod,
)
from cryptography import x509 as crypto_x509
from cryptography.hazmat.primitives.serialization.pkcs12 import load_key_and_certificates
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes

from gestiondte.models import CertificadoSII

CRSEED_URL = "https://palena.sii.cl/DTEWS/CrSeed.jws"
GETTOKEN_URL = "https://palena.sii.cl/DTEWS/GetTokenFromSeed.jws"
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
DEFAULT_NS = "http://DefaultNamespace"


def parse_soap_response_text(response_text: str) -> Optional[str]:
    """Devuelve el contenido de una respuesta SOAP, sin ruido de namespaces."""
    try:
        root = ET.fromstring(response_text.encode("utf-8", errors="replace"))
    except ET.ParseError:
        return None

    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag in {"getSeedReturn", "getTokenReturn", "getStateReturn"}:
            return (elem.text or "").strip()
        if tag in {"return"}:
            return (elem.text or "").strip()
    return None


def parse_estado_glosa_xml(xml_text: str) -> Tuple[str, str, bool]:
    """Extrae ESTADO, GLOSA y si existe TOKEN/SEMILLA desde XML de SII."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8", errors="replace"))
    except ET.ParseError:
        return "", "", False

    estado = ""
    glosa = ""
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "ESTADO":
            estado = (elem.text or "").strip()
        elif tag == "GLOSA":
            glosa = (elem.text or "").strip()

    token_present = any(elem.tag.split("}")[-1] == "TOKEN" for elem in root.iter())
    semilla_present = any(elem.tag.split("}")[-1] == "SEMILLA" for elem in root.iter())
    return estado, glosa, token_present or semilla_present


def sanitize(value: Optional[str], limit: int = 120) -> str:
    if value is None:
        return ""
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "..."


def get_certificado_activo(empresa_codigo: Optional[str]) -> Optional[CertificadoSII]:
    if empresa_codigo:
        cert = CertificadoSII.objects.filter(empresa_codigo=empresa_codigo).order_by("-activo", "-updated_at").first()
        if cert:
            return cert
    cert = CertificadoSII.objects.filter(activo=True).order_by("-updated_at").first()
    return cert


def load_pfx(cert: CertificadoSII):
    password = cert.get_password()
    try:
        with open(cert.archivo.path, "rb") as fh:
            pfx_bytes = fh.read()
    except Exception as exc:
        raise RuntimeError(f"No se pudo leer el PFX en disco: {exc}")

    try:
        private_key, cert_obj, chain = load_key_and_certificates(pfx_bytes, password.encode() if password else None)
    except Exception as exc:
        raise RuntimeError(f"No se pudo cargar el PFX: {exc}")

    if cert_obj is None or private_key is None:
        raise RuntimeError("El archivo no contiene private key/certificado válidos.")
    return private_key, cert_obj, chain


def soap_call(url: str, body: str, action: str = "") -> requests.Response:
    headers = {"Content-Type": "text/xml; charset=utf-8"}
    if action:
        headers["SOAPAction"] = action
    return requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=40)


def cr_seed_diagnostic(cert: CertificadoSII) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "certificado": cert,
        "empresa_codigo": cert.empresa_codigo,
        "http_status": None,
        "content_type": None,
        "respuesta_llegada": False,
        "estado": "",
        "glosa": "",
        "semilla_presente": False,
        "semilla": "",
        "error": None,
    }

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:ser="http://DefaultNamespace">'
        '<soapenv:Body><ser:getSeed/></soapenv:Body></soapenv:Envelope>'
    )

    last_error = None
    for action in ("", "getSeed", "\"getSeed\""):
        try:
            response = soap_call(CRSEED_URL, body, action=action)
            result["http_status"] = response.status_code
            result["content_type"] = response.headers.get("Content-Type", "")
            result["respuesta_llegada"] = bool(response.text and response.text.strip())
            payload = response.text
            if payload and response.content:
                raw = parse_soap_response_text(payload)
                if raw:
                    xml_text = raw
                    try:
                        xml_root = ET.fromstring(xml_text.encode("utf-8", errors="replace"))
                    except ET.ParseError:
                        xml_root = None
                    if xml_root is not None:
                        estado = ""
                        glosa = ""
                        semilla = ""
                        for node in xml_root.iter():
                            tag = node.tag.split("}")[-1]
                            if tag == "ESTADO":
                                estado = (node.text or "").strip()
                            elif tag == "GLOSA":
                                glosa = (node.text or "").strip()
                            elif tag == "SEMILLA":
                                semilla = (node.text or "").strip()
                        result["estado"] = estado
                        result["glosa"] = glosa
                        result["semilla_presente"] = bool(semilla)
                        result["semilla"] = semilla
                        if semilla:
                            return result
                        result["error"] = "Respuesta recibida pero sin SEMILLA en el cuerpo XML"
                        last_error = result["error"]
                        continue
                else:
                    last_error = "Respuesta recibida pero sin estructura reconocible"
            if response.status_code in (200, 500, 400):
                last_error = "Respuesta recibida pero sin estructura reconocible"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"

    result["error"] = last_error
    return result


def parse_semilla_from_response(xml_text: str) -> Tuple[str, str, str, bool]:
    """Extrae ESTADO, GLOSA y SEMILLA del XML de respuesta de CrSeed."""
    estado = ""
    glosa = ""
    semilla = ""
    root = None
    try:
        root = ET.fromstring(xml_text.encode("utf-8", errors="replace"))
    except ET.ParseError:
        return estado, glosa, semilla, False

    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "ESTADO":
            estado = (elem.text or "").strip()
        elif tag == "GLOSA":
            glosa = (elem.text or "").strip()
        elif tag == "SEMILLA":
            semilla = (elem.text or "").strip()

    return estado, glosa, semilla, bool(semilla)


def build_gettoken_xml(seed: str) -> str:
    return (
        '<?xml version="1.0"?>'
        '<getToken>'
        '<item><Semilla>{}</Semilla></item>'
        '</getToken>'
    ).format(seed)


def sign_gettoken_xml(xml_text: str, private_key, cert_obj) -> Tuple[str, str, str, bool]:
    """Firma XML con XMLDSIG usando el certificado PFX. Retorna XML firmado, algoritmo usado y validación local."""
    xml_bytes = xml_text.encode("utf-8")
    root = etree.fromstring(xml_bytes)

    for sig_name, sig_alg, digest_alg in (
        ("RSA_SHA256", SignatureMethod.RSA_SHA256, DigestAlgorithm.SHA256),
        ("RSA_SHA1", SignatureMethod.RSA_SHA1, DigestAlgorithm.SHA1),
    ):
        try:
            signer = XMLSigner(
                method=SignatureConstructionMethod.ENVELOPED,
                signature_algorithm=sig_alg,
                digest_algorithm=digest_alg,
                c14n_algorithm=CanonicalizationMethod.INCLUSIVE,
                key_info=True,
            )
            signed = signer.sign(root, key=private_key, cert=cert_obj)
            verifier = XMLVerifier()
            verifier.verify(signed, x509_cert=cert_obj)
            signed_xml = etree.tostring(signed, encoding="utf-8", xml_declaration=True)
            return signed_xml.decode("utf-8"), sig_name, digest_alg.name, True
        except Exception:
            continue

    return xml_text, "NO_VALIDO", "NO_VALIDO", False


def get_token_from_seed_diagnostic(signed_xml: str, cert: CertificadoSII) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "http_status": None,
        "content_type": None,
        "respuesta_xml_valida": False,
        "estado": "",
        "glosa": "",
        "token_presente": False,
        "token": "",
        "error": None,
    }

    try:
        soap_payload = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:ser="http://DefaultNamespace">'
            '<soapenv:Body><ser:getToken><![CDATA[' + signed_xml + ']]></ser:getToken></soapenv:Body>'
            '</soapenv:Envelope>'
        )
    except Exception as exc:
        result["error"] = f"No se pudo construir payload SOAP: {exc}"
        return result

    try:
        response = soap_call(GETTOKEN_URL, soap_payload, action="getToken")
    except Exception as exc:
        result["error"] = f"Error HTTP: {exc}"
        return result

    result["http_status"] = response.status_code
    result["content_type"] = response.headers.get("Content-Type", "")
    result["respuesta_xml_valida"] = bool(response.text and response.text.strip())

    try:
        xml_root = ET.fromstring(response.text.encode("utf-8", errors="replace"))
        for node in xml_root.iter():
            tag = node.tag.split("}")[-1]
            if tag == "ESTADO":
                result["estado"] = (node.text or "").strip()
            elif tag == "GLOSA":
                result["glosa"] = (node.text or "").strip()
            elif tag == "TOKEN":
                result["token_presente"] = bool((node.text or "").strip())
                result["token"] = (node.text or "").strip()
    except Exception as exc:
        result["error"] = f"No se pudo parsear XML de respuesta: {exc}"
        return result

    return result


def main() -> int:
    empresa_arg = sys.argv[1] if len(sys.argv) > 1 else None
    cert = get_certificado_activo(empresa_arg)
    if not cert:
        print("ERROR: No hay CertificadoSII activo o disponible.")
        return 2

    if not cert.archivo or not cert.archivo.name:
        print("ERROR: El certificado no tiene archivo asociado.")
        return 2

    try:
        private_key, cert_obj, _ = load_pfx(cert)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 2

    empresa = cert.empresa_codigo
    print("=== DIAGNÓSTICO SII CLÁSICO ===")
    print(f"certificado: {cert.archivo.name}")
    print(f"empresa: {empresa}")
    print(f"titular: {cert.titular or 'desconocido'}")
    print(f"vigencia: {cert.valido_hasta}")

    cr = cr_seed_diagnostic(cert)
    print("[CrSeed]")
    print(f"HTTP status: {cr.get('http_status')}")
    print(f"Content-Type: {cr.get('content_type')}")
    print(f"respuesta_llegada: {'Sí' if cr.get('respuesta_llegada') else 'No'}")
    print(f"ESTADO: {sanitize(cr.get('estado'))}")
    print(f"GLOSA: {sanitize(cr.get('glosa'))}")
    print(f"semilla_presente: {'Sí' if cr.get('semilla_presente') else 'No'}")
    print(f"semilla: {sanitize(cr.get('semilla'), 20)}")

    seed = cr.get("semilla") or ""
    if not seed:
        print("PUNTO DE FALLO: CrSeed (sin semilla válida)")
        return 1

    xml_seed = build_gettoken_xml(seed)
    signed_xml, alg_name, digest_name, local_valid = sign_gettoken_xml(xml_seed, private_key, cert_obj)
    print("[firma XML]")
    print(f"XML firmado generado: {'Sí' if signed_xml else 'No'}")
    print(f"firma local válida: {'Sí' if local_valid else 'No'}")
    print(f"algoritmo de firma: {alg_name}")
    print(f"digest: {digest_name}")

    if not local_valid:
        print("PUNTO DE FALLO: firma XML")
        return 1

    token_result = get_token_from_seed_diagnostic(signed_xml, cert)
    print("[GetTokenFromSeed]")
    print(f"HTTP status: {token_result.get('http_status')}")
    print(f"Content-Type: {token_result.get('content_type')}")
    print(f"respuesta_XML_valida: {'Sí' if token_result.get('respuesta_xml_valida') else 'No'}")
    print(f"ESTADO: {sanitize(token_result.get('estado'))}")
    print(f"GLOSA: {sanitize(token_result.get('glosa'))}")
    print(f"TOKEN presente: {'Sí' if token_result.get('token_presente') else 'No'}")

    if token_result.get("token_presente"):
        print("RESULTADO: TOKEN clásico SII obtenido: Sí")
        return 0

    print("PUNTO DE FALLO: GetTokenFromSeed")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
