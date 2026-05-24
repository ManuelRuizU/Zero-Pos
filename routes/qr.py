import logging
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
    monto = float(data.get("monto", 0))
    concepto = str(data.get("concepto", "Pago ZERO POS")).strip()

    with db_session() as conn:
        cfg = conn.execute("SELECT clave, valor FROM config").fetchall()
        config = {r["clave"]: r["valor"] for r in cfg}

    from utils.qr import generar_qr_pago
    resultado = generar_qr_pago(monto, concepto, config)
    return jsonify(resultado)
