import logging
from flask import Blueprint, request, jsonify, session
from database import db_session

ventas_bp = Blueprint("ventas", __name__, url_prefix="/api/ventas")
logger = logging.getLogger("zero_pos.ventas")


def _require_auth():
    uid = session.get("usuario_id")
    if not uid:
        return None, jsonify({"error": "No autenticado"}), 401
    return uid, None, None


@ventas_bp.route("", methods=["POST"])
def crear_venta():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    items = data.get("items", [])
    if not items:
        return jsonify({"error": "Carrito vacío"}), 400

    metodo_pago = data.get("metodo_pago", "efectivo")
    descuento_global = float(data.get("descuento", 0))
    cliente_nombre = data.get("cliente_nombre")
    cliente_rut = data.get("cliente_rut")
    notas = data.get("notas")
    turno_id = session.get("turno_id")

    with db_session() as conn:
        total = 0
        items_validados = []

        for item in items:
            pid = int(item.get("producto_id", 0))
            qty = int(item.get("cantidad", 1))
            descuento_item = float(item.get("descuento", 0))

            prod = conn.execute(
                "SELECT id, nombre, precio, stock FROM productos WHERE id=? AND activo=1",
                (pid,)
            ).fetchone()
            if not prod:
                return jsonify({"error": f"Producto {pid} no encontrado"}), 404
            if prod["stock"] < qty:
                return jsonify({"error": f"Stock insuficiente: {prod['nombre']}"}), 409

            precio_unit = float(prod["precio"])
            subtotal = round((precio_unit * qty) - descuento_item, 2)
            total += subtotal
            items_validados.append({
                "producto_id": pid,
                "cantidad": qty,
                "precio_unit": precio_unit,
                "descuento": descuento_item,
                "subtotal": subtotal,
            })

        total = round(total - descuento_global, 2)
        iva_pct = float(conn.execute(
            "SELECT valor FROM config WHERE clave='iva_porcentaje'"
        ).fetchone()["valor"] or 19)
        impuesto = round(total * iva_pct / (100 + iva_pct), 2)

        cur = conn.execute(
            """INSERT INTO ventas
               (turno_id, usuario_id, total, descuento, impuesto,
                metodo_pago, cliente_nombre, cliente_rut, notas)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (turno_id, uid, total, descuento_global, impuesto,
             metodo_pago, cliente_nombre, cliente_rut, notas)
        )
        venta_id = cur.lastrowid

        for it in items_validados:
            conn.execute(
                """INSERT INTO venta_items
                   (venta_id, producto_id, cantidad, precio_unit, descuento, subtotal)
                   VALUES (?,?,?,?,?,?)""",
                (venta_id, it["producto_id"], it["cantidad"],
                 it["precio_unit"], it["descuento"], it["subtotal"])
            )
            conn.execute(
                "UPDATE productos SET stock = stock - ? WHERE id=?",
                (it["cantidad"], it["producto_id"])
            )
            _check_stock_alerta(conn, it["producto_id"])

        logger.info(f"Venta #{venta_id} creada por usuario {uid} — total={total}")
        return jsonify({"ok": True, "venta_id": venta_id, "total": total}), 201


def _check_stock_alerta(conn, producto_id: int):
    prod = conn.execute(
        "SELECT stock, stock_minimo FROM productos WHERE id=?", (producto_id,)
    ).fetchone()
    if prod and prod["stock"] <= prod["stock_minimo"]:
        ya_existe = conn.execute(
            "SELECT id FROM alertas_stock WHERE producto_id=? AND leida=0",
            (producto_id,)
        ).fetchone()
        if not ya_existe:
            conn.execute(
                "INSERT INTO alertas_stock (producto_id, tipo) VALUES (?, 'stock_bajo')",
                (producto_id,)
            )


@ventas_bp.route("", methods=["GET"])
def listar_ventas():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    fecha_desde = request.args.get("desde")
    fecha_hasta = request.args.get("hasta")
    limite = min(int(request.args.get("limite", 50)), 200)

    query = """
        SELECT v.*, u.nombre as cajero
        FROM ventas v LEFT JOIN usuarios u ON v.usuario_id = u.id
        WHERE 1=1
    """
    params = []
    if fecha_desde:
        query += " AND DATE(v.creado_en) >= ?"
        params.append(fecha_desde)
    if fecha_hasta:
        query += " AND DATE(v.creado_en) <= ?"
        params.append(fecha_hasta)
    query += " ORDER BY v.creado_en DESC LIMIT ?"
    params.append(limite)

    with db_session() as conn:
        rows = conn.execute(query, params).fetchall()
        return jsonify([dict(r) for r in rows])


@ventas_bp.route("/<int:vid>", methods=["GET"])
def detalle_venta(vid):
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        venta = conn.execute(
            """SELECT v.*, u.nombre as cajero
               FROM ventas v LEFT JOIN usuarios u ON v.usuario_id=u.id
               WHERE v.id=?""",
            (vid,)
        ).fetchone()
        if not venta:
            return jsonify({"error": "Venta no encontrada"}), 404

        items = conn.execute(
            """SELECT vi.*, p.nombre as producto_nombre
               FROM venta_items vi JOIN productos p ON vi.producto_id=p.id
               WHERE vi.venta_id=?""",
            (vid,)
        ).fetchall()

        return jsonify({
            "venta": dict(venta),
            "items": [dict(i) for i in items],
        })


@ventas_bp.route("/<int:vid>/anular", methods=["POST"])
def anular_venta(vid):
    if session.get("usuario_rol") not in ("admin",):
        return jsonify({"error": "Sin permisos"}), 403

    with db_session() as conn:
        venta = conn.execute(
            "SELECT * FROM ventas WHERE id=? AND estado='completada'", (vid,)
        ).fetchone()
        if not venta:
            return jsonify({"error": "Venta no encontrada o ya anulada"}), 404

        items = conn.execute(
            "SELECT producto_id, cantidad FROM venta_items WHERE venta_id=?", (vid,)
        ).fetchall()
        for it in items:
            conn.execute(
                "UPDATE productos SET stock = stock + ? WHERE id=?",
                (it["cantidad"], it["producto_id"])
            )

        conn.execute(
            "UPDATE ventas SET estado='anulada' WHERE id=?", (vid,)
        )
        return jsonify({"ok": True})


@ventas_bp.route("/<int:vid>/devolucion", methods=["POST"])
def devolucion(vid):
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    motivo = data.get("motivo", "")
    items_dev = data.get("items", [])

    with db_session() as conn:
        venta = conn.execute(
            "SELECT * FROM ventas WHERE id=? AND estado='completada'", (vid,)
        ).fetchone()
        if not venta:
            return jsonify({"error": "Venta no disponible para devolución"}), 404

        monto_devuelto = 0
        for it in items_dev:
            pid = int(it.get("producto_id"))
            qty = int(it.get("cantidad", 1))
            orig = conn.execute(
                "SELECT * FROM venta_items WHERE venta_id=? AND producto_id=?",
                (vid, pid)
            ).fetchone()
            if not orig or orig["cantidad"] < qty:
                return jsonify({"error": f"Cantidad de devolución inválida para producto {pid}"}), 400
            monto_devuelto += orig["precio_unit"] * qty
            conn.execute(
                "UPDATE productos SET stock = stock + ? WHERE id=?", (qty, pid)
            )

        conn.execute(
            "INSERT INTO devoluciones (venta_id, usuario_id, motivo, monto) VALUES (?,?,?,?)",
            (vid, uid, motivo, round(monto_devuelto, 2))
        )
        conn.execute("UPDATE ventas SET estado='devuelta' WHERE id=?", (vid,))
        return jsonify({"ok": True, "monto_devuelto": round(monto_devuelto, 2)})


@ventas_bp.route("/resumen/hoy", methods=["GET"])
def resumen_hoy():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        row = conn.execute(
            """SELECT
                COUNT(*) as num_ventas,
                COALESCE(SUM(total), 0) as total_ventas,
                COALESCE(AVG(total), 0) as ticket_promedio
               FROM ventas
               WHERE DATE(creado_en) = DATE('now') AND estado='completada'"""
        ).fetchone()
        return jsonify(dict(row))
