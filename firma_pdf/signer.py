"""Motor de firmado criptográfico de PDFs con pyHanko e IncrementalPdfFileWriter."""

import io
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Union

import fitz  # PyMuPDF
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import fields, signers

from firma_pdf.cert_utils import load_p12_certificate, extract_signer_name
from firma_pdf.coordinates import (
    compute_signature_box,
    find_auto_signature_target,
    STAMP_WIDTH,
    STAMP_HEIGHT,
)
from firma_pdf.stamp import build_firmaec_stamp_style, build_firmaec_qr_payload


def prepare_pdf_bytes_for_signing(pdf_bytes: bytes) -> bytes:
    """Si el PDF no contiene firmas criptográficas previas, normaliza su estructura
    con PyMuPDF para eliminar secciones xref híbridas o tablas corruptas."""
    if b"/ByteRange" in pdf_bytes:
        return pdf_bytes
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for p in doc:
                for w in p.widgets():
                    if w.field_name and w.is_signed:
                        return pdf_bytes
            return doc.tobytes(garbage=3, deflate=True)
    except Exception:
        return pdf_bytes


def find_unique_field_name(existing_names: List[str], base: str = "Firma") -> str:
    """Genera un nombre de campo de firma que no colisione con firmas previas."""
    index = 1
    while f"{base}_{index}" in existing_names or f"{base}{index}" in existing_names:
        index += 1
    return f"{base}_{index}"


def parse_page_arg(page_str: str, total_pages: int) -> List[int]:
    """Interpreta el argumento de página ('first', 'last', 'all', o número entero 1-based).
    
    Retorna lista de índices 0-based.
    """
    page_str = str(page_str).lower().strip()
    if page_str in ("last", "ultima", "última"):
        return [total_pages - 1]
    if page_str in ("first", "primera"):
        return [0]
    if page_str in ("all", "todas", "todo"):
        return list(range(total_pages))

    try:
        val = int(page_str)
        if val < 1 or val > total_pages:
            raise ValueError(f"Página {val} fuera de rango. El documento tiene {total_pages} página(s).")
        return [val - 1]
    except ValueError as e:
        if "fuera de rango" in str(e):
            raise
        raise ValueError(f"Valor de página no reconocido: '{page_str}'. Usa 'first', 'last', 'all' o un número.")


def get_available_output_path(target_out: Path, max_attempts: int = 9999) -> Path:
    """Si el archivo de salida ya existe, busca automáticamente un nombre alternativo como archivo-signed_1.pdf."""
    if not target_out.exists():
        return target_out
    parent = target_out.parent
    stem = target_out.stem
    suffix = target_out.suffix
    for counter in range(1, max_attempts + 1):
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"No se pudo encontrar un nombre de salida disponible para {target_out}")


def sign_single_page(
    current_pdf_bytes: bytes,
    target_page_idx: int,
    p12_path: Union[str, Path],
    password: str,
    signer_name: str,
    pos: Optional[str] = None,
    search_text: Optional[str] = None,
    coords: Optional[Tuple[float, float]] = None,
    offset: Tuple[float, float] = (0.0, 0.0),
    reason: str = "Firma Electrónica",
    location: str = "",
    verify_url: Optional[str] = None,
    logo_path: Optional[Union[str, Path]] = None,
) -> bytes:
    """Aplica una firma criptográfica con estampa QR sobre una página específica en memoria."""
    with fitz.open(stream=current_pdf_bytes, filetype="pdf") as doc:
        page = doc[target_page_idx]
        existing_field_names = [
            w.field_name for p in doc for w in p.widgets() if w.field_name
        ]
        box = compute_signature_box(
            page=page,
            pos=pos,
            search_text=search_text,
            coords=coords,
            offset=offset,
            w=STAMP_WIDTH,
            h=STAMP_HEIGHT,
        )

    field_name = find_unique_field_name(existing_field_names)

    pass_bytes = password.encode("utf-8")
    signer = signers.SimpleSigner.load_pkcs12(str(p12_path), passphrase=pass_bytes)

    stamp_style = build_firmaec_stamp_style(border_width=0, logo_path=logo_path)

    qr_payload = build_firmaec_qr_payload(
        signer_name=signer_name,
        reason=reason,
        location=location,
        timestamp=datetime.now(),
        verify_url=verify_url,
    )

    app_params = {
        "signer": signer_name,
        "url": qr_payload,
    }

    field_spec = fields.SigFieldSpec(
        sig_field_name=field_name,
        on_page=target_page_idx,
        box=box,
    )

    meta = signers.PdfSignatureMetadata(
        field_name=field_name,
        reason=reason,
        location=location or None,
    )

    pdf_signer = signers.PdfSigner(
        signature_meta=meta,
        signer=signer,
        stamp_style=stamp_style,
        new_field_spec=field_spec,
    )

    in_buf = io.BytesIO(current_pdf_bytes)
    out_buf = io.BytesIO()
    w = IncrementalPdfFileWriter(in_buf, strict=False)
    pdf_signer.sign_pdf(
        w,
        output=out_buf,
        appearance_text_params=app_params,
    )
    return out_buf.getvalue()


def _resolve_output_and_cert(
    input_path: Union[str, Path],
    output_path: Optional[Union[str, Path]],
    p12_path: Union[str, Path],
    password: str,
    suffix: str,
) -> Tuple[Path, Path, str]:
    """Valida entrada, resuelve ruta de salida disponible y extrae el nombre del firmante."""
    in_file = Path(input_path).resolve()
    if not in_file.is_file():
        raise FileNotFoundError(f"No existe el archivo de entrada: {in_file}")

    if output_path is None:
        target_out = in_file.with_name(f"{in_file.stem}{suffix}.pdf")
    else:
        out_p = Path(output_path).resolve()
        if out_p.is_dir():
            target_out = out_p / f"{in_file.stem}{suffix}.pdf"
        else:
            out_p.parent.mkdir(parents=True, exist_ok=True)
            target_out = out_p

    target_out = get_available_output_path(target_out)
    _, cert, _ = load_p12_certificate(p12_path, password)
    signer_name = extract_signer_name(cert)
    return in_file, target_out, signer_name


def sign_pdf_file(
    input_path: Union[str, Path],
    output_path: Optional[Union[str, Path]],
    p12_path: Union[str, Path],
    password: str,
    page_spec: str = "last",
    pos: Optional[str] = None,
    search_text: Optional[str] = None,
    coords: Optional[Tuple[float, float]] = None,
    offset: Tuple[float, float] = (0.0, 0.0),
    reason: str = "Firma Electrónica",
    location: str = "",
    verify_url: Optional[str] = None,
    suffix: str = "-signed",
    logo_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Firma un archivo PDF completo según las especificaciones de página y posición."""
    in_file, target_out, signer_name = _resolve_output_and_cert(
        input_path, output_path, p12_path, password, suffix
    )

    raw_pdf_bytes = in_file.read_bytes()
    pdf_bytes = prepare_pdf_bytes_for_signing(raw_pdf_bytes)
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc_inspect:
        total_pages = len(doc_inspect)
        auto_mode = str(page_spec).lower().strip() in ("last", "ultima", "última", "auto")

        if auto_mode:
            target_page_idx, auto_box = find_auto_signature_target(
                doc=doc_inspect,
                search_text=search_text or signer_name,
                w=STAMP_WIDTH,
                h=STAMP_HEIGHT,
            )
            target_page_indices = [target_page_idx]
            if auto_box is not None and coords is None:
                coords = (float(auto_box[0]), float(auto_box[1]))
                search_text = None
            elif coords is None and pos is None:
                pos = "bottom-right"
                search_text = None
        else:
            target_page_indices = parse_page_arg(page_spec, total_pages)

    current_bytes = pdf_bytes
    for page_idx in target_page_indices:
        current_bytes = sign_single_page(
            current_pdf_bytes=current_bytes,
            target_page_idx=page_idx,
            p12_path=p12_path,
            password=password,
            signer_name=signer_name,
            pos=pos,
            search_text=search_text,
            coords=coords,
            offset=offset,
            reason=reason,
            location=location,
            verify_url=verify_url,
            logo_path=logo_path,
        )

    target_out.write_bytes(current_bytes)
    return target_out


def sign_pdf_multi_boxes(
    input_path: Union[str, Path],
    output_path: Optional[Union[str, Path]],
    p12_path: Union[str, Path],
    password: str,
    boxes: List[Tuple[int, float, float]],
    reason: str = "Firma Electrónica",
    location: str = "",
    verify_url: Optional[str] = None,
    suffix: str = "-signed",
    logo_path: Optional[Union[str, Path]] = None,
) -> Path:
    """Aplica múltiples firmas (en la misma o distintas páginas) de manera incremental sobre el mismo documento."""
    in_file, target_out, signer_name = _resolve_output_and_cert(
        input_path, output_path, p12_path, password, suffix
    )

    current_bytes = prepare_pdf_bytes_for_signing(in_file.read_bytes())
    for (page_idx, x1, y1) in boxes:
        current_bytes = sign_single_page(
            current_pdf_bytes=current_bytes,
            target_page_idx=page_idx,
            p12_path=p12_path,
            password=password,
            signer_name=signer_name,
            coords=(x1, y1),
            reason=reason,
            location=location,
            verify_url=verify_url,
            logo_path=logo_path,
        )

    target_out.write_bytes(current_bytes)
    return target_out


def _is_already_signed_name(filename: str) -> bool:
    low = filename.lower()
    return low.endswith("_firmado.pdf") or low.endswith("-signed.pdf")


def resolve_batch_files(inputs: List[str]) -> List[Path]:
    """Resuelve rutas de archivos, carpetas o patrones comodín para firmado por lotes."""
    resolved: List[Path] = []

    for item in inputs:
        p = Path(item).resolve()
        if p.is_file():
            if p.suffix.lower() == ".pdf":
                resolved.append(p)
        elif p.is_dir():
            for pdf_file in sorted(p.rglob("*.pdf")):
                if not _is_already_signed_name(pdf_file.name):
                    resolved.append(pdf_file)
        else:
            parent = p.parent if str(p.parent) != "" else Path(".")
            pattern = p.name
            matches = list(parent.glob(pattern))
            for m in matches:
                if m.is_file() and m.suffix.lower() == ".pdf":
                    if not _is_already_signed_name(m.name):
                        resolved.append(m)

    seen = set()
    final_list = []
    for f in resolved:
        if f not in seen:
            seen.add(f)
            final_list.append(f)

    return final_list
