import logging
from datetime import datetime
from flask import Blueprint, request, jsonify, session
from database import db_session, pesos
from routes.productos import cache_invalidate as _invalidate_productos

ventas_bp = Blueprint("ventas", __name__, url_prefix="/api/ventas")

# Estado en memoria para pantalla cliente (Orange Pi = servidor único)
_pantalla: dict = {"items": [], "total": 0, "activa": False}

@ventas_bp.after_request
def _invalidate_on_venta(response):
    if request.method == "POST" and response.status_code < 400:
        _invalidate_productos()
    return response
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

    venta_id = None
    total = 0
    items_para_ticket = []
    config_negocio = {}
    config_imp = {}

    with db_session() as conn:
        items_validados = []

        for item in items:
            pid = int(item.get("producto_id", 0))
            qty = int(item.get("cantidad", 1))
            descuento_item = float(item.get("descuento", 0))
            variante_id = item.get("variante_id")
            nombre_variante = item.get("nombre_variante", "")

            prod = conn.execute(
                "SELECT id, nombre, precio, stock, tiene_variantes FROM productos WHERE id=? AND activo=1",
                (pid,)
            ).fetchone()
            if not prod:
                return jsonify({"error": f"Producto {pid} no encontrado"}), 404

            if variante_id:
                # Validar stock de la variante específica
                v = conn.execute(
                    "SELECT precio, stock FROM producto_variantes WHERE id=? AND producto_id=? AND activo=1",
                    (variante_id, pid)
                ).fetchone()
                if not v:
                    return jsonify({"error": f"Variante no encontrada para {prod['nombre']}"}), 404
                if v["stock"] < qty:
                    return jsonify({"error": f"Stock insuficiente: {prod['nombre']} ({nombre_variante})"}), 409
                precio_unit = float(v["precio"])
            else:
                if prod["stock"] < qty:
                    return jsonify({"error": f"Stock insuficiente: {prod['nombre']}"}), 409
                precio_unit = float(prod["precio"])

            subtotal = pesos((precio_unit * qty) - descuento_item)
            total += subtotal
            items_validados.append({
                "producto_id": pid,
                "producto_nombre": prod["nombre"],
                "variante_id": variante_id,
                "nombre_variante": nombre_variante,
                "cantidad": qty,
                "precio_unit": pesos(precio_unit),
                "descuento": pesos(descuento_item),
                "subtotal": subtotal,
            })

        total = pesos(total - descuento_global)
        cfg_rows = conn.execute("SELECT clave, valor FROM config").fetchall()
        config_negocio = {r["clave"]: r["valor"] for r in cfg_rows}

        iva_pct = float(config_negocio.get("iva_porcentaje") or 19)
        impuesto = pesos(total * iva_pct / (100 + iva_pct))

        # Leer config de impresora desde DB (misma fuente que usa test_conexion)
        config_imp = {
            "tipo": config_negocio.get("impresora_tipo", "red"),
            "ip":   config_negocio.get("impresora_ip", "192.168.1.100"),
            "puerto": config_negocio.get("impresora_puerto", "9100"),
        }

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
                   (venta_id, producto_id, variante_id, nombre_variante,
                    cantidad, precio_unit, descuento, subtotal)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (venta_id, it["producto_id"], it.get("variante_id"),
                 it.get("nombre_variante"), it["cantidad"],
                 it["precio_unit"], it["descuento"], it["subtotal"])
            )
            if it.get("variante_id"):
                conn.execute(
                    "UPDATE producto_variantes SET stock = stock - ? WHERE id=?",
                    (it["cantidad"], it["variante_id"])
                )
            else:
                conn.execute(
                    "UPDATE productos SET stock = stock - ? WHERE id=?",
                    (it["cantidad"], it["producto_id"])
                )
            _check_stock_alerta(conn, it["producto_id"])

        items_para_ticket = items_validados
        logger.info(f"Venta #{venta_id} creada por usuario {uid} — total={total}")

    # La transacción ya está committed. Imprimir sin afectar la respuesta.
    _imprimir_ticket_async(venta_id, total, metodo_pago, items_para_ticket,
                           config_negocio, config_imp)

    return jsonify({"ok": True, "venta_id": venta_id, "total": total}), 201


def _imprimir_ticket_async(venta_id, total, metodo_pago, items, config_negocio, config_imp):
    """Imprime en hilo separado para no bloquear la respuesta HTTP."""
    import threading

    def _print():
        try:
            from utils.impresora import imprimir_recibo
            venta_data = {
                "id": venta_id,
                "total": total,
                "metodo_pago": metodo_pago,
                "creado_en": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            resultado = imprimir_recibo(venta_data, items, config_negocio, config_imp)
            if resultado.get("ok"):
                logger.info(f"Ticket venta #{venta_id} impreso OK")
            else:
                logger.warning(f"Impresión venta #{venta_id}: {resultado.get('error', 'error desconocido')}")
        except Exception as e:
            logger.warning(f"Error al imprimir ticket venta #{venta_id}: {e}")

    threading.Thread(target=_print, daemon=True, name=f"ticket-{venta_id}").start()


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
            (vid, uid, motivo, pesos(monto_devuelto))
        )
        conn.execute("UPDATE ventas SET estado='devuelta' WHERE id=?", (vid,))
        return jsonify({"ok": True, "monto_devuelto": pesos(monto_devuelto)})


@ventas_bp.route("/rapida", methods=["POST"])
def venta_rapida():
    """Venta rápida: items con nombre libre y precio, sin producto en catálogo."""
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    items = data.get("items", [])
    if not items:
        return jsonify({"error": "Carrito vacío"}), 400

    metodo_pago = data.get("metodo_pago", "efectivo")
    descuento_global = float(data.get("descuento", 0))
    guardar_productos = data.get("guardar_productos", False)
    turno_id = session.get("turno_id")

    total = 0
    items_para_ticket = []
    config_negocio = {}
    config_imp = {}
    venta_id = None

    with db_session() as conn:
        cfg_rows = conn.execute("SELECT clave, valor FROM config").fetchall()
        config_negocio = {r["clave"]: r["valor"] for r in cfg_rows}
        config_imp = {
            "tipo": config_negocio.get("impresora_tipo", "red"),
            "ip": config_negocio.get("impresora_ip", "192.168.1.100"),
            "puerto": config_negocio.get("impresora_puerto", "9100"),
        }

        # Obtener o crear categoría "Venta Rápida"
        cat = conn.execute(
            "SELECT id FROM categorias WHERE nombre='Venta Rápida'"
        ).fetchone()
        if not cat:
            cur_cat = conn.execute(
                "INSERT INTO categorias (nombre, icono, color) VALUES ('Venta Rápida','⚡','#6366f1')"
            )
            cat_id = cur_cat.lastrowid
        else:
            cat_id = cat["id"]

        iva_pct = float(config_negocio.get("iva_porcentaje") or 19)
        items_validados = []

        for item in items:
            nombre = str(item.get("nombre", "Producto")).strip() or "Producto"
            precio_unit = float(item.get("precio_unit", 0))
            qty = int(item.get("cantidad", 1))

            # Crear producto temporal (activo según guardar_productos)
            cur_prod = conn.execute(
                """INSERT INTO productos
                   (nombre, precio, stock, stock_minimo, categoria_id, activo)
                   VALUES (?,?,?,0,?,?)""",
                (nombre, precio_unit, qty, cat_id, 1 if guardar_productos else 0)
            )
            prod_id = cur_prod.lastrowid

            subtotal = pesos(precio_unit * qty)
            total += subtotal
            items_validados.append({
                "producto_id": prod_id,
                "producto_nombre": nombre,
                "variante_id": None,
                "nombre_variante": "",
                "cantidad": qty,
                "precio_unit": pesos(precio_unit),
                "descuento": 0,
                "subtotal": subtotal,
            })

        total = pesos(total - descuento_global)
        impuesto = pesos(total * iva_pct / (100 + iva_pct))

        cur = conn.execute(
            """INSERT INTO ventas
               (turno_id, usuario_id, total, descuento, impuesto, metodo_pago)
               VALUES (?,?,?,?,?,?)""",
            (turno_id, uid, total, descuento_global, impuesto, metodo_pago)
        )
        venta_id = cur.lastrowid

        for it in items_validados:
            conn.execute(
                """INSERT INTO venta_items
                   (venta_id, producto_id, cantidad, precio_unit, descuento, subtotal)
                   VALUES (?,?,?,?,0,?)""",
                (venta_id, it["producto_id"], it["cantidad"],
                 it["precio_unit"], it["subtotal"])
            )
        items_para_ticket = items_validados
        logger.info(f"Venta rápida #{venta_id} — total={total}")

    _imprimir_ticket_async(venta_id, total, metodo_pago, items_para_ticket,
                           config_negocio, config_imp)
    return jsonify({"ok": True, "venta_id": venta_id, "total": total}), 201


@ventas_bp.route("/pantalla-cliente", methods=["GET"])
def pantalla_cliente_get():
    """Sin autenticación — la red local es el perímetro de seguridad."""
    return jsonify(_pantalla)


@ventas_bp.route("/pantalla-cliente/estado", methods=["POST"])
def pantalla_cliente_set():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    global _pantalla
    data = request.get_json(silent=True) or {}
    items = data.get("items", [])
    _pantalla = {
        "items": [
            {
                "nombre":    i.get("nombre", ""),
                "cantidad":  int(i.get("cantidad", 1)),
                "precio_unit": pesos(i.get("precio_unit", 0)),
                "subtotal":  pesos(i.get("subtotal", 0)),
            }
            for i in items
        ],
        "total":  pesos(data.get("total", 0)),
        "activa": bool(items),
    }
    return jsonify({"ok": True})


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
