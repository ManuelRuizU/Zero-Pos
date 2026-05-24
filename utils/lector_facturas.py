import io
import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("zero_pos.facturas")
BASE_DIR = Path(__file__).parent.parent


def procesar_pdf_factura(archivo, proveedor_id=None) -> dict:
    try:
        import pdfplumber
        contenido = archivo.read()
        texto = ""
        tablas = []

        with pdfplumber.open(io.BytesIO(contenido)) as pdf:
            for page in pdf.pages:
                texto += (page.extract_text() or "") + "\n"
                tbl = page.extract_table()
                if tbl:
                    tablas.extend(tbl)

        datos = _parsear_texto_factura(texto, tablas)

        guardar_pdf = BASE_DIR / "facturas_pdf"
        guardar_pdf.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        nombre_pdf = f"factura_{ts}.pdf"
        (guardar_pdf / nombre_pdf).write_bytes(contenido)

        from database import db_session
        with db_session() as conn:
            cur = conn.execute(
                """INSERT INTO facturas_proveedor
                   (proveedor_id, numero_factura, fecha_emision, total, archivo_pdf, datos_json)
                   VALUES (?,?,?,?,?,?)""",
                (
                    proveedor_id,
                    datos.get("numero_factura"),
                    datos.get("fecha_emision"),
                    datos.get("total"),
                    nombre_pdf,
                    json.dumps(datos, ensure_ascii=False),
                )
            )

        return {"ok": True, "factura_id": cur.lastrowid, "datos": datos}

    except ImportError:
        return {"ok": False, "error": "pdfplumber no instalado"}
    except Exception as e:
        logger.error(f"Error procesando factura: {e}")
        return {"ok": False, "error": str(e)}


def _parsear_texto_factura(texto: str, tablas: list) -> dict:
    import re
    datos = {
        "texto_completo": texto[:2000],
        "items": [],
        "total": None,
        "numero_factura": None,
        "fecha_emision": None,
    }

    folio_match = re.search(r"(?:N[°º]|Folio|Número)\s*:?\s*(\d+)", texto, re.IGNORECASE)
    if folio_match:
        datos["numero_factura"] = folio_match.group(1)

    fecha_match = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", texto)
    if fecha_match:
        datos["fecha_emision"] = fecha_match.group(0)

    total_match = re.search(r"(?:Total|TOTAL)\s*:?\s*\$?\s*([\d\.,]+)", texto)
    if total_match:
        val = total_match.group(1).replace(".", "").replace(",", "")
        try:
            datos["total"] = float(val)
        except ValueError:
            pass

    for fila in tablas:
        if fila and len(fila) >= 3:
            datos["items"].append({
                "descripcion": str(fila[0] or "").strip(),
                "cantidad": str(fila[1] or "").strip(),
                "precio": str(fila[-1] or "").strip(),
            })

    return datos
