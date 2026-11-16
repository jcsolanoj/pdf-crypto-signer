"""Interfaz gráfica de usuario (GUI) para Firma Ultrarápida (--quick) y Visor Avanzado Multi-Documento / Multi-Sitio."""

import os
import sys
import time
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from firma_pdf.config import get_credentials, load_local_meta, CONFIG_DIR
from firma_pdf.coordinates import (
    STAMP_WIDTH,
    STAMP_HEIGHT,
    search_text_box,
    find_auto_signature_target,
    get_preset_box,
)
from firma_pdf.signer import sign_pdf_file, sign_pdf_multi_boxes, resolve_batch_files


def _collect_explorer_multi_selection(initial_files: List[str]) -> Optional[List[Path]]:
    """Agrupa múltiples archivos seleccionados en el Explorador de Windows cuando este lanza
    varios procesos en paralelo al hacer clic derecho sobre una selección múltiple."""
    valid_paths = [Path(f).resolve() for f in initial_files if Path(f).is_file() and f.lower().endswith(".pdf")]
    if not valid_paths:
        return []
    if sys.platform != "win32":
        return valid_paths

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    batch_file = CONFIG_DIR / "explorer_batch.json"
    lock_file = CONFIG_DIR / "explorer_batch.lock"

    now = time.time()
    is_leader = False

    try:
        # Si el archivo de lote existe y tiene menos de 1.2 segundos, agregarse y terminar este proceso secundario
        if batch_file.exists() and (now - batch_file.stat().st_mtime) < 1.2:
            for _ in range(15):
                try:
                    with open(lock_file, "x"):
                        data = json.loads(batch_file.read_text(encoding="utf-8"))
                        for vp in valid_paths:
                            if str(vp) not in data["files"]:
                                data["files"].append(str(vp))
                        batch_file.write_text(json.dumps(data), encoding="utf-8")
                    lock_file.unlink(missing_ok=True)
                    return None  # Proceso secundario absorbido por el proceso principal
                except FileExistsError:
                    time.sleep(0.02)
        else:
            with open(lock_file, "x"):
                batch_file.write_text(json.dumps({"files": [str(p) for p in valid_paths]}), encoding="utf-8")
                is_leader = True
            lock_file.unlink(missing_ok=True)
    except Exception:
        return valid_paths

    if is_leader:
        # Esperar 280 ms por si Windows Explorer está lanzando más archivos de la misma selección
        time.sleep(0.28)
        try:
            data = json.loads(batch_file.read_text(encoding="utf-8"))
            batch_file.unlink(missing_ok=True)
            return [Path(p) for p in data.get("files", []) if Path(p).is_file()]
        except Exception:
            return valid_paths

    return valid_paths


class QuickSignDialog:
    """Ventana minimalista de Firma Ultrarápida: solicita el PIN de 4 dígitos,
    busca automáticamente el nombre del firmante sin abrir el visor y guarda como *-signed.pdf."""

    def __init__(self, files: List[Path]):
        self.files = files
        self.root = tk.Tk()
        self.root.title("Firma Rápida - pdf-crypto-signer")
        self.root.resizable(False, False)
        self.root.configure(bg="#ffffff")
        self.root.attributes("-topmost", True)

        w, h = 410, 205
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        self._build_ui()
        self.root.after(50, lambda: self.ent_pin.focus_force())

    def _build_ui(self):
        header = tk.Frame(self.root, bg="#0a3ed0", height=44)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(
            header,
            text="⚡ Firma Electrónica Rápida",
            font=("Segoe UI", 10, "bold"),
            bg="#0a3ed0",
            fg="#ffffff",
        ).pack(side=tk.LEFT, padx=14)

        body = tk.Frame(self.root, bg="#ffffff", padx=18, pady=12)
        body.pack(fill=tk.BOTH, expand=True)

        if len(self.files) == 1:
            f_name = self.files[0].name
            out_name = f"{self.files[0].stem}-signed.pdf"
            desc = f"📄 {f_name}\n➔  {out_name}"
        else:
            desc = f"📚 {len(self.files)} documentos seleccionados\n➔  Se guardarán como *-signed.pdf"

        self.lbl_info = tk.Label(
            body,
            text=desc,
            font=("Segoe UI", 9),
            bg="#ffffff",
            fg="#334155",
            justify=tk.LEFT,
            anchor="w",
        )
        self.lbl_info.pack(fill=tk.X, pady=(0, 10))

        pin_row = tk.Frame(body, bg="#ffffff")
        pin_row.pack(fill=tk.X, pady=4)

        tk.Label(
            pin_row,
            text="PIN (4 dígitos):",
            font=("Segoe UI", 10, "bold"),
            bg="#ffffff",
            fg="#0f172a",
        ).pack(side=tk.LEFT)

        self.pin_var = tk.StringVar()
        self.pin_var.trace_add("write", self._on_pin_change)

        self.ent_pin = tk.Entry(
            pin_row,
            textvariable=self.pin_var,
            show="•",
            width=8,
            font=("Segoe UI", 13, "bold"),
            justify="center",
            relief=tk.SOLID,
            bd=1,
        )
        self.ent_pin.pack(side=tk.LEFT, padx=10)
        self.ent_pin.bind("<Return>", lambda e: self._execute_sign())
        self.ent_pin.bind("<Escape>", lambda e: self.root.destroy())

        self.btn_sign = tk.Button(
            pin_row,
            text="Firmar Ahora",
            font=("Segoe UI", 9, "bold"),
            bg="#10b981",
            fg="#ffffff",
            activebackground="#059669",
            relief=tk.FLAT,
            padx=12,
            pady=5,
            cursor="hand2",
            command=self._execute_sign,
        )
        self.btn_sign.pack(side=tk.RIGHT)

        self.lbl_status = tk.Label(
            body,
            text="Ingresa los 4 dígitos de tu PIN para firmar al instante.",
            font=("Segoe UI", 8),
            bg="#ffffff",
            fg="#64748b",
            anchor="w",
        )
        self.lbl_status.pack(fill=tk.X, pady=(8, 0))

    def _on_pin_change(self, *args):
        val = self.pin_var.get().strip()
        if len(val) == 4 and val.isdigit():
            # Auto-ejecutar apenas se ingresan los 4 dígitos para máxima velocidad
            self.root.after(80, self._execute_sign)

    def _execute_sign(self):
        if getattr(self, "_signing", False):
            return
        pin = self.pin_var.get().strip()
        if not pin:
            self.lbl_status.configure(text="⚠️ Ingresa tu PIN para continuar.", fg="#dc2626")
            return

        self._signing = True
        self.lbl_status.configure(text="⏳ Firmando documento(s)...", fg="#0a3ed0")
        self.root.update_idletasks()

        try:
            p12_path, password = get_credentials(pin=pin)
        except Exception as e:
            self._signing = False
            self.pin_var.set("")
            self.lbl_status.configure(text=f"❌ {e}", fg="#dc2626")
            self.ent_pin.focus_force()
            return

        meta = load_local_meta()
        logo_val = meta.get("logo_path") or None
        location_val = meta.get("default_location", "")

        signed_outputs = []
        errors = []
        for f_path in self.files:
            try:
                out_path = sign_pdf_file(
                    input_path=f_path,
                    output_path=None,
                    p12_path=p12_path,
                    password=password,
                    page_spec="auto",
                    location=location_val,
                    suffix="-signed",
                    logo_path=logo_val,
                )
                signed_outputs.append(out_path)
            except Exception as e:
                errors.append(f"{f_path.name}: {e}")

        if errors:
            self._signing = False
            messagebox.showerror("Error al firmar", "\n".join(errors), parent=self.root)
            self.root.destroy()
            return

        self.lbl_status.configure(
            text=f"✅ ¡Listo! Guardado: {signed_outputs[0].name if len(signed_outputs) == 1 else f'{len(signed_outputs)} archivos (-signed.pdf)'}",
            fg="#059669",
            font=("Segoe UI", 9, "bold"),
        )
        self.root.update_idletasks()
        self.root.after(750, self.root.destroy)

    def run(self):
        self.root.mainloop()


class PDFSignerApp:
    """Visor Avanzado para firmar múltiples documentos en lote y/o estampar múltiples firmas
    en distintos sitios o páginas de un mismo documento."""

    def __init__(self, root: tk.Tk, initial_files: Optional[List[Path]] = None):
        self.root = root
        self.root.title("Visor de Firma Electrónica - pdf-crypto-signer")
        self.root.geometry("1140x800")
        self.root.minsize(880, 620)

        self.file_list: List[Path] = []
        self.current_file_idx = 0
        self.doc: Optional[fitz.Document] = None
        self.current_page_idx = 0

        # Almacena las marcas manuales por cada archivo: Dict[Path, List[Tuple[page_idx, x1, y1, x2, y2]]]
        self.doc_manual_boxes: Dict[Path, List[Tuple[int, int, int, int, int]]] = {}

        self._setup_theme()
        self._create_widgets()

        if initial_files:
            for p in initial_files:
                if p.is_file() and p.suffix.lower() == ".pdf" and p not in self.file_list:
                    self.file_list.append(p)
            if self.file_list:
                self._refresh_file_selector()
                self._load_document(self.file_list[0])

    def _setup_theme(self):
        self.bg_color = "#f1f5f9"
        self.primary_blue = "#0a3ed0"
        self.text_dark = "#1e293b"
        self.root.configure(bg=self.bg_color)

    @property
    def current_file(self) -> Optional[Path]:
        if 0 <= self.current_file_idx < len(self.file_list):
            return self.file_list[self.current_file_idx]
        return None

    @property
    def current_manual_boxes(self) -> List[Tuple[int, int, int, int, int]]:
        cf = self.current_file
        if cf is None:
            return []
        return self.doc_manual_boxes.setdefault(cf, [])

    def _create_widgets(self):
        # 1. Barra Superior (Gestión de Lotes y Firma)
        top_frame = tk.Frame(self.root, bg="#ffffff", height=68, relief=tk.RAISED, bd=1)
        top_frame.pack(fill=tk.X, side=tk.TOP)

        btn_open = tk.Button(
            top_frame, text="📂 Abrir PDF(s)", font=("Segoe UI", 9, "bold"),
            bg=self.primary_blue, fg="white", activebackground="#0035ab",
            relief=tk.FLAT, padx=10, pady=6, cursor="hand2", command=self._on_open_files
        )
        btn_open.pack(side=tk.LEFT, padx=(12, 4), pady=10)

        btn_add = tk.Button(
            top_frame, text="➕ Agregar más PDF(s)", font=("Segoe UI", 9, "bold"),
            bg="#3b82f6", fg="white", activebackground="#2563eb",
            relief=tk.FLAT, padx=10, pady=6, cursor="hand2", command=self._on_add_files
        )
        btn_add.pack(side=tk.LEFT, padx=4, pady=10)

        btn_folder = tk.Button(
            top_frame, text="📁 Agregar Carpeta", font=("Segoe UI", 9),
            bg="#e2e8f0", fg=self.text_dark, activebackground="#cbd5e1",
            relief=tk.FLAT, padx=8, pady=6, cursor="hand2", command=self._on_add_folder
        )
        btn_folder.pack(side=tk.LEFT, padx=4, pady=10)

        tk.Label(top_frame, text="Documento activo:", font=("Segoe UI", 9, "bold"), bg="#ffffff", fg=self.text_dark).pack(side=tk.LEFT, padx=(12, 4))
        self.cmb_files = ttk.Combobox(top_frame, state="readonly", width=34, font=("Segoe UI", 9))
        self.cmb_files.pack(side=tk.LEFT, padx=4, pady=10)
        self.cmb_files.bind("<<ComboboxSelected>>", self._on_file_combo_selected)

        # Panel derecho: PIN y botón Firmar
        pin_frame = tk.Frame(top_frame, bg="#ffffff")
        pin_frame.pack(side=tk.RIGHT, padx=14, pady=10)

        tk.Label(pin_frame, text="PIN:", font=("Segoe UI", 9, "bold"), bg="#ffffff", fg=self.text_dark).pack(side=tk.LEFT, padx=4)
        self.ent_pin = tk.Entry(pin_frame, show="•", width=6, font=("Segoe UI", 11, "bold"), justify="center")
        self.ent_pin.pack(side=tk.LEFT, padx=4)
        self.ent_pin.bind("<Return>", lambda e: self._on_sign_action())

        self.btn_sign = tk.Button(
            pin_frame, text="✍️ Firmar Lote (-signed.pdf)", font=("Segoe UI", 10, "bold"),
            bg="#10b981", fg="white", activebackground="#059669",
            relief=tk.FLAT, padx=14, pady=6, cursor="hand2", command=self._on_sign_action
        )
        self.btn_sign.pack(side=tk.LEFT, padx=8)

        # 2. Barra de Navegación de Páginas y Modo Multi-Sitio
        nav_frame = tk.Frame(self.root, bg="#e2e8f0", height=46)
        nav_frame.pack(fill=tk.X, side=tk.TOP)

        self.btn_prev = tk.Button(nav_frame, text="◀ Pág. Anterior", font=("Segoe UI", 9), command=self._prev_page)
        self.btn_prev.pack(side=tk.LEFT, padx=(12, 4), pady=6)

        self.lbl_page_counter = tk.Label(nav_frame, text="Página 0 de 0", font=("Segoe UI", 9, "bold"), bg="#e2e8f0")
        self.lbl_page_counter.pack(side=tk.LEFT, padx=6)

        self.btn_next = tk.Button(nav_frame, text="Pág. Siguiente ▶", font=("Segoe UI", 9), command=self._next_page)
        self.btn_next.pack(side=tk.LEFT, padx=4, pady=6)

        tk.Label(nav_frame, text="| Posicionamiento:", bg="#e2e8f0", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(14, 6))
        self.mode_var = tk.StringVar(value="auto")
        rb_auto = tk.Radiobutton(
            nav_frame, text="Auto (Buscar mi nombre)", variable=self.mode_var,
            value="auto", bg="#e2e8f0", command=self._on_mode_change
        )
        rb_auto.pack(side=tk.LEFT, padx=4)

        rb_click = tk.Radiobutton(
            nav_frame, text="Manual / Múltiples sitios (Clic izquierdo agrega firma, Clic derecho quita)",
            variable=self.mode_var, value="click", bg="#e2e8f0", command=self._on_mode_change
        )
        rb_click.pack(side=tk.LEFT, padx=4)

        self.apply_all_var = tk.BooleanVar(value=False)
        chk_all = tk.Checkbutton(
            nav_frame, text="Replicar marcas manuales en todo el lote",
            variable=self.apply_all_var, bg="#e2e8f0", font=("Segoe UI", 8)
        )
        chk_all.pack(side=tk.LEFT, padx=8)

        btn_clear_marks = tk.Button(nav_frame, text="🗑️ Borrar marcas", font=("Segoe UI", 8), command=self._clear_marks)
        btn_clear_marks.pack(side=tk.RIGHT, padx=12, pady=6)

        btn_undo_mark = tk.Button(nav_frame, text="↩ Quitar última", font=("Segoe UI", 8), command=self._undo_last_mark)
        btn_undo_mark.pack(side=tk.RIGHT, padx=4, pady=6)

        # 3. Lienzo de Previsualización del PDF
        center_frame = tk.Frame(self.root, bg=self.bg_color)
        center_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        self.canvas = tk.Canvas(center_frame, bg="#64748b", highlightthickness=0, cursor="crosshair")
        v_scroll = tk.Scrollbar(center_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        h_scroll = tk.Scrollbar(center_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)

        self.canvas.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas.bind("<Button-1>", self._on_canvas_left_click)
        self.canvas.bind("<Button-3>", self._on_canvas_right_click)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)

        # 4. Barra de Estado
        self.status_lbl = tk.Label(
            self.root,
            text="Haz clic izquierdo en cualquier parte de la página para agregar una o varias firmas, o usa el modo Auto.",
            font=("Segoe UI", 9), anchor=tk.W, bg="#cbd5e1", padx=12, pady=5
        )
        self.status_lbl.pack(fill=tk.X, side=tk.BOTTOM)

    def _refresh_file_selector(self):
        items = [f"[{i + 1}/{len(self.file_list)}] {p.name}" for i, p in enumerate(self.file_list)]
        self.cmb_files["values"] = items
        if items and 0 <= self.current_file_idx < len(items):
            self.cmb_files.current(self.current_file_idx)
        self.btn_sign.configure(
            text=f"✍️ Firmar {len(self.file_list)} PDF(s) (-signed.pdf)" if len(self.file_list) > 1 else "✍️ Firmar Ahora (-signed.pdf)"
        )

    def _on_file_combo_selected(self, event):
        idx = self.cmb_files.current()
        if 0 <= idx < len(self.file_list):
            self.current_file_idx = idx
            self._load_document(self.file_list[idx])

    def _on_open_files(self):
        paths = filedialog.askopenfilenames(
            title="Seleccionar archivo(s) PDF para firmar",
            filetypes=[("Archivos PDF", "*.pdf")]
        )
        if paths:
            self.file_list = [Path(p).resolve() for p in paths]
            self.doc_manual_boxes.clear()
            self.current_file_idx = 0
            self._refresh_file_selector()
            self._load_document(self.file_list[0])

    def _on_add_files(self):
        paths = filedialog.askopenfilenames(
            title="Agregar más archivo(s) PDF al lote actual",
            filetypes=[("Archivos PDF", "*.pdf")]
        )
        if paths:
            added = 0
            for p_str in paths:
                p = Path(p_str).resolve()
                if p not in self.file_list:
                    self.file_list.append(p)
                    added += 1
            self._refresh_file_selector()
            if self.doc is None and self.file_list:
                self._load_document(self.file_list[0])
            self.status_lbl.configure(text=f"Se agregaron {added} documento(s) al lote. Total: {len(self.file_list)} archivos.")

    def _on_add_folder(self):
        folder = filedialog.askdirectory(title="Seleccionar carpeta con PDFs para agregar al lote")
        if folder:
            batch = resolve_batch_files([folder])
            added = 0
            for p in batch:
                if p not in self.file_list:
                    self.file_list.append(p)
                    added += 1
            self._refresh_file_selector()
            if self.doc is None and self.file_list:
                self._load_document(self.file_list[0])
            self.status_lbl.configure(text=f"Se agregaron {added} PDF(s) de la carpeta. Total en lote: {len(self.file_list)}.")

    def _load_document(self, path: Path):
        try:
            if self.doc:
                self.doc.close()
            self.doc = fitz.open(path)
            boxes = self.doc_manual_boxes.get(path, [])
            if boxes:
                self.current_page_idx = boxes[-1][0]
            else:
                target_p, _ = find_auto_signature_target(self.doc, None, w=STAMP_WIDTH, h=STAMP_HEIGHT)
                self.current_page_idx = target_p
            self._render_current_page()
            self.status_lbl.configure(
                text=f"Documento activo [{self.current_file_idx + 1}/{len(self.file_list)}]: {path.name} ({len(boxes)} firma(s) manual(es) marcada(s))"
            )
        except Exception as e:
            messagebox.showerror("Error al abrir PDF", f"No se pudo cargar el archivo:\n{e}")

    def _render_current_page(self):
        if not self.doc:
            return

        total_pages = len(self.doc)
        self.lbl_page_counter.configure(text=f"Página {self.current_page_idx + 1} de {total_pages}")
        self.btn_prev.configure(state=tk.NORMAL if self.current_page_idx > 0 else tk.DISABLED)
        self.btn_next.configure(state=tk.NORMAL if self.current_page_idx < total_pages - 1 else tk.DISABLED)

        page = self.doc[self.current_page_idx]

        zoom = 1.35
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        self.pix_w = pix.width
        self.pix_h = pix.height
        self.scale_x = pix.width / page.rect.width
        self.scale_y = pix.height / page.rect.height

        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        self.tk_img = ImageTk.PhotoImage(img)

        self.canvas.delete("all")
        self.canvas.configure(scrollregion=(0, 0, pix.width, pix.height))
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_img)

        boxes = self.current_manual_boxes

        if self.mode_var.get() == "auto" and not boxes:
            target_p, auto_box = find_auto_signature_target(self.doc, None, w=STAMP_WIDTH, h=STAMP_HEIGHT)
            if self.current_page_idx == target_p:
                page_h = page.rect.height
                if auto_box:
                    cx1 = auto_box[0] * self.scale_x
                    cy1 = (page_h - auto_box[3]) * self.scale_y
                    cx2 = auto_box[2] * self.scale_x
                    cy2 = (page_h - auto_box[1]) * self.scale_y
                    self._draw_stamp_preview(cx1, cy1, cx2, cy2, label="Auto: Firma Detectada", color="#0a3ed0")
                else:
                    b = get_preset_box("bottom-right", page.rect.width, page.rect.height, w=STAMP_WIDTH, h=STAMP_HEIGHT)
                    cx1 = b[0] * self.scale_x
                    cy1 = (page_h - b[3]) * self.scale_y
                    cx2 = b[2] * self.scale_x
                    cy2 = (page_h - b[1]) * self.scale_y
                    self._draw_stamp_preview(cx1, cy1, cx2, cy2, label="Auto: Pie de página", color="#0a3ed0")

        for idx, (p_idx, bx1, by1, bx2, by2) in enumerate(boxes, start=1):
            if p_idx == self.current_page_idx:
                page_h = page.rect.height
                cx1 = bx1 * self.scale_x
                cy1 = (page_h - by2) * self.scale_y
                cx2 = bx2 * self.scale_x
                cy2 = (page_h - by1) * self.scale_y
                self._draw_stamp_preview(cx1, cy1, cx2, cy2, label=f"Firma #{idx} (Pág. {p_idx + 1})", color="#059669")

    def _draw_stamp_preview(self, x1, y1, x2, y2, label="Firma", color="#0a3ed0"):
        self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline=color, width=2, dash=(6, 4), fill="#3b82f6", stipple="gray25"
        )
        self.canvas.create_text(
            x1 + 8, y1 + 14, text=f"🏷️ {label}", anchor=tk.W,
            font=("Segoe UI", 9, "bold"), fill="#001e6c"
        )

    def _on_canvas_left_click(self, event):
        """Agrega una firma en el punto donde se hizo clic."""
        if not self.doc or not self.current_file:
            return

        click_x = self.canvas.canvasx(event.x)
        click_y = self.canvas.canvasy(event.y)

        page = self.doc[self.current_page_idx]
        page_w = page.rect.width
        page_h = page.rect.height

        pdf_x = click_x / self.scale_x
        pdf_y = page_h - (click_y / self.scale_y)

        w = STAMP_WIDTH
        h = STAMP_HEIGHT
        x1 = int(round(max(10, min(page_w - w - 10, pdf_x - w / 2))))
        y1 = int(round(max(10, min(page_h - h - 10, pdf_y - h / 2))))
        x2 = int(round(x1 + w))
        y2 = int(round(y1 + h))

        boxes = self.current_manual_boxes
        boxes.append((self.current_page_idx, x1, y1, x2, y2))
        self.mode_var.set("click")
        self._render_current_page()
        self.status_lbl.configure(
            text=f"➕ Firma #{len(boxes)} agregada en página {self.current_page_idx + 1} (Coords PDF: {x1}, {y1}). Puedes agregar más en esta u otras páginas."
        )

    def _on_canvas_right_click(self, event):
        """Elimina una marca manual si se hace clic derecho sobre ella."""
        if not self.doc or not self.current_file:
            return

        click_x = self.canvas.canvasx(event.x)
        click_y = self.canvas.canvasy(event.y)
        page_h = self.doc[self.current_page_idx].rect.height

        pdf_x = click_x / self.scale_x
        pdf_y = page_h - (click_y / self.scale_y)

        boxes = self.current_manual_boxes
        for i in range(len(boxes) - 1, -1, -1):
            p_idx, bx1, by1, bx2, by2 = boxes[i]
            if p_idx == self.current_page_idx and bx1 <= pdf_x <= bx2 and by1 <= pdf_y <= by2:
                boxes.pop(i)
                self._render_current_page()
                self.status_lbl.configure(text=f"🗑️ Firma #{i + 1} eliminada. Quedan {len(boxes)} firma(s) en este documento.")
                return

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _undo_last_mark(self):
        boxes = self.current_manual_boxes
        if boxes:
            boxes.pop()
            self._render_current_page()
            self.status_lbl.configure(text=f"Última marca eliminada. Quedan {len(boxes)} marca(s).")

    def _clear_marks(self):
        boxes = self.current_manual_boxes
        boxes.clear()
        self._render_current_page()
        self.status_lbl.configure(text="Todas las marcas manuales de este documento fueron borradas.")

    def _prev_page(self):
        if self.doc and self.current_page_idx > 0:
            self.current_page_idx -= 1
            self._render_current_page()

    def _next_page(self):
        if self.doc and self.current_page_idx < len(self.doc) - 1:
            self.current_page_idx += 1
            self._render_current_page()

    def _on_mode_change(self):
        self._render_current_page()

    def _on_sign_action(self):
        if not self.file_list:
            messagebox.showwarning("Sin archivos", "Por favor abre al menos un archivo PDF para firmar.")
            return

        pin = self.ent_pin.get().strip() or None

        try:
            p12_path, password = get_credentials(pin=pin)
        except Exception as e:
            messagebox.showerror("PIN Requerido / Credenciales", f"{e}")
            self.ent_pin.focus_force()
            return

        t0 = time.time()
        success_files: List[Path] = []
        shared_boxes = self.current_manual_boxes if self.apply_all_var.get() else []

        meta = load_local_meta()
        logo_val = meta.get("logo_path") or None
        location_val = meta.get("default_location", "")

        for file_path in self.file_list:
            try:
                file_boxes = self.doc_manual_boxes.get(file_path, []) or shared_boxes
                if file_boxes:
                    coords_list = [(p_idx, float(x1), float(y1)) for (p_idx, x1, y1, _x2, _y2) in file_boxes]
                    out_file = sign_pdf_multi_boxes(
                        input_path=file_path,
                        output_path=None,
                        p12_path=p12_path,
                        password=password,
                        boxes=coords_list,
                        location=location_val,
                        suffix="-signed",
                        logo_path=logo_val,
                    )
                else:
                    out_file = sign_pdf_file(
                        input_path=file_path,
                        output_path=None,
                        p12_path=p12_path,
                        password=password,
                        page_spec="auto",
                        location=location_val,
                        suffix="-signed",
                        logo_path=logo_val,
                    )
                success_files.append(out_file)
            except Exception as e:
                messagebox.showerror("Error al firmar", f"Falló al firmar {file_path.name}:\n{e}")

        elapsed = time.time() - t0
        if success_files:
            names_preview = "\n".join(f"• {p.name}" for p in success_files[:6])
            if len(success_files) > 6:
                names_preview += f"\n... y {len(success_files) - 6} más."
            self.status_lbl.configure(
                text=f"✅ {len(success_files)} documento(s) firmado(s) exitosamente en {elapsed:.2f} s."
            )
            messagebox.showinfo(
                "Firma Completada",
                f"Se firmaron {len(success_files)} documento(s) en {elapsed:.2f} s:\n\n{names_preview}"
            )


def launch_gui(raw_args: Optional[List[str]] = None):
    args = list(raw_args) if raw_args is not None else sys.argv[1:]
    quick_mode = False
    file_args: List[str] = []

    for a in args:
        if a in ("--quick", "-q"):
            quick_mode = True
        else:
            file_args.append(a)

    if quick_mode:
        collected = _collect_explorer_multi_selection(file_args)
        if collected is None or not collected:
            return
        dlg = QuickSignDialog(collected)
        dlg.run()
        return

    collected = _collect_explorer_multi_selection(file_args) if file_args else []
    if collected is None:
        return

    root = tk.Tk()
    app = PDFSignerApp(root, initial_files=collected)
    root.mainloop()


if __name__ == "__main__":
    launch_gui()
