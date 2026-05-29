import io
import base64
import logging
from datetime import date
from flask import Blueprint, request, jsonify, session
from database import db_session, pesos
from routes.direcciones import registrar_direccion_pedido

pedidos_bp = Blueprint("pedidos", __name__, url_prefix="/api")
logger = logging.getLogger("zero_pos.pedidos")

# Estado en memoria para notificación "llamar" en pantalla
_llamar: dict = {"pedido_id": None, "numero": None, "nombre": None, "ts": 0.0}


def _auth():
    return session.get("usuario_id")


def _fmt(n):
    return f"${n:,.0f}".replace(",", ".")


# ─────────────────────────────── CLIENTES ────────────────────────────────────

@pedidos_bp.route("/clientes/buscar", methods=["GET"])
def clientes_buscar():
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    tel = (request.args.get("tel") or request.args.get("telefono") or "").strip()
    if not tel:
        return jsonify(None)
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM clientes WHERE telefono LIKE ?", (f"%{tel}%",)
        ).fetchone()
        if not row:
            return jsonify(None)
        result = dict(row)
        recs = conn.execute(
            """SELECT receptor_nombre as nombre, receptor_tel as tel, COUNT(*) as veces
               FROM pedidos
               WHERE cliente_id=? AND receptor_nombre IS NOT NULL AND receptor_nombre != ''
               GROUP BY receptor_nombre, receptor_tel
               ORDER BY veces DESC LIMIT 3""",
            (row["id"],)
        ).fetchall()
        result["receptores_frecuentes"] = [dict(r) for r in recs]
    return jsonify(result)


@pedidos_bp.route("/clientes/<int:cid>", methods=["GET"])
def clientes_perfil(cid):
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        cliente = conn.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone()
        if not cliente:
            return jsonify({"error": "Cliente no encontrado"}), 404
        cliente = dict(cliente)

        pedidos = conn.execute(
            """SELECT p.id, p.numero, p.tipo, p.estado, p.total, p.metodo_pago,
                      p.direccion, p.notas, p.creado_en
               FROM pedidos p WHERE p.cliente_id=?
               ORDER BY p.creado_en DESC LIMIT 10""",
            (cid,)
        ).fetchall()
        pedidos = [dict(r) for r in pedidos]

        # Add items summary to each pedido
        for p in pedidos:
            items = conn.execute(
                "SELECT nombre, cantidad FROM pedido_items WHERE pedido_id=? ORDER BY id",
                (p["id"],)
            ).fetchall()
            p["items"] = [dict(i) for i in items]

        # Stats: producto favorito
        fav_row = conn.execute(
            """SELECT nombre, SUM(cantidad) as total
               FROM pedido_items pi
               JOIN pedidos p ON pi.pedido_id = p.id
               WHERE p.cliente_id=?
               GROUP BY nombre ORDER BY total DESC LIMIT 1""",
            (cid,)
        ).fetchone()

        # Método de pago habitual
        pago_row = conn.execute(
            """SELECT metodo_pago, COUNT(*) as c FROM pedidos
               WHERE cliente_id=? GROUP BY metodo_pago ORDER BY c DESC LIMIT 1""",
            (cid,)
        ).fetchone()

        # Dirección habitual
        dir_row = conn.execute(
            """SELECT direccion, COUNT(*) as c FROM pedidos
               WHERE cliente_id=? AND direccion IS NOT NULL AND direccion != ''
               GROUP BY direccion ORDER BY c DESC LIMIT 1""",
            (cid,)
        ).fetchone()

        # Notas frecuentes → preferencias detectadas
        notas_rows = conn.execute(
            "SELECT notas FROM pedidos WHERE cliente_id=? AND notas IS NOT NULL AND notas != ''",
            (cid,)
        ).fetchall()

    keywords = ["sin wasabi", "sin cebolla", "sin picante", "sin mariscos",
                "sin gluten", "extra salsa", "poco arroz", "doble porcion"]
    counts: dict[str, int] = {}
    for r in notas_rows:
        txt = r["notas"].lower()
        for kw in keywords:
            if kw in txt:
                counts[kw] = counts.get(kw, 0) + 1

    prefs = []
    for kw, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        if cnt >= 2:
            prefs.append(f"'{kw.title()}' frecuente ({cnt}x)")

    if pago_row and pago_row["metodo_pago"] != "efectivo":
        prefs.append(f"Paga con {pago_row['metodo_pago']}")
    if dir_row and dir_row["c"] >= 2:
        prefs.append(f"Delivery al mismo domicilio ({dir_row['c']}x)")

    stats = {
        "total_pedidos":     cliente["total_pedidos"],
        "total_gastado":     cliente["total_gastado"],
        "producto_favorito": fav_row["nombre"] if fav_row else None,
        "metodo_pago_habitual": pago_row["metodo_pago"] if pago_row else "efectivo",
        "direccion_habitual": dir_row["direccion"] if dir_row else None,
    }

    return jsonify({
        "cliente": cliente,
        "pedidos": pedidos,
        "stats": stats,
        "preferencias_detectadas": prefs,
    })


@pedidos_bp.route("/clientes", methods=["POST"])
def clientes_upsert():
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    tel = (data.get("telefono") or "").strip()
    nombre = (data.get("nombre") or "").strip()
    if not tel or not nombre:
        return jsonify({"error": "nombre y telefono requeridos"}), 400

    with db_session() as conn:
        existing = conn.execute(
            "SELECT id FROM clientes WHERE telefono=?", (tel,)
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE clientes SET nombre=?, telefono2=?, email=?,
                   direccion=?, depto=?, comuna=?, notas=?
                   WHERE id=?""",
                (nombre, data.get("telefono2"), data.get("email"),
                 data.get("direccion"), data.get("depto"),
                 data.get("comuna"), data.get("notas"), existing["id"])
            )
            cid = existing["id"]
        else:
            cur = conn.execute(
                """INSERT INTO clientes
                   (nombre, telefono, telefono2, email, direccion, depto, comuna, notas)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (nombre, tel, data.get("telefono2"), data.get("email"),
                 data.get("direccion"), data.get("depto"),
                 data.get("comuna"), data.get("notas"))
            )
            cid = cur.lastrowid
        row = conn.execute("SELECT * FROM clientes WHERE id=?", (cid,)).fetchone()
    return jsonify(dict(row))


# ─────────────────────────────── PEDIDOS ─────────────────────────────────────

@pedidos_bp.route("/pedidos", methods=["GET"])
def pedidos_listar():
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401

    solo_activos = request.args.get("activos", "0") == "1"
    estado_fil   = request.args.get("estado", "")

    query = """
        SELECT p.*, u.nombre as cajero_nombre
        FROM pedidos p LEFT JOIN usuarios u ON u.id = p.usuario_id
        WHERE 1=1
    """
    params = []
    if solo_activos:
        query += " AND p.estado NOT IN ('despachado','cancelado')"
    if estado_fil:
        query += " AND p.estado=?"
        params.append(estado_fil)

    query += " ORDER BY p.creado_en ASC"

    with db_session() as conn:
        rows = [dict(r) for r in conn.execute(query, params).fetchall()]
        for p in rows:
            items = conn.execute(
                "SELECT * FROM pedido_items WHERE pedido_id=? ORDER BY id",
                (p["id"],)
            ).fetchall()
            p["items"] = [dict(i) for i in items]

    return jsonify(rows)


@pedidos_bp.route("/pedidos/<int:pid>", methods=["GET"])
def pedidos_detalle(pid):
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        pedido = conn.execute("SELECT * FROM pedidos WHERE id=?", (pid,)).fetchone()
        if not pedido:
            return jsonify({"error": "Pedido no encontrado"}), 404
        pedido = dict(pedido)
        items = conn.execute(
            "SELECT * FROM pedido_items WHERE pedido_id=? ORDER BY id", (pid,)
        ).fetchall()
        pedido["items"] = [dict(i) for i in items]
    return jsonify(pedido)


@pedidos_bp.route("/pedidos", methods=["POST"])
def pedidos_crear():
    uid = _auth()
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    tipo   = data.get("tipo", "delivery")
    nombre = (data.get("cliente_nombre") or "").strip()
    items  = data.get("items", [])
    origen = data.get("origen", "pos")  # pos | meson
    estado_inicial = data.get("estado", "nuevo")

    if tipo not in ("delivery", "retiro", "local"):
        return jsonify({"error": "tipo inválido"}), 400
    if tipo != "local" and not nombre:
        return jsonify({"error": "cliente_nombre requerido"}), 400
    if tipo == "local":
        nombre = nombre or "Local"
    if not items:
        return jsonify({"error": "items requeridos"}), 400
    if estado_inicial not in ("nuevo", "en_espera"):
        estado_inicial = "nuevo"

    total = sum(pesos(i.get("subtotal", 0)) for i in items)

    with db_session() as conn:
        # Número diario
        today = date.today().isoformat()
        numero = conn.execute(
            "SELECT COALESCE(MAX(numero),0)+1 FROM pedidos WHERE DATE(creado_en)=?",
            (today,)
        ).fetchone()[0]

        # Buscar o crear cliente
        cliente_id = None
        tel = (data.get("cliente_tel") or "").strip()
        if tel:
            cl = conn.execute(
                "SELECT id FROM clientes WHERE telefono=?", (tel,)
            ).fetchone()
            if cl:
                cliente_id = cl["id"]
                conn.execute(
                    "UPDATE clientes SET nombre=?, direccion=?, depto=?, comuna=? WHERE id=?",
                    (nombre,
                     data.get("direccion") or None,
                     data.get("depto") or None,
                     data.get("comuna") or None,
                     cliente_id)
                )
            else:
                cur = conn.execute(
                    """INSERT INTO clientes
                       (nombre, telefono, telefono2, email, direccion, depto, comuna)
                       VALUES (?,?,?,?,?,?,?)""",
                    (nombre, tel,
                     data.get("cliente_tel2") or None,
                     data.get("cliente_email") or None,
                     data.get("direccion") or None,
                     data.get("depto") or None,
                     data.get("comuna") or None)
                )
                cliente_id = cur.lastrowid

        # Auto-assign nombre for meson pedidos without client name
        if origen == "meson" and not nombre:
            nombre = f"#{numero}"

        cur = conn.execute(
            """INSERT INTO pedidos
               (numero, tipo, estado, origen, cliente_id, cliente_nombre, cliente_tel,
                cliente_tel2, cliente_email, direccion, depto, referencia,
                comuna, notas, total, metodo_pago, usuario_id, receptor_nombre, receptor_tel)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (numero, tipo, estado_inicial, origen, cliente_id, nombre,
             data.get("cliente_tel") or None,
             data.get("cliente_tel2") or None,
             data.get("cliente_email") or None,
             data.get("direccion") or None,
             data.get("depto") or None,
             data.get("referencia") or None,
             data.get("comuna") or None,
             data.get("notas") or None,
             total,
             data.get("metodo_pago", "efectivo"),
             uid,
             data.get("receptor_nombre") or None,
             data.get("receptor_tel") or None)
        )
        pedido_id = cur.lastrowid
        registrar_direccion_pedido(conn, data.get("direccion"), data.get("comuna") or "")

        for item in items:
            subtotal = pesos(item.get("subtotal", 0))
            conn.execute(
                """INSERT INTO pedido_items
                   (pedido_id, producto_id, variante_id, nombre, cantidad, precio, subtotal, notas)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (pedido_id,
                 item.get("producto_id"),
                 item.get("variante_id"),
                 str(item.get("nombre", "")),
                 int(item.get("cantidad", 1)),
                 pesos(item.get("precio", 0)),
                 subtotal,
                 item.get("notas") or None)
            )

        # Update client stats
        if cliente_id:
            conn.execute(
                """UPDATE clientes
                   SET total_pedidos = total_pedidos + 1,
                       total_gastado = total_gastado + ?
                   WHERE id=?""",
                (total, cliente_id)
            )

        pedido = dict(conn.execute("SELECT * FROM pedidos WHERE id=?", (pedido_id,)).fetchone())
        pedido["items"] = [
            dict(r) for r in conn.execute(
                "SELECT * FROM pedido_items WHERE pedido_id=?", (pedido_id,)
            ).fetchall()
        ]

    logger.info(f"Pedido #{numero} ({tipo}) creado — total {_fmt(total)}")
    return jsonify(pedido), 201


@pedidos_bp.route("/pedidos/<int:pid>/estado", methods=["PUT"])
def pedidos_estado(pid):
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    data  = request.get_json(silent=True) or {}
    nuevo = (data.get("estado") or "").strip()
    if nuevo not in ("en_espera", "nuevo", "preparando", "listo", "despachado", "cancelado", "completado"):
        return jsonify({"error": "estado inválido"}), 400

    with db_session() as conn:
        pedido = conn.execute("SELECT id FROM pedidos WHERE id=?", (pid,)).fetchone()
        if not pedido:
            return jsonify({"error": "Pedido no encontrado"}), 404
        conn.execute(
            "UPDATE pedidos SET estado=?, actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
            (nuevo, pid)
        )
        row = dict(conn.execute("SELECT * FROM pedidos WHERE id=?", (pid,)).fetchone())

    return jsonify(row)


@pedidos_bp.route("/pedidos/<int:pid>", methods=["DELETE"])
def pedidos_cancelar(pid):
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        pedido = conn.execute("SELECT id FROM pedidos WHERE id=?", (pid,)).fetchone()
        if not pedido:
            return jsonify({"error": "Pedido no encontrado"}), 404
        conn.execute(
            "UPDATE pedidos SET estado='cancelado', actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
            (pid,)
        )
    return jsonify({"ok": True})


# ─────────────────────────────── COLA MESON ──────────────────────────────────

@pedidos_bp.route("/pedidos/en-espera", methods=["GET"])
def pedidos_en_espera():
    """Lista pedidos en_espera para cola de caja (sin auth para meson.html)."""
    with db_session() as conn:
        rows = conn.execute(
            """SELECT p.*, u.nombre as cajero_nombre
               FROM pedidos p LEFT JOIN usuarios u ON u.id = p.usuario_id
               WHERE p.estado='en_espera'
               ORDER BY p.creado_en ASC"""
        ).fetchall()
        result = []
        for p in rows:
            p = dict(p)
            items = conn.execute(
                "SELECT * FROM pedido_items WHERE pedido_id=? ORDER BY id",
                (p["id"],)
            ).fetchall()
            p["items"] = [dict(i) for i in items]
            result.append(p)
    return jsonify(result)


@pedidos_bp.route("/pedidos/<int:pid>/llamar", methods=["POST"])
def pedidos_llamar(pid):
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    import time
    global _llamar
    with db_session() as conn:
        p = conn.execute("SELECT numero, cliente_nombre FROM pedidos WHERE id=?", (pid,)).fetchone()
        if not p:
            return jsonify({"error": "Pedido no encontrado"}), 404
        _llamar = {
            "pedido_id": pid,
            "numero":    p["numero"],
            "nombre":    p["cliente_nombre"],
            "ts":        time.time(),
        }
    return jsonify({"ok": True})


@pedidos_bp.route("/pedidos/llamar/activo", methods=["GET"])
def pedidos_llamar_activo():
    """Sin auth — meson.html/display polling para mostrar notificación."""
    import time
    if _llamar["ts"] and (time.time() - _llamar["ts"]) < 8:
        return jsonify({
            "activo": True,
            "numero": _llamar["numero"],
            "nombre": _llamar["nombre"],
        })
    return jsonify({"activo": False})


# ─────────────────────────────── QR RUTA ─────────────────────────────────────

@pedidos_bp.route("/pedidos/<int:pid>/qr-ruta", methods=["GET"])
def pedidos_qr_ruta(pid):
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        pedido = conn.execute(
            "SELECT direccion, depto, referencia, comuna, cliente_nombre FROM pedidos WHERE id=?",
            (pid,)
        ).fetchone()
    if not pedido:
        return jsonify({"error": "Pedido no encontrado"}), 404

    partes = [pedido["direccion"] or ""]
    if pedido["depto"]:
        partes.append(f"Depto {pedido['depto']}")
    if pedido["comuna"]:
        partes.append(pedido["comuna"])
    direccion_full = ", ".join(p for p in partes if p)

    if not direccion_full.strip():
        return jsonify({"error": "Sin dirección"}), 400

    maps_url = f"https://maps.google.com/?q={direccion_full.replace(' ', '+')}"

    try:
        import qrcode
        qr = qrcode.QRCode(version=2, box_size=6, border=3)
        qr.add_data(maps_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return jsonify({
            "ok": True,
            "qr_base64": b64,
            "maps_url": maps_url,
            "direccion": direccion_full,
        })
    except ImportError:
        return jsonify({"ok": False, "maps_url": maps_url, "direccion": direccion_full})
