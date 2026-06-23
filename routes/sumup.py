import logging
import threading
import uuid
import requests
from flask import Blueprint, request, jsonify, session
from database import db_session, ensure_column, registrar_movimiento_stock

sumup_bp = Blueprint("sumup", __name__, url_prefix="/api/sumup")
logger = logging.getLogger("zero_pos.sumup")

SUMUP_API_BASE = "https://api.sumup.com/v0.1"


def _get_sumup_config(conn) -> dict:
    rows = conn.execute(
        """SELECT clave, valor FROM config
           WHERE clave IN ('sumup_api_key', 'sumup_merchant_code',
                           'sumup_currency', 'sumup_email')"""
    ).fetchall()
    return {r["clave"]: r["valor"] for r in rows}


def _ensure_tabla(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pagos_sumup (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id       INTEGER,
            checkout_id    TEXT NOT NULL,
            checkout_ref   TEXT,
            monto          REAL,
            link_pago      TEXT,
            estado         TEXT DEFAULT 'pendiente',
            creado_en      DATETIME DEFAULT CURRENT_TIMESTAMP,
            actualizado_en DATETIME
        )
    """)
    ensure_column(conn, 'pagos_sumup', 'link_pago', 'TEXT')


def _get_access_token(api_key: str) -> str:
    """Obtiene token OAuth usando API key (para flujo completo OAuth)."""
    resp = requests.post(
        "https://api.sumup.com/token",
        data={
            "grant_type": "client_credentials",
            "client_id": api_key,
            "client_secret": api_key,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _confirmar_venta_pendiente(conn, venta_id: int) -> dict | None:
    """Descuenta stock y marca la venta como completada si estaba pendiente.
    Retorna datos del ticket, o None si la venta no era pendiente."""
    venta = conn.execute(
        "SELECT * FROM ventas WHERE id=? AND estado='pendiente'", (venta_id,)
    ).fetchone()
    if not venta:
        return None
    venta = dict(venta)

    items = conn.execute(
        """SELECT vi.*, p.modo_stock, p.nombre AS producto_nombre
           FROM venta_items vi
           JOIN productos p ON p.id = vi.producto_id
           WHERE vi.venta_id=?""",
        (venta_id,)
    ).fetchall()
    items_list = [dict(i) for i in items]

    for it in items_list:
        try:
            if it.get("variante_id"):
                registrar_movimiento_stock(conn, it["producto_id"], it["variante_id"],
                                           "salida", it["cantidad"], "venta", 0, venta_id=venta_id)
            elif it.get("modo_stock") != "sin_stock":
                registrar_movimiento_stock(conn, it["producto_id"], None,
                                           "salida", it["cantidad"], "venta", 0, venta_id=venta_id)
        except Exception as e:
            logger.warning(f"SumUp confirmar: no se pudo descontar stock venta #{venta_id}: {e}")

    conn.execute(
        "UPDATE ventas SET estado='completada', metodo_pago='tarjeta' WHERE id=?",
        (venta_id,)
    )

    total = float(venta.get("total") or 0)
    neto  = float(venta.get("neto") or 0)
    return {
        "venta_id":  venta_id,
        "total":     total,
        "neto":      neto,
        "impuesto":  total - neto,
        "items":     items_list,
    }


def _imprimir_ticket_sumup(ticket_data: dict) -> None:
    """Imprime ticket en hilo daemon para una venta recién confirmada por SumUp."""
    def _do():
        try:
            from routes.ventas import _imprimir_ticket_async
            with db_session() as conn:
                cfg_rows = conn.execute("SELECT clave, valor FROM config").fetchall()
                cfg = {r["clave"]: r["valor"] for r in cfg_rows}
            config_imp = {
                "tipo":   cfg.get("impresora_tipo", "red"),
                "ip":     cfg.get("impresora_ip", "192.168.1.100"),
                "puerto": cfg.get("impresora_puerto", "9100"),
            }
            _imprimir_ticket_async(
                ticket_data["venta_id"], ticket_data["total"], "tarjeta",
                ticket_data["items"], cfg, config_imp,
                neto=ticket_data["neto"], impuesto=ticket_data["impuesto"],
            )
        except Exception as e:
            logger.warning(f"No se pudo imprimir ticket SumUp venta #{ticket_data.get('venta_id')}: {e}")

    threading.Thread(target=_do, daemon=True, name=f"ticket-sumup-{ticket_data.get('venta_id')}").start()


@sumup_bp.route("/crear_checkout", methods=["POST"])
def crear_checkout():
    """Crea un checkout en SumUp para cobrar con lector Air."""
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    venta_id   = data.get("venta_id")
    descripcion = str(data.get("descripcion", "Venta ZERO POS")).strip()

    try:
        monto = float(data.get("monto", 0))
        if monto <= 0:
            return jsonify({"error": "Monto inválido"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Monto debe ser numérico"}), 400

    with db_session() as conn:
        cfg = _get_sumup_config(conn)

    api_key       = cfg.get("sumup_api_key", "")
    merchant_code = cfg.get("sumup_merchant_code", "")
    currency      = cfg.get("sumup_currency", "CLP")

    if not api_key or not merchant_code:
        return jsonify({
            "error": "SumUp no configurado. Ve a Admin → Config → Pagos."
        }), 503

    try:
        checkout_ref = f"zpos-{venta_id or uuid.uuid4().hex[:8]}"

        resp = requests.post(
            f"{SUMUP_API_BASE}/checkouts",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "checkout_reference": checkout_ref,
                "amount": round(monto, 2),
                "currency": currency,
                "merchant_code": merchant_code,
                "description": descripcion,
            },
            timeout=10,
        )
        resp.raise_for_status()
        checkout    = resp.json()
        checkout_id = checkout.get("id")

        with db_session() as conn:
            _ensure_tabla(conn)
            conn.execute(
                """INSERT INTO pagos_sumup (venta_id, checkout_id, checkout_ref, monto)
                   VALUES (?,?,?,?)""",
                (venta_id, checkout_id, checkout_ref, monto),
            )

        logger.info(f"SumUp checkout creado: {checkout_id} monto={monto}")
        return jsonify({
            "ok": True,
            "checkout_id": checkout_id,
            "checkout_ref": checkout_ref,
            "monto": monto,
            "instruccion": "Presenta el lector SumUp Air al cliente",
        })

    except requests.HTTPError as e:
        logger.error(f"SumUp API error: {e.response.text}")
        return jsonify({"error": f"Error SumUp: {e.response.status_code}"}), 502
    except Exception as e:
        logger.error(f"Error crear checkout SumUp: {e}")
        return jsonify({"error": str(e)}), 500


@sumup_bp.route("/estado/<checkout_id>", methods=["GET"])
def estado_checkout(checkout_id):
    """Consulta el estado de un checkout SumUp."""
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        cfg = _get_sumup_config(conn)

    api_key = cfg.get("sumup_api_key", "")
    if not api_key:
        return jsonify({"error": "SumUp no configurado"}), 503

    try:
        resp = requests.get(
            f"{SUMUP_API_BASE}/checkouts/{checkout_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        checkout = resp.json()
        estado   = checkout.get("status", "UNKNOWN")

        ticket_data = None
        with db_session() as conn:
            conn.execute(
                """UPDATE pagos_sumup
                   SET estado=?, actualizado_en=CURRENT_TIMESTAMP
                   WHERE checkout_id=?""",
                (estado.lower(), checkout_id),
            )
            if estado == "PAID":
                pago = conn.execute(
                    "SELECT venta_id FROM pagos_sumup WHERE checkout_id=?",
                    (checkout_id,)
                ).fetchone()
                if pago and pago["venta_id"]:
                    ticket_data = _confirmar_venta_pendiente(conn, pago["venta_id"])
                    if ticket_data:
                        logger.info(f"Venta #{pago['venta_id']} completada + stock descontado via SumUp")
                    else:
                        logger.info(f"Venta #{pago['venta_id']} ya completada (no era pendiente)")

        if ticket_data:
            _imprimir_ticket_sumup(ticket_data)

        return jsonify({
            "ok": True,
            "checkout_id": checkout_id,
            "estado": estado,
            "pagado": estado == "PAID",
        })

    except Exception as e:
        logger.error(f"Error estado SumUp: {e}")
        return jsonify({"error": str(e)}), 500


@sumup_bp.route("/webhook", methods=["POST"])
def webhook():
    """Webhook de SumUp para notificaciones de pago (sin auth — IP pública SumUp)."""
    data        = request.get_json(silent=True) or {}
    checkout_id = data.get("id")
    estado      = data.get("status", "")

    if checkout_id and estado:
        ticket_data = None
        try:
            with db_session() as conn:
                conn.execute(
                    """UPDATE pagos_sumup
                       SET estado=?, actualizado_en=CURRENT_TIMESTAMP
                       WHERE checkout_id=?""",
                    (estado.lower(), checkout_id),
                )
                if estado == "PAID":
                    pago = conn.execute(
                        "SELECT venta_id FROM pagos_sumup WHERE checkout_id=?",
                        (checkout_id,)
                    ).fetchone()
                    if pago and pago["venta_id"]:
                        ticket_data = _confirmar_venta_pendiente(conn, pago["venta_id"])
                        if ticket_data:
                            logger.info(f"Webhook SumUp: venta #{pago['venta_id']} completada + stock")
        except Exception as e:
            logger.error(f"Error webhook SumUp: {e}")

        if ticket_data:
            _imprimir_ticket_sumup(ticket_data)

    return "OK", 200


@sumup_bp.route("/confirmar_webhook", methods=["POST"])
def confirmar_webhook():
    """Cliente.html notifica pago exitoso del widget SumUp — sin autenticación."""
    data        = request.get_json(silent=True) or {}
    checkout_id = data.get("checkout_id")
    status      = data.get("status", "")

    if not checkout_id:
        return jsonify({"error": "checkout_id requerido"}), 400

    ticket_data = None
    try:
        with db_session() as conn:
            conn.execute(
                """UPDATE pagos_sumup
                   SET estado=?, actualizado_en=CURRENT_TIMESTAMP
                   WHERE checkout_id=?""",
                (status.lower(), checkout_id),
            )
            if status == "PAID":
                pago = conn.execute(
                    "SELECT venta_id FROM pagos_sumup WHERE checkout_id=?",
                    (checkout_id,)
                ).fetchone()
                if pago and pago["venta_id"]:
                    ticket_data = _confirmar_venta_pendiente(conn, pago["venta_id"])
                    if ticket_data:
                        logger.info(f"confirmar_webhook SumUp: venta #{pago['venta_id']} completada")
    except Exception as e:
        logger.error(f"Error confirmar_webhook SumUp: {e}")
        return jsonify({"error": str(e)}), 500

    if ticket_data:
        _imprimir_ticket_sumup(ticket_data)

    return jsonify({"ok": True})


@sumup_bp.route("/crear_link_pago", methods=["POST"])
def crear_link_pago():
    """Crea checkout SumUp y devuelve link de pago para QR en pantalla cliente."""
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    data        = request.get_json(silent=True) or {}
    venta_id    = data.get("venta_id")
    descripcion = str(data.get("descripcion", "Venta ZERO POS")).strip()

    try:
        monto = float(data.get("monto", 0))
        if not (1 <= monto <= 10_000_000):
            return jsonify({"error": "Monto inválido (1–10.000.000)"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Monto debe ser numérico"}), 400

    with db_session() as conn:
        cfg = _get_sumup_config(conn)

    api_key       = cfg.get("sumup_api_key", "")
    merchant_code = cfg.get("sumup_merchant_code", "")
    pay_to_email  = cfg.get("sumup_email", "")
    currency      = cfg.get("sumup_currency", "CLP")

    if not api_key:
        return jsonify({"error": "SumUp no configurado. Ve a Admin → Config → Pagos."}), 503

    try:
        checkout_ref = f"zpos-{venta_id or uuid.uuid4().hex[:8]}"

        resp = requests.post(
            "https://api.sumup.com/v0.1/checkouts",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "checkout_reference": checkout_ref,
                "amount": round(float(monto), 2),
                "currency": currency,
                "description": descripcion,
                **({"merchant_code": merchant_code}
                   if merchant_code else {}),
                **({"pay_to_email": pay_to_email}
                   if pay_to_email and not merchant_code else {}),
                "hosted_checkout": {"enabled": True},
            },
            timeout=10,
        )
        resp.raise_for_status()
        checkout    = resp.json()
        checkout_id = checkout.get("id")
        hosted_url  = checkout.get("hosted_checkout_url", "")
        link_pago   = hosted_url or f"https://pay.sumup.com/b2c/checkout/{checkout_id}"

        with db_session() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pagos_sumup (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    venta_id       INTEGER,
                    checkout_id    TEXT NOT NULL,
                    checkout_ref   TEXT,
                    monto          REAL,
                    link_pago      TEXT,
                    estado         TEXT DEFAULT 'pendiente',
                    creado_en      DATETIME DEFAULT CURRENT_TIMESTAMP,
                    actualizado_en DATETIME
                )
            """)
            conn.execute(
                """INSERT OR IGNORE INTO pagos_sumup
                       (venta_id, checkout_id, checkout_ref, monto, link_pago)
                   VALUES (?,?,?,?,?)""",
                (venta_id, checkout_id, checkout_ref, monto, link_pago),
            )

        logger.info(f"SumUp link creado: {checkout_id} monto={monto}")
        return jsonify({"ok": True, "checkout_id": checkout_id, "link_pago": link_pago})

    except requests.HTTPError as e:
        logger.error(f"SumUp API error crear_link_pago: {e.response.text}")
        return jsonify({"error": f"Error SumUp: {e.response.status_code}"}), 502
    except Exception as e:
        logger.error(f"Error crear_link_pago: {e}")
        return jsonify({"error": str(e)}), 500


@sumup_bp.route("/estado_cliente", methods=["GET"])
def estado_cliente():
    """Estado del pago SumUp activo para cliente.html — sin autenticación."""
    checkout_id = request.args.get("checkout_id", "")
    if not checkout_id:
        return jsonify({"estado": "sin_pago"})
    with db_session() as conn:
        pago = conn.execute(
            "SELECT estado, monto, link_pago FROM pagos_sumup WHERE checkout_id=?",
            (checkout_id,),
        ).fetchone()
    if not pago:
        return jsonify({"estado": "sin_pago"})
    return jsonify({
        "estado":    pago["estado"],
        "monto":     pago["monto"],
        "link_pago": pago["link_pago"],
    })
