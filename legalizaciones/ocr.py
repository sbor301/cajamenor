"""
Servicio de OCR para extracción automática de datos de facturas colombianas.
Soporta PDFs con texto embebido (pdfplumber) e imágenes (pytesseract).

Estrategia de parsing:
- Pre-procesado: elimina caracteres cuadruplicados de PDFs de operadores (Claro, etc.)
- NIT: primera ocurrencia de 'NIT XXXXXXXXX-X' — soporta guiones y puntos de miles
- Razón social: línea inmediatamente anterior al NIT del emisor
- Número factura: 'No. FExxxx', 'FExxxx', 'FVxxxx', 'FACTURA ... 3 - 292562732', etc.
- Fecha: DD/MM/YYYY o 'Mmm DD/YY' del campo 'Fecha del documento'
- Valor base: ÚLTIMO subtotal (post-descuento) o única aparición
- IVA: línea 'IVA (...%) $xxx' — cualquier porcentaje DIAN
- Total: 'Total a pagar / Total factura / TOTAL A PAGAR' — nunca la cabecera de tabla
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
    except Exception:
        return ""


def _texto_desde_imagen(file_obj):
    try:
        import pytesseract
        from PIL import Image, ImageFilter, ImageEnhance
        from django.conf import settings

        cmd = getattr(settings, "TESSERACT_CMD", None)
        data = getattr(settings, "TESSERACT_DATA", None)
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd

        config = "--psm 6"
        if data:
            config += f' --tessdata-dir "{data}"'

        file_obj.seek(0)
        img = Image.open(file_obj)
        img = img.convert("L")
        img = ImageEnhance.Contrast(img).enhance(2.0)
        img = img.filter(ImageFilter.SHARPEN)

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
        texto = _texto_desde_pdf(file_obj)
        if not texto.strip():
            texto = _texto_desde_imagen(file_obj)
    return texto


# ── Pre-procesado de texto ────────────────────────────────────────────────────

# Meses abreviados en español (facturas de operadores telefónicos)
_MESES_ES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def _normalizar_texto(texto: str) -> str:
    """
    Limpia artefactos comunes de PDFs mal generados:
    1. Caracteres cuadruplicados: 'CCCCUUUUDDDDAAAA' → 'CIUDAD'
       (PDFs de Claro/Comcel renderizan cada letra 4 veces)
    2. Colapsa líneas en blanco múltiples
    """
    # Paso 1: reducir letras, dígitos y signos repetidos 4 veces seguidas
    normalizado = re.sub(r'([A-ZÁÉÍÓÚÑa-záéíóúñ0-9:.\-])\1{3}', r'\1', texto)
    # Paso 2: colapsar más de 2 saltos de línea consecutivos
    normalizado = re.sub(r'\n{3,}', '\n\n', normalizado)
    return normalizado


# ── Utilidades numéricas ──────────────────────────────────────────────────────

def _limpiar_numero(valor: str) -> float | None:
    """
    Convierte número colombiano/americano a float.
    Soporta: '7.618.727,26', '252,365.00', '1234567.89', '$1.234,56'
    """
    v = valor.strip().lstrip("$").strip()
    # Formato colombiano: puntos miles + coma decimal → 7.618.727,26
    if re.search(r"\d\.\d{3}", v) and "," in v:
        v = v.replace(".", "").replace(",", ".")
    # Solo puntos de miles (sin parte decimal explícita): 7.618.727
    elif re.search(r"\d\.\d{3}", v):
        v = v.replace(".", "")
    # Coma como miles (formato americano): 252,365.00 → quitar coma
    elif "," in v and "." in v:
        v = v.replace(",", "")
    # Coma como decimal única: 805,939 → 805.939
    elif "," in v:
        v = v.replace(",", ".")
    v = re.sub(r"[^\d.]", "", v)
    try:
        return float(v) if v else None
    except ValueError:
        return None


def _es_nombre_empresa(linea: str) -> bool:
    """
    Heurística: ¿la línea parece ser un nombre de empresa?
    Condiciones: longitud 5–80, no empieza con dígito, sin URLs/emails,
    no es una dirección/teléfono, contiene al menos una letra.
    """
    l = linea.strip()
    if len(l) < 5 or len(l) > 80:
        return False
    if re.match(r"^\d", l):
        return False
    if re.search(r"[@/\\]", l):          # email, URL o path
        return False
    if re.match(
        r"^(calle|cra|carrera|av\.|avenida|tel|cel|\+57|ref|fecha|total|sub|iva|pago)",
        l, re.IGNORECASE
    ):
        return False
    if not re.search(r"[A-ZÁÉÍÓÚÑa-záéíóúñ]", l):
        return False
    return True


# ── Limpieza de NIT ───────────────────────────────────────────────────────────

def _limpiar_nit(raw: str) -> str:
    """Elimina puntos de miles del NIT: '800.153.993-7' → '800153993-7'"""
    partes = raw.replace("–", "-").split("-")
    if len(partes) == 2:
        numero = re.sub(r"[^\d]", "", partes[0])
        digito = partes[1].strip()
        return f"{numero}-{digito}"
    return re.sub(r"[^\d\-]", "", raw)


# ── Parser principal ──────────────────────────────────────────────────────────

def parsear_factura(texto: str) -> dict:
    resultado = {}
    # Normalizar antes de parsear (colapsa cuadruplicados, etc.)
    t = _normalizar_texto(texto)

    # ── 1. NIT del emisor ────────────────────────────────────────────────────
    # Soporta: 'NIT 901478875-8', 'NIT 800.153.993-7', 'NIT: 900750787-1'
    nit_m = re.search(
        r'\bNIT\s*:?\s*([\d.]{7,15}[-–]\d)\b',
        t, re.IGNORECASE
    )
    if nit_m:
        resultado["cedula_nit"] = _limpiar_nit(nit_m.group(1))
    else:
        # Fallback: patrón puro sin etiqueta NIT
        nit_raw = re.search(r'\b(\d{7,10})\s*[-–]\s*(\d)\b', t)
        if nit_raw:
            resultado["cedula_nit"] = f"{nit_raw.group(1)}-{nit_raw.group(2)}"

    # ── 2. Razón social del emisor ───────────────────────────────────────────
    # Línea inmediatamente anterior a la primera aparición de 'NIT XXXXXXXX-X'
    if nit_m:
        texto_antes = t[:nit_m.start()]
        lineas_antes = [l.strip() for l in texto_antes.split("\n") if l.strip()]
        for linea in reversed(lineas_antes):
            if _es_nombre_empresa(linea):
                # Si la línea tiene dos empresas juntas (ej: "COMCEL S.A. CLIENTE S.A.S.")
                # extraer solo la primera, hasta el primer sufijo legal seguido de otra empresa.
                m_split = re.search(
                    r'^(.*?(?:S\.A\.S|LTDA|S\.A\.|SAS|CORP|INC)\.?)\s+[A-ZÁÉÍÓÚÑ]',
                    linea, re.IGNORECASE
                )
                if m_split:
                    resultado["cliente_proveedor"] = m_split.group(1).strip()
                else:
                    resultado["cliente_proveedor"] = linea.strip()
                break

    # Fallback: label explícito
    if "cliente_proveedor" not in resultado:
        prov_m = re.search(
            r'(?:raz[oó]n\s+social|nombre\s+empresa|proveedor|expedido\s+por)\s*:?\s*'
            r'([A-ZÁÉÍÓÚÑ][^\n\r]{3,70})',
            t, re.IGNORECASE
        )
        if prov_m:
            resultado["cliente_proveedor"] = prov_m.group(1).strip()

    # ── 3. Número de factura ─────────────────────────────────────────────────
    fact_patterns = [
        # "No. FE3223"  /  "No FE3223"
        r'No\.?\s+([A-Z]{1,3}\d{2,8})\b',
        # "N° FE3223"  /  "Nº 3223"
        r'N[°º]\s*([A-Z]{0,3}\d{2,8})\b',
        # "FACTURA ELECTRÓNICA DE VENTA: 3 - 292562732"
        r'FACTURA\s+ELECTR[OÓ]NICA\s+DE\s+VENTA\s*[:\s]+(\d+\s*-\s*\d+)',
        # "FACTURA ELECTRÓNICA ... FE3223"
        r'FACTURA\s+ELECTR[OÓ]NICA[^\n]{0,60}\b([A-Z]{1,3}\d{2,8})\b',
        # Prefijos DIAN directos: FE, FV, FT, FC
        r'\b(F[EVTC]\d{3,8})\b',
        # Genérico con label
        r'(?:factura|fact\.?|invoice)\s*(?:de\s+venta\s*)?(?:electr[oó]nica\s*)?'
        r'[N°#nº\s]*[:\s]*([A-Z0-9]{1,5}[-]?\d{2,10})',
    ]
    for pat in fact_patterns:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            resultado["numero_factura"] = re.sub(r'\s+', '', m.group(1)).strip()
            break

    # ── 4. Fecha del documento ───────────────────────────────────────────────
    # Opción A: DD/MM/YYYY (formato DIAN estándar)
    fecha_m = re.search(r'\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})\b', t)
    if fecha_m:
        d, mes, y = fecha_m.groups()
        try:
            f = datetime(int(y), int(mes), int(d))
            resultado["fecha"] = f.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Opción B: "Abr 01/26" o "Abr 01/2026" (facturas de operadores)
    if "fecha" not in resultado:
        mes_abr = re.search(
            r'\b([A-Za-z]{3})\s+(\d{1,2})[/\-](\d{2,4})\b', t
        )
        if mes_abr:
            nombre_mes, dia, anio = mes_abr.groups()
            num_mes = _MESES_ES.get(nombre_mes.lower())
            if num_mes:
                anio_int = int(anio)
                if anio_int < 100:
                    anio_int += 2000
                try:
                    f = datetime(anio_int, num_mes, int(dia))
                    resultado["fecha"] = f.strftime("%Y-%m-%d")
                except ValueError:
                    pass

    # Opción C: YYYY-MM-DD (metadato generación/aprobación DIAN)
    if "fecha" not in resultado:
        fecha_iso = re.search(r'\b(20\d{2})-(0[1-9]|1[0-2])-(\d{2})\b', t)
        if fecha_iso:
            resultado["fecha"] = (
                f"{fecha_iso.group(1)}-{fecha_iso.group(2)}-{fecha_iso.group(3)}"
            )

    # ── 5. Subtotales (con o sin descuento) ──────────────────────────────────
    # Facturas con descuento tienen DOS subtotales:
    #   Subtotal  $7.618.727,26   ← bruto
    #   Descuento $3.376.940,90
    #   Subtotal  $4.241.786,36   ← base gravable  ← usamos ESTE
    # Si hay un solo subtotal, es la base gravable.
    # Nota: el primero puede estar en mitad de una línea (pdfplumber multi-columna);
    # el segundo suele iniciar su propia línea. Tomamos el último valor válido.
    subtotales_raw = re.findall(
        r'\bSubtotal\s*\$?\s*([\d.,]+)',
        t, re.IGNORECASE
    )
    subtotales_vals = [_limpiar_numero(s) for s in subtotales_raw]
    subtotales_vals = [v for v in subtotales_vals if v and v > 0]

    if subtotales_vals:
        resultado["valor_base"] = subtotales_vals[-1]  # el último = post-descuento

    # Fallback: etiquetas alternativas de base gravable
    if "valor_base" not in resultado:
        base_m = re.search(
            r'(?:base\s+gravable|base\s+iva|valor\s+base|neto|cargos\s+del\s+mes)'
            r'\s*[:\$]?[^\S\n]*([\d.,]+)',
            t, re.IGNORECASE
        )
        if base_m:
            v = _limpiar_numero(base_m.group(1))
            if v and v > 0:
                resultado["valor_base"] = v

    # ── 6. IVA ───────────────────────────────────────────────────────────────
    # Patrón DIAN: "IVA (19.00%) $805.939,41"
    # Capturamos TAMBIÉN el porcentaje del paréntesis
    iva_m = re.search(
        r'IVA\s*\(\s*([\d]+(?:[.,]\d+)?)\s*%\s*\)\s*\$?\s*([\d.,]+)',
        t, re.IGNORECASE
    )
    if iva_m:
        pct = round(float(iva_m.group(1).replace(",", ".")))
        if pct in (0, 5, 19):
            resultado["iva_porcentaje"] = pct
        v = _limpiar_numero(iva_m.group(2))
        if v and v > 0:
            resultado["iva"] = v
    else:
        # Fallback sin monto: solo porcentaje — "IVA 19%" / "IVA: 5%"
        pct_m = re.search(r'\bIVA\s*:?\s*(19|5|0)\s*%', t, re.IGNORECASE)
        if pct_m:
            resultado["iva_porcentaje"] = int(pct_m.group(1))

    # Fallback: "Total IVA $xxx" (facturas de operadores)
    if "iva" not in resultado:
        iva_fb = re.search(
            r'(?:total\s+iva|iva\s+total|iva|impuesto\s+iva)\s*[:\$]?\s*\$?\s*([\d.,]+)',
            t, re.IGNORECASE
        )
        if iva_fb:
            v = _limpiar_numero(iva_fb.group(1))
            if v and v > 0:
                resultado["iva"] = v

    # ── 7. Total a pagar ──────────────────────────────────────────────────────
    # CUIDADO: pdfplumber extrae la cabecera "... Descuento Total\n1 RailClamp..."
    # — el "Total" de la cabecera captura el "1" de la primera línea de ítems.
    # SOLUCIÓN A: etiquetas específicas primero (total a pagar, total factura, etc.)
    # SOLUCIÓN B: para el "Total $xxx" simple, exigir que no haya salto de línea
    #             entre "Total" y el monto.
    # SOLUCIÓN C: filtrar valores < 1.000 (los contadores de líneas siempre son pequeños).
    total_patterns = [
        # Alta prioridad — etiquetas inequívocas
        (r'(?:total\s+a\s+pagar|total\s+factura|valor\s+a\s+pagar|gran\s+total|valor\s+total)'
         r'[^\n$:]*\$?\s*([\d.,]+)'),
        # "Total $5.047.725,76" — $ en la misma línea
        r'(?:^|(?<=\n))[^\S\n]*Total[^\S\n]*\$[^\S\n]*([\d.,]+)',
        # "Total: 5.047.725,76" — : en la misma línea
        r'(?:^|(?<=\n))[^\S\n]*Total[^\S\n]*:[^\S\n]*([\d.,]+)',
    ]
    for pat in total_patterns:
        for tv in re.findall(pat, t, re.IGNORECASE | re.MULTILINE):
            v = _limpiar_numero(tv)
            if v and v > 1_000:
                resultado["valor_total"] = v
                break
        if "valor_total" in resultado:
            break

    # ── 8. Inferencia: base desde total e IVA ────────────────────────────────
    if "valor_base" not in resultado and "valor_total" in resultado and "iva" in resultado:
        inferida = round(resultado["valor_total"] - resultado["iva"], 2)
        if inferida > 0:
            resultado["valor_base"] = inferida

    return resultado


# ── Punto de entrada principal ────────────────────────────────────────────────

def analizar_archivo(file_obj, content_type: str) -> dict:
    texto = extraer_texto(file_obj, content_type)

    if not texto.strip():
        return {
            "ok": False,
            "mensaje": (
                "No se pudo extraer texto del archivo. "
                "Para imágenes, verifica que Tesseract OCR esté instalado. "
                "Para PDFs, el documento debe tener texto seleccionable."
            ),
            "campos": {},
        }

    campos = parsear_factura(texto)
    n = len(campos)
    confianza = "alta" if n >= 5 else ("media" if n >= 3 else "baja")

    return {
        "ok": True,
        "confianza": confianza,
        "campos_detectados": n,
        "campos": campos,
        "texto_raw": texto[:1200],
    }
