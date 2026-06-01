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
        gris = ImageEnhance.Contrast(gris).enhance(2.0)
        gris = gris.filter(ImageFilter.SHARPEN)
        w, h = gris.size
        if w < 1000:
            gris = gris.resize((w * 2, h * 2), _PIL.LANCZOS)

        try:
            return pytesseract.image_to_string(gris, lang="spa", config="--oem 3 --psm 6")
        except Exception:
            return pytesseract.image_to_string(gris, config="--oem 3 --psm 6")
    except ImportError:
        logger.warning("pytesseract no instalado")
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
            timeout=90,
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


def parsear_heuristico(texto: str) -> dict:
    """Fallback regex cuando TinyLlama no está disponible."""
    datos: dict = {
        "proveedor": {"nombre": None, "rut": None, "vendedor_nombre": None, "vendedor_telefono": None},
        "folio": None,
        "fecha": None,
        "total": None,
        "productos": [],
    }

    folio_m = re.search(r"(?:N[°º]|Folio|Número)\s*:?\s*(\d+)", texto, re.IGNORECASE)
    if folio_m:
        datos["folio"] = folio_m.group(1)

    fecha_m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", texto)
    if fecha_m:
        d, mo, y = fecha_m.group(1), fecha_m.group(2), fecha_m.group(3)
        if len(y) == 2:
            y = "20" + y
        datos["fecha"] = f"{y}-{mo.zfill(2)}-{d.zfill(2)}"

    total_m = re.search(r"(?:Total|TOTAL)\s*:?\s*\$?\s*([\d\.,]+)", texto)
    if total_m:
        val = total_m.group(1).replace(".", "").replace(",", "")
        try:
            datos["total"] = int(val)
        except ValueError:
            pass

    rut_m = re.search(r"\b(\d{1,2}[.\d]*\d{3}-[\dkK])\b", texto)
    if rut_m:
        datos["proveedor"]["rut"] = rut_m.group(1)

    # Intentar extraer líneas de productos (cantidad · descripción · precio)
    for linea in texto.split("\n"):
        linea = linea.strip()
        m = re.match(r"^(\d+)\s+(.{5,50}?)\s+(\d[\d\.]{2,})\s*$", linea)
        if m:
            try:
                precio = int(m.group(3).replace(".", ""))
                datos["productos"].append({
                    "nombre": m.group(2).strip(),
                    "codigo_barras": None,
                    "cantidad": int(m.group(1)),
                    "precio_unitario": precio,
                    "subtotal": precio * int(m.group(1)),
                })
            except ValueError:
                pass

    return datos


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
        logger.info("TinyLlama no disponible, usando heurística regex")
        datos = parsear_heuristico(texto)
        fuente = "heuristico"

    datos["_fuente"] = fuente
    datos["_texto_chars"] = len(texto)
    return {"ok": True, "datos": datos}
