import importlib.util
import logging
import urllib.parse
from pathlib import Path

logger = logging.getLogger("zero_pos.impresora")

try:
    ESCPOS_OK = importlib.util.find_spec("escpos") is not None
except ValueError:
    ESCPOS_OK = "escpos" in __import__("sys").modules
if not ESCPOS_OK:
    logger.warning("python-escpos no instalado — impresión desactivada")

try:
    import bluetooth  # noqa: F401
    BT_OK = True
except ImportError:
    BT_OK = False


def limpiar_texto(texto) -> str:
    if not texto:
        return ""
    reemplazos = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ü': 'u',
        'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U', 'Ü': 'U',
        'ñ': 'n', 'Ñ': 'N', '°': ' ', '✅': 'OK',
        '📱': '', '📍': '', '⚠': '!', '🔔': '',
    }
    for orig, remp in reemplazos.items():
        texto = texto.replace(orig, remp)
    return texto.encode('ascii', 'ignore').decode('ascii')


def _get_printer(config_imp: dict):
    from escpos.printer import Network, Usb, File  # noqa: F401
    tipo = config_imp.get("tipo", "red")
    if tipo == "red":
        ip = config_imp.get("ip", "192.168.1.100")
        puerto = int(config_imp.get("puerto", 9100))
        return Network(ip, port=puerto, timeout=5)
    elif tipo == "usb":
        vid = int(config_imp.get("vendor_id", "0x04b8"), 16)
        pid = int(config_imp.get("product_id", "0x0202"), 16)
        return Usb(vid, pid)
    elif tipo == "archivo":
        ruta = config_imp.get("ruta", "/dev/usb/lp0")
        return File(ruta)
    raise ValueError(f"Tipo de impresora desconocido: {tipo}")


def _maps_url(pedido: dict) -> str:
    partes = [pedido.get("direccion") or ""]
    if pedido.get("depto"):
        partes.append(f"Depto {pedido['depto']}")
    if pedido.get("comuna"):
        partes.append(pedido["comuna"])
    partes.append("Chile")
    direccion = ", ".join(p for p in partes if p)
    return f"https://maps.google.com/?q={urllib.parse.quote(direccion)}"


def _generar_qr_bytes(url: str) -> bytes | None:
    try:
        import qrcode, io
        qr = qrcode.QRCode(version=2, box_size=5, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def imprimir_recibo(venta: dict, items: list, config: dict, config_imp: dict,
                    pedido: dict | None = None) -> dict:
    if not ESCPOS_OK:
        texto = _formatear_texto(venta, items, config, pedido)
        logger.info(f"[SIMULADO] Ticket venta #{venta['id']}")
        return {"ok": True, "simulado": True, "texto": texto}

    try:
        p = _get_printer(config_imp)
        nombre_negocio = limpiar_texto(config.get("nombre_negocio", "ZERO POS"))
        moneda = config.get("moneda", "CLP")
        SEP = "-" * 32

        p.set(align="center", bold=True, height=2, width=2)
        p.text(f"{nombre_negocio}\n")
        p.set(align="center", bold=False, height=1, width=1)

        if pedido:
            tipo = pedido.get("tipo", "")
            numero = pedido.get("numero", "")
            p.text(f"Pedido #{numero}\n")
            p.text(f"{limpiar_texto(str(venta.get('creado_en', '')))}\n")
            if tipo == "delivery":
                p.set(bold=True)
                p.text("DELIVERY\n")
            elif tipo == "retiro":
                p.set(bold=True)
                p.text("RETIRO EN LOCAL\n")
            p.set(bold=False)
            p.text(SEP + "\n")

            # Datos cliente
            p.set(align="left", bold=True)
            p.text("CLIENTE:\n")
            p.set(bold=False)
            p.text(f"{limpiar_texto(pedido.get('cliente_nombre', ''))}\n")
            if pedido.get("cliente_tel"):
                p.text(f"  {limpiar_texto(str(pedido['cliente_tel']))}\n")
            if tipo == "delivery":
                if pedido.get("direccion"):
                    p.text(f"  {limpiar_texto(pedido['direccion'])}\n")
                if pedido.get("depto"):
                    p.text(f"  Depto {limpiar_texto(str(pedido['depto']))}")
                    if pedido.get("comuna"):
                        p.text(f", {limpiar_texto(pedido['comuna'])}")
                    p.text("\n")
                elif pedido.get("comuna"):
                    p.text(f"  {limpiar_texto(pedido['comuna'])}\n")
                if pedido.get("referencia"):
                    p.text(f"  Ref: {limpiar_texto(pedido['referencia'])}\n")
            elif tipo == "retiro" and pedido.get("notas"):
                p.text(f"  Hora retiro: {limpiar_texto(str(pedido.get('hora_retiro', '')))}\n")
        else:
            p.text(f"Venta #{venta['id']}\n")
            p.text(f"{limpiar_texto(str(venta.get('creado_en', '')))}\n")

        p.text(SEP + "\n")
        p.set(align="left")
        for it in items:
            nombre = limpiar_texto(it.get("producto_nombre", it.get("nombre", "?")))[:20]
            subtotal = f"{it.get('subtotal', 0):,.0f}"
            cant = it.get("cantidad", 1)
            pu = it.get("precio_unit", it.get("precio", 0))
            p.text(f"{cant}x {nombre}\n")
            p.text(f"   {pu:,.0f} = {moneda} {subtotal}\n")
            if it.get("notas"):
                p.text(f"   *** {limpiar_texto(it['notas'])}\n")

        p.text(SEP + "\n")
        p.set(align="right", bold=True)
        p.text(f"TOTAL: {moneda} {venta['total']:,.0f}\n")
        p.set(align="center", bold=False)
        metodo = limpiar_texto(venta.get("metodo_pago", "efectivo")).upper()
        p.text(f"Pago: {metodo}\n")

        if pedido and pedido.get("notas"):
            p.text(SEP + "\n")
            p.set(align="left")
            p.text(f"Notas: {limpiar_texto(pedido['notas'])}\n")

        # QR ruta solo para delivery con dirección
        if pedido and pedido.get("tipo") == "delivery" and pedido.get("direccion"):
            url = _maps_url(pedido)
            qr_bytes = _generar_qr_bytes(url)
            p.text(SEP + "\n")
            p.set(align="center")
            if qr_bytes:
                try:
                    from PIL import Image
                    import io
                    img = Image.open(io.BytesIO(qr_bytes)).resize((200, 200))
                    p.image(img)
                except Exception:
                    p.text(f"{url[:42]}\n")
            else:
                p.text(f"{url[:42]}\n")

        p.text("\nGracias!\nZERO POS\n\n")
        p.cut()
        p.close()
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error impresora: {e}")
        return {"ok": False, "error": str(e)}


def test_conexion() -> dict:
    if not ESCPOS_OK:
        return {"ok": False, "error": "python-escpos no instalado"}
    try:
        from database import db_session
        with db_session() as conn:
            rows = conn.execute(
                "SELECT clave, valor FROM config WHERE clave LIKE 'impresora_%'"
            ).fetchall()
            cfg = {r["clave"]: r["valor"] for r in rows}
        config_imp = {
            "tipo": cfg.get("impresora_tipo", "red"),
            "ip": cfg.get("impresora_ip", "192.168.1.100"),
            "puerto": cfg.get("impresora_puerto", "9100"),
        }
        p = _get_printer(config_imp)
        p.text("ZERO POS - Test OK\n")
        p.cut()
        p.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _formatear_texto(venta: dict, items: list, config: dict,
                     pedido: dict | None = None) -> str:
    moneda = config.get("moneda", "CLP")
    nombre_negocio = limpiar_texto(config.get("nombre_negocio", "ZERO POS"))
    SEP = "=" * 32

    if pedido:
        tipo = pedido.get("tipo", "")
        tipo_label = {"delivery": "DELIVERY", "retiro": "RETIRO EN LOCAL"}.get(tipo, tipo.upper())
        lineas = [
            nombre_negocio,
            SEP,
            f"Pedido #{pedido.get('numero', '')}",
            f"Fecha: {limpiar_texto(str(venta.get('creado_en', '')))}",
            tipo_label,
            "-" * 32,
            "CLIENTE:",
            f"  {limpiar_texto(pedido.get('cliente_nombre', ''))}",
        ]
        if pedido.get("cliente_tel"):
            lineas.append(f"  Tel: {limpiar_texto(str(pedido['cliente_tel']))}")
        if tipo == "delivery":
            if pedido.get("direccion"):
                lineas.append(f"  {limpiar_texto(pedido['direccion'])}")
            if pedido.get("depto"):
                lineas.append(f"  Depto {limpiar_texto(str(pedido['depto']))}")
            if pedido.get("referencia"):
                lineas.append(f"  Ref: {limpiar_texto(pedido['referencia'])}")
            if pedido.get("direccion"):
                url = _maps_url(pedido)
                lineas += ["-" * 32, f"Ruta: {url}"]
    else:
        lineas = [
            nombre_negocio,
            SEP,
            f"Venta #{venta['id']}",
            f"Fecha: {limpiar_texto(str(venta.get('creado_en', '')))}",
        ]

    lineas.append("-" * 32)
    for it in items:
        nombre = limpiar_texto(it.get("producto_nombre", it.get("nombre", "?")))
        lineas.append(f"{nombre}")
        pu = it.get("precio_unit", it.get("precio", 0))
        lineas.append(f"  {it.get('cantidad',1)} x {pu:,.0f} = {moneda} {it.get('subtotal',0):,.0f}")
        if it.get("notas"):
            lineas.append(f"  *** {limpiar_texto(it['notas'])}")

    lineas += [
        "-" * 32,
        f"TOTAL: {moneda} {venta['total']:,.0f}",
        f"Pago: {limpiar_texto(venta.get('metodo_pago', 'efectivo')).upper()}",
    ]

    if pedido and pedido.get("notas"):
        lineas += ["-" * 32, f"Notas: {limpiar_texto(pedido['notas'])}"]

    lineas.append("")
    lineas.append("Gracias!")
    return "\n".join(lineas)
