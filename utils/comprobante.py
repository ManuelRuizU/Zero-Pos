import io
import logging
import urllib.parse
from datetime import datetime

logger = logging.getLogger("zero_pos.comprobante")


def generar_qr_comprobante(venta: dict) -> dict:
    texto = (
        f"ZERO POS\n"
        f"Venta #{venta['id']}\n"
        f"Total: ${venta['total']:,.0f}\n"
        f"Fecha: {venta.get('creado_en', '')}\n"
        f"Pago: {venta.get('metodo_pago', '').upper()}"
    )
    try:
        import qrcode
        import base64
        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(texto)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {"ok": True, "qr_base64": b64, "texto": texto}
    except ImportError:
        return {"ok": False, "error": "qrcode no instalado", "texto": texto}


def generar_link_whatsapp(telefono: str, venta: dict, items: list) -> str:
    lineas = [
        "🧾 *Comprobante de compra*",
        f"Venta #{venta['id']}",
        f"Fecha: {venta.get('creado_en', datetime.now().strftime('%Y-%m-%d %H:%M'))}",
        "",
        "*Detalle:*",
    ]
    for it in items:
        lineas.append(f"  • {it.get('nombre', '?')} x{it['cantidad']} — ${it['subtotal']:,.0f}")

    lineas += [
        "",
        f"*Total: ${venta['total']:,.0f}*",
        f"Pago: {venta.get('metodo_pago', '').upper()}",
        "",
        "_ZERO POS — Sin comisiones_",
    ]

    mensaje = "\n".join(lineas)
    tel = "".join(c for c in telefono if c.isdigit() or c == "+")
    if not tel.startswith("+"):
        tel = "+56" + tel.lstrip("0")

    return f"https://wa.me/{tel}?text={urllib.parse.quote(mensaje)}"
