"""Utilidades para la inspección y validación de certificados X.509 y PKCS#12 (.p12)."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives.serialization import pkcs12


def load_p12_certificate(p12_path: str | Path, password: str | bytes) -> Tuple[object, x509.Certificate, list]:
    """Carga y valida un archivo PKCS#12 (.p12 / .pfx).
    
    Retorna (private_key, cert, additional_certs).
    Lanza ValueError si el archivo no existe o la contraseña es inválida.
    """
    path = Path(p12_path)
    if not path.is_file():
        raise FileNotFoundError(f"No se encontró el archivo de certificado en: {path}")
    
    pfx_data = path.read_bytes()
    pass_bytes = password.encode("utf-8") if isinstance(password, str) else password
    
    try:
        key, cert, add_certs = pkcs12.load_key_and_certificates(pfx_data, pass_bytes)
    except Exception as e:
        raise ValueError(f"Error al desbloquear el certificado .p12 (posible contraseña incorrecta): {e}")
    
    if key is None or cert is None:
        raise ValueError("El archivo .p12 no contiene una clave privada o certificado de usuario válido.")
    
    return key, cert, (add_certs or [])


def extract_signer_name(cert: x509.Certificate) -> str:
    """Extrae el Common Name (CN) del certificado para usarlo en la estampa de firma."""
    cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if cn_attrs:
        return str(cn_attrs[0].value).strip()
    
    # Fallback: intentar con GIVEN_NAME + SURNAME si no hay CN
    given_attrs = cert.subject.get_attributes_for_oid(NameOID.GIVEN_NAME)
    surname_attrs = cert.subject.get_attributes_for_oid(NameOID.SURNAME)
    if given_attrs or surname_attrs:
        given = given_attrs[0].value if given_attrs else ""
        surname = surname_attrs[0].value if surname_attrs else ""
        return f"{given} {surname}".strip()
    
    return "Firma Electrónica Autorizada"


def get_cert_summary(p12_path: str | Path, password: str | bytes) -> dict:
    """Retorna un resumen de metadatos del certificado."""
    _, cert, _ = load_p12_certificate(p12_path, password)
    signer_name = extract_signer_name(cert)
    
    issuer_cn = "Desconocido"
    issuer_attrs = cert.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)
    if issuer_attrs:
        issuer_cn = str(issuer_attrs[0].value)
    
    now = datetime.now(timezone.utc)
    is_expired = now > cert.not_valid_after_utc
    is_not_yet_valid = now < cert.not_valid_before_utc

    return {
        "signer_name": signer_name,
        "issuer": issuer_cn,
        "valid_from": cert.not_valid_before_utc.strftime("%Y-%m-%d"),
        "valid_to": cert.not_valid_after_utc.strftime("%Y-%m-%d"),
        "is_expired": is_expired,
        "is_not_yet_valid": is_not_yet_valid,
        "serial_number": hex(cert.serial_number),
    }
