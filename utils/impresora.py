import logging
from pathlib import Path

logger = logging.getLogger("zero_pos.impresora")

try:
    from escpos.printer import Network, Usb, File
    ESCPOS_OK = True
except ImportError:
    ESCPOS_OK = False
    logger.warning("python-escpos no instalado — impresión desactivada")

try:
    import bluetooth
    BT_OK = True
except ImportError:
    BT_OK = False


def _get_printer(config_imp: dict):
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


def imprimir_recibo(venta: dict, items: list, config: dict, config_imp: dict) -> dict:
    if not ESCPOS_OK:
        texto = _formatear_texto(venta, items, config)
        logger.info(f"[SIMULADO] Ticket venta #{venta['id']}")
        return {"ok": True, "simulado": True, "texto": texto}

    try:
        p = _get_printer(config_imp)
        nombre_negocio = config.get("nombre_negocio", "ZERO POS")
        moneda = config.get("moneda", "CLP")

        p.set(align="center", bold=True, height=2, width=2)
        p.text(f"{nombre_negocio}\n")
        p.set(align="center", bold=False, height=1, width=1)
        p.text("-" * 32 + "\n")
        p.text(f"Venta #{venta['id']}\n")
        p.text(f"{venta['creado_en']}\n")
        p.text("-" * 32 + "\n")

        p.set(align="left")
        for it in items:
            nombre = it["producto_nombre"][:20]
            subtotal = f"{it['subtotal']:,.0f}"
            p.text(f"{nombre}\n")
            p.text(f"  {it['cantidad']} x {it['precio_unit']:,.0f} = {moneda} {subtotal}\n")

        p.text("-" * 32 + "\n")
        p.set(align="right", bold=True)
        p.text(f"TOTAL: {moneda} {venta['total']:,.0f}\n")
        p.set(align="center", bold=False)
        p.text(f"Pago: {venta['metodo_pago'].upper()}\n")
        p.text("\nGracias por su compra!\n")
        p.text("ZERO POS — Sin comisiones\n\n")
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


def _formatear_texto(venta: dict, items: list, config: dict) -> str:
    moneda = config.get("moneda", "CLP")
    lineas = [
        config.get("nombre_negocio", "ZERO POS"),
        "=" * 32,
        f"Venta #{venta['id']}",
        f"Fecha: {venta.get('creado_en', '')}",
        "-" * 32,
    ]
    for it in items:
        lineas.append(f"{it.get('producto_nombre', '?')}")
        lineas.append(f"  {it['cantidad']} x {it['precio_unit']:,.0f} = {moneda} {it['subtotal']:,.0f}")
    lineas += [
        "-" * 32,
        f"TOTAL: {moneda} {venta['total']:,.0f}",
        f"Pago: {venta['metodo_pago'].upper()}",
        "",
        "Gracias por su compra!",
    ]
    return "\n".join(lineas)
