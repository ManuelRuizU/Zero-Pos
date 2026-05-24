import io
import json
import logging
import base64

logger = logging.getLogger("zero_pos.qr")


def generar_qr_producto(prod: dict) -> io.BytesIO:
    datos = json.dumps({
        "id": prod["id"],
        "nombre": prod["nombre"],
        "precio": prod["precio"],
        "barras": prod.get("codigo_barras"),
    }, ensure_ascii=False)

    try:
        import qrcode
        qr = qrcode.QRCode(version=2, box_size=8, border=3)
        qr.add_data(datos)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except ImportError:
        buf = io.BytesIO(b"")
        buf.seek(0)
        return buf


def generar_qr_pago(monto: float, concepto: str, config: dict) -> dict:
    nombre = config.get("nombre_negocio", "ZERO POS")
    moneda = config.get("moneda", "CLP")
    banco = config.get("banco_nombre", "")
    cuenta = config.get("banco_cuenta", "")
    rut = config.get("rut_negocio", "")

    if banco and cuenta:
        texto_pago = (
            f"Transferencia a {nombre}\n"
            f"RUT: {rut}\n"
            f"Banco: {banco}\n"
            f"Cuenta: {cuenta}\n"
            f"Monto: {moneda} {monto:,.0f}\n"
            f"Concepto: {concepto}"
        )
    else:
        texto_pago = f"{nombre}\nMonto: {moneda} {monto:,.0f}\n{concepto}"

    try:
        import qrcode
        qr = qrcode.QRCode(version=2, box_size=8, border=3)
        qr.add_data(texto_pago)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {"ok": True, "qr_base64": b64, "texto": texto_pago}
    except ImportError:
        return {"ok": False, "error": "qrcode no instalado", "texto": texto_pago}
