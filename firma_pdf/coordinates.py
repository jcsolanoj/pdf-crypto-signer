"""Motor de cálculo y conversión de coordenadas entre PyMuPDF y el estándar PDF / pyHanko."""

import unicodedata
from typing import Tuple, Optional, List
import fitz

STAMP_WIDTH = 215
STAMP_HEIGHT = 65
DEFAULT_MARGIN = 35


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )


def generate_name_variants(name: Optional[str]) -> List[str]:
    """Genera variantes de búsqueda dinámicas a partir de un nombre completo."""
    if not name or not name.strip():
        return []
    clean = " ".join(name.strip().split())
    variants: List[str] = [clean]
    no_accents = _strip_accents(clean)
    if no_accents != clean:
        variants.append(no_accents)

    tokens = clean.split()
    if len(tokens) >= 3:
        # Ej. "Nombre1 Nombre2 Apellido1 Apellido2" -> "Nombre1 Apellido1", "Apellido1 Apellido2"
        candidates = [
            f"{tokens[0]} {tokens[-2]}",
            f"{tokens[0]} {tokens[-1]}",
            f"{tokens[-2]} {tokens[-1]}",
            tokens[-2],
            tokens[-1],
        ]
        for cand in candidates:
            for v in (cand, _strip_accents(cand)):
                if v and v not in variants:
                    variants.append(v)
    elif len(tokens) == 2:
        for cand in (tokens[1], _strip_accents(tokens[1])):
            if cand and cand not in variants:
                variants.append(cand)
    return variants


def parse_offset(offset_str: Optional[str]) -> Tuple[float, float]:
    """Parsea una cadena 'dx,dy' a dos floats (dx, dy)."""
    if not offset_str:
        return 0.0, 0.0
    try:
        parts = [float(p.strip()) for p in offset_str.split(",")]
        if len(parts) == 1:
            return parts[0], 0.0
        return parts[0], parts[1]
    except Exception as e:
        raise ValueError(f"Formato de offset inválido '{offset_str}'. Usa 'dx,dy' (ej. '10,-5').")


def parse_coords(coords_str: Optional[str]) -> Optional[Tuple[float, float]]:
    """Parsea una cadena 'x,y' a dos floats (x, y) en sistema de coordenadas PDF."""
    if not coords_str:
        return None
    try:
        parts = [float(p.strip()) for p in coords_str.split(",")]
        if len(parts) != 2:
            raise ValueError()
        return parts[0], parts[1]
    except Exception:
        raise ValueError(f"Formato de coordenadas inválido '{coords_str}'. Usa 'x,y' (ej. '100,200').")


def get_preset_box(pos: str, page_width: float, page_height: float,
                   w: float = STAMP_WIDTH, h: float = STAMP_HEIGHT,
                   margin: float = DEFAULT_MARGIN) -> Tuple[int, int, int, int]:
    """Calcula el recuadro (x1, y1, x2, y2) en coordenadas PDF para una posición predefinida."""
    pos = pos.lower().strip()

    if pos in ("bottom-right", "br"):
        x1 = page_width - margin - w
        y1 = margin
    elif pos in ("bottom-left", "bl"):
        x1 = margin
        y1 = margin
    elif pos in ("bottom-center", "bc"):
        x1 = (page_width - w) / 2
        y1 = margin
    elif pos in ("top-right", "tr"):
        x1 = page_width - margin - w
        y1 = page_height - margin - h
    elif pos in ("top-left", "tl"):
        x1 = margin
        y1 = page_height - margin - h
    elif pos in ("center", "c"):
        x1 = (page_width - w) / 2
        y1 = (page_height - h) / 2
    else:
        raise ValueError(
            f"Posición predefinida desconocida: '{pos}'. "
            "Opciones válidas: bottom-right, bottom-left, bottom-center, top-right, top-left, center."
        )

    return int(round(x1)), int(round(y1)), int(round(x1 + w)), int(round(y1 + h))


def search_text_box(page: fitz.Page, search_text: str,
                    w: float = STAMP_WIDTH, h: float = STAMP_HEIGHT) -> Optional[Tuple[int, int, int, int]]:
    """Busca el texto dentro de la página con PyMuPDF y calcula el recuadro en coordenadas PDF."""
    rects: List[fitz.Rect] = page.search_for(search_text)
    if not rects:
        for alt in generate_name_variants(search_text)[1:]:
            rects = page.search_for(alt)
            if rects:
                break
    if not rects:
        return None

    target_rect = rects[-1]
    page_height = page.rect.height

    x1 = target_rect.x0
    # Ubicarlo encima del texto con holgura para la estampa ampliada
    y1 = page_height - target_rect.y0 + 4

    if y1 + h > page_height - 10:
        y1 = max(10, page_height - target_rect.y1 - 5)

    x2 = x1 + w
    y2 = y1 + h

    return int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))


def find_auto_signature_target(
    doc: fitz.Document,
    search_text: Optional[str] = None,
    w: float = STAMP_WIDTH,
    h: float = STAMP_HEIGHT,
) -> Tuple[int, Optional[Tuple[int, int, int, int]]]:
    """Determina de forma inteligente la página y coordenadas óptimas para estampar la firma.

    Reglas:
    1. Si el documento tiene 1 página: busca el texto/nombre del firmante o palabras clave de firma.
    2. Si el documento tiene múltiples páginas (>1):
       - Busca desde la ÚLTIMA página hacia atrás (de N-1 a 1) para evitar firmar sobre la carátula.
       - Si no encuentra el nombre del firmante, busca palabras clave genéricas de firma en la última página.
       - Si tampoco aparecen, devuelve la última página para posicionamiento por defecto.
    """
    total_pages = len(doc)
    if total_pages == 0:
        return 0, None

    name_variants = generate_name_variants(search_text)
    signature_keywords = [
        "Firma del Docente", "Firma Docente", "Firma Autorizada",
        "Firmado por", "Revisado por", "Aprobado por",
        "Atentamente", "Firma", "Signature",
    ]

    if total_pages == 1:
        page = doc[0]
        for term in name_variants + signature_keywords:
            box = search_text_box(page, term, w=w, h=h)
            if box:
                return 0, box
        return 0, None

    # 1. Buscar el nombre en páginas desde la última hacia atrás (N-1 hasta 1)
    if name_variants:
        for p_idx in range(total_pages - 1, 0, -1):
            page = doc[p_idx]
            for term in name_variants:
                box = search_text_box(page, term, w=w, h=h)
                if box:
                    return p_idx, box

    # 2. Si no se encontró el nombre entre N-1 y 1, buscar palabras clave de firma en la última página
    last_page = doc[total_pages - 1]
    for kw in signature_keywords:
        box = search_text_box(last_page, kw, w=w, h=h)
        if box:
            return total_pages - 1, box

    # 3. Si tampoco hay palabras clave, firmar en la ÚLTIMA página en posición por defecto
    return total_pages - 1, None


def compute_signature_box(
    page: fitz.Page,
    pos: Optional[str] = None,
    search_text: Optional[str] = None,
    coords: Optional[Tuple[float, float]] = None,
    offset: Tuple[float, float] = (0.0, 0.0),
    w: float = STAMP_WIDTH,
    h: float = STAMP_HEIGHT,
) -> Tuple[int, int, int, int]:
    """Calcula la caja delimitadora final (x1, y1, x2, y2) en coordenadas PDF (pyHanko)."""
    page_w = page.rect.width
    page_h = page.rect.height

    box = None

    if search_text:
        box = search_text_box(page, search_text, w=w, h=h)
        if not box:
            print(f"[AVISO] No se encontró el texto '{search_text}'. Usando posición por defecto (bottom-right).")

    if box is None and coords is not None:
        cx, cy = coords
        box = (int(round(cx)), int(round(cy)), int(round(cx + w)), int(round(cy + h)))

    if box is None:
        target_pos = pos if pos else "bottom-right"
        box = get_preset_box(target_pos, page_w, page_h, w=w, h=h)

    dx, dy = offset
    x1, y1, x2, y2 = box
    x1 += dx
    x2 += dx
    y1 += dy
    y2 += dy

    if x1 < 10:
        shift_x = 10 - x1
        x1 += shift_x
        x2 += shift_x
    if x2 > page_w - 10:
        shift_x = (page_w - 10) - x2
        x1 += shift_x
        x2 += shift_x

    if y1 < 10:
        shift_y = 10 - y1
        y1 += shift_y
        y2 += shift_y
    if y2 > page_h - 10:
        shift_y = (page_h - 10) - y2
        y1 += shift_y
        y2 += shift_y

    return int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
