import io
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger("zero_pos.facturas")
BASE_DIR = Path(__file__).parent.parent

TINYLLAMA_MODEL = "tinyllama"
OLLAMA_URL = "http://localhost:11434/api/generate"

# Prompt en formato TinyLlama-Chat
_PROMPT_TPL = """\
<|system|>
Eres un asistente que extrae datos de facturas comerciales en español. Responde SOLO con JSON válido, sin texto adicional ni markdown.
</s>
<|user|>
Del siguiente texto de factura extrae este JSON exacto:
{{
  "proveedor": {{"nombre": null, "rut": null, "vendedor_nombre": null, "vendedor_telefono": null}},
  "folio": null,
  "fecha": null,
  "total": 0,
  "productos": [
    {{"nombre": "descripcion", "codigo_barras": null, "cantidad": 1, "precio_unitario": 0, "subtotal": 0}}
  ]
}}
Reglas: total, precio_unitario y subtotal como enteros CLP sin decimales. fecha en formato YYYY-MM-DD. Si un campo no aparece usa null.

TEXTO:
{texto}
</s>
<|assistant|>
"""


def extraer_texto(archivo_bytes: bytes, content_type: str) -> str:
    """Extrae texto de PDF (pdfplumber) o imagen (Tesseract OCR)."""
    if "pdf" in content_type:
        return _texto_pdf(archivo_bytes)
    return _texto_ocr(archivo_bytes)


def _texto_pdf(data: bytes) -> str:
    try:
        import pdfplumber
        texto = ""
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                texto += (page.extract_text() or "") + "\n"
                tbl = page.extract_table()
                if tbl:
                    for fila in tbl:
                        if fila:
                            texto += " | ".join(str(c or "") for c in fila) + "\n"
        return texto.strip()
    except ImportError:
        logger.warning("pdfplumber no instalado")
        return ""
    except Exception as e:
        logger.error(f"_texto_pdf: {e}")
        return ""


def _texto_ocr(data: bytes) -> str:
    try:
        import numpy as np
        import pytesseract
        from PIL import Image as _PIL, ImageOps, ImageEnhance, ImageFilter

        img = _PIL.open(io.BytesIO(data))
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        if img.mode != "RGB":
            img = img.convert("RGB")

        gris = img.convert("L")
        gris = ImageEnhance.Contrast(gris).enhance(3.0)
        gris = gris.filter(ImageFilter.SHARPEN)

        # Escalar a 2000px de ancho si es menor
        w, h = gris.size
        if w < 2000:
            scale = 2000 / w
            gris = gris.resize((2000, int(h * scale)), _PIL.LANCZOS)

        # Binarización con numpy (umbral 128)
        arr = np.array(gris)
        arr = np.where(arr >= 128, 255, 0).astype(np.uint8)
        gris = _PIL.fromarray(arr)

        try:
            return pytesseract.image_to_string(gris, lang="spa", config="--oem 3 --psm 6")
        except Exception:
            return pytesseract.image_to_string(gris, config="--oem 3 --psm 6")
    except ImportError:
        logger.warning("pytesseract/numpy no instalado")
        return ""
    except Exception as e:
        logger.error(f"_texto_ocr: {e}")
        return ""


def llamar_tinyllama(texto: str) -> dict | None:
    """Llama a TinyLlama vía ollama y retorna el JSON extraído."""
    try:
        import requests as _req
        prompt = _PROMPT_TPL.format(texto=texto[:3000])
        resp = _req.post(
            OLLAMA_URL,
            json={"model": TINYLLAMA_MODEL, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.05, "num_predict": 1024}},
            timeout=30,
        )
        if resp.status_code != 200:
            logger.warning(f"Ollama HTTP {resp.status_code}: {resp.text[:200]}")
            return None
        raw = resp.json().get("response", "").strip()
        # Limpiar posibles bloques de markdown
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else parts[0]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        logger.warning(f"llamar_tinyllama: {e}")
        return None


def extraer_con_regex(texto: str) -> dict:
    """Fallback regex mejorado para facturas chilenas cuando TinyLlama no está disponible."""
    datos: dict = {
        "proveedor": {"nombre": None, "rut": None, "vendedor_nombre": None, "vendedor_telefono": None},
        "folio": None,
        "fecha": None,
        "total": None,
        "productos": [],
    }

    # Folio — soporta N°, Nº, FOLIO:, etc.
    folio_m = re.search(r"(?:N[°º\s]*|FOLIO[:\s]+)(\d+)", texto, re.IGNORECASE)
    if folio_m:
        datos["folio"] = folio_m.group(1)

    # Fecha DD/MM/YYYY o DD-MM-YYYY
    fecha_m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", texto)
    if fecha_m:
        d, mo, y = fecha_m.group(1), fecha_m.group(2), fecha_m.group(3)
        if len(y) == 2:
            y = "20" + y
        datos["fecha"] = f"{y}-{mo.zfill(2)}-{d.zfill(2)}"

    # Total
    total_m = re.search(r"(?:Total|TOTAL)\s*:?\s*\$?\s*([\d\.,]+)", texto)
    if total_m:
        val = total_m.group(1).replace(".", "").replace(",", "")
        try:
            datos["total"] = int(val)
        except ValueError:
            pass

    # RUT chileno: 12.345.678-9 o 12-345-678-K
    rut_m = re.search(r"\d{1,2}[\.\-]\d{3}[\.\-]\d{3}[\-]\w", texto)
    if rut_m:
        datos["proveedor"]["rut"] = rut_m.group(0)

    # Productos: código · descripción · cantidad · precio_unitario
    # Formato facturas chilenas con columna de código alfanumérico
    for linea in texto.split("\n"):
        linea = linea.strip()
        # Línea con código de producto al inicio (ej: "ABC-123  Descripción largo  5  1.890")
        m = re.match(r"^([A-Z0-9\-/]+)\s+(.{5,50}?)\s+(\d+)\s+(\d[\d\.]+)\s*$", linea)
        if m:
            try:
                precio = int(m.group(4).replace(".", ""))
                cant = int(m.group(3))
                datos["productos"].append({
                    "nombre": m.group(2).strip(),
                    "codigo_barras": m.group(1).strip(),
                    "cantidad": cant,
                    "precio_unitario": precio,
                    "subtotal": precio * cant,
                })
                continue
            except ValueError:
                pass
        # Fallback: cantidad · descripción · precio (sin código)
        m2 = re.match(r"^(\d+)\s+(.{5,50}?)\s+(\d[\d\.]{2,})\s*$", linea)
        if m2:
            try:
                precio = int(m2.group(3).replace(".", ""))
                cant = int(m2.group(1))
                datos["productos"].append({
                    "nombre": m2.group(2).strip(),
                    "codigo_barras": None,
                    "cantidad": cant,
                    "precio_unitario": precio,
                    "subtotal": precio * cant,
                })
            except ValueError:
                pass

    return datos


# Alias para compatibilidad
parsear_heuristico = extraer_con_regex


def procesar_factura(archivo_bytes: bytes, content_type: str) -> dict:
    """
    Pipeline completo:
    1. Extrae texto (PDF→pdfplumber, imagen→OCR)
    2. Intenta TinyLlama vía ollama
    3. Fallback a heurística regex
    Retorna dict compatible con el modal de revisión del frontend.
    """
    texto = extraer_texto(archivo_bytes, content_type)
    if not texto.strip():
        return {"ok": False, "error": "No se pudo extraer texto del archivo"}

    logger.info(f"Texto extraído ({len(texto)} chars): {texto[:200]!r}")

    datos = llamar_tinyllama(texto)
    fuente = "tinyllama"

    if not datos:
        logger.info("TinyLlama no disponible, usando regex mejorado")
        datos = extraer_con_regex(texto)
        fuente = "heuristico"

    datos["_fuente"] = fuente
    datos["_texto_chars"] = len(texto)
    return {"ok": True, "datos": datos}
