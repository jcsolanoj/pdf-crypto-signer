"""Pruebas unitarias y de integración para pdf-crypto-signer."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import fitz
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from firma_pdf.cert_utils import extract_signer_name, get_cert_summary, load_p12_certificate
from firma_pdf.cli import create_parser
from firma_pdf.config import _hash_pin, _verify_pin
from firma_pdf.coordinates import generate_name_variants, get_preset_box, parse_coords, parse_offset
from firma_pdf.signer import sign_pdf_file, sign_pdf_multi_boxes
from firma_pdf.stamp import build_firmaec_qr_payload, _pdf_escape_latin1


def _create_test_p12(path: Path, cn: str = "Ana María Pérez", password: str = "secret123") -> Path:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    p12_bytes = pkcs12.serialize_key_and_certificates(
        name=b"test-cert",
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode("utf-8")),
    )
    path.write_bytes(p12_bytes)
    return path


def _create_test_pdf(path: Path, pages: int = 2, last_page_text: str = "Firma del Docente") -> Path:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        if i == pages - 1:
            page.insert_text((100, 700), last_page_text, fontsize=12)
        else:
            page.insert_text((100, 100), f"Página {i + 1}", fontsize=12)
    doc.save(path)
    doc.close()
    return path


def test_pin_hashing_and_verification():
    hashed = _hash_pin("1234")
    assert "$" in hashed
    assert _verify_pin("1234", hashed) is True
    assert _verify_pin("0000", hashed) is False


def test_coordinates_and_name_variants():
    assert parse_offset("10,-5") == (10.0, -5.0)
    assert parse_coords("100,200") == (100.0, 200.0)
    box = get_preset_box("bottom-right", 595, 842)
    assert len(box) == 4 and box[2] > box[0] and box[3] > box[1]
    variants = generate_name_variants("Ana María Pérez Gómez")
    assert "Ana María Pérez Gómez" in variants
    assert "Ana Maria Perez Gomez" in variants
    assert "Pérez Gómez" in variants


def test_qr_payload_and_pdf_escaping():
    url_payload = build_firmaec_qr_payload("Test User", verify_url="https://example.com/verify/123")
    assert url_payload == "https://example.com/verify/123"

    auto_payload = build_firmaec_qr_payload("Ana Pérez", location="Quito")
    assert "FIRMADO POR: ANA PEREZ" in auto_payload
    assert "LUGAR: QUITO" in auto_payload

    escaped = _pdf_escape_latin1("Nombre (Prueba) \\ Test")
    assert b"\\(Prueba\\)" in escaped
    assert b"\\\\" in escaped


def test_cli_parser_defaults():
    parser = create_parser()
    args = parser.parse_args([])
    assert args.pos is None
    assert args.gui is False


def test_cert_load_and_sign_pdf_single_and_multi(tmp_path: Path):
    p12_path = _create_test_p12(tmp_path / "test.p12", cn="Ana (Prueba) Pérez", password="pass")
    pdf_path = _create_test_pdf(tmp_path / "doc.pdf", pages=2, last_page_text="Ana (Prueba) Pérez")

    _, cert, _ = load_p12_certificate(p12_path, "pass")
    assert extract_signer_name(cert) == "Ana (Prueba) Pérez"
    summary = get_cert_summary(p12_path, "pass")
    assert summary["is_expired"] is False

    signed_path = sign_pdf_file(
        input_path=pdf_path,
        output_path=None,
        p12_path=p12_path,
        password="pass",
        page_spec="last",
        location="Quito",
    )
    assert signed_path.is_file()
    assert signed_path.name == "doc-signed.pdf"
    assert b"/ByteRange" in signed_path.read_bytes()

    multi_path = sign_pdf_multi_boxes(
        input_path=pdf_path,
        output_path=tmp_path / "multi-signed.pdf",
        p12_path=p12_path,
        password="pass",
        boxes=[(0, 50.0, 50.0), (1, 100.0, 100.0)],
    )
    assert multi_path.is_file()
    with fitz.open(multi_path) as doc:
        signed_widgets = [w for p in doc for w in p.widgets() if w.is_signed]
        assert len(signed_widgets) == 2
