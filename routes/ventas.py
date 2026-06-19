import logging
import re
import threading
from datetime import datetime
from flask import Blueprint, request, jsonify, session
from database import (db_session, pesos, registrar_movimiento_stock, tiene_permiso,
                       encolar_ticket, marcar_ticket_impreso, marcar_ticket_fallido,
                       log_event)
from routes.productos import cache_invalidate as _invalidate_productos

ventas_bp = Blueprint("ventas", __name__, url_prefix="/api/ventas")

# ── Caché de configuración (TTL 60 s) ────────────────────────────────────────
_config_cache: dict = {}
_config_cache_ts: float = 0.0
_CONFIG_TTL = 60  # segundos


def _get_config_cached(conn) -> dict:
    global _config_cache, _config_cache_ts
    import time
    ahora = time.time()
    if ahora - _config_cache_ts < _CONFIG_TTL and _config_cache:
        return _config_cache
    rows = conn.execute("SELECT clave, valor FROM config").fetchall()
    _config_cache = {r["clave"]: r["valor"] for r in rows}
    _config_cache_ts = ahora
    return _config_cache


def invalidar_config_cache() -> None:
    global _config_cache_ts
    _config_cache_ts = 0.0


# ── Estado en memoria para pantalla cliente (Orange Pi = servidor único) ─────
_pantalla: dict = {
    "items": [], "total": 0, "subtotal": 0, "iva": 0,
    "metodo_pago": "", "monto_recibido": 0, "vuelto": 0,
    "estado": "idle", "activa": False,
}

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

    # Verificar descuento máximo permitido por rol
    if descuento_global > 0:
        max_desc_pct = tiene_permiso(dict(session), "descuento_maximo_pct")
        if max_desc_pct is False or max_desc_pct == 0:
            return jsonify({"error": "No tienes permiso para aplicar descuentos"}), 403

    cliente_nombre = data.get("cliente_nombre")
    cliente_rut = (data.get("cliente_rut") or "").strip() or None
    if cliente_rut and not re.match(r'^\d{1,8}-[\dkK]$', cliente_rut):
        return jsonify({"error": "RUT inválido. Formato: 12345678-9"}), 400
    notas = data.get("notas")
    pedido_id = data.get("pedido_id")
    turno_id  = session.get("turno_id")
    empleado  = session.get("usuario_nombre", "")

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
                "SELECT id, nombre, precio, stock, tiene_variantes, modo_stock FROM productos WHERE id=? AND activo=1",
                (pid,)
            ).fetchone()
            if not prod:
                return jsonify({"error": f"Producto {pid} no encontrado"}), 404

            modo_stock = prod["modo_stock"] or "normal"

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
                if modo_stock != "sin_stock" and prod["stock"] < qty:
                    return jsonify({"error": f"Stock insuficiente: {prod['nombre']}"}), 409
                precio_unit = float(prod["precio"])

            # FEFO: si el producto tiene lotes activos, usar el de vencimiento más próximo
            lote_id = item.get("lote_id") or None
            lote_info = None
            if not lote_id:
                lote_row = conn.execute(
                    """SELECT id, numero_lote, fecha_vencimiento, cantidad_actual
                       FROM lotes WHERE producto_id=? AND estado='activo'
                       AND cantidad_actual > 0
                       ORDER BY fecha_vencimiento ASC NULLS LAST LIMIT 1""",
                    (pid,)
                ).fetchone()
                if lote_row:
                    lote_id = lote_row["id"]
                    lote_info = {
                        "id": lote_row["id"],
                        "numero_lote": lote_row["numero_lote"],
                        "vencimiento": lote_row["fecha_vencimiento"],
                    }
            elif lote_id:
                lr = conn.execute(
                    "SELECT id, numero_lote, fecha_vencimiento FROM lotes WHERE id=?", (lote_id,)
                ).fetchone()
                if lr:
                    lote_info = {"id": lr["id"], "numero_lote": lr["numero_lote"],
                                 "vencimiento": lr["fecha_vencimiento"]}

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
                "modo_stock": modo_stock,
                "lote_id": lote_id,
                "lote_info": lote_info,
                "modificadores_desc": item.get("modificadores_desc") or None,
            })

        total = pesos(total - descuento_global)
        config_negocio = _get_config_cached(conn)

        iva_pct = float(config_negocio.get("iva_porcentaje") or 19)
        neto     = pesos(total / (1 + iva_pct / 100))
        impuesto = total - neto

        # Leer config de impresora desde DB (misma fuente que usa test_conexion)
        config_imp = {
            "tipo": config_negocio.get("impresora_tipo", "red"),
            "ip":   config_negocio.get("impresora_ip", "192.168.1.100"),
            "puerto": config_negocio.get("impresora_puerto", "9100"),
        }

        cur = conn.execute(
            """INSERT INTO ventas
               (turno_id, usuario_id, pedido_id, total, descuento, neto, impuesto,
                metodo_pago, cliente_nombre, cliente_rut, notas)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (turno_id, uid, pedido_id, total, descuento_global, neto, impuesto,
             metodo_pago, cliente_nombre, cliente_rut, notas)
        )
        venta_id = cur.lastrowid

        if pedido_id:
            conn.execute(
                "UPDATE pedidos SET estado='completado', actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
                (pedido_id,)
            )

        for it in items_validados:
            conn.execute(
                """INSERT INTO venta_items
                   (venta_id, producto_id, variante_id, nombre_variante,
                    cantidad, precio_unit, descuento, subtotal, lote_id, modificadores_desc)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (venta_id, it["producto_id"], it.get("variante_id"),
                 it.get("nombre_variante"), it["cantidad"],
                 it["precio_unit"], it["descuento"], it["subtotal"],
                 it.get("lote_id"), it.get("modificadores_desc"))
            )
            try:
                if it.get("variante_id"):
                    registrar_movimiento_stock(
                        conn, it["producto_id"], it["variante_id"],
                        "salida", it["cantidad"], "venta", uid, venta_id=venta_id)
                elif it.get("modo_stock") != "sin_stock":
                    registrar_movimiento_stock(
                        conn, it["producto_id"], None,
                        "salida", it["cantidad"], "venta", uid, venta_id=venta_id)
            except ValueError as e:
                conn.rollback()
                return jsonify({"error": str(e)}), 409
            if it.get("modo_stock") != "sin_stock":
                _check_stock_alerta(conn, it["producto_id"])
            # Descontar del lote si aplica
            if it.get("lote_id"):
                conn.execute(
                    """UPDATE lotes
                       SET cantidad_actual = MAX(0, cantidad_actual - ?),
                           estado = CASE WHEN cantidad_actual - ? <= 0 THEN 'agotado' ELSE estado END
                       WHERE id=?""",
                    (it["cantidad"], it["cantidad"], it["lote_id"])
                )

        items_para_ticket = items_validados

        # Cargar datos del pedido asociado (para ticket delivery/retiro)
        pedido_data = None
        if pedido_id:
            row = conn.execute("SELECT * FROM pedidos WHERE id=?", (pedido_id,)).fetchone()
            if row:
                pedido_data = dict(row)

        logger.info(f"Venta #{venta_id} creada por usuario {uid} — total={total}")
        log_event(conn, 'venta', 'crear',
                  entidad_id=venta_id,
                  payload={'total': total, 'metodo': metodo_pago, 'items': len(items_validados)},
                  usuario_id=uid,
                  usuario_nombre=session.get('usuario_nombre'))

    # La transacción ya está committed. Imprimir sin afectar la respuesta.
    try:
        _imprimir_ticket_async(venta_id, total, metodo_pago, items_para_ticket,
                               config_negocio, config_imp, pedido_data, empleado)
    except Exception as e:
        logger.error(f"Error al imprimir ticket venta #{venta_id}: {e}")

    return jsonify({"ok": True, "venta_id": venta_id, "total": total}), 201


def _imprimir_ticket_async(venta_id, total, metodo_pago, items, config_negocio, config_imp,
                           pedido=None, empleado=""):
    """Encola el ticket PRIMERO (la venta ya está guardada), luego imprime en hilo separado.
    Si la impresión falla, el ticket queda en cola para reintento automático.
    La venta NUNCA se pierde aunque falle la impresora."""
    from utils.impresora import _formatear_texto, imprimir_comanda

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    venta_data = {
        "id": venta_id, "total": total, "metodo_pago": metodo_pago,
        "creado_en": now_str, "cajero": empleado, "neto": neto, "impuesto": impuesto,
    }

    # Generar contenido del ticket de forma síncrona antes del hilo
    try:
        contenido = _formatear_texto(venta_data, items, config_negocio, pedido)
    except Exception as e:
        logger.warning(f"Error al formatear ticket #{venta_id}: {e}")
        contenido = f"Venta #{venta_id} — ${total:,}\n{now_str}\n"

    # Guardar en cola ANTES de intentar imprimir
    cola_id = None
    try:
        with db_session() as conn:
            cola_id = encolar_ticket(conn, venta_id, contenido,
                                     config_imp.get("ip") or config_imp.get("tipo"))
    except Exception as e:
        logger.warning(f"Error al encolar ticket #{venta_id}: {e}")

    def _print():
        from utils.impresora import enviar_crudo
        try:
            resultado = enviar_crudo(config_imp, contenido)
            if resultado.get("ok"):
                logger.info(f"Ticket venta #{venta_id} impreso OK")
                if cola_id:
                    try:
                        with db_session() as conn:
                            marcar_ticket_impreso(conn, cola_id)
                    except Exception:
                        pass
            else:
                err = resultado.get("error", "error desconocido")
                logger.warning(f"Impresión venta #{venta_id}: {err}")
                if cola_id:
                    try:
                        with db_session() as conn:
                            marcar_ticket_fallido(conn, cola_id, err)
                    except Exception:
                        pass

            # Comanda de cocina (no se encola, es best-effort)
            if pedido and pedido.get("tipo") in ("delivery", "retiro", "local"):
                ip_cocina = config_negocio.get("impresora_cocina_ip", "")
                if ip_cocina:
                    config_cocina = {
                        "tipo":   config_negocio.get("impresora_cocina_tipo", "red"),
                        "ip":     ip_cocina,
                        "puerto": config_negocio.get("impresora_cocina_puerto", "9100"),
                    }
                    res_c = imprimir_comanda(venta_data, items, config_negocio, config_cocina, pedido)
                    if not res_c.get("ok"):
                        logger.warning(f"Comanda venta #{venta_id}: {res_c.get('error', '')}")
        except Exception as e:
            logger.warning(f"Error al imprimir ticket venta #{venta_id}: {e}")
            if cola_id:
                try:
                    with db_session() as conn:
                        marcar_ticket_fallido(conn, cola_id, str(e))
                except Exception:
                    pass

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
    if not tiene_permiso(dict(session), "puede_anular_ventas"):
        return jsonify({"error": "Sin permisos para anular ventas"}), 403
    uid = session.get("usuario_id")
    motivo = (request.get_json(silent=True) or {}).get('motivo', '')

    with db_session() as conn:
        venta = conn.execute(
            "SELECT * FROM ventas WHERE id=? AND estado='completada'", (vid,)
        ).fetchone()
        if not venta:
            return jsonify({"error": "Venta no encontrada o ya anulada"}), 404

        items = conn.execute(
            "SELECT producto_id, variante_id, cantidad FROM venta_items WHERE venta_id=?", (vid,)
        ).fetchall()
        for it in items:
            registrar_movimiento_stock(
                conn, it["producto_id"], it["variante_id"],
                "entrada", it["cantidad"], "anulacion", uid, venta_id=vid,
                notas=f"Devolución por anulación venta #{vid}")

        conn.execute(
            "UPDATE ventas SET estado='anulada' WHERE id=?", (vid,)
        )
        log_event(conn, 'venta', 'anular',
                  entidad_id=vid,
                  payload={'motivo': motivo} if motivo else None,
                  usuario_id=uid,
                  usuario_nombre=session.get('usuario_nombre'))
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
            registrar_movimiento_stock(
                conn, pid, orig["variante_id"] if "variante_id" in orig.keys() else None,
                "devolucion", qty, motivo or "devolucion", uid, venta_id=vid)

        cur_dev = conn.execute(
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
    pedido_id_rapida = data.get("pedido_id")
    turno_id = session.get("turno_id")

    total = 0
    items_para_ticket = []
    config_negocio = {}
    config_imp = {}
    venta_id = None

    with db_session() as conn:
        config_negocio = _get_config_cached(conn)
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

        total    = pesos(total - descuento_global)
        neto     = pesos(total / (1 + iva_pct / 100))
        impuesto = total - neto

        cur = conn.execute(
            """INSERT INTO ventas
               (turno_id, usuario_id, pedido_id, total, descuento, neto, impuesto, metodo_pago)
               VALUES (?,?,?,?,?,?,?,?)""",
            (turno_id, uid, pedido_id_rapida, total, descuento_global, neto, impuesto, metodo_pago)
        )
        venta_id = cur.lastrowid

        if pedido_id_rapida:
            conn.execute(
                "UPDATE pedidos SET estado='completado', actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
                (pedido_id_rapida,)
            )

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
                           config_negocio, config_imp,
                           empleado=session.get("usuario_nombre", ""))
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
    estado = data.get("estado", "carrito" if items else "idle")
    _pantalla = {
        "items": [
            {
                "nombre":      i.get("nombre", ""),
                "cantidad":    int(i.get("cantidad", 1)),
                "precio_unit": pesos(i.get("precio_unit", 0)),
                "subtotal":    pesos(i.get("subtotal", 0)),
                "imagen_url":  i.get("imagen_url") or None,
            }
            for i in items
        ],
        "total":          pesos(data.get("total", 0)),
        "subtotal":       pesos(data.get("subtotal", 0)),
        "iva":            pesos(data.get("iva", 0)),
        "metodo_pago":    str(data.get("metodo_pago", "")),
        "monto_recibido": pesos(data.get("monto_recibido", 0)),
        "vuelto":         pesos(data.get("vuelto", 0)),
        "estado":         estado,
        "activa":         bool(items),
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
