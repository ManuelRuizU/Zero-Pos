import logging
from flask import Blueprint, request, jsonify, session
from database import db_session

impresora_bp = Blueprint("impresora", __name__, url_prefix="/api/impresora")
logger = logging.getLogger("zero_pos.impresora")


@impresora_bp.route("/ticket/<int:venta_id>", methods=["POST"])
def imprimir_ticket(venta_id):
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    config_imp = data.get("config", {})

    with db_session() as conn:
        venta = conn.execute(
            "SELECT * FROM ventas WHERE id=?", (venta_id,)
        ).fetchone()
        if not venta:
            return jsonify({"error": "Venta no encontrada"}), 404

        items = conn.execute(
            """SELECT vi.cantidad, vi.precio_unit, vi.subtotal, p.nombre
               FROM venta_items vi JOIN productos p ON vi.producto_id=p.id
               WHERE vi.venta_id=?""",
            (venta_id,)
        ).fetchall()

        cfg = conn.execute("SELECT clave, valor FROM config").fetchall()
        config = {r["clave"]: r["valor"] for r in cfg}

    from utils.impresora import imprimir_recibo
    resultado = imprimir_recibo(dict(venta), [dict(i) for i in items], config, config_imp)
    return jsonify(resultado)


@impresora_bp.route("/config", methods=["GET"])
def obtener_config():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute(
            "SELECT clave, valor FROM config WHERE clave LIKE 'impresora_%'"
        ).fetchall()
        return jsonify({r["clave"]: r["valor"] for r in rows})


@impresora_bp.route("/config", methods=["POST"])
def guardar_config():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    data = request.get_json(silent=True) or {}
    with db_session() as conn:
        for clave, valor in data.items():
            if clave.startswith("impresora_"):
                conn.execute(
                    "INSERT OR REPLACE INTO config (clave, valor) VALUES (?,?)",
                    (clave, str(valor))
                )
    return jsonify({"ok": True})


@impresora_bp.route("/test", methods=["POST"])
def test_impresora():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    from utils.impresora import test_conexion
    resultado = test_conexion()
    return jsonify(resultado)
