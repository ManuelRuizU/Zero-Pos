import logging
from flask import Blueprint, request, jsonify, session
from database import db_session

impresora_bp = Blueprint("impresora", __name__, url_prefix="/api/impresora")
logger = logging.getLogger("zero_pos.impresora")


@impresora_bp.route("/ticket/<int:venta_id>", methods=["POST"])
def imprimir_ticket(venta_id):
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    pedido = None
    with db_session() as conn:
        venta = conn.execute(
            """SELECT v.*, u.nombre as cajero
               FROM ventas v LEFT JOIN usuarios u ON u.id = v.usuario_id
               WHERE v.id=?""",
            (venta_id,)
        ).fetchone()
        if not venta:
            return jsonify({"error": "Venta no encontrada"}), 404

        items = conn.execute(
            """SELECT vi.cantidad, vi.precio_unit, vi.subtotal,
                      p.nombre as producto_nombre, vi.notas
               FROM venta_items vi JOIN productos p ON vi.producto_id=p.id
               WHERE vi.venta_id=?""",
            (venta_id,)
        ).fetchall()

        pid = venta["pedido_id"] if "pedido_id" in venta.keys() else None
        if pid:
            row = conn.execute("SELECT * FROM pedidos WHERE id=?", (pid,)).fetchone()
            if row:
                pedido = dict(row)

        cfg = conn.execute("SELECT clave, valor FROM config").fetchall()
        config = {r["clave"]: r["valor"] for r in cfg}

        fiado_info = None
        if venta["metodo_pago"] == "credito":
            mov = conn.execute(
                """SELECT fm.monto, fm.deuda_antes, fm.deuda_despues,
                          cf.nombre, cf.apellido, cf.qr_token, cf.limite_credito
                   FROM fiado_movimientos fm
                   JOIN clientes_fiado cf ON cf.id = fm.cliente_id
                   WHERE fm.venta_id=? AND fm.tipo='cargo'
                   ORDER BY fm.id DESC LIMIT 1""",
                (venta_id,)
            ).fetchone()
            if mov:
                fiado_info = dict(mov)
                fiado_info["ip_local"] = config.get("ip_local", "127.0.0.1")

    config_imp = {
        "tipo":   config.get("impresora_tipo", "red"),
        "ip":     config.get("impresora_ip", "192.168.1.100"),
        "puerto": config.get("impresora_puerto", "9100"),
    }

    from utils.impresora import imprimir_recibo
    resultado = imprimir_recibo(dict(venta), [dict(i) for i in items], config, config_imp,
                                pedido=pedido, fiado_info=fiado_info)
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


@impresora_bp.route("/estado", methods=["GET"])
def estado_impresora():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        cfg_rows = conn.execute(
            "SELECT clave, valor FROM config WHERE clave LIKE 'impresora_%'"
        ).fetchall()
        cfg = {r["clave"]: r["valor"] for r in cfg_rows}

        cola_pendiente = conn.execute(
            "SELECT COUNT(*) FROM cola_impresion WHERE estado='pendiente'"
        ).fetchone()[0]

        ultimo_error = conn.execute(
            "SELECT error_msg FROM cola_impresion WHERE estado IN ('pendiente','fallido') "
            "AND error_msg IS NOT NULL ORDER BY actualizado_en DESC LIMIT 1"
        ).fetchone()

    config_imp = {
        "tipo":   cfg.get("impresora_tipo", "red"),
        "ip":     cfg.get("impresora_ip", ""),
        "puerto": cfg.get("impresora_puerto", "9100"),
    }

    if not config_imp["ip"] and config_imp["tipo"] == "red":
        return jsonify({
            "conectada": False, "papel": "desconocido",
            "sin_papel": False, "poco_papel": False,
            "pendientes": cola_pendiente,
            "ultimo_error": "Impresora no configurada",
        })

    from utils.impresora import estado_impresora as _estado
    estado = _estado(config_imp)
    papel = estado.get("papel", "ok")

    return jsonify({
        "conectada":   estado["conectada"],
        "papel":       papel,
        "sin_papel":   papel == "sin_papel",
        "poco_papel":  papel == "poco_papel",
        "pendientes":  cola_pendiente,
        "ultimo_error": estado.get("error") or (ultimo_error["error_msg"] if ultimo_error else None),
    })


@impresora_bp.route("/reimprimir", methods=["POST"])
def reimprimir():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    if data.get("accion") == "procesar_pendientes":
        import threading
        from flask import current_app
        flask_app = current_app._get_current_object()
        def _run():
            from database import db_session, marcar_ticket_impreso, marcar_ticket_fallido
            from utils.impresora import enviar_crudo
            with flask_app.app_context():
                try:
                    with db_session() as conn:
                        cfg_rows = conn.execute("SELECT clave, valor FROM config WHERE clave LIKE 'impresora_%'").fetchall()
                        cfg = {r["clave"]: r["valor"] for r in cfg_rows}
                        pendientes = conn.execute(
                            "SELECT id, contenido FROM cola_impresion "
                            "WHERE estado IN ('pendiente','fallido') AND intentos < 3 ORDER BY id ASC LIMIT 10"
                        ).fetchall()
                    config_imp = {"tipo": cfg.get("impresora_tipo","red"), "ip": cfg.get("impresora_ip",""), "puerto": cfg.get("impresora_puerto","9100")}
                    for row in pendientes:
                        res = enviar_crudo(config_imp, row["contenido"])
                        with db_session() as conn2:
                            if res.get("ok"):
                                marcar_ticket_impreso(conn2, row["id"])
                            else:
                                marcar_ticket_fallido(conn2, row["id"], res.get("error",""))
                except Exception:
                    pass
        threading.Thread(target=_run, daemon=True).start()
        return jsonify({"ok": True, "mensaje": "Cola de impresión procesándose"})

    venta_id = data.get("venta_id")
    cola_id  = data.get("cola_id")

    with db_session() as conn:
        cfg_rows = conn.execute("SELECT clave, valor FROM config WHERE clave LIKE 'impresora_%'").fetchall()
        cfg = {r["clave"]: r["valor"] for r in cfg_rows}

        contenido = None
        if cola_id:
            row = conn.execute("SELECT contenido FROM cola_impresion WHERE id=?", (cola_id,)).fetchone()
            if row:
                contenido = row["contenido"]

        if not contenido and venta_id:
            # Regenerar ticket desde la venta
            venta = conn.execute(
                "SELECT v.*, u.nombre as cajero FROM ventas v LEFT JOIN usuarios u ON u.id=v.usuario_id WHERE v.id=?",
                (venta_id,)
            ).fetchone()
            items = conn.execute(
                "SELECT vi.cantidad, vi.precio_unit, vi.subtotal, p.nombre as producto_nombre, vi.notas "
                "FROM venta_items vi JOIN productos p ON vi.producto_id=p.id WHERE vi.venta_id=?",
                (venta_id,)
            ).fetchall()
            config_all = {r["clave"]: r["valor"] for r in conn.execute("SELECT clave, valor FROM config").fetchall()}
            pedido = None
            pid = dict(venta).get("pedido_id") if venta else None
            if pid:
                row = conn.execute("SELECT * FROM pedidos WHERE id=?", (pid,)).fetchone()
                if row:
                    pedido = dict(row)
            if venta:
                from utils.impresora import _formatear_texto
                contenido = _formatear_texto(dict(venta), [dict(i) for i in items], config_all, pedido)

        if not contenido:
            return jsonify({"error": "No se encontró el ticket"}), 404

        # Agregar a la cola con estado pendiente (prioridad: al frente)
        new_id = conn.execute(
            "INSERT INTO cola_impresion (venta_id, contenido, estado) VALUES (?,?,'pendiente')",
            (venta_id, contenido)
        ).lastrowid

    # Intentar imprimir ahora mismo
    config_imp = {
        "tipo":   cfg.get("impresora_tipo", "red"),
        "ip":     cfg.get("impresora_ip", ""),
        "puerto": cfg.get("impresora_puerto", "9100"),
    }
    from utils.impresora import enviar_crudo
    from database import marcar_ticket_impreso, marcar_ticket_fallido
    resultado = enviar_crudo(config_imp, contenido)
    try:
        with db_session() as conn2:
            if resultado.get("ok"):
                marcar_ticket_impreso(conn2, new_id)
            else:
                marcar_ticket_fallido(conn2, new_id, resultado.get("error", ""))
    except Exception:
        pass

    return jsonify({
        "ok": resultado.get("ok", False),
        "cola_id": new_id,
        "error": resultado.get("error") if not resultado.get("ok") else None,
    })
