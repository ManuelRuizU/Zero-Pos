# routes/comprobante.py

import logging
import urllib.parse
from flask import Blueprint, request, jsonify, session
from database import db_session

comprobante_bp = Blueprint("comprobante", __name__, url_prefix="/api/comprobante")
logger = logging.getLogger("zero_pos.comprobante")


def _normalizar_telefono(tel: str) -> str:
    """Normaliza teléfono chileno a formato internacional."""
    tel = ''.join(c for c in tel if c.isdigit())
    if len(tel) == 9 and tel.startswith('9'):
        return '569' + tel
    elif len(tel) == 11 and tel.startswith('56'):
        return tel
    elif len(tel) == 8:
        return '562' + tel  # teléfono fijo Santiago
    raise ValueError(f"Teléfono inválido: {tel}")


@comprobante_bp.route("/<int:venta_id>/qr", methods=["GET"])
def qr_comprobante(venta_id):
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        venta = conn.execute("SELECT * FROM ventas WHERE id=?", (venta_id,)).fetchone()
        if not venta:
            return jsonify({"error": "Venta no encontrada"}), 404

    from utils.comprobante import generar_qr_comprobante
    resultado = generar_qr_comprobante(dict(venta))
    return jsonify(resultado)


@comprobante_bp.route("/<int:venta_id>/whatsapp", methods=["POST"])
def whatsapp_comprobante(venta_id):
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}

    # CAMBIO 1 — normalizar teléfono chileno
    try:
        telefono = _normalizar_telefono(data.get("telefono", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # CAMBIO 2 — rate limit 60 segundos por venta+teléfono
    from time import time
    clave_rl = f"wa_{venta_id}_{data.get('telefono', '')}"
    ultimo = session.get(clave_rl, 0)
    if time() - ultimo < 60:
        segundos = int(60 - (time() - ultimo))
        return jsonify({"error": f"Espera {segundos} segundos antes de reenviar"}), 429
    session[clave_rl] = time()

    with db_session() as conn:
        venta = conn.execute("SELECT * FROM ventas WHERE id=?", (venta_id,)).fetchone()
        if not venta:
            return jsonify({"error": "Venta no encontrada"}), 404
        items = conn.execute(
            """SELECT vi.cantidad, vi.subtotal, p.nombre AS producto_nombre
               FROM venta_items vi JOIN productos p ON vi.producto_id=p.id
               WHERE vi.venta_id=?""",
            (venta_id,)
        ).fetchall()
        # CAMBIO 3 — plantilla configurable desde config
        cfg = conn.execute(
            "SELECT clave, valor FROM config WHERE clave IN ('whatsapp_plantilla', 'nombre_negocio')"
        ).fetchall()

    venta = dict(venta)
    items = [dict(i) for i in items]
    cfg_map = {r['clave']: r['valor'] for r in cfg}

    plantilla = cfg_map.get('whatsapp_plantilla') or \
        "Hola! Gracias por tu compra en {negocio} 🛍️\n" \
        "Total: ${total}\n" \
        "Productos: {items}\n" \
        "¡Vuelve pronto! 😊"

    mensaje = plantilla.format(
        negocio=cfg_map.get('nombre_negocio', 'ZERO POS'),
        total=f"{venta['total']:,.0f}".replace(',', '.'),
        items=', '.join([i['producto_nombre'] for i in items[:3]]),
        venta_id=venta_id,
        fecha=venta['creado_en'][:10] if venta.get('creado_en') else ''
    )

    link = f"https://wa.me/{telefono}?text={urllib.parse.quote(mensaje)}"
    return jsonify({"ok": True, "link": link})
