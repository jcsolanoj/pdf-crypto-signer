"""Gestión segura de credenciales en el almacén del sistema vía keyring."""

import getpass
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from typing import Optional, Tuple
import keyring
from keyring.errors import NoKeyringError

from firma_pdf.cert_utils import get_cert_summary

SERVICE_NAME = "pdf-crypto-signer"
USER_P12_PATH = "p12_path"
USER_P12_PASS = "p12_password"
USER_P12_PIN_HASH = "p12_pin_hash"

CONFIG_DIR = Path.home() / ".pdf-crypto-signer"
CONFIG_FILE = CONFIG_DIR / "config.json"


def _hash_pin(pin: str, salt: Optional[bytes] = None) -> str:
    """Deriva un hash PBKDF2-HMAC-SHA256 con sal para el PIN."""
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 100_000)
    return f"{salt.hex()}${dk.hex()}"


def _verify_pin(pin: str, stored_hash: str) -> bool:
    """Verifica un PIN en tiempo constante contra su hash PBKDF2."""
    if "$" not in stored_hash:
        return hmac.compare_digest(pin, stored_hash)
    salt_hex, dk_hex = stored_hash.split("$", 1)
    expected = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(salt_hex), 100_000).hex()
    return hmac.compare_digest(expected, dk_hex)


def load_local_meta() -> dict:
    """Recupera metadatos no sensibles desde config.json."""
    if CONFIG_FILE.is_file():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_local_meta(p12_path: str, logo_path: Optional[str] = None, default_location: str = ""):
    """Guarda configuración local no sensible en config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass
    data = {
        "p12_path": p12_path,
        "logo_path": logo_path or "",
        "default_location": default_location,
    }
    CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def _get_local_meta_path() -> Optional[str]:
    """Recupera la ruta del .p12 desde config.json si existe."""
    return load_local_meta().get("p12_path")


def interactive_setup() -> None:
    """Flujo interactivo por consola para configurar la firma electrónica en el almacén del sistema."""
    print("\n" + "=" * 65)
    print("CONFIGURACIÓN DE FIRMA ELECTRÓNICA (pdf-crypto-signer)")
    print("Las credenciales se guardan de forma segura en el almacén del sistema.")
    print("=" * 65 + "\n")

    # 1. Solicitar ruta del archivo .p12
    raw_path = input("Ingresa la ruta absoluta de tu archivo de firma (.p12 o .pfx): ").strip()
    raw_path = raw_path.strip('"').strip("'")
    p12_path = Path(raw_path).resolve()

    if not p12_path.is_file():
        print(f"\n[ERROR] El archivo no existe: {p12_path}")
        sys.exit(1)

    # 2. Solicitar contraseña del .p12 de forma oculta
    password = getpass.getpass("Ingresa la contraseña de tu firma .p12: ")
    if not password:
        print("\n[ERROR] La contraseña no puede estar vacía.")
        sys.exit(1)

    # 3. Validar inmediatamente que el .p12 se abra con la clave antes de guardar
    print("\nVerificando certificado criptográfico...")
    try:
        summary = get_cert_summary(p12_path, password)
    except Exception as e:
        print(f"\n[ERROR CRÍTICO] No se pudo desbloquear el certificado:")
        print(f" -> {e}")
        print("Verifica que la contraseña o el archivo sean los correctos.")
        sys.exit(1)

    print("\n[OK] Certificado válido y verificado:")
    print(f"  • Titular (CN): {summary['signer_name']}")
    print(f"  • Emisor (CA):  {summary['issuer']}")
    print(f"  • Válido hasta: {summary['valid_to']}")

    # 4. Configurar PIN opcional para autorización rápida
    print("\n--- Autorización Rápida (PIN Opcional) ---")
    print("Puedes definir un PIN para autorizar firmas rápidamente desde CLI o scripts.")
    raw_pin = getpass.getpass("Ingresa un PIN (o presiona Enter para omitir): ").strip()

    pin_hash_to_store = _hash_pin(raw_pin) if raw_pin else None

    # 5. Opciones opcionales de personalización
    raw_logo = input("Ruta opcional a un logo PNG para el centro del QR (Enter para omitir): ").strip().strip('"').strip("'")
    logo_path = str(Path(raw_logo).resolve()) if raw_logo and Path(raw_logo).is_file() else ""
    default_location = input("Ubicación por defecto en la firma (ej. Ciudad, País; Enter para omitir): ").strip()

    # 6. Guardar en almacén del sistema vía keyring
    try:
        keyring.set_password(SERVICE_NAME, USER_P12_PATH, str(p12_path))
        keyring.set_password(SERVICE_NAME, USER_P12_PASS, password)
        if pin_hash_to_store:
            keyring.set_password(SERVICE_NAME, USER_P12_PIN_HASH, pin_hash_to_store)
        _save_local_meta(str(p12_path), logo_path=logo_path, default_location=default_location)
    except NoKeyringError:
        print("\n[ERROR] No hay un backend de keyring disponible en este sistema.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] No se pudo guardar en el almacén de credenciales: {e}")
        sys.exit(1)

    print("\n" + "=" * 65)
    print("¡CONFIGURACIÓN EXITOSA!")
    print(f"Servicio registrado: '{SERVICE_NAME}' en el almacén de credenciales.")
    if pin_hash_to_store:
        print("PIN configurado (almacenado con hash PBKDF2-SHA256) para autorizaciones rápidas.")
    print("Ahora puedes firmar documentos ejecutando 'firmar-pdf'.")
    print("=" * 65 + "\n")


def get_credentials(pin: Optional[str] = None) -> Tuple[Path, str]:
    """Recupera la ruta del .p12 y la contraseña desde el almacén del sistema.

    Si se configuró un PIN, valida que coincida contra su hash.
    """
    try:
        p12_path_str = keyring.get_password(SERVICE_NAME, USER_P12_PATH) or _get_local_meta_path()
        p12_pass = keyring.get_password(SERVICE_NAME, USER_P12_PASS)
        configured_pin_hash = keyring.get_password(SERVICE_NAME, USER_P12_PIN_HASH)
    except NoKeyringError as e:
        raise RuntimeError(
            "No hay un servicio keyring disponible en este entorno. "
            "Configura un almacén de secretos o pasa el certificado explícitamente."
        ) from e

    if not p12_path_str or not p12_pass:
        raise RuntimeError(
            "Firma electrónica no configurada. Ejecuta 'firmar-pdf --setup' manualmente en tu terminal."
        )

    p12_path = Path(p12_path_str)
    if not p12_path.is_file():
        raise FileNotFoundError(f"El archivo .p12 configurado no existe en: {p12_path}")

    # Verificar PIN si está configurado
    if configured_pin_hash:
        if pin is not None:
            if not _verify_pin(str(pin).strip(), configured_pin_hash):
                raise PermissionError("PIN de autorización incorrecto.")
        else:
            if sys.stdin.isatty():
                entered_pin = getpass.getpass("Ingresa tu PIN para firmar: ").strip()
                if not _verify_pin(entered_pin, configured_pin_hash):
                    raise PermissionError("PIN de autorización incorrecto.")
            else:
                raise PermissionError(
                    "Se requiere el argumento --pin (o variable FIRMA_PDF_PIN) para autorizar la firma."
                )

    return p12_path, p12_pass
