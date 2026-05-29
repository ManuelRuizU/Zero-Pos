import datetime
import logging
import subprocess
from flask import Blueprint, request, jsonify, session
from database import db_session

config_bp = Blueprint("config", __name__, url_prefix="/api/config")
logger = logging.getLogger("zero_pos.config")

# Claves permitidas — lista blanca para evitar escritura arbitraria
CLAVES_PERMITIDAS = {
    "nombre_negocio", "moneda", "iva_porcentaje", "rut_negocio",
    "impresora_tipo", "impresora_ip", "impresora_puerto",
    "khipu_receiver_id", "khipu_secret",
    "banco_nombre", "banco_tipo_cuenta", "banco_cuenta", "banco_titular",
    "backup_hora",
    "pantalla_cliente_activa", "pantalla_cocina_activa",
    "modulo_delivery", "modo_mesas", "tipo_negocio",
    "google_maps_api_key",
    "comuna_negocio",
    "delivery_tarifa_tipo",
    "delivery_precio_fijo",
    "delivery_precio_km1",
    "delivery_precio_km3",
    "delivery_precio_km5",
    "delivery_precio_mas5",
    "delivery_texto",
}


@config_bp.route("", methods=["GET"])
def obtener():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute("SELECT clave, valor FROM config").fetchall()
        return jsonify({r["clave"]: r["valor"] for r in rows})


@config_bp.route("", methods=["POST"])
def guardar():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403

    data = request.get_json(silent=True) or {}
    rechazadas = [k for k in data if k not in CLAVES_PERMITIDAS]
    if rechazadas:
        return jsonify({"error": f"Claves no permitidas: {rechazadas}"}), 400

    with db_session() as conn:
        for clave, valor in data.items():
            conn.execute(
                "INSERT INTO config (clave, valor) VALUES (?,?) "
                "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
                (clave, str(valor) if valor is not None else "")
            )

    logger.info(f"Config actualizada: {list(data.keys())}")
    return jsonify({"ok": True})


@config_bp.route("/sistema/sincronizar-hora", methods=["POST"])
def sincronizar_hora():
    data = request.get_json(silent=True) or {}
    ts = data.get("timestamp")
    if ts:
        try:
            dt = datetime.datetime.fromtimestamp(float(ts))
            fecha_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            res = subprocess.run(
                ["sudo", "date", "-s", fecha_str],
                capture_output=True, timeout=3
            )
            if res.returncode == 0:
                logger.info(f"Reloj sincronizado: {fecha_str}")
            else:
                logger.warning(f"sudo date rechazado: {res.stderr}")
        except Exception:
            pass  # Sin sudo → silencioso, no crítico
    return jsonify({"ok": True})
