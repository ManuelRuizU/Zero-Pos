import json
import logging
import time
import urllib.request
import urllib.error
from pathlib import Path
from flask import Blueprint, request, jsonify, session
from database import db_session

BASE_DIR = Path(__file__).parent.parent
PRODUCTOS_BASE_FILE = BASE_DIR / "data" / "productos_base.json"

productos_bp = Blueprint("productos", __name__, url_prefix="/api/productos")
logger = logging.getLogger("zero_pos.productos")

@productos_bp.after_request
def _invalidate_on_write(response):
    if request.method in ("POST", "PUT", "DELETE", "PATCH") and response.status_code < 400:
        cache_invalidate()
    return response

# Simple in-process cache for the full product list (no filters)
_CACHE: dict = {}
_CACHE_TS: dict = {}
_CACHE_TTL = 60  # seconds

def _cache_get(key: str):
    if key in _CACHE and time.monotonic() - _CACHE_TS.get(key, 0) < _CACHE_TTL:
        return _CACHE[key]
    return None

def _cache_set(key: str, value):
    _CACHE[key] = value
    _CACHE_TS[key] = time.monotonic()

def cache_invalidate():
    """Call after any product write (create/update/delete/stock change)."""
    _CACHE.clear()
    _CACHE_TS.clear()


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

    # Cache only the standard POS load (no filters, active only)
    cache_key = None
    if not busqueda and not categoria_id and solo_activos and not alerta_stock:
        cache_key = "productos_activos"
        cached = _cache_get(cache_key)
        if cached is not None:
            return jsonify(cached)

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
        rows = [dict(r) for r in conn.execute(query, params).fetchall()]

    if cache_key:
        _cache_set(cache_key, rows)

    return jsonify(rows)


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
    """Busca en DB local. Para lookup completo usar /barras/<codigo>/lookup."""
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        # Busca en producto padre
        prod = conn.execute(
            "SELECT * FROM productos WHERE codigo_barras=? AND activo=1", (codigo,)
        ).fetchone()
        if prod:
            return jsonify(dict(prod))
        # Busca en variantes
        variante = conn.execute(
            """SELECT pv.*, p.nombre as producto_nombre, p.id as producto_id_padre
               FROM producto_variantes pv
               JOIN productos p ON pv.producto_id=p.id
               WHERE pv.codigo_barras=? AND pv.activo=1""",
            (codigo,)
        ).fetchone()
        if variante:
            return jsonify({**dict(variante), "es_variante": True})
        return jsonify({"error": "Código no encontrado"}), 404


@productos_bp.route("/barras/<codigo>/lookup", methods=["GET"])
def lookup_barras(codigo):
    """Lookup progresivo: DB local → productos_base.json → Open Food Facts."""
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        prod = conn.execute(
            "SELECT p.*, c.nombre as categoria_nombre FROM productos p "
            "LEFT JOIN categorias c ON p.categoria_id=c.id "
            "WHERE p.codigo_barras=? AND p.activo=1", (codigo,)
        ).fetchone()
        if prod:
            return jsonify({"fuente": "local", "encontrado": True, **dict(prod)})

        variante = conn.execute(
            """SELECT pv.*, p.nombre as producto_nombre, p.id as producto_id_padre,
                      p.categoria_id, c.nombre as categoria_nombre
               FROM producto_variantes pv
               JOIN productos p ON pv.producto_id=p.id
               LEFT JOIN categorias c ON p.categoria_id=c.id
               WHERE pv.codigo_barras=? AND pv.activo=1""",
            (codigo,)
        ).fetchone()
        if variante:
            return jsonify({"fuente": "local", "encontrado": True,
                            "es_variante": True, **dict(variante)})

    # Buscar en productos_base.json
    resultado_json = _buscar_en_json(codigo)
    if resultado_json:
        return jsonify({"fuente": "catalogo_base", "encontrado": True, **resultado_json})

    # Consultar Open Food Facts
    resultado_off = _buscar_open_food_facts(codigo)
    if resultado_off:
        return jsonify({"fuente": "open_food_facts", "encontrado": True, **resultado_off})

    return jsonify({"encontrado": False, "codigo": codigo,
                    "sugerencia": "Producto no encontrado. Ingresa nombre y precio."})


def _buscar_en_json(codigo: str) -> dict | None:
    if not PRODUCTOS_BASE_FILE.exists():
        return None
    try:
        data = json.loads(PRODUCTOS_BASE_FILE.read_text(encoding="utf-8"))
        for tipo_data in data.values():
            for prod in tipo_data.get("productos", []):
                for v in prod.get("variantes", []):
                    if v.get("codigo_barras") == codigo:
                        return {
                            "nombre": prod["nombre"],
                            "nombre_variante": v["nombre"],
                            "precio_sugerido": v["precio"],
                            "categoria_sugerida": prod.get("categoria", ""),
                        }
    except Exception:
        pass
    return None


def _buscar_open_food_facts(codigo: str) -> dict | None:
    try:
        url = f"https://world.openfoodfacts.org/api/v0/product/{codigo}.json"
        req = urllib.request.Request(url, headers={"User-Agent": "ZeroPOS/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
        if data.get("status") != 1:
            return None
        product = data.get("product", {})
        nombre = (product.get("product_name_es")
                  or product.get("product_name")
                  or product.get("abbreviated_product_name")
                  or "").strip()
        if not nombre:
            return None
        return {
            "nombre": nombre,
            "marca": product.get("brands", ""),
            "categoria_sugerida": product.get("categories_tags", [""])[0].replace("en:", "").replace("-", " ").title() if product.get("categories_tags") else "",
            "imagen_url": product.get("image_thumb_url", ""),
            "precio_sugerido": None,
        }
    except Exception:
        return None


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


# ── Variantes ─────────────────────────────────────────────────────────────────

@productos_bp.route("/<int:pid>/variantes", methods=["GET"])
def listar_variantes(pid):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM producto_variantes WHERE producto_id=? AND activo=1 ORDER BY id",
            (pid,)
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@productos_bp.route("/<int:pid>/variantes", methods=["POST"])
def crear_variante(pid):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400

    with db_session() as conn:
        cur = conn.execute(
            """INSERT INTO producto_variantes
               (producto_id, nombre, precio, precio_costo, stock, stock_minimo, codigo_barras)
               VALUES (?,?,?,?,?,?,?)""",
            (pid, nombre,
             float(data.get("precio", 0)),
             float(data.get("precio_costo", 0)),
             int(data.get("stock", 0)),
             int(data.get("stock_minimo", 5)),
             data.get("codigo_barras"))
        )
        conn.execute(
            "UPDATE productos SET tiene_variantes=1 WHERE id=?", (pid,)
        )
        return jsonify({"ok": True, "id": cur.lastrowid}), 201


@productos_bp.route("/<int:pid>/variantes/<int:vid>", methods=["PUT"])
def actualizar_variante(pid, vid):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    campos = {}
    for campo in ("nombre", "precio", "precio_costo", "stock", "stock_minimo",
                  "codigo_barras", "activo"):
        if campo in data:
            campos[campo] = data[campo]
    if not campos:
        return jsonify({"error": "Sin cambios"}), 400
    set_clause = ", ".join(f"{k}=?" for k in campos)
    with db_session() as conn:
        conn.execute(
            f"UPDATE producto_variantes SET {set_clause} WHERE id=? AND producto_id=?",
            list(campos.values()) + [vid, pid]
        )
        return jsonify({"ok": True})


@productos_bp.route("/<int:pid>/variantes/<int:vid>/stock", methods=["POST"])
def ajustar_stock_variante(pid, vid):
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    tipo = data.get("tipo", "ajuste")
    cantidad = int(data.get("cantidad", 0))

    with db_session() as conn:
        v = conn.execute(
            "SELECT stock FROM producto_variantes WHERE id=? AND producto_id=?", (vid, pid)
        ).fetchone()
        if not v:
            return jsonify({"error": "Variante no encontrada"}), 404

        if tipo == "ajuste":
            nuevo = cantidad
        elif tipo == "entrada":
            nuevo = v["stock"] + cantidad
        else:
            nuevo = max(0, v["stock"] - cantidad)

        conn.execute(
            "UPDATE producto_variantes SET stock=? WHERE id=?", (nuevo, vid)
        )
        _registrar_movimiento(conn, pid, tipo, cantidad, data.get("motivo", ""), uid)
        return jsonify({"ok": True, "stock_nuevo": nuevo})


# ── Subcategorías ──────────────────────────────────────────────────────────────

@productos_bp.route("/subcategorias", methods=["GET"])
def listar_subcategorias():
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    cat_id = request.args.get("categoria_id")
    with db_session() as conn:
        if cat_id:
            rows = conn.execute(
                "SELECT * FROM subcategorias WHERE categoria_id=? ORDER BY nombre", (int(cat_id),)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT s.*, c.nombre as categoria_nombre FROM subcategorias s "
                "JOIN categorias c ON s.categoria_id=c.id ORDER BY c.nombre, s.nombre"
            ).fetchall()
        return jsonify([dict(r) for r in rows])
