"""Punto de entrada de línea de comandos (CLI) y lanzador para la herramienta firmar-pdf."""

import os
import sys
import argparse
from pathlib import Path

from firma_pdf import __version__
from firma_pdf.config import interactive_setup, get_credentials, load_local_meta
from firma_pdf.coordinates import parse_offset, parse_coords
from firma_pdf.signer import sign_pdf_file, resolve_batch_files


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="firmar-pdf",
        description="Firma electrónica criptográfica de documentos PDF (PKCS#12 / PAdES) con estampa QR y visor GUI.",
        epilog=(
            "Ejemplos:\n"
            "  firmar-pdf --gui contrato.pdf\n"
            '  firmar-pdf -i contrato.pdf --search-text "Nombre Apellido" --pin 1234\n'
            "  firmar-pdf --install-context-menu\n"
            "  firmar-pdf -i ./facturas/ -o ./firmadas/ --page last\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--setup",
        action="store_true",
        help="Inicia el asistente interactivo para registrar el certificado .p12 en Windows Credential Manager.",
    )

    parser.add_argument(
        "-g", "--gui",
        action="store_true",
        help="Abre el visor gráfico interactivo para seleccionar la posición exacta de la firma con un clic.",
    )

    parser.add_argument(
        "--install-context-menu",
        action="store_true",
        help="Registra las opciones de clic derecho en el Explorador de Windows para firmar cualquier PDF.",
    )

    parser.add_argument(
        "--uninstall-context-menu",
        action="store_true",
        help="Elimina las opciones de clic derecho del Explorador de Windows.",
    )

    parser.add_argument(
        "-i", "--input",
        nargs="*",
        help="Ruta a uno o varios archivos PDF, patrón comodín o carpeta completa.",
    )

    parser.add_argument(
        "-o", "--output-dir",
        help="Directorio de destino opcional. Si no se indica, se guarda con el sufijo '-signed.pdf'.",
    )

    parser.add_argument(
        "-p", "--page",
        default="last",
        help="Página donde estampar la firma: 'first', 'last' (por defecto), 'all', o número de página (1, 2...).",
    )

    parser.add_argument(
        "--pos",
        default=None,
        choices=["bottom-right", "bottom-left", "bottom-center", "top-right", "top-left", "center"],
        help="Posición predefinida de la estampa visual (por defecto: bottom-right al firmar por CLI).",
    )

    parser.add_argument(
        "-s", "--search-text",
        help="Texto a buscar en el PDF para ubicar la firma automáticamente encima o sobre él.",
    )

    parser.add_argument(
        "-c", "--coords",
        help="Coordenadas manuales 'x,y' en sistema PDF (origen abajo a la izquierda).",
    )

    parser.add_argument(
        "--offset",
        help="Desplazamiento fino 'dx,dy' relativo al texto o posición (ej. '0,15' o '-10,5').",
    )

    parser.add_argument(
        "--pin",
        help="PIN para autorizar el firmado en scripts (también puede definirse vía variable FIRMA_PDF_PIN).",
    )

    parser.add_argument(
        "--reason",
        default="Firma Electrónica",
        help="Razón o motivo de la firma (por defecto: 'Firma Electrónica').",
    )

    parser.add_argument(
        "--location",
        default=None,
        help="Ubicación geográfica de la firma (opcional; si se omite usa la configurada en --setup).",
    )

    parser.add_argument(
        "--verify-url",
        help="URL o texto personalizado a codificar dentro del código QR.",
    )

    parser.add_argument(
        "--logo",
        help="Ruta opcional a un archivo PNG para incrustar en el centro del código QR.",
    )

    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()

    # 1. Asistente interactivo
    if args.setup:
        interactive_setup()
        sys.exit(0)

    # 2. Instalador / Desinstalador de menú contextual (solo Windows)
    if args.install_context_menu:
        from firma_pdf.context_menu import install_context_menu
        install_context_menu()
        sys.exit(0)

    if args.uninstall_context_menu:
        from firma_pdf.context_menu import uninstall_context_menu
        uninstall_context_menu()
        sys.exit(0)

    # 3. Lanzar interfaz gráfica interactiva si se pide --gui o si no se pasaron argumentos de entrada
    if args.gui or (not args.input and not args.search_text and not args.pos):
        from firma_pdf.gui import launch_gui
        launch_gui(raw_args=args.input or [])
        sys.exit(0)

    # 4. Validar archivos de entrada en modo CLI
    if not args.input:
        parser.print_help()
        print("\n[ERROR] Debes proporcionar al menos un archivo con -i/--input, o abrir el visor con --gui.")
        sys.exit(1)

    files = resolve_batch_files(args.input)
    if not files:
        print(f"\n[ERROR] No se encontraron archivos PDF válidos en: {args.input}")
        sys.exit(1)

    # 5. Obtener credenciales desde el almacén del sistema
    pin_value = args.pin if args.pin is not None else os.environ.get("FIRMA_PDF_PIN")
    try:
        p12_path, password = get_credentials(pin=pin_value)
    except Exception as e:
        print(f"\n[ERROR DE SEGURIDAD] {e}")
        sys.exit(1)

    meta = load_local_meta()
    location_val = args.location if args.location is not None else meta.get("default_location", "")
    logo_val = args.logo if args.logo is not None else (meta.get("logo_path") or None)

    # 6. Parsear desplazamientos y coordenadas
    try:
        offset_val = parse_offset(args.offset)
        coords_val = parse_coords(args.coords)
    except ValueError as ve:
        print(f"\n[ERROR] {ve}")
        sys.exit(1)

    print(f"\nIniciando proceso de firma para {len(files)} documento(s)...")

    success_count = 0
    fail_count = 0

    for file_path in files:
        try:
            out_file = sign_pdf_file(
                input_path=file_path,
                output_path=args.output_dir,
                p12_path=p12_path,
                password=password,
                page_spec=args.page,
                pos=args.pos,
                search_text=args.search_text,
                coords=coords_val,
                offset=offset_val,
                reason=args.reason,
                location=location_val,
                verify_url=args.verify_url,
                logo_path=logo_val,
            )
            print(f" [OK] Firmado exitosamente: {out_file.name}")
            print(f"      Ruta: {out_file}")
            success_count += 1
        except Exception as e:
            print(f" [ERROR] Falló al firmar {file_path.name}: {e}")
            fail_count += 1

    print("\n" + "-" * 50)
    print(f"Proceso finalizado: {success_count} exitoso(s), {fail_count} fallido(s).")
    print("-" * 50 + "\n")

    if fail_count > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
