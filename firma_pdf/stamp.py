"""Estilo visual de la estampa de firma electrónica con QR de alta definición y tipografía Times-Bold."""

import textwrap
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Union

import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import CircleModuleDrawer
from PIL import Image, ImageDraw

from pyhanko.pdf_utils import content, layout, images
from pyhanko.pdf_utils.generic import pdf_name
from pyhanko.pdf_utils.font.basic import SimpleFontEngineFactory
from pyhanko.stamp.qr import QRStamp, QRStampStyle, QRPosition

ROYAL_BLUE = (10, 62, 208)


def _pdf_escape_latin1(text: str) -> bytes:
    """Escapa paréntesis y barras invertidas y codifica de forma segura a Latin-1 para PDF."""
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return escaped.encode("latin1", errors="replace")


def _to_qr_alphanumeric(text: str) -> str:
    """Normaliza una cadena al alfabeto ISO QR Alphanumeric (0-9, A-Z, espacio, $%*+-./:)
    para lograr codificación de 5.5 bits/carácter."""
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").upper()
    allowed = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:")
    return "".join(ch if ch in allowed else " " for ch in norm)


def build_firmaec_qr_payload(
    signer_name: str,
    reason: str = "",
    location: str = "",
    timestamp: Optional[datetime] = None,
    verify_url: Optional[str] = None,
) -> str:
    """Construye el contenido que se codifica dentro del código QR."""
    if verify_url and verify_url.strip():
        return verify_url.strip()

    if timestamp is None:
        timestamp = datetime.now()

    date_str = timestamp.strftime("%Y-%m-%d %H:%M")
    clean_name = _to_qr_alphanumeric(signer_name).strip()

    parts = [f"FIRMADO POR: {clean_name}", f"FECHA: {date_str}"]
    if location and location.strip():
        parts.append(f"LUGAR: {_to_qr_alphanumeric(location).strip()}")
    if reason and reason.strip() and reason.strip().lower() != "firma electrónica":
        parts.append(f"RAZON: {_to_qr_alphanumeric(reason).strip()}")
    return _to_qr_alphanumeric(" / ".join(parts))


def generate_stylish_qr(
    data: str,
    primary_color: Tuple[int, int, int] = ROYAL_BLUE,
    logo_path: Optional[Union[str, Path]] = None,
) -> Image.Image:
    """Genera un código QR con puntos circulares, ojos redondeados y logo central opcional."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_Q,
        box_size=28,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)

    resolved_logo = Path(logo_path) if logo_path else None
    has_logo = resolved_logo is not None and resolved_logo.is_file()

    if has_logo:
        m_count = qr.modules_count
        center_idx = m_count / 2.0
        half_span = 5.1
        for r in range(m_count):
            for c in range(m_count):
                dr = abs((r + 0.5) - center_idx)
                dc = abs((c + 0.5) - center_idx)
                if dr <= half_span and dc <= half_span:
                    if dr > half_span - 1.5 and dc > half_span - 1.5:
                        if (dr - (half_span - 1.5)) ** 2 + (dc - (half_span - 1.5)) ** 2 > 1.6 ** 2:
                            continue
                    qr.modules[r][c] = False

    base_img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=CircleModuleDrawer(),
    ).convert("RGBA")

    w, h = base_img.size
    n = len(qr.get_matrix())
    border = qr.border
    box_size = w // n
    draw = ImageDraw.Draw(base_img)

    # Dibujar los 3 ojos con esquinas redondeadas
    def draw_rounded_eye(r0: int, c0: int):
        x0 = c0 * box_size
        y0 = r0 * box_size
        size = 7 * box_size
        draw.rectangle([x0, y0, x0 + size, y0 + size], fill=(255, 255, 255, 255))
        c_out = box_size * 0.9
        draw.rounded_rectangle([x0, y0, x0 + size, y0 + size], radius=c_out, fill=primary_color + (255,))
        m1 = box_size
        draw.rounded_rectangle([x0 + m1, y0 + m1, x0 + size - m1, y0 + size - m1], radius=c_out * 0.65, fill=(255, 255, 255, 255))
        m2 = box_size * 2
        draw.rounded_rectangle([x0 + m2, y0 + m2, x0 + size - m2, y0 + size - m2], radius=c_out * 0.45, fill=primary_color + (255,))

    draw_rounded_eye(border, border)
    draw_rounded_eye(border, n - border - 7)
    draw_rounded_eye(n - border - 7, border)

    # Incrustar logo opcional en el centro si el usuario proveyó uno
    if has_logo and resolved_logo is not None:
        cx = w // 2
        cy = h // 2
        logo_img = Image.open(resolved_logo).convert("RGBA")
        lw = int(box_size * 9.8)
        logo_resized = logo_img.resize((lw, lw), Image.Resampling.LANCZOS)
        base_img.paste(logo_resized, (cx - lw // 2, cy - lw // 2), logo_resized)

    return base_img.convert("RGB")


class ElegantQRStamp(QRStamp):
    """Estampa visual distinguida: QR de alta definición y texto en Times-Bold."""

    def _qr_xobject(self):
        logo_path = self.style.logo_path if hasattr(self.style, "logo_path") else None
        pil_qr = generate_stylish_qr(self.url, logo_path=logo_path)
        pdf_img = images.PdfImage(pil_qr, writer=self.writer)
        form_xobj = pdf_img.as_form_xobject()
        return self.writer.add_object(form_xobj), pil_qr.size[0]

    def _inner_layout_natural_size(self):
        reg_fe = SimpleFontEngineFactory("Helvetica", 0.5)
        bold_fe = SimpleFontEngineFactory("Times-Bold", 0.5)

        self.set_resource(
            category=content.ResourceType.FONT,
            name=pdf_name("/FReg"),
            value=reg_fe.create_font_engine(self.writer).as_resource(),
        )
        self.set_resource(
            category=content.ResourceType.FONT,
            name=pdf_name("/FBold"),
            value=bold_fe.create_font_engine(self.writer).as_resource(),
        )

        signer_name = self.text_params.get("signer", "").upper().strip()
        name_lines = textwrap.wrap(signer_name, width=18)
        if not name_lines:
            name_lines = [signer_name]

        header_line = "Firmado electrónicamente por:"

        w_header = 0.52 * 7.5 * len(header_line)
        w_name = max(0.55 * 11.5 * len(l) for l in name_lines)
        text_width = int(round(max(w_header, w_name) + 8))

        text_height = int(round(11.0 + 9.0 + len(name_lines) * 15.0))

        # Tamaño físico del QR en el PDF: 63 puntos con cuadrícula 33x33 (puntos grandes) que encaja sin tapar 'Atentamente,'
        qr_size = 63

        cmds = [
            b"/Tx BMC q BT",
            b"/FReg 6.8 Tf 9.5 TL",
            b"0 %g Td" % (text_height - 9.0),
            b"(%s) Tj" % _pdf_escape_latin1(header_line),
            b"/FBold 10.8 Tf 14.0 TL",
            b"0.22 w 2 Tr",
            b"0 -17.0 Td",
        ]
        for i, nl in enumerate(name_lines):
            if i < len(name_lines) - 1:
                cmds.append(b"(%s) Tj T*" % _pdf_escape_latin1(nl))
            else:
                cmds.append(b"(%s) Tj" % _pdf_escape_latin1(nl))
        cmds.append(b"0 Tr ET Q EMC")
        text_commands = [b" ".join(cmds)]

        qr_ref, natural_qr_size = self._qr_xobject()
        self.set_resource(
            category=content.ResourceType.XOBJECT,
            name=pdf_name("/QR"),
            value=qr_ref,
        )

        style = self.style
        innsep = 1

        qr_innunits_scale = qr_size / natural_qr_size
        qr_padded = qr_size + 2 * innsep

        inn_width = qr_padded + text_width + 4
        inn_height = max(qr_padded, text_height)

        default_layout = style.qr_position.value
        qr_layout_rule = layout.SimpleBoxLayoutRule(
            x_align=default_layout.x_align,
            y_align=default_layout.y_align,
            margins=layout.Margins.uniform(innsep),
            inner_content_scaling=layout.InnerScaling.NO_SCALING,
        )

        inner_box = layout.BoxConstraints(inn_width, inn_height)
        qr_inn_pos = qr_layout_rule.fit(inner_box, qr_size, qr_size)

        draw_qr_command = b"q %g 0 0 %g %g %g cm /QR Do Q" % (
            qr_inn_pos.x_scale * qr_innunits_scale,
            qr_inn_pos.y_scale * qr_innunits_scale,
            qr_inn_pos.x_pos,
            qr_inn_pos.y_pos,
        )

        tb_margins = layout.Margins(left=qr_padded + 3, right=0, top=0, bottom=0)
        tb_layout_rule = layout.SimpleBoxLayoutRule(
            x_align=default_layout.x_align.flipped,
            y_align=default_layout.y_align.flipped,
            margins=tb_margins,
            inner_content_scaling=layout.InnerScaling.NO_SCALING,
        )

        text_inn_pos = tb_layout_rule.fit(inner_box, text_width, text_height)
        commands = [draw_qr_command, b"q", text_inn_pos.as_cm()]
        commands.extend(text_commands)
        commands.append(b"Q")
        return commands, (inn_width, inn_height)


class ElegantQRStampStyle(QRStampStyle):
    """Estilo de estampa distinguida."""
    logo_path: Optional[str] = None

    def create_stamp(self, writer, box, text_params):
        try:
            url = text_params.pop("url")
        except KeyError:
            raise layout.LayoutError("Requiere parámetro url.")
        return ElegantQRStamp(writer, style=self, url=url, text_params=text_params, box=box)


def build_firmaec_stamp_style(
    border_width: int = 0,
    logo_path: Optional[Union[str, Path]] = None,
) -> ElegantQRStampStyle:
    """Construye la estampa con diseño elegante."""
    style = ElegantQRStampStyle(
        border_width=border_width,
        background=None,
        background_opacity=0.0,
        innsep=3,
        qr_position=QRPosition.LEFT_OF_TEXT,
    )
    style.logo_path = str(logo_path) if logo_path else None
    return style
