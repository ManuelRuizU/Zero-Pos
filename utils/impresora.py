import importlib.util
import logging
import os
import socket
import urllib.parse
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent


def _obtener_ip_local() -> str:
    """Lee ip_local desde config DB; si falla detecta en tiempo real."""
    try:
        from database import db_session
        with db_session() as conn:
            row = conn.execute("SELECT valor FROM config WHERE clave='ip_local'").fetchone()
        if row and row['valor'] and row['valor'] not in ('127.0.0.1', 'localhost'):
            return row['valor']
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return '192.168.1.1'

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

ANCHO = 42  # 80mm paper at 12cpi


def limpiar_texto(texto) -> str:
    if not texto:
        return ""
    reemplazos = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ü': 'u',
        'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U', 'Ü': 'U',
        'ñ': 'n', 'Ñ': 'N', '°': ' ', '✅': 'OK',
        '📱': '', '📍': '', '⚠': '!', '🔔': '',
        '═': '=', '─': '-', '━': '-', '│': '|',
        '┌': '+', '┐': '+', '└': '+', '┘': '+',
        '├': '+', '┤': '+', '┬': '+', '┴': '+', '┼': '+',
        '•': '*', '·': '.', '→': '->', '←': '<-',
        '✓': 'OK', '✗': 'X', '★': '*',
    }
    for orig, remp in reemplazos.items():
        texto = texto.replace(orig, remp)
    return texto.encode('ascii', 'ignore').decode('ascii')


def separador(tipo: str = 'simple', largo: int = ANCHO) -> str:
    if tipo == 'doble':
        return '=' * largo
    elif tipo == 'estrella':
        return '*' * largo
    return '-' * largo


def _clp(valor) -> str:
    """$18.000 (formato pesos chilenos sin decimales)."""
    return '$' + f"{int(round(float(valor or 0))):,}".replace(',', '.')


def _sep(c='=', n=ANCHO) -> str:
    return c * n


def _sep2(n=ANCHO) -> str:
    return '-' * n


def _linea_precio(nombre, precio, n=ANCHO) -> str:
    precio_str = _clp(precio)
    libre = n - len(precio_str)
    if len(nombre) >= libre:
        nombre = nombre[:libre - 1]
    return nombre.ljust(libre) + precio_str


def _hora_ticket(ts) -> str:
    try:
        if isinstance(ts, datetime):
            dt = ts
        else:
            dt = datetime.fromisoformat(str(ts).replace(' ', 'T'))
        h = dt.hour % 12 or 12
        ampm = "AM" if dt.hour < 12 else "PM"
        return f"{h}:{dt.minute:02d} {ampm}"
    except Exception:
        return str(ts or "")[:5]


def _fecha_ticket(ts) -> str:
    try:
        if isinstance(ts, datetime):
            dt = ts
        else:
            dt = datetime.fromisoformat(str(ts).replace(' ', 'T'))
        return dt.strftime("%d-%m-%y")
    except Exception:
        return str(ts or "")[:10]


def imprimir_logo(p) -> None:
    """Imprime el logo del negocio si existe static/negocio/logo_ticket.png."""
    logo_path = BASE_DIR / "static" / "negocio" / "logo_ticket.png"
    if not logo_path.exists():
        return
    try:
        from PIL import Image
        import io as _io
        img = Image.open(logo_path).convert("L")
        max_ancho = 384
        if img.width > max_ancho:
            ratio = max_ancho / img.width
            img = img.resize((max_ancho, int(img.height * ratio)), Image.LANCZOS)
        buf = _io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        p.set(align="center")
        p.image(buf)
        p.text("\n")
    except Exception as e:
        logger.debug(f"Error logo ticket: {e}")


def cortar_ticket(p, config: dict) -> None:
    """Corta el papel si impresora_autocorte=='1' (default). Modo FULL o PART."""
    if config.get("impresora_autocorte", "1") != "0":
        try:
            modo = config.get("impresora_corte_tipo", "FULL")
            if modo == "PART":
                p.cut(mode="PART")
            else:
                p.cut()
        except Exception as e:
            logger.debug(f"Impresora sin cortador: {e}")
            p.text("\n\n\n")
    else:
        p.text("\n\n\n")


def _get_printer(config_imp: dict):
    from escpos.printer import Network, Usb, File  # noqa: F401
    tipo = config_imp.get("tipo", "red")
    if tipo == "red":
        return Network(config_imp.get("ip", "192.168.1.100"),
                       port=int(config_imp.get("puerto", 9100)), timeout=5)
    elif tipo == "usb":
        vid = int(config_imp.get("vendor_id", "0x04b8"), 16)
        pid = int(config_imp.get("product_id", "0x0202"), 16)
        return Usb(vid, pid)
    elif tipo == "archivo":
        from escpos.printer import File
        return File(config_imp.get("ruta", "/dev/usb/lp0"))
    raise ValueError(f"Tipo de impresora desconocido: {tipo}")


def _maps_url(pedido: dict) -> str:
    partes = [pedido.get("direccion") or ""]
    if pedido.get("depto"):
        partes.append(f"Depto {pedido['depto']}")
    if pedido.get("comuna"):
        partes.append(pedido["comuna"])
    partes.append("Chile")
    return "https://maps.google.com/?q=" + urllib.parse.quote(", ".join(p for p in partes if p))


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


def imprimir_qr(p, contenido: str, size: int = 200, align: str = 'center') -> None:
    """Imprime QR siempre como imagen PNG. Nunca usa printer.qr() nativo."""
    try:
        import qrcode
        from PIL import Image
        import io

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=6,
            border=3,
        )
        qr.add_data(contenido)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white').convert('RGB')
        img = img.resize((size, size), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, 'PNG')
        buf.seek(0)

        p.set(align=align)
        p.image(buf)
        p.set(align='left')
    except Exception as e:
        logger.error(f"Error QR imagen: {e}")
        p.set(align='center')
        p.text(f"{contenido[:ANCHO]}\n")
        p.set(align='left')


# ── BOLETA CLIENTE ────────────────────────────────────────────────────────────

def imprimir_recibo(venta: dict, items: list, config: dict, config_imp: dict,
                    pedido: dict | None = None, fiado_info: dict | None = None) -> dict:
    texto = _formatear_texto(venta, items, config, pedido)

    if not ESCPOS_OK:
        logger.info(f"[SIMULADO] Ticket venta #{venta['id']}")
        return {"ok": True, "simulado": True, "texto": texto}

    try:
        p = _get_printer(config_imp)
        N = ANCHO
        SEP  = _sep('=', N)
        SEP2 = _sep2(N)

        nombre_neg   = limpiar_texto(config.get("nombre_negocio", "ZERO POS"))
        direccion_neg = limpiar_texto(config.get("direccion_negocio", ""))
        telefono_neg  = limpiar_texto(config.get("telefono_negocio", ""))
        whatsapp_neg  = limpiar_texto(config.get("whatsapp_negocio", ""))
        cajero        = limpiar_texto(venta.get("cajero", "Propietario"))

        creado_en = venta.get("creado_en", "")
        hora_str  = _hora_ticket(creado_en)
        fecha_str = _fecha_ticket(creado_en)

        p.text("\n\n\n")
        imprimir_logo(p)
        # ── CABECERA ──────────────────────────────────────────────
        p.set(align="center", bold=True, height=2, width=2)
        p.text(nombre_neg + "\n")
        p.set(bold=False, height=1, width=1)
        if direccion_neg:
            p.text(direccion_neg.center(N) + "\n")
        if telefono_neg:
            p.text(("Tel: " + telefono_neg).center(N) + "\n")
        if whatsapp_neg:
            p.text(("WhatsApp: " + whatsapp_neg).center(N) + "\n")
        p.text(SEP + "\n")

        # ── ENCABEZADO PEDIDO / VENTA ─────────────────────────────
        p.set(align="left")
        if pedido:
            cliente_n = limpiar_texto(pedido.get("cliente_nombre", ""))
            tipo = pedido.get("tipo", "local")
            p.text(f"Pedido: {cliente_n} - {hora_str}\n")
            p.text(f"Empleado: {cajero}\n")
            p.text(f"Terminal: {config.get('nombre_terminal', 'ZERO POS')}\n")
            p.text(SEP + "\n")

            # Bloque cliente
            receptor_n = limpiar_texto(pedido.get("receptor_nombre") or "")
            if receptor_n:
                p.text(f"Pedido de: {cliente_n}\n")
                if pedido.get("cliente_tel"):
                    p.text("  Tel: " + limpiar_texto(str(pedido["cliente_tel"])) + "\n")
                p.text(f"Entregar a: {receptor_n}\n")
                if pedido.get("receptor_tel"):
                    p.text("  Tel: " + limpiar_texto(str(pedido["receptor_tel"])) + "\n")
                if tipo == "delivery" and pedido.get("direccion"):
                    dir_full = limpiar_texto(pedido["direccion"])
                    if pedido.get("depto"):
                        dir_full += " Dpto " + limpiar_texto(str(pedido["depto"]))
                    if pedido.get("comuna"):
                        dir_full += ", " + limpiar_texto(pedido["comuna"])
                    p.text("  " + dir_full + "\n")
                    if pedido.get("referencia"):
                        p.text("  Ref: " + limpiar_texto(pedido["referencia"]) + "\n")
            else:
                p.text(f"Cliente: {cliente_n}\n")
                if tipo == "delivery" and pedido.get("direccion"):
                    dir_full = limpiar_texto(pedido["direccion"])
                    if pedido.get("depto"):
                        dir_full += " Dpto " + limpiar_texto(str(pedido["depto"]))
                    if pedido.get("comuna"):
                        dir_full += ", " + limpiar_texto(pedido["comuna"])
                    p.text(dir_full + "\n")
                    if pedido.get("referencia"):
                        p.text("Ref: " + limpiar_texto(pedido["referencia"]) + "\n")
                elif tipo == "retiro" and pedido.get("hora_retiro"):
                    p.text("Retiro: " + limpiar_texto(str(pedido["hora_retiro"])) + "\n")
                if pedido.get("cliente_tel"):
                    p.text(limpiar_texto(str(pedido["cliente_tel"])) + "\n")

            tipo_labels = {"delivery": "DELIVERY", "retiro": "RETIRO EN LOCAL", "local": "VENTA LOCAL"}
            p.text(SEP2 + "\n")
            p.set(align="center", bold=True)
            p.text(tipo_labels.get(tipo, tipo.upper()) + "\n")
            p.set(align="left", bold=False)
            p.text(SEP2 + "\n")
        else:
            p.text(f"Venta #{venta['id']} - {hora_str}\n")
            p.text(f"Empleado: {cajero}\n")
            p.text(f"Terminal: {config.get('nombre_terminal', 'ZERO POS')}\n")
            p.text(SEP + "\n")

        # ── ITEMS ─────────────────────────────────────────────────
        for it in items:
            nombre = limpiar_texto(it.get("producto_nombre", it.get("nombre", "?")))
            cant = it.get("cantidad", 1)
            subtotal = it.get("subtotal", 0)
            label = nombre if cant == 1 else f"{cant}x {nombre}"
            p.text(_linea_precio(label, subtotal, N) + "\n")
            if it.get("notas"):
                p.text("  *** " + limpiar_texto(it["notas"]) + "\n")

        # ── TOTAL ─────────────────────────────────────────────────
        p.text(SEP + "\n")
        p.set(bold=True)
        p.text(_linea_precio("TOTAL:", venta["total"], N) + "\n")
        p.set(bold=False)
        p.text("Pago: " + limpiar_texto(venta.get("metodo_pago", "efectivo")).capitalize() + "\n")

        if pedido and pedido.get("notas"):
            p.text(SEP + "\n")
            p.set(align="left")
            p.text("Notas: " + limpiar_texto(pedido["notas"]) + "\n")

        # ── QR RUTA ───────────────────────────────────────────────
        if pedido and pedido.get("tipo") == "delivery" and pedido.get("direccion"):
            url = _maps_url(pedido)
            p.text(SEP + "\n")
            imprimir_qr(p, url, size=180)

        # ── ZERO CREDIT ───────────────────────────────────────────
        if venta.get("metodo_pago") == "credito" and fiado_info:
            c_nombre = limpiar_texto(
                f"{fiado_info.get('nombre','')} {fiado_info.get('apellido','') or ''}"
            ).strip()
            qr_token   = fiado_info.get("qr_token", "")
            url_credit = f"http://{_obtener_ip_local()}:5000/credit/{qr_token}"
            compra     = int(fiado_info.get('monto', 0))
            deuda_ant  = int(fiado_info.get('deuda_antes', 0))
            deuda_tot  = int(fiado_info.get('deuda_despues', 0))
            limite     = int(fiado_info.get('limite_credito', 0))
            disponible = max(0, limite - deuda_tot)

            def _linea_r(label, monto, ancho=N):
                monto_str = _clp(monto)
                esp = max(1, ancho - len(label) - len(monto_str))
                return label + ' ' * esp + monto_str + "\n"

            p.text("\n")
            p.set(align="center")
            p.text(SEP + "\n")
            p.set(bold=True)
            p.text("PAGO EN CUENTA CORRIENTE\n")
            p.set(bold=False, align="left")
            p.text(SEP + "\n")
            p.text(f"Cliente: {c_nombre[:24]}\n")
            p.text(_linea_r("Esta compra:", compra))
            p.text(_linea_r("Deuda anterior:", max(0, deuda_ant)))
            p.set(bold=True)
            p.text(_linea_r("Deuda total:", deuda_tot))
            p.set(bold=False)
            p.text(_linea_r("Cupo disponible:", disponible))
            p.text(SEP2 + "\n\n")
            p.set(align="center")
            p.text("Escanea para ver tu cuenta:\n\n")
            imprimir_qr(p, url_credit, size=140)
            p.text("\n")
            p.text(SEP + "\n")
            p.set(align="left")

        # ── FOOTER ────────────────────────────────────────────────
        p.text(SEP + "\n")
        p.set(align="center")
        p.text("Gracias por preferirnos!".center(N) + "\n")
        num_display = ""
        if pedido:
            num_display = f"#{pedido.get('numero', '')}-{str(venta['id']).zfill(4)}"
        p.text(f"{fecha_str}  {hora_str}  {num_display}".center(N) + "\n")
        p.text(SEP + "\n")
        p.text("\n\n\n\n\n")
        cortar_ticket(p, config)
        p.close()
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error impresora: {e}")
        return {"ok": False, "error": str(e)}


# ── COMANDA COCINA ────────────────────────────────────────────────────────────

def imprimir_comanda(venta: dict, items: list, config: dict, config_imp: dict,
                     pedido: dict | None = None) -> dict:
    texto = _formatear_comanda_texto(venta, items, config, pedido)

    if not ESCPOS_OK:
        logger.info(f"[SIMULADO] Comanda venta #{venta['id']}")
        return {"ok": True, "simulado": True, "texto": texto}

    try:
        p = _get_printer(config_imp)
        N = ANCHO
        SEP  = _sep('=', N)
        SEP2 = _sep2(N)

        cajero    = limpiar_texto(venta.get("cajero", ""))
        creado_en = venta.get("creado_en", "")
        hora_str  = _hora_ticket(creado_en)
        fecha_str = _fecha_ticket(creado_en)

        p.text("\n\n\n")
        imprimir_logo(p)
        p.text(SEP + "\n")

        # ── NÚMERO PEDIDO GRANDE ──────────────────────────────────
        if pedido:
            num_display = f"#{pedido.get('numero', '')}-{str(venta['id']).zfill(3)}"
            cliente_n = limpiar_texto(pedido.get("cliente_nombre", ""))
            p.set(align="center", bold=True, height=2, width=2)
            p.text(num_display + "\n")
            p.set(bold=False, height=1, width=1)
            p.text((cliente_n + " - " + hora_str).center(N) + "\n")
        else:
            p.set(align="center", bold=True, height=2, width=2)
            p.text(f"#{venta['id']}" + "\n")
            p.set(bold=False, height=1, width=1)

        p.text(SEP + "\n")

        partes = [fecha_str]
        if cajero:
            partes.append(cajero)
        partes.append("ZERO")
        p.set(align="center")
        p.text("  |  ".join(partes).center(N) + "\n")

        # ── TIPO Y DIRECCIÓN ──────────────────────────────────────
        if pedido:
            tipo = pedido.get("tipo", "local")
            tipo_labels = {"delivery": "DELIVERY", "retiro": "RETIRO EN LOCAL", "local": "VENTA LOCAL"}
            p.text(SEP2 + "\n")
            p.set(align="center", bold=True)
            p.text(tipo_labels.get(tipo, tipo.upper()) + "\n")
            p.set(bold=False)
            p.text(SEP2 + "\n")
            if tipo == "delivery" and pedido.get("direccion"):
                p.set(align="left")
                dir_full = limpiar_texto(pedido["direccion"])
                if pedido.get("depto"):
                    dir_full += " Dpto " + limpiar_texto(str(pedido["depto"]))
                p.text(dir_full + "\n")
                if pedido.get("referencia"):
                    p.text("Ref: " + limpiar_texto(pedido["referencia"]) + "\n")

        # ── ITEMS ─────────────────────────────────────────────────
        p.set(align="left")
        for it in items:
            nombre = limpiar_texto(it.get("producto_nombre", it.get("nombre", "?")))
            cant = it.get("cantidad", 1)
            notas = it.get("notas", "")
            if notas:
                # Item de cocina con personalización → sin precio
                p.set(bold=True)
                p.text(f"{cant}x {nombre}\n")
                p.set(bold=False)
                p.text("   *** " + limpiar_texto(notas) + "\n\n")
            else:
                # Item sin notas (ej. Reparto, cargo extra) → mostrar precio
                subtotal = it.get("subtotal", 0)
                if subtotal:
                    p.text(_linea_precio(f"{cant}x {nombre}", subtotal, N) + "\n")
                else:
                    p.set(bold=True)
                    p.text(f"{cant}x {nombre}\n")
                    p.set(bold=False)

        if pedido and pedido.get("notas"):
            p.text(SEP2 + "\n")
            p.text("NOTA: " + limpiar_texto(pedido["notas"]) + "\n")

        p.text(SEP + "\n")
        p.text("\n\n\n\n\n")
        cortar_ticket(p, config)
        p.close()
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error comanda: {e}")
        return {"ok": False, "error": str(e)}


def enviar_crudo(config_imp: dict, texto: str, config: dict | None = None) -> dict:
    """Envía texto pre-formateado a la impresora. Usa socket directo para red, escpos para USB/archivo."""
    tipo = config_imp.get("tipo", "red")
    cfg = config or {}
    autocorte = cfg.get("impresora_autocorte", "1") != "0"
    corte_tipo = cfg.get("impresora_corte_tipo", "FULL")
    if tipo == "red":
        import socket as _sock
        ip = config_imp.get("ip", "192.168.1.100")
        puerto = int(config_imp.get("puerto", 9100))
        try:
            with _sock.create_connection((ip, puerto), timeout=5) as s:
                payload = texto.encode("latin-1", errors="replace")
                if autocorte:
                    CUT = b"\x1d\x56\x01" if corte_tipo == "PART" else b"\x1d\x56\x00"
                    s.sendall(payload + CUT)
                else:
                    s.sendall(payload)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    else:
        # Fallback escpos para USB/archivo
        if not ESCPOS_OK:
            return {"ok": False, "error": "python-escpos no instalado"}
        try:
            p = _get_printer(config_imp)
            p.text(texto)
            p.cut()
            p.close()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}


def estado_impresora(config_imp: dict) -> dict:
    """Verifica conectividad y estado de papel de la impresora."""
    tipo = config_imp.get("tipo", "red")
    resultado = {"conectada": False, "papel": "desconocido", "error": None}

    if tipo == "red":
        import socket as _sock
        ip = config_imp.get("ip", "192.168.1.100")
        puerto = int(config_imp.get("puerto", 9100))
        try:
            with _sock.create_connection((ip, puerto), timeout=3) as s:
                resultado["conectada"] = True
                # DLE EOT (1) — printer status (ESC/POS)
                try:
                    s.sendall(b"\x10\x04\x01")
                    s.settimeout(1)
                    resp = s.recv(1)
                    if resp:
                        b = resp[0]
                        # Bit 5: paper near-end; Bit 3: no paper
                        if b & 0x20:
                            resultado["papel"] = "poco"
                        elif b & 0x08:
                            resultado["papel"] = "sin_papel"
                        else:
                            resultado["papel"] = "ok"
                except Exception:
                    resultado["papel"] = "ok"  # si no responde al status, asumimos ok
        except Exception as e:
            resultado["error"] = str(e)
    elif ESCPOS_OK:
        try:
            p = _get_printer(config_imp)
            p.close()
            resultado["conectada"] = True
            resultado["papel"] = "ok"
        except Exception as e:
            resultado["error"] = str(e)

    return resultado


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
            "ip":   cfg.get("impresora_ip", "192.168.1.100"),
            "puerto": cfg.get("impresora_puerto", "9100"),
        }
        p = _get_printer(config_imp)
        p.text("ZERO POS - Test OK\n")
        p.cut()
        p.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── APERTURA DE TURNO ────────────────────────────────────────────────────────

def _formatear_apertura_turno(turno: dict, config: dict) -> str:
    import json as _json
    N    = ANCHO
    SEP  = _sep('=', N)
    SEP2 = _sep2(N)

    nombre_neg = limpiar_texto(config.get("nombre_negocio", "ZERO POS"))
    terminal   = limpiar_texto(config.get("nombre_terminal", "Caja 1"))
    cajero     = limpiar_texto(turno.get("cajero", ""))

    apertura_ts = turno.get("apertura") or turno.get("creado_en", "")
    try:
        fecha_str = f"{_fecha_ticket(apertura_ts)} {_hora_ticket(apertura_ts)}"
    except Exception:
        fecha_str = str(apertura_ts or "")[:16]

    fondo_inicial = int(turno.get("fondo_inicial") or 0)

    def lp(label, val):
        return _linea_precio(label, val, N)

    lineas = ["\n\n", SEP, nombre_neg.center(N), SEP,
              "APERTURA DE TURNO".center(N), SEP]
    lineas.append(f"Turno: #{turno.get('id', '')}")
    lineas.append(f"Terminal: {terminal}")
    if cajero:
        lineas.append(f"Cajero: {cajero}")
    if fecha_str:
        lineas.append(f"Fecha:    {fecha_str}")

    lineas += [SEP2, lp("Fondo inicial:", fondo_inicial)]

    denoms_raw = turno.get("denominaciones_apertura")
    if denoms_raw:
        try:
            denoms = _json.loads(denoms_raw) if isinstance(denoms_raw, str) else denoms_raw
            d_items = sorted(
                [(int(k), int(v)) for k, v in denoms.items() if int(v) > 0],
                key=lambda x: -x[0]
            )
            if d_items:
                lineas += [SEP2, "BILLETES Y MONEDAS".center(N), SEP2]
                for denom, cant in d_items:
                    label = f"{_clp(denom)} x {cant} ="
                    lineas.append(lp(label, denom * cant))
        except Exception:
            pass

    lineas += [SEP, "¡Listo para vender!".center(N), SEP, "\n\n\n\n\n"]
    return "\n".join(lineas)


def imprimir_apertura_turno(turno: dict, config: dict, config_imp: dict) -> dict:
    """Imprime el ticket de apertura de turno via enviar_crudo."""
    texto = _formatear_apertura_turno(turno, config)
    logger.info(f"Imprimiendo apertura turno #{turno.get('id')}")
    return enviar_crudo(config_imp, texto, config)


# ── CIERRE DE TURNO ───────────────────────────────────────────────────────────

def _formatear_cierre_turno(turno: dict, ventas_resumen: dict, config: dict) -> str:
    import json as _json
    N    = ANCHO
    SEP  = _sep('=', N)
    SEP2 = _sep2(N)

    nombre_neg    = limpiar_texto(config.get("nombre_negocio", "ZERO POS"))
    direccion_neg = limpiar_texto(config.get("direccion_negocio", ""))
    telefono_neg  = limpiar_texto(config.get("telefono_negocio", ""))
    terminal      = limpiar_texto(config.get("nombre_terminal", "Caja 1"))
    cajero        = limpiar_texto(turno.get("cajero", ""))

    def _ap(ts):
        try:
            return f"{_fecha_ticket(ts)} {_hora_ticket(ts)}"
        except Exception:
            return str(ts or "")[:16]

    apertura_str = _ap(turno.get("apertura") or turno.get("creado_en", ""))
    cierre_str   = _ap(turno.get("cierre", ""))

    efectivo      = int(ventas_resumen.get("efectivo", 0))
    tarjeta       = int(ventas_resumen.get("tarjeta", 0))
    transferencia = int(ventas_resumen.get("transferencia", 0))
    credito       = int(ventas_resumen.get("credito", 0))
    total_ventas  = int(ventas_resumen.get("total", 0))
    ventas_count  = int(ventas_resumen.get("ventas_count", 0))

    fondo_inicial = int(turno.get("fondo_inicial") or 0)
    fondo_final   = int(turno.get("fondo_final") or 0)
    ef_teorico    = fondo_inicial + efectivo   # fondo + cobros (reembolsos = 0)
    descuadre     = fondo_final - ef_teorico

    def lp(label, val):
        return _linea_precio(label, val, N)

    def lc(label, val):
        s = str(val)
        return label[:N - len(s)].ljust(N - len(s)) + s

    lineas = ["\n\n"]

    # 1. HEADER NEGOCIO
    lineas += [SEP, nombre_neg.center(N)]
    if direccion_neg:
        lineas.append(direccion_neg.center(N))
    if telefono_neg:
        lineas.append(telefono_neg.center(N))

    # 2. CIERRE DE TURNO — número, terminal, cajero
    lineas += [SEP, "CIERRE DE TURNO".center(N), SEP]
    lineas.append(f"Turno: #{turno.get('id', '')}")
    lineas.append(f"Terminal: {terminal}")
    if cajero:
        lineas.append(f"Cajero: {cajero}")

    # 3. APERTURA Y CIERRE
    if apertura_str:
        lineas.append(f"Apertura: {apertura_str}")
    if cierre_str:
        lineas.append(f"Cierre:   {cierre_str}")

    # 4. VENTAS DEL TURNO
    lineas += [SEP2, "VENTAS DEL TURNO".center(N), SEP2]
    lineas.append(lc("Transacciones:", ventas_count))
    lineas.append(lp("Ventas brutas:", total_ventas))
    lineas.append(lp("Reembolsos:", 0))
    lineas.append(lp("Descuentos:", 0))
    lineas.append(lp("Ventas netas:", total_ventas))
    lineas.append(SEP2)
    if efectivo:
        lineas.append(lp("Efectivo:", efectivo))
    if tarjeta:
        lineas.append(lp("Tarjeta:", tarjeta))
    if transferencia:
        lineas.append(lp("Transferencia:", transferencia))
    if credito:
        lineas.append(lp("Credito (fiado):", credito))

    # 5. CAJÓN DE EFECTIVO
    lineas += [SEP2, "CAJON DE EFECTIVO".center(N), SEP2]
    lineas.append(lp("Fondo inicial:", fondo_inicial))
    lineas.append(lp("Cobros efectivo:", efectivo))
    lineas.append(lp("Reembolsos efectivo:", 0))
    lineas.append(lp("Depositado:", 0))
    lineas.append(lp("Pagos/Salidas:", 0))
    lineas.append(lp("Efectivo teorico:", ef_teorico))
    lineas.append(lp("Efectivo real:", fondo_final))
    if descuadre == 0:
        lineas.append("CUADRE EXACTO OK".center(N))
    elif descuadre > 0:
        lineas.append(lp("SOBRANTE:", descuadre))
    else:
        lineas.append(lp("FALTANTE:", abs(descuadre)))

    # 6. BILLETES Y MONEDAS
    denoms_raw = turno.get("denominaciones_cierre")
    if denoms_raw:
        try:
            denoms = _json.loads(denoms_raw) if isinstance(denoms_raw, str) else denoms_raw
            d_items = sorted(
                [(int(k), int(v)) for k, v in denoms.items() if int(v) > 0],
                key=lambda x: -x[0]
            )
            if d_items:
                lineas += [SEP2, "BILLETES Y MONEDAS".center(N), SEP2]
                for denom, cant in d_items:
                    label = f"{_clp(denom)} x {cant} ="
                    lineas.append(lp(label, denom * cant))
        except Exception:
            pass

    # 7. FOOTER
    now = datetime.now()
    lineas += [
        SEP,
        f"{_fecha_ticket(now)}  {_hora_ticket(now)}".center(N),
        "ZERO POS".center(N),
        SEP,
        "\n\n\n\n\n",
    ]
    return "\n".join(lineas)


def imprimir_cierre_turno(turno: dict, ventas_resumen: dict,
                           config: dict, config_imp: dict) -> dict:
    """Imprime el ticket de cierre de turno via enviar_crudo."""
    texto = _formatear_cierre_turno(turno, ventas_resumen, config)
    logger.info(f"Imprimiendo cierre turno #{turno.get('id')}")
    return enviar_crudo(config_imp, texto, config)


# ── FORMATOS TEXTO (simulación / logs) ────────────────────────────────────────

def _formatear_texto(venta: dict, items: list, config: dict,
                     pedido: dict | None = None) -> str:
    N = ANCHO
    SEP  = '=' * N
    SEP2 = '-' * N

    nombre_neg    = limpiar_texto(config.get("nombre_negocio", "ZERO POS"))
    direccion_neg = limpiar_texto(config.get("direccion_negocio", ""))
    telefono_neg  = limpiar_texto(config.get("telefono_negocio", ""))
    whatsapp_neg  = limpiar_texto(config.get("whatsapp_negocio", ""))
    cajero        = limpiar_texto(venta.get("cajero", "Propietario"))
    creado_en     = venta.get("creado_en", "")
    hora_str      = _hora_ticket(creado_en)
    fecha_str     = _fecha_ticket(creado_en)

    lineas = [SEP, nombre_neg.center(N)]
    if direccion_neg:
        lineas.append(direccion_neg.center(N))
    if telefono_neg:
        lineas.append(("Tel: " + telefono_neg).center(N))
    if whatsapp_neg:
        lineas.append(("WhatsApp: " + whatsapp_neg).center(N))
    lineas.append(SEP)

    if pedido:
        cliente_n = limpiar_texto(pedido.get("cliente_nombre", ""))
        tipo = pedido.get("tipo", "local")
        receptor_n = limpiar_texto(pedido.get("receptor_nombre") or "")
        lineas += [
            f"Pedido: {cliente_n} - {hora_str}",
            f"Empleado: {cajero}",
            f"Terminal: {config.get('nombre_terminal', 'ZERO POS')}",
            SEP,
        ]
        if receptor_n:
            lineas.append(f"Pedido de: {cliente_n}")
            if pedido.get("cliente_tel"):
                lineas.append("  Tel: " + limpiar_texto(str(pedido["cliente_tel"])))
            lineas.append(f"Entregar a: {receptor_n}")
            if pedido.get("receptor_tel"):
                lineas.append("  Tel: " + limpiar_texto(str(pedido["receptor_tel"])))
            if tipo == "delivery" and pedido.get("direccion"):
                dir_full = limpiar_texto(pedido["direccion"])
                if pedido.get("depto"):
                    dir_full += " Dpto " + limpiar_texto(str(pedido["depto"]))
                if pedido.get("comuna"):
                    dir_full += ", " + limpiar_texto(pedido["comuna"])
                lineas.append("  " + dir_full)
                if pedido.get("referencia"):
                    lineas.append("  Ref: " + limpiar_texto(pedido["referencia"]))
        else:
            lineas.append(f"Cliente: {cliente_n}")
            if tipo == "delivery" and pedido.get("direccion"):
                dir_full = limpiar_texto(pedido["direccion"])
                if pedido.get("depto"):
                    dir_full += " Dpto " + limpiar_texto(str(pedido["depto"]))
                if pedido.get("comuna"):
                    dir_full += ", " + limpiar_texto(pedido["comuna"])
                lineas.append(dir_full)
                if pedido.get("referencia"):
                    lineas.append("Ref: " + limpiar_texto(pedido["referencia"]))
            elif tipo == "retiro" and pedido.get("hora_retiro"):
                lineas.append("Retiro: " + limpiar_texto(str(pedido["hora_retiro"])))
            if pedido.get("cliente_tel"):
                lineas.append(limpiar_texto(str(pedido["cliente_tel"])))
        tipo_labels = {"delivery": "DELIVERY", "retiro": "RETIRO EN LOCAL", "local": "VENTA LOCAL"}
        lineas += [SEP2, tipo_labels.get(tipo, tipo.upper()).center(N), SEP2]
    else:
        lineas += [
            f"Venta #{venta['id']} - {hora_str}",
            f"Empleado: {cajero}",
            f"Terminal: {config.get('nombre_terminal', 'ZERO POS')}",
            SEP,
        ]

    for it in items:
        nombre = limpiar_texto(it.get("producto_nombre", it.get("nombre", "?")))
        cant = it.get("cantidad", 1)
        precio_unit = it.get("precio_unit", 0)
        subtotal = it.get("subtotal", 0)
        if cant == 1:
            lineas.append(_linea_precio(nombre, subtotal, N))
        else:
            lineas.append(_linea_precio(f"{cant}x {nombre}", subtotal, N))
            lineas.append(f"  {cant} x {_clp(precio_unit)}".ljust(N))
        if it.get("notas"):
            lineas.append("  *** " + limpiar_texto(it["notas"]))

    lineas += [
        SEP,
        _linea_precio("TOTAL:", venta["total"], N),
        "Pago: " + limpiar_texto(venta.get("metodo_pago", "efectivo")).capitalize(),
    ]

    if pedido and pedido.get("notas"):
        lineas += [SEP, "Notas: " + limpiar_texto(pedido["notas"])]

    if pedido and pedido.get("tipo") == "delivery" and pedido.get("direccion"):
        lineas += [SEP, _maps_url(pedido)[:N]]

    if venta.get("metodo_pago") == "credito":
        lineas += [
            SEP,
            "ZERO CREDIT".center(N),
            SEP,
            "Pago en cuenta corriente".center(N),
            "",
        ]

    from database import db_session
    try:
        with db_session() as conn:
            row = conn.execute(
                "SELECT valor FROM config WHERE clave='mensaje_ticket'"
            ).fetchone()
            mensaje = row["valor"] if row and row["valor"] else "Gracias por preferirnos!"
    except Exception:
        mensaje = "Gracias por preferirnos!"

    num_display = ""
    if pedido:
        num_display = f"#{pedido.get('numero', '')}-{str(venta['id']).zfill(4)}"
    lineas += [
        SEP,
        limpiar_texto(mensaje).center(N),
        f"{fecha_str}  {hora_str}  {num_display}".center(N),
        SEP,
        "", "", "", "", "",
    ]
    return "\n\n\n" + "\n".join(lineas)


def _formatear_comanda_texto(venta: dict, items: list, config: dict,
                              pedido: dict | None = None) -> str:
    N = ANCHO
    SEP  = '=' * N
    SEP2 = '-' * N

    cajero    = limpiar_texto(venta.get("cajero", ""))
    creado_en = venta.get("creado_en", "")
    hora_str  = _hora_ticket(creado_en)
    fecha_str = _fecha_ticket(creado_en)

    lineas = [SEP]
    if pedido:
        num_display = f"#{pedido.get('numero', '')}-{str(venta['id']).zfill(3)}"
        cliente_n = limpiar_texto(pedido.get("cliente_nombre", ""))
        lineas += [num_display.center(N), (cliente_n + " - " + hora_str).center(N)]
    else:
        lineas.append(f"#{venta['id']}".center(N))

    partes = [fecha_str]
    if cajero:
        partes.append(cajero)
    partes.append("ZERO")
    lineas += [SEP, "  |  ".join(partes).center(N)]

    if pedido:
        tipo = pedido.get("tipo", "local")
        tipo_labels = {"delivery": "DELIVERY", "retiro": "RETIRO EN LOCAL", "local": "VENTA LOCAL"}
        lineas += [SEP2, tipo_labels.get(tipo, tipo.upper()).center(N), SEP2]
        if tipo == "delivery" and pedido.get("direccion"):
            dir_full = limpiar_texto(pedido["direccion"])
            if pedido.get("depto"):
                dir_full += " Dpto " + limpiar_texto(str(pedido["depto"]))
            lineas.append(dir_full)

    for it in items:
        nombre = limpiar_texto(it.get("producto_nombre", it.get("nombre", "?")))
        cant = it.get("cantidad", 1)
        notas = it.get("notas", "")
        if notas:
            lineas += [f"{cant}x {nombre}", "   *** " + limpiar_texto(notas), ""]
        else:
            subtotal = it.get("subtotal", 0)
            if subtotal:
                lineas.append(_linea_precio(f"{cant}x {nombre}", subtotal, N))
            else:
                lineas.append(f"{cant}x {nombre}")

    if pedido and pedido.get("notas"):
        lineas += [SEP2, "NOTA: " + limpiar_texto(pedido["notas"])]

    lineas += [SEP, "", "", "", "", ""]
    return "\n\n\n" + "\n".join(lineas)


def imprimir_tarjeta_credit(cliente: dict, config: dict) -> dict:
    """Imprime tarjeta de membresía ZERO CREDIT con QR portal y QR WiFi opcional."""
    config_imp = {
        "tipo": config.get("impresora_tipo", "red"),
        "ip": config.get("impresora_ip", ""),
        "puerto": config.get("impresora_puerto", "9100"),
    }

    ip = _obtener_ip_local()
    url_portal = f"http://{ip}:5000/credit/{cliente.get('qr_token', '')}"
    N = ANCHO

    # Texto plano para fallback cuando no hay escpos
    nombre_c = limpiar_texto(f"{cliente.get('nombre','')} {cliente.get('apellido','') or ''}").strip()
    limite_fmt = f"${cliente.get('limite_credito', 0):,}".replace(',', '.')
    dia_pago = cliente.get('dia_pago')
    if dia_pago:
        pago_txt = f"Dia {dia_pago} de cada mes"
    else:
        freq_map = {'semanal': 'Semanal', 'quincenal': 'Quincenal', 'mensual': 'Mensual', 'dia_fijo': 'Mensual'}
        pago_txt = freq_map.get(str(cliente.get('frecuencia_pago', 'mensual')), 'Mensual')

    if not ESCPOS_OK:
        SEP = '=' * N
        lineas = [SEP, "ZERO CREDIT".center(N), SEP, "", nombre_c.center(N),
                  f"Tel: {limpiar_texto(str(cliente.get('telefono') or '-'))}".center(N),
                  "", f"Limite: {limite_fmt}".center(N), f"Pago: {pago_txt}".center(N), "",
                  url_portal.center(N), "", "Escanea QR para ver tu cuenta".center(N),
                  SEP, limpiar_texto(config.get('nombre_negocio', 'ZERO POS')).center(N),
                  limpiar_texto(config.get('direccion_negocio', '')).center(N), SEP]
        return enviar_crudo(config_imp, "\n".join(lineas) + "\n\n\n")

    try:
        p = _get_printer(config_imp)
        p.text("\n\n\n")
        imprimir_logo(p)

        # Título
        p.set(align="center", bold=True)
        p.text("ZERO CREDIT\n")
        p.set(bold=False)
        p.text(limpiar_texto(config.get('nombre_negocio', '')) + "\n")
        p.text('-' * N + "\n\n")

        # Nombre del cliente grande
        p.set(align="center", bold=True, height=2)
        p.text(nombre_c[:20] + "\n")
        p.set(height=1, bold=False)
        tel = cliente.get('telefono')
        if tel:
            p.text(f"Tel: {limpiar_texto(str(tel))}\n")
        p.text("\n")
        p.text('-' * N + "\n\n")

        # Condiciones
        p.set(align="left")
        p.text(f"Limite:  {limite_fmt}\n")
        p.text(f"Pago:    {pago_txt}\n\n")
        p.text('-' * N + "\n\n")

        # QR portal grande
        p.set(align="center")
        p.text("Escanea para ver\n")
        p.text("tu cuenta ZERO CREDIT:\n\n")
        imprimir_qr(p, url_portal, size=220)
        p.text("\n")
        p.text('-' * N + "\n")

        # QR WiFi opcional
        ssid = (config.get('wifi_ssid') or '').strip()
        if ssid:
            wifi_pass = (config.get('wifi_password') or '').strip()
            wifi_qr = f"WIFI:T:WPA;S:{ssid};P:{wifi_pass};;"
            p.text("\n")
            p.set(align="center")
            p.text("Conectate al WiFi del local\n")
            p.text(f"Red: {limpiar_texto(ssid)}\n\n")
            imprimir_qr(p, wifi_qr, size=160)
            p.text("\n")
            p.text('-' * N + "\n")

        # Pie
        p.set(align="center", bold=False)
        p.text(limpiar_texto(config.get('nombre_negocio', '')) + "\n")
        dir_neg = limpiar_texto(config.get('direccion_negocio', '') or '')
        if dir_neg:
            p.text(dir_neg + "\n")

        p.text("\n\n\n\n\n\n\n\n")
        cortar_ticket(p, config)
        p.close()
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error imprimir tarjeta: {e}")
        return {"ok": False, "error": str(e)}
