#kipu.py

import json
import hmac
import hashlib
import logging
from flask import Blueprint, request, jsonify, session
from database import db_session

khipu_bp = Blueprint("khipu", __name__, url_prefix="/api/khipu")
logger = logging.getLogger("zero_pos.khipu")


def _get_khipu_config(conn):
    rows = conn.execute(
        "SELECT clave, valor FROM config WHERE clave IN ('khipu_receiver_id','khipu_secret')"
    ).fetchall()
    return {r["clave"]: r["valor"] for r in rows}


@khipu_bp.route("/crear_pago", methods=["POST"])
def crear_pago():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    monto = float(data.get("monto", 0))
    concepto = str(data.get("concepto", "Compra ZERO POS")).strip()
    venta_id = data.get("venta_id")

    if monto <= 0:
        return jsonify({"error": "Monto inválido"}), 400

    with db_session() as conn:
        cfg = _get_khipu_config(conn)

    receiver_id = cfg.get("khipu_receiver_id", "")
    secret = cfg.get("khipu_secret", "")

    if not receiver_id or not secret:
        return jsonify({"error": "Khipu no configurado. Ve a Configuración → Pagos."}), 503

    try:
        import urllib.request
        import urllib.parse

        params = {
            "receiver_id": receiver_id,
            "subject": concepto,
            "currency": "CLP",
            "amount": str(int(monto)),
            "transaction_id": f"zpos-{venta_id or 'manual'}",
            "notify_url": "",
            "return_url": "",
        }
        body = urllib.parse.urlencode(params).encode()
        sig = hmac.new(key=secret.encode(), msg=body, digestmod=hashlib.sha256).hexdigest()

        req = urllib.request.Request(
            "https://khipu.com/api/2.0/payments",
            data=body,
            headers={
                "Authorization": f"Khipu {receiver_id}:{sig}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())

        payment_id = result.get("payment_id")
        payment_url = result.get("payment_url") or result.get("simplified_transfer_url")

        with db_session() as conn:
            conn.execute(
                """INSERT INTO pagos_khipu (venta_id, payment_id, payment_url, monto)
                   VALUES (?,?,?,?)""",
                (venta_id, payment_id, payment_url, monto)
            )

        return jsonify({
            "ok": True,
            "payment_id": payment_id,
            "payment_url": payment_url,
        })

    except Exception as e:
        logger.error(f"Error Khipu: {e}")
        return jsonify({"error": f"Error al crear pago: {str(e)}"}), 500


@khipu_bp.route("/verificar/<payment_id>", methods=["GET"])
def verificar_pago(payment_id):
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        pago = conn.execute(
            "SELECT * FROM pagos_khipu WHERE payment_id=?", (payment_id,)
        ).fetchone()
        if not pago:
            return jsonify({"error": "Pago no encontrado"}), 404
        return jsonify(dict(pago))


@khipu_bp.route("/webhook", methods=["POST"])
def webhook():
    data = request.form.to_dict()
    payment_id = data.get("payment_id")
    status = data.get("status")

    if payment_id and status:
        with db_session() as conn:
            conn.execute(
                "UPDATE pagos_khipu SET estado=?, actualizado_en=CURRENT_TIMESTAMP WHERE payment_id=?",
                (status, payment_id)
            )
            if status == "done":
                pago = conn.execute(
                    "SELECT venta_id FROM pagos_khipu WHERE payment_id=?", (payment_id,)
                ).fetchone()
                if pago and pago["venta_id"]:
                    conn.execute(
                        "UPDATE ventas SET estado='completada' WHERE id=? AND estado='pendiente'",
                        (pago["venta_id"],)
                    )
    return "OK", 200
