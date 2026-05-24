import logging
from flask import Blueprint, request, jsonify, session
from database import db_session

inventario_bp = Blueprint("inventario", __name__, url_prefix="/api/inventario")
logger = logging.getLogger("zero_pos.inventario")


def _auth():
    return session.get("usuario_id")


# ── Proveedores ───────────────────────────────────────────────────────────────

@inventario_bp.route("/proveedores", methods=["GET"])
def listar_proveedores():
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM proveedores WHERE activo=1 ORDER BY nombre"
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@inventario_bp.route("/proveedores", methods=["POST"])
def crear_proveedor():
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400
    with db_session() as conn:
        cur = conn.execute(
            """INSERT INTO proveedores (nombre, rut, contacto, telefono, email, direccion, notas)
               VALUES (?,?,?,?,?,?,?)""",
            (nombre, data.get("rut"), data.get("contacto"),
             data.get("telefono"), data.get("email"),
             data.get("direccion"), data.get("notas"))
        )
        return jsonify({"ok": True, "id": cur.lastrowid}), 201


@inventario_bp.route("/proveedores/<int:pid>", methods=["PUT"])
def actualizar_proveedor(pid):
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    campos = {k: v for k, v in data.items()
              if k in ("nombre", "rut", "contacto", "telefono", "email", "direccion", "notas")}
    if not campos:
        return jsonify({"error": "Sin datos"}), 400
    set_clause = ", ".join(f"{k}=?" for k in campos)
    with db_session() as conn:
        conn.execute(f"UPDATE proveedores SET {set_clause} WHERE id=?",
                     list(campos.values()) + [pid])
        return jsonify({"ok": True})


@inventario_bp.route("/proveedores/<int:pid>", methods=["DELETE"])
def eliminar_proveedor(pid):
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    with db_session() as conn:
        conn.execute("UPDATE proveedores SET activo=0 WHERE id=?", (pid,))
        return jsonify({"ok": True})


# ── Órdenes de compra ─────────────────────────────────────────────────────────

@inventario_bp.route("/ordenes", methods=["GET"])
def listar_ordenes():
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute(
            """SELECT o.*, p.nombre as proveedor_nombre
               FROM ordenes_compra o LEFT JOIN proveedores p ON o.proveedor_id=p.id
               ORDER BY o.creado_en DESC LIMIT 100"""
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@inventario_bp.route("/ordenes", methods=["POST"])
def crear_orden():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    items = data.get("items", [])
    if not items:
        return jsonify({"error": "Sin productos"}), 400

    with db_session() as conn:
        total = sum(float(it.get("precio_unit", 0)) * int(it.get("cantidad", 1))
                    for it in items)
        cur = conn.execute(
            "INSERT INTO ordenes_compra (proveedor_id, usuario_id, total, notas) VALUES (?,?,?,?)",
            (data.get("proveedor_id"), uid, round(total, 2), data.get("notas"))
        )
        oid = cur.lastrowid
        for it in items:
            qty = int(it.get("cantidad", 1))
            pu = float(it.get("precio_unit", 0))
            conn.execute(
                "INSERT INTO orden_items (orden_id, producto_id, cantidad, precio_unit, subtotal) VALUES (?,?,?,?,?)",
                (oid, it["producto_id"], qty, pu, round(qty * pu, 2))
            )
        return jsonify({"ok": True, "id": oid}), 201


@inventario_bp.route("/ordenes/<int:oid>/recibir", methods=["POST"])
def recibir_orden(oid):
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        orden = conn.execute(
            "SELECT * FROM ordenes_compra WHERE id=? AND estado='enviada'", (oid,)
        ).fetchone()
        if not orden:
            return jsonify({"error": "Orden no encontrada o no enviada"}), 404

        items = conn.execute(
            "SELECT * FROM orden_items WHERE orden_id=?", (oid,)
        ).fetchall()
        for it in items:
            conn.execute(
                "UPDATE productos SET stock = stock + ?, actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
                (it["cantidad"], it["producto_id"])
            )
            conn.execute(
                """INSERT INTO stock_movimientos (producto_id, tipo, cantidad, referencia, usuario_id)
                   VALUES (?,?,?,?,?)""",
                (it["producto_id"], "entrada", it["cantidad"], f"OC-{oid}", uid)
            )
        conn.execute(
            "UPDATE ordenes_compra SET estado='recibida', recibido_en=CURRENT_TIMESTAMP WHERE id=?",
            (oid,)
        )
        return jsonify({"ok": True})


# ── Márgenes / análisis ───────────────────────────────────────────────────────

@inventario_bp.route("/margenes", methods=["GET"])
def margenes():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    with db_session() as conn:
        rows = conn.execute(
            """SELECT id, nombre, precio, precio_costo,
                precio - precio_costo as margen_abs,
                CASE WHEN precio > 0
                     THEN ROUND((precio - precio_costo)*100.0/precio, 2)
                     ELSE 0 END as margen_pct
               FROM productos WHERE activo=1
               ORDER BY margen_pct"""
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@inventario_bp.route("/movimientos/<int:producto_id>", methods=["GET"])
def movimientos_producto(producto_id):
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute(
            """SELECT sm.*, u.nombre as usuario_nombre
               FROM stock_movimientos sm
               LEFT JOIN usuarios u ON sm.usuario_id=u.id
               WHERE sm.producto_id=?
               ORDER BY sm.creado_en DESC LIMIT 100""",
            (producto_id,)
        ).fetchall()
        return jsonify([dict(r) for r in rows])
