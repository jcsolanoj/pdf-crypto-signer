"""Instalador y desinstalador del menú contextual de Windows para archivos PDF."""

import sys
from pathlib import Path


REG_BASE = r"Software\Classes\SystemFileAssociations\.pdf\shell"


def _require_windows():
    if sys.platform != "win32":
        raise RuntimeError("El menú contextual solo es compatible con Windows.")
    import winreg
    return winreg


def install_context_menu():
    """Registra las opciones de clic derecho para archivos .pdf en el Registro de Windows del usuario."""
    winreg = _require_windows()
    pythonw_path = Path(sys.executable).parent / "pythonw.exe"
    if not pythonw_path.is_file():
        pythonw_path = Path(sys.executable)

    # 1. Menú: Abrir en Visor de Firma (Manual / Múltiples)
    key_gui_path = f"{REG_BASE}\\FirmarPDF_GUI"
    cmd_gui = f'"{pythonw_path}" -m firma_pdf.gui "%1"'

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_gui_path) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Abrir en Visor de Firma (Manual / Múltiples)")
        winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, "imageres.dll,-102")

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{key_gui_path}\\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd_gui)

    # 2. Menú: Firma Ultrarápida (Sin abrir visor -> busca nombre y guarda -signed.pdf)
    key_auto_path = f"{REG_BASE}\\FirmarPDF_Auto"
    cmd_auto = f'"{pythonw_path}" -m firma_pdf.gui --quick "%1"'

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_auto_path) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "Firmar PDF (Firma Rápida)")
        winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, "shell32.dll,-16763")

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{key_auto_path}\\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd_auto)

    print("\n[OK] Menú contextual de Windows registrado exitosamente en el Explorador de Archivos.")
    print("Ahora puedes hacer clic derecho sobre cualquier archivo .pdf y seleccionar:")
    print("  • 'Firmar PDF (Firma Rápida)'")
    print("  • 'Abrir en Visor de Firma (Manual / Múltiples)'\n")


def uninstall_context_menu():
    """Elimina las entradas del menú contextual de Windows."""
    winreg = _require_windows()
    for sub in ["FirmarPDF_GUI\\command", "FirmarPDF_GUI", "FirmarPDF_Auto\\command", "FirmarPDF_Auto"]:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{REG_BASE}\\{sub}")
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[AVISO] No se pudo eliminar subclave {sub}: {e}")

    print("\n[OK] Menú contextual desinstalado correctamente del Registro de Windows.\n")
