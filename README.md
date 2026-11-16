# pdf-crypto-signer

Herramienta CLI y GUI en Python para firmar documentos PDF criptográficamente (estándar **PAdES / PKCS#12** mediante `pyHanko`) con estampa visual y código QR de verificación.

Compatible con **cualquier certificado electrónico estándar `.p12` / `.pfx`** (incluidos certificados emitidos por entidades acreditadas de Ecuador como Security Data, BCE o ANF, entre otros).

---

## Características principales

- **Firma criptográfica real (PAdES / SHA-256):** Firmas incrementales compatibles con Adobe Acrobat, Chrome, Edge y validadores oficiales sin invalidar firmas previas.
- **Estampa QR limpia y configurable:** Código QR de alta definición generado dinámicamente con el nombre del titular extraído del certificado X.509 (opcionalmente puedes incrustar tu propio logo PNG en el centro).
- **Visor gráfico interactivo (GUI):** Selecciona múltiples PDFs y haz clic exactamente donde quieres estampar una o varias firmas en distintas páginas.
- **Modo automático inteligente (`--page last` / `auto`):** Busca dinámicamente el nombre del titular o palabras clave de firma al final del documento evitando firmar sobre la carátula.
- **Almacenamiento seguro de credenciales:** Usa el almacén del sistema (`keyring`, ej. Windows Credential Manager) y almacena el PIN opcional como hash `PBKDF2-HMAC-SHA256` con sal.
- **Integración con Explorador de Windows (opcional):** Menú contextual de clic derecho (*Firma Rápida* y *Visor de Firma*) sin requerir permisos de administrador.

---

## Instalación

Requiere **Python 3.10 o superior**.

```bash
git clone https://github.com/jcsolanoj/pdf-crypto-signer.git
cd pdf-crypto-signer
pip install .
```

Para desarrollo y pruebas:

```bash
pip install -e ".[dev]"
pytest
```

---

## Configuración inicial

Registra tu certificado `.p12` / `.pfx`, contraseña, PIN opcional, logo opcional y ubicación por defecto:

```bash
firmar-pdf --setup
```

*(Opcional en Windows)* Registra el menú contextual de clic derecho sobre archivos `.pdf`:

```bash
firmar-pdf --install-context-menu
```

Para desinstalarlo en cualquier momento:

```bash
firmar-pdf --uninstall-context-menu
```

> **Nota:** `--install-context-menu` registra en `HKCU` la ruta del intérprete Python activo. Si instalas dentro de un `venv`, mantén ese entorno en la misma ruta.

---

## Uso

### 1. Interfaz gráfica (Visor interactivo)

Ejecutar sin argumentos o con `--gui`:

```bash
firmar-pdf
firmar-pdf --gui documento.pdf
```

### 2. Línea de comandos (CLI)

Firmar un documento buscando un texto específico o usando una posición predefinida:

```bash
firmar-pdf -i contrato.pdf --pos bottom-right
firmar-pdf -i contrato.pdf --search-text "Nombre Apellido" --offset "0,10"
```

Firmar todos los PDFs de una carpeta y guardarlos en otra:

```bash
firmar-pdf -i ./documentos/ -o ./firmados/ --page last
```

Personalizar URL del QR, motivo, ubicación o logo central:

```bash
firmar-pdf -i acta.pdf --verify-url "https://ejemplo.com/verificar" --reason "Aprobado" --location "Quito" --logo ./mi_logo.png
```

Por defecto, los archivos firmados se guardan junto al original con el sufijo `-signed.pdf` (por ejemplo, `contrato-signed.pdf`). Si el archivo ya existe, se genera automáticamente `contrato-signed_1.pdf` para no sobrescribir documentos previos.

En scripts automatizados puedes autorizar el PIN mediante la variable de entorno `FIRMA_PDF_PIN` o el argumento `--pin`.

---

## Estructura del proyecto

```text
pdf-crypto-signer/
├── firma_pdf/
│   ├── __init__.py
│   ├── cert_utils.py          # Carga y validación de certificados .p12/.pfx
│   ├── cli.py                 # Punto de entrada CLI (firmar-pdf)
│   ├── config.py              # Almacén seguro de credenciales (keyring + PBKDF2)
│   ├── context_menu.py        # Menú contextual de Windows (HKCU)
│   ├── coordinates.py         # Búsqueda dinámica de texto y cálculo de cajas PDF
│   ├── gui.py                 # Visor Tkinter multi-documento y diálogo rápido
│   ├── signer.py              # Motor de firmado incremental en memoria (pyHanko)
│   └── stamp.py               # Estampa visual y generador QR configurable
├── tests/
│   └── test_signer.py         # Suite de pruebas automatizadas
├── .gitignore
├── LICENSE
├── pyproject.toml
└── README.md
```

---

## Licencia

Distribuido bajo licencia MIT. Consulta [LICENSE](LICENSE) para más detalles.
