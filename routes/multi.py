import logging
from flask import Blueprint, request, jsonify, session
from database import db_session

multi_bp = Blueprint("multi", __name__, url_prefix="/api/sucursales")
logger = logging.getLogger("zero_pos.multi")


def _require_admin():
    return session.get("usuario_rol") == "admin"


@multi_bp.route("", methods=["GET"])
def listar():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute("SELECT * FROM sucursales ORDER BY nombre").fetchall()
        return jsonify([dict(r) for r in rows])


@multi_bp.route("", methods=["POST"])
def crear():
    if not _require_admin():
        return jsonify({"error": "Sin permisos"}), 403
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400
    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO sucursales (nombre, direccion, telefono) VALUES (?,?,?)",
            (nombre, data.get("direccion"), data.get("telefono"))
        )
        return jsonify({"ok": True, "id": cur.lastrowid}), 201


@multi_bp.route("/<int:sid>", methods=["PUT"])
def actualizar(sid):
    if not _require_admin():
        return jsonify({"error": "Sin permisos"}), 403
    data = request.get_json(silent=True) or {}
    campos = {k: v for k, v in data.items()
              if k in ("nombre", "direccion", "telefono", "activa")}
    if not campos:
        return jsonify({"error": "Sin datos"}), 400
    set_clause = ", ".join(f"{k}=?" for k in campos)
    with db_session() as conn:
        conn.execute(f"UPDATE sucursales SET {set_clause} WHERE id=?",
                     list(campos.values()) + [sid])
        return jsonify({"ok": True})


@multi_bp.route("/<int:sid>/resumen", methods=["GET"])
def resumen_sucursal(sid):
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        ventas = conn.execute(
            """SELECT COUNT(*) as num, COALESCE(SUM(total),0) as total
               FROM ventas WHERE sucursal_id=? AND DATE(creado_en)=DATE('now') AND estado='completada'""",
            (sid,)
        ).fetchone()
        productos = conn.execute(
            "SELECT COUNT(*) as num FROM productos WHERE sucursal_id=? AND activo=1",
            (sid,)
        ).fetchone()
        return jsonify({
            "ventas_hoy": dict(ventas),
            "productos_activos": productos["num"],
        })


@multi_bp.route("/sincronizar", methods=["POST"])
def sincronizar():
    if not _require_admin():
        return jsonify({"error": "Sin permisos"}), 403
    from utils.multi_tienda import sincronizar_sucursales
    resultado = sincronizar_sucursales()
    return jsonify(resultado)
