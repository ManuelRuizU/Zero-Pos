import logging
from flask import Blueprint, request, jsonify, session
from database import db_session

comprobante_bp = Blueprint("comprobante", __name__, url_prefix="/api/comprobante")
logger = logging.getLogger("zero_pos.comprobante")


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
    telefono = str(data.get("telefono", "")).strip()
    if not telefono:
        return jsonify({"error": "Teléfono requerido"}), 400

    with db_session() as conn:
        venta = conn.execute("SELECT * FROM ventas WHERE id=?", (venta_id,)).fetchone()
        if not venta:
            return jsonify({"error": "Venta no encontrada"}), 404
        items = conn.execute(
            """SELECT vi.cantidad, vi.subtotal, p.nombre
               FROM venta_items vi JOIN productos p ON vi.producto_id=p.id
               WHERE vi.venta_id=?""",
            (venta_id,)
        ).fetchall()

    from utils.comprobante import generar_link_whatsapp
    link = generar_link_whatsapp(telefono, dict(venta), [dict(i) for i in items])
    return jsonify({"ok": True, "link": link})
