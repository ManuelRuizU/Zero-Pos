import logging
from flask import Blueprint, request, jsonify, session
from database import db_session

productos_bp = Blueprint("productos", __name__, url_prefix="/api/productos")
logger = logging.getLogger("zero_pos.productos")


def _require_auth():
    return session.get("usuario_id")


@productos_bp.route("", methods=["GET"])
def listar():
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401

    busqueda = request.args.get("q", "").strip()
    categoria_id = request.args.get("categoria_id")
    solo_activos = request.args.get("activos", "1") == "1"
    alerta_stock = request.args.get("alerta_stock", "0") == "1"

    query = """
        SELECT p.*, c.nombre as categoria_nombre
        FROM productos p LEFT JOIN categorias c ON p.categoria_id=c.id
        WHERE 1=1
    """
    params = []

    if solo_activos:
        query += " AND p.activo=1"
    if busqueda:
        query += " AND (p.nombre LIKE ? OR p.codigo_barras LIKE ?)"
        params += [f"%{busqueda}%", f"%{busqueda}%"]
    if categoria_id:
        query += " AND p.categoria_id=?"
        params.append(int(categoria_id))
    if alerta_stock:
        query += " AND p.stock <= p.stock_minimo"

    query += " ORDER BY p.nombre"

    with db_session() as conn:
        rows = conn.execute(query, params).fetchall()
        return jsonify([dict(r) for r in rows])


@productos_bp.route("/<int:pid>", methods=["GET"])
def obtener(pid):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        prod = conn.execute(
            """SELECT p.*, c.nombre as categoria_nombre
               FROM productos p LEFT JOIN categorias c ON p.categoria_id=c.id
               WHERE p.id=?""",
            (pid,)
        ).fetchone()
        if not prod:
            return jsonify({"error": "Producto no encontrado"}), 404
        return jsonify(dict(prod))


@productos_bp.route("/barras/<codigo>", methods=["GET"])
def por_barras(codigo):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        prod = conn.execute(
            "SELECT * FROM productos WHERE codigo_barras=? AND activo=1",
            (codigo,)
        ).fetchone()
        if not prod:
            return jsonify({"error": "Código no encontrado"}), 404
        return jsonify(dict(prod))


@productos_bp.route("", methods=["POST"])
def crear():
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400

    with db_session() as conn:
        cur = conn.execute(
            """INSERT INTO productos
               (nombre, descripcion, precio, precio_costo, stock, stock_minimo,
                codigo_barras, categoria_id, imagen_url)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                nombre,
                data.get("descripcion"),
                float(data.get("precio", 0)),
                float(data.get("precio_costo", 0)),
                int(data.get("stock", 0)),
                int(data.get("stock_minimo", 5)),
                data.get("codigo_barras"),
                data.get("categoria_id"),
                data.get("imagen_url"),
            )
        )
        _registrar_movimiento(conn, cur.lastrowid, "entrada",
                              int(data.get("stock", 0)), "stock_inicial",
                              session.get("usuario_id"))
        return jsonify({"ok": True, "id": cur.lastrowid}), 201


@productos_bp.route("/<int:pid>", methods=["PUT"])
def actualizar(pid):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    campos = {}
    permitidos = ("nombre", "descripcion", "precio", "precio_costo",
                  "stock_minimo", "codigo_barras", "categoria_id",
                  "imagen_url", "activo")
    for campo in permitidos:
        if campo in data:
            campos[campo] = data[campo]

    if not campos:
        return jsonify({"error": "Sin campos para actualizar"}), 400

    set_clause = ", ".join(f"{k}=?" for k in campos)
    valores = list(campos.values()) + [pid]

    with db_session() as conn:
        conn.execute(
            f"UPDATE productos SET {set_clause}, actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
            valores
        )
        return jsonify({"ok": True})


@productos_bp.route("/<int:pid>/stock", methods=["POST"])
def ajustar_stock(pid):
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    tipo = data.get("tipo", "ajuste")
    cantidad = int(data.get("cantidad", 0))
    motivo = data.get("motivo", "")

    if tipo not in ("entrada", "salida", "ajuste"):
        return jsonify({"error": "Tipo inválido"}), 400

    with db_session() as conn:
        prod = conn.execute(
            "SELECT stock FROM productos WHERE id=?", (pid,)
        ).fetchone()
        if not prod:
            return jsonify({"error": "Producto no encontrado"}), 404

        if tipo == "ajuste":
            nuevo_stock = cantidad
        elif tipo == "entrada":
            nuevo_stock = prod["stock"] + cantidad
        else:
            nuevo_stock = max(0, prod["stock"] - cantidad)

        conn.execute(
            "UPDATE productos SET stock=?, actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
            (nuevo_stock, pid)
        )
        _registrar_movimiento(conn, pid, tipo, cantidad, motivo, uid)
        return jsonify({"ok": True, "stock_nuevo": nuevo_stock})


@productos_bp.route("/<int:pid>", methods=["DELETE"])
def eliminar(pid):
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403

    with db_session() as conn:
        conn.execute("UPDATE productos SET activo=0 WHERE id=?", (pid,))
        return jsonify({"ok": True})


# ── Categorías ────────────────────────────────────────────────────────────────

@productos_bp.route("/categorias", methods=["GET"])
def listar_categorias():
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute("SELECT * FROM categorias ORDER BY nombre").fetchall()
        return jsonify([dict(r) for r in rows])


@productos_bp.route("/categorias", methods=["POST"])
def crear_categoria():
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400
    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO categorias (nombre, color, icono) VALUES (?,?,?)",
            (nombre, data.get("color", "#6366f1"), data.get("icono", "📦"))
        )
        return jsonify({"ok": True, "id": cur.lastrowid}), 201


# ── Alertas stock ─────────────────────────────────────────────────────────────

@productos_bp.route("/alertas", methods=["GET"])
def alertas():
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute(
            """SELECT a.*, p.nombre as producto_nombre, p.stock, p.stock_minimo
               FROM alertas_stock a JOIN productos p ON a.producto_id=p.id
               WHERE a.leida=0 ORDER BY a.creado_en DESC"""
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@productos_bp.route("/alertas/<int:aid>/leer", methods=["POST"])
def marcar_alerta(aid):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        conn.execute("UPDATE alertas_stock SET leida=1 WHERE id=?", (aid,))
        return jsonify({"ok": True})


def _registrar_movimiento(conn, producto_id, tipo, cantidad, motivo, usuario_id):
    conn.execute(
        """INSERT INTO stock_movimientos (producto_id, tipo, cantidad, motivo, usuario_id)
           VALUES (?,?,?,?,?)""",
        (producto_id, tipo, cantidad, motivo, usuario_id)
    )
