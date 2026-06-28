import datetime
import logging
import re as _re
import subprocess
from flask import Blueprint, request, jsonify, session
from database import db_session

config_bp = Blueprint("config", __name__, url_prefix="/api/config")
logger = logging.getLogger("zero_pos.config")

# Claves permitidas — lista blanca para evitar escritura arbitraria
CLAVES_PERMITIDAS = {
    "nombre_negocio", "moneda", "iva_porcentaje", "rut_negocio",
    "impresora_tipo", "impresora_ip", "impresora_puerto",
    "impresora_autocorte", "impresora_corte_tipo",
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
    "subtipo_negocio",
    "telefono_negocio",
    "direccion_negocio",
    "nombre_responsable",
    "email_negocio",
    "sii_activo",
    "responsable_nombre",
    "responsable_telefono",
    "responsable_email",
    "razon_social",
    "giro",
    "tema_color",
    "tema_modo",
    "smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_from", "smtp_provider",
    "backup_email_destino", "backup_destinos", "backup_retener_dias", "backup_rclone_remote",
    "wifi_ssid", "wifi_password",
    "nombre_terminal",
    "whatsapp_plantilla",
    "sumup_api_key", "sumup_merchant_code", "sumup_currency", "sumup_email",
    "cajero_reemplazo_colacion",
}

_VALIDADORES = {
    "iva_porcentaje":             lambda v: 0 <= float(v) <= 30,
    "impresora_puerto":           lambda v: 1 <= int(v) <= 65535,
    "impresora_cocina_puerto":    lambda v: 1 <= int(v) <= 65535,
    "moneda":                     lambda v: v in ["CLP", "USD", "ARS"],
    "backup_hora":                lambda v: bool(_re.match(r'^\d{2}:\d{2}$', v)) if v else True,
    "jornada_horas_semanales":    lambda v: 1 <= int(v) <= 60,
}


def upsert_config(conn, data: dict) -> None:
    """Escribe claves de configuración usando la misma lógica de upsert en ambas rutas."""
    for clave, valor in data.items():
        conn.execute(
            "INSERT INTO config (clave, valor) VALUES (?,?) "
            "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
            (clave, str(valor) if valor is not None else "")
        )


@config_bp.route("", methods=["GET"])
def obtener():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute("SELECT clave, valor FROM config").fetchall()
        return jsonify({r["clave"]: r["valor"] for r in rows})


@config_bp.route("", methods=["POST", "PUT"])
def guardar():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403

    data = request.get_json(silent=True) or {}
    rechazadas = [k for k in data if k not in CLAVES_PERMITIDAS]
    if rechazadas:
        return jsonify({"error": f"Claves no permitidas: {rechazadas}"}), 400

    for clave, valor in data.items():
        if clave in _VALIDADORES and valor not in (None, ''):
            try:
                if not _VALIDADORES[clave](str(valor)):
                    return jsonify({"error": f"Valor inválido para {clave}: {valor}"}), 400
            except (ValueError, TypeError):
                return jsonify({"error": f"Formato incorrecto para {clave}: {valor}"}), 400

    with db_session() as conn:
        upsert_config(conn, data)

    from routes.ventas import invalidar_config_cache
    invalidar_config_cache()

    logger.info(f"Config actualizada: {list(data.keys())}")
    return jsonify({"ok": True})


@config_bp.route("/logo-ticket", methods=["POST"])
def subir_logo_ticket():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403

    archivo = request.files.get("logo")
    if not archivo or not archivo.filename:
        return jsonify({"error": "No se recibió imagen"}), 400

    try:
        from PIL import Image
        import io
        from pathlib import Path

        img = Image.open(archivo.stream).convert("L")
        max_ancho = 384
        if img.width > max_ancho:
            ratio = max_ancho / img.width
            img = img.resize((max_ancho, int(img.height * ratio)), Image.LANCZOS)

        destino = Path(__file__).parent.parent / "static" / "negocio"
        destino.mkdir(parents=True, exist_ok=True)
        img.save(destino / "logo_ticket.png", "PNG")

        logger.info("Logo ticket actualizado")
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Error subiendo logo: {e}")
        return jsonify({"error": str(e)}), 500


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
