# routes/qr.py

import logging
import re as _re
from flask import Blueprint, request, jsonify, session, send_file
from database import db_session

qr_bp = Blueprint("qr", __name__, url_prefix="/api/qr")
logger = logging.getLogger("zero_pos.qr")


@qr_bp.route("/producto/<int:pid>", methods=["GET"])
def qr_producto(pid):
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        prod = conn.execute(
            "SELECT id, nombre, precio, codigo_barras FROM productos WHERE id=?", (pid,)
        ).fetchone()
        if not prod:
            return jsonify({"error": "Producto no encontrado"}), 404

    from utils.qr import generar_qr_producto
    buf = generar_qr_producto(dict(prod))
    return send_file(buf, mimetype="image/png")


@qr_bp.route("/pago", methods=["POST"])
def qr_pago():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}

    try:
        monto = float(data.get("monto", 0))
        if not (1 <= monto <= 10_000_000):
            return jsonify({"error": "Monto debe estar entre $1 y $10.000.000"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Monto debe ser numérico"}), 400

    concepto = str(data.get("concepto", ""))
    concepto = _re.sub(r'[^\w\s\-.,áéíóúñÁÉÍÓÚÑ]', '', concepto)[:50]
    if not concepto:
        concepto = f"Pago venta #{data.get('venta_id', '')}"

    with db_session() as conn:
        cfg = conn.execute("SELECT clave, valor FROM config").fetchall()
        config = {r["clave"]: r["valor"] for r in cfg}

    from utils.qr import generar_qr_pago
    resultado = generar_qr_pago(monto, concepto, config)
    return jsonify(resultado)
