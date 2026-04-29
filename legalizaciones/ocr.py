"""
Servicio de OCR para extracción automática de datos de facturas colombianas.
Soporta PDFs con texto embebido (pdfplumber) e imágenes (pytesseract).
"""
import re
from datetime import datetime


# ── Extracción de texto ───────────────────────────────────────────────────────

def _texto_desde_pdf(file_obj):
    try:
        import pdfplumber
        file_obj.seek(0)
        with pdfplumber.open(file_obj) as pdf:
            partes = [p.extract_text() or "" for p in pdf.pages]
        return "\n".join(partes)
    except Exception as e:
        return ""


def _texto_desde_imagen(file_obj):
    try:
        import pytesseract
        from PIL import Image, ImageFilter, ImageEnhance
        from django.conf import settings

        # Configurar ejecutable y carpeta de idiomas
        cmd = getattr(settings, "TESSERACT_CMD", None)
        data = getattr(settings, "TESSERACT_DATA", None)
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd

        config = "--psm 6"
        if data:
            config += f' --tessdata-dir "{data}"'

        file_obj.seek(0)
        img = Image.open(file_obj)

        # Pre-procesado para mejorar la legibilidad
        img = img.convert("L")                          # escala de grises
        img = ImageEnhance.Contrast(img).enhance(2.0)   # aumentar contraste
        img = img.filter(ImageFilter.SHARPEN)            # nitidez

        return pytesseract.image_to_string(img, lang="spa+eng", config=config)
    except ImportError:
        return ""
    except Exception:
        return ""


def extraer_texto(file_obj, content_type: str) -> str:
    ct = (content_type or "").lower()
    if "pdf" in ct:
        texto = _texto_desde_pdf(file_obj)
    elif any(x in ct for x in ("image", "jpg", "jpeg", "png", "tiff", "webp")):
        texto = _texto_desde_imagen(file_obj)
    else:
        # Intentar PDF primero, luego imagen
        texto = _texto_desde_pdf(file_obj)
        if not texto.strip():
            texto = _texto_desde_imagen(file_obj)
    return texto


# ── Parser de campos ──────────────────────────────────────────────────────────

def _limpiar_numero(valor: str) -> float | None:
    """Convierte '1.234.567,89' o '1234567.89' a float."""
    v = valor.strip()
    # Formato colombiano: puntos como miles, coma como decimal
    if re.search(r"\d\.\d{3}", v) and "," in v:
        v = v.replace(".", "").replace(",", ".")
    elif re.search(r"\d\.\d{3}", v):
        v = v.replace(".", "")
    else:
        v = v.replace(",", ".")
    v = re.sub(r"[^\d.]", "", v)
    try:
        return float(v)
    except ValueError:
        return None


def parsear_factura(texto: str) -> dict:
    resultado = {}
    t = texto

    # ── NIT / Cédula ─────────────────────────────────────────────────────────
    nit = re.search(
        r'\b(\d{6,10})\s*[-–]\s*(\d)\b',
        t
    )
    if nit:
        resultado["cedula_nit"] = f"{nit.group(1)}-{nit.group(2)}"
    else:
        nit2 = re.search(
            r'(?:nit|n\.i\.t\.?|c[eé]dula)\s*[:#]?\s*(\d[\d\s\-\.]{5,14}\d)',
            t, re.IGNORECASE
        )
        if nit2:
            resultado["cedula_nit"] = re.sub(r'\s', '', nit2.group(1))

    # ── Número de factura ─────────────────────────────────────────────────────
    fact = re.search(
        r'(?:factura|fact\.?|fv\s*n[oú°]?|fe\s*n[oú°]?|n[oú°]\s+factura|invoice)\s*[#:\s]*([A-Z0-9]{1,5}[-\s]?\d{2,10})',
        t, re.IGNORECASE
    )
    if fact:
        resultado["numero_factura"] = fact.group(1).strip()

    # ── Fecha ─────────────────────────────────────────────────────────────────
    # Formato: DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
    fecha = re.search(r'\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})\b', t)
    if fecha:
        d, m, y = fecha.groups()
        try:
            f = datetime(int(y), int(m), int(d))
            resultado["fecha"] = f.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # ── Razón social / Proveedor ──────────────────────────────────────────────
    prov = re.search(
        r'(?:raz[oó]n\s+social|nombre|proveedor|empresa|expedido\s+a|facturar\s+a)\s*:?\s*([A-ZÁÉÍÓÚÑ][^\n\r]{3,60})',
        t, re.IGNORECASE
    )
    if prov:
        resultado["cliente_proveedor"] = prov.group(1).strip()

    # ── Valores ───────────────────────────────────────────────────────────────
    # IVA
    iva_m = re.search(
        r'(?:iva|impuesto)\s*(?:\(?19\s*%\)?|\(?5\s*%\)?)?\s*[:\$]?\s*([\d.,]+)',
        t, re.IGNORECASE
    )
    if iva_m:
        v = _limpiar_numero(iva_m.group(1))
        if v and v > 0:
            resultado["iva"] = v

    # Subtotal / base gravable
    base_m = re.search(
        r'(?:subtotal|base\s+gravable|base\s+iva|valor\s+base|neto)\s*[:\$]?\s*([\d.,]+)',
        t, re.IGNORECASE
    )
    if base_m:
        v = _limpiar_numero(base_m.group(1))
        if v and v > 0:
            resultado["valor_base"] = v

    # Total a pagar (el mayor encontrado suele ser el total)
    totales = re.findall(
        r'(?:total\s+a\s+pagar|total\s+factura|gran\s+total|valor\s+total|total)\s*[:\$]?\s*([\d.,]+)',
        t, re.IGNORECASE
    )
    for tv in totales:
        v = _limpiar_numero(tv)
        if v and v > 0:
            resultado["valor_total"] = v
            break

    # Si tenemos total e IVA, inferir base
    if "valor_base" not in resultado and "valor_total" in resultado and "iva" in resultado:
        resultado["valor_base"] = round(resultado["valor_total"] - resultado["iva"], 2)

    return resultado


# ── Punto de entrada principal ────────────────────────────────────────────────

def analizar_archivo(file_obj, content_type: str) -> dict:
    texto = extraer_texto(file_obj, content_type)

    if not texto.strip():
        return {
            "ok": False,
            "mensaje": "No se pudo extraer texto del archivo. "
                       "Para imágenes, instala Tesseract OCR. "
                       "Para PDFs, el documento debe tener texto seleccionable.",
            "campos": {},
        }

    campos = parsear_factura(texto)
    confianza = "alta" if len(campos) >= 4 else ("media" if len(campos) >= 2 else "baja")

    return {
        "ok": True,
        "confianza": confianza,
        "campos_detectados": len(campos),
        "campos": campos,
        "texto_raw": texto[:800],
    }
