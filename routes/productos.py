import json
import logging
import time
import unicodedata
import urllib.request
import urllib.error
from pathlib import Path
from flask import Blueprint, request, jsonify, session
from database import db_session, tiene_permiso
from scripts.clasificar_productos import clasificar_producto, obtener_o_crear_categoria
from utils.normalizar import normalizar_nombre

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


def _generar_sku(cat_nombre: str, producto_id: int) -> str:
    clean = "".join(
        c for c in unicodedata.normalize("NFKD", (cat_nombre or "").upper())
        if c.isascii() and c.isalpha()
    )
    return f"{clean[:3] or 'PRD'}-{producto_id:05d}"


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
        SELECT p.*, c.nombre as categoria_nombre, m.nombre as marca_nombre
        FROM productos p
        LEFT JOIN categorias c ON p.categoria_id=c.id
        LEFT JOIN marcas m ON p.marca_id=m.id
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


@productos_bp.route("/completos", methods=["GET"])
def listar_completos():
    """Todos los productos activos con sus variantes en una sola query JOIN."""
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401

    sucursal_id = session.get("sucursal_id")
    # Con sucursal: no usar caché global (cada sucursal tiene su catálogo)
    cache_key = f"productos_completos_s{sucursal_id}" if sucursal_id else "productos_completos"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(cached)

    suc_cond = "AND p.sucursal_id=?" if sucursal_id else ""
    suc_param = [sucursal_id] if sucursal_id else []

    with db_session() as conn:
        rows = conn.execute(f"""
            SELECT p.id, p.nombre, p.precio, p.precio_costo, p.stock,
                   p.stock_minimo, p.codigo_barras, p.categoria_id,
                   p.subcategoria_id, p.tiene_variantes,
                   p.es_granel, p.unidad_medida, p.precio_por,
                   p.modo_stock, p.hora_reset_stock,
                   p.imagen_url, p.descripcion, c.nombre as categoria_nombre,
                   v.id as v_id, v.nombre as v_nombre,
                   v.precio as v_precio, v.stock as v_stock,
                   v.codigo_barras as v_barras
            FROM productos p
            LEFT JOIN categorias c ON c.id = p.categoria_id
            LEFT JOIN producto_variantes v
                   ON v.producto_id = p.id AND v.activo = 1
            WHERE p.activo = 1 {suc_cond}
            ORDER BY p.nombre, v.id
        """, suc_param).fetchall()

    productos: dict = {}
    for r in rows:
        pid = r["id"]
        if pid not in productos:
            productos[pid] = {
                "id":             pid,
                "nombre":         r["nombre"],
                "precio":         r["precio"],
                "precio_costo":   r["precio_costo"],
                "stock":          r["stock"],
                "stock_minimo":   r["stock_minimo"],
                "codigo_barras":  r["codigo_barras"],
                "categoria_id":   r["categoria_id"],
                "subcategoria_id": r["subcategoria_id"],
                "tiene_variantes": r["tiene_variantes"],
                "es_granel":       r["es_granel"] if "es_granel" in r.keys() else 0,
                "unidad_medida":   r["unidad_medida"] if "unidad_medida" in r.keys() else "unidad",
                "precio_por":      r["precio_por"] if "precio_por" in r.keys() else "unidad",
                "modo_stock":      r["modo_stock"] if "modo_stock" in r.keys() else "normal",
                "hora_reset_stock": r["hora_reset_stock"] if "hora_reset_stock" in r.keys() else "06:00",
                "imagen_url":      r["imagen_url"],
                "descripcion":    r["descripcion"],
                "categoria_nombre": r["categoria_nombre"],
                "_variantes":     [],
            }
        if r["v_id"] is not None:
            productos[pid]["_variantes"].append({
                "id":            r["v_id"],
                "nombre":        r["v_nombre"],
                "precio":        r["v_precio"],
                "stock":         r["v_stock"],
                "codigo_barras": r["v_barras"],
            })

    result = list(productos.values())
    for p in result:
        if p["_variantes"]:
            p["stock_real"] = sum(v["stock"] for v in p["_variantes"])
        else:
            p["stock_real"] = p["stock"]
    _cache_set(cache_key, result)
    return jsonify(result)


@productos_bp.route("/<int:pid>", methods=["GET"])
def obtener(pid):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        prod = conn.execute(
            """SELECT p.*, c.nombre as categoria_nombre, m.nombre as marca_nombre
               FROM productos p
               LEFT JOIN categorias c ON p.categoria_id=c.id
               LEFT JOIN marcas m ON p.marca_id=m.id
               WHERE p.id=?""",
            (pid,)
        ).fetchone()
        if not prod:
            return jsonify({"error": "Producto no encontrado"}), 404
        return jsonify(dict(prod))


@productos_bp.route("/detectar-codigo", methods=["POST"])
def detectar_codigo():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    archivo = request.files.get("imagen")
    if not archivo:
        return jsonify({"error": "Imagen requerida"}), 400

    try:
        from PIL import Image
        from pyzbar import pyzbar as _pyzbar
        import io

        img_bytes = archivo.read()
        img = Image.open(io.BytesIO(img_bytes))
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        codigos = _pyzbar.decode(img)

        if not codigos:
            w, h = img.size
            centro = img.crop((int(w * 0.1), int(h * 0.1), int(w * 0.9), int(h * 0.9)))
            codigos = _pyzbar.decode(centro)

        if not codigos:
            img_small = img.resize((800, 600), Image.LANCZOS)
            codigos = _pyzbar.decode(img_small)

        if not codigos:
            gris = img.convert("L")
            codigos = _pyzbar.decode(gris)

        if codigos:
            codigo = codigos[0].data.decode("utf-8")
            tipo = codigos[0].type
            logger.info(f"Código detectado: {codigo} ({tipo})")
            return jsonify({"ok": True, "codigo": codigo, "tipo": tipo})

        return jsonify({"ok": False, "codigo": None, "mensaje": "No se detectó ningún código"})

    except Exception as e:
        logger.error(f"Error detectando código: {e}")
        return jsonify({"error": str(e)}), 500


def _identificar_codigo(codigo: str) -> dict:
    """Detecta si el código escaneado es un QR de lote ZERO o un código de barras normal."""
    import json as _json
    try:
        datos = _json.loads(codigo)
        if isinstance(datos, dict) and datos.get("t") == "L":
            return {
                "tipo": "lote",
                "lote_id": datos["l"],
                "producto_id": datos["p"],
                "vencimiento": datos.get("v") or None,
            }
    except Exception:
        pass
    return {"tipo": "barras", "codigo": codigo}


@productos_bp.route("/buscar-codigo", methods=["POST"])
def buscar_codigo():
    """Búsqueda unificada: acepta código de barras normal o QR de lote ZERO."""
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    codigo = str(data.get("codigo", "")).strip()
    if not codigo:
        return jsonify({"error": "Código requerido"}), 400

    identificado = _identificar_codigo(codigo)

    with db_session() as conn:
        if identificado["tipo"] == "lote":
            lote_id    = identificado["lote_id"]
            producto_id = identificado["producto_id"]

            lote = conn.execute(
                """SELECT l.*, p.nombre, p.precio, p.imagen_url
                   FROM lotes l JOIN productos p ON p.id=l.producto_id
                   WHERE l.id=? AND l.producto_id=? AND p.activo=1""",
                (lote_id, producto_id)
            ).fetchone()

            if not lote:
                return jsonify({"error": "Lote no encontrado o inactivo"}), 404

            if lote["estado"] != "activo":
                return jsonify({"error": f"Lote {lote['estado']}", "lote_id": lote_id}), 400

            from datetime import date as _date
            venc = lote["fecha_vencimiento"]
            if venc and venc < _date.today().isoformat():
                return jsonify({
                    "error": "PRODUCTO VENCIDO",
                    "lote_id": lote_id,
                    "producto_id": producto_id,
                    "nombre": lote["nombre"],
                    "vencimiento": venc,
                    "vencido": True,
                }), 400

            return jsonify({
                "id": producto_id,
                "nombre": lote["nombre"],
                "precio": lote["precio"],
                "imagen_url": lote["imagen_url"],
                "lote_id": lote_id,
                "lote_numero": lote["numero_lote"],
                "vencimiento": venc,
                "tiene_lote": True,
            })

        # Barras normal — busca en productos y variantes
        prod = conn.execute(
            "SELECT * FROM productos WHERE codigo_barras=? AND activo=1",
            (identificado["codigo"],)
        ).fetchone()
        if prod:
            return jsonify({**dict(prod), "tiene_lote": False})

        variante = conn.execute(
            """SELECT pv.*, p.nombre as producto_nombre, p.id as producto_id_padre
               FROM producto_variantes pv JOIN productos p ON pv.producto_id=p.id
               WHERE pv.codigo_barras=? AND pv.activo=1""",
            (identificado["codigo"],)
        ).fetchone()
        if variante:
            return jsonify({**dict(variante), "es_variante": True, "tiene_lote": False})

    return jsonify({"error": "Código no encontrado"}), 404


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
    nombre = normalizar_nombre(str(data.get("nombre", "")).strip())
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400

    modo_stock = data.get("modo_stock", "normal")
    if modo_stock not in ("normal", "produccion", "sin_stock"):
        modo_stock = "normal"

    activo = int(bool(data.get("activo", 1)))
    pendiente_verificar = int(bool(data.get("pendiente_verificar", 0)))
    categoria_id = data.get("categoria_id")

    with db_session() as conn:
        # Duplicate barcode → upsert existing product (activo o inactivo)
        barras = (data.get("codigo_barras") or "").strip() or None
        if barras:
            exist_barras = conn.execute(
                "SELECT id FROM productos WHERE codigo_barras=?", (barras,)
            ).fetchone()
            if exist_barras:
                pid = exist_barras["id"]
                conn.execute(
                    """UPDATE productos SET nombre=?, precio=?, precio_costo=?,
                       activo=1, imagen_url=COALESCE(?,imagen_url) WHERE id=?""",
                    (nombre, float(data.get("precio", 0)), float(data.get("precio_costo", 0)),
                     data.get("imagen_url"), pid)
                )
                sku_row = conn.execute("SELECT sku FROM productos WHERE id=?", (pid,)).fetchone()
                return jsonify({"ok": True, "actualizado": True, "id": pid, "sku": sku_row["sku"] if sku_row else None})

        # Duplicate name → 409
        import unicodedata as _udn
        def _norm(s):
            return "".join(c.lower() for c in _udn.normalize("NFKD", s) if c.isalnum())
        exist_nombre = conn.execute(
            "SELECT id, nombre FROM productos WHERE activo=1"
        ).fetchall()
        for row in exist_nombre:
            if _norm(row["nombre"]) == _norm(nombre):
                return jsonify({"error": "duplicado", "existente": dict(row)}), 409

        if not categoria_id:
            cat_kw, depto_kw = clasificar_producto(nombre)
            if cat_kw != 'Sin categoría':
                categoria_id = obtener_o_crear_categoria(conn, cat_kw, depto_kw)
                # clasificado automáticamente → no requiere revisión manual
            else:
                sin_cat = conn.execute(
                    "SELECT id FROM categorias WHERE nombre='Sin categoría'"
                ).fetchone()
                if sin_cat:
                    categoria_id = sin_cat["id"]
                else:
                    _sc = conn.execute(
                        "INSERT INTO categorias (nombre, departamento, icono) VALUES ('Sin categoría','Otros','📦')"
                    )
                    categoria_id = _sc.lastrowid
                pendiente_verificar = 1

        import sqlite3 as _sqlite3
        try:
            cur = conn.execute(
                """INSERT INTO productos
                   (nombre, descripcion, precio, precio_costo, stock, stock_minimo,
                    codigo_barras, categoria_id, imagen_url, activo,
                    es_granel, unidad_medida, precio_por, modo_stock, hora_reset_stock,
                    pendiente_verificar, tiene_impuesto_adicional, tasa_impuesto_adicional,
                    marca_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    nombre,
                    data.get("descripcion"),
                    float(data.get("precio", 0)),
                    float(data.get("precio_costo", 0)),
                    int(data.get("stock", 0)),
                    int(data.get("stock_minimo", 5)),
                    data.get("codigo_barras"),
                    categoria_id,
                    data.get("imagen_url"),
                    activo,
                    int(bool(data.get("es_granel", 0))),
                    data.get("unidad_medida", "unidad"),
                    data.get("precio_por", "unidad"),
                    modo_stock,
                    data.get("hora_reset_stock", "06:00"),
                    pendiente_verificar,
                    int(bool(data.get("tiene_impuesto_adicional", 0))),
                    float(data.get("tasa_impuesto_adicional", 0)),
                    data.get("marca_id") or None,
                )
            )
        except _sqlite3.IntegrityError as ie:
            exist = conn.execute(
                "SELECT id, nombre FROM productos WHERE codigo_barras=? OR (activo=1 AND nombre=?)",
                (data.get("codigo_barras"), nombre)
            ).fetchone()
            if exist:
                return jsonify({"error": "duplicado", "existente": dict(exist)}), 409
            return jsonify({"error": str(ie)}), 409
        pid = cur.lastrowid
        cat_row = conn.execute(
            "SELECT COALESCE(c.nombre,'') as cn FROM productos p LEFT JOIN categorias c ON p.categoria_id=c.id WHERE p.id=?",
            (pid,)
        ).fetchone()
        sku = _generar_sku(cat_row["cn"] if cat_row else "", pid)
        conn.execute("UPDATE productos SET sku=? WHERE id=?", (sku, pid))
        if int(data.get("stock", 0)) > 0:
            _registrar_movimiento(conn, pid, "entrada",
                                  int(data.get("stock", 0)), "stock_inicial",
                                  session.get("usuario_id"))
        return jsonify({"ok": True, "id": pid, "sku": sku}), 201


@productos_bp.route("/<int:pid>", methods=["PUT"])
def actualizar(pid):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}

    # Verificar permiso de editar precios si se intenta cambiar precio o precio_costo
    if ("precio" in data or "precio_costo" in data):
        if not tiene_permiso(dict(session), "puede_editar_precios"):
            return jsonify({"error": "Sin permisos para editar precios"}), 403

    campos = {}
    permitidos = ("nombre", "descripcion", "precio", "precio_costo",
                  "stock", "stock_minimo", "codigo_barras", "categoria_id",
                  "imagen_url", "activo", "es_granel", "unidad_medida", "precio_por",
                  "modo_stock", "hora_reset_stock", "sku",
                  "pendiente_verificar", "tiene_impuesto_adicional", "tasa_impuesto_adicional",
                  "marca_id", "tiene_lotes")
    for campo in permitidos:
        if campo in data:
            campos[campo] = data[campo]

    if not campos:
        return jsonify({"error": "Sin campos para actualizar"}), 400

    if "nombre" in campos:
        campos["nombre"] = normalizar_nombre(str(campos["nombre"]).strip())

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


# ── Pendientes de verificar (creados desde mesón) ─────────────────────────────

@productos_bp.route("/pendientes-verificar", methods=["GET"])
def pendientes_verificar():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    with db_session() as conn:
        rows = conn.execute(
            """SELECT id, nombre, precio, precio_costo, stock, codigo_barras, creado_en
               FROM productos WHERE pendiente_verificar=1 ORDER BY creado_en DESC"""
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@productos_bp.route("/pendientes-verificar/<int:pid>/aprobar", methods=["POST"])
def aprobar_pendiente(pid):
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    data = request.get_json(silent=True) or {}
    with db_session() as conn:
        campos = {"activo": 1, "pendiente_verificar": 0}
        for k in ("nombre", "precio", "precio_costo", "categoria_id"):
            if k in data:
                campos[k] = data[k]
        sets = ", ".join(f"{k}=?" for k in campos)
        conn.execute(
            f"UPDATE productos SET {sets}, actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
            (*campos.values(), pid)
        )
        return jsonify({"ok": True})


# ── Categorías ────────────────────────────────────────────────────────────────

@productos_bp.route("/marcas", methods=["GET"])
def listar_marcas():
    q = request.args.get("q", "").strip()
    with db_session() as conn:
        if q:
            rows = conn.execute(
                "SELECT id, nombre, fabricante, pais_origen FROM marcas WHERE nombre LIKE ? ORDER BY nombre LIMIT 20",
                (f"%{q}%",)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, nombre, fabricante, pais_origen FROM marcas ORDER BY nombre LIMIT 100"
            ).fetchall()
    return jsonify([dict(r) for r in rows])


@productos_bp.route("/marcas", methods=["POST"])
def crear_marca():
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400
    with db_session() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO marcas (nombre, fabricante, pais_origen, sitio_web) VALUES (?,?,?,?)",
                (nombre, data.get("fabricante"), data.get("pais_origen", "Chile"), data.get("sitio_web"))
            )
            return jsonify({"ok": True, "id": cur.lastrowid, "nombre": nombre}), 201
        except Exception:
            existing = conn.execute("SELECT id, nombre FROM marcas WHERE nombre=?", (nombre,)).fetchone()
            if existing:
                return jsonify({"ok": True, "id": existing["id"], "nombre": existing["nombre"], "existente": True})
            raise


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
            "INSERT INTO categorias (nombre, color, icono, departamento) VALUES (?,?,?,?)",
            (nombre, data.get("color", "#6366f1"), data.get("icono", "📦"),
             data.get("departamento", "Alimentación"))
        )
        return jsonify({"ok": True, "id": cur.lastrowid}), 201


@productos_bp.route("/categorias/arbol", methods=["GET"])
def categorias_arbol():
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute(
            """SELECT c.id, c.nombre, c.icono, c.departamento,
                      COUNT(p.id) as total_productos
               FROM categorias c
               LEFT JOIN productos p ON p.categoria_id=c.id AND p.activo=1
               GROUP BY c.id
               ORDER BY c.departamento, c.nombre"""
        ).fetchall()
    arbol = {}
    for r in rows:
        d = r["departamento"] or "Otros"
        arbol.setdefault(d, []).append({
            "id": r["id"],
            "nombre": r["nombre"],
            "icono": r["icono"] or "📦",
            "total_productos": r["total_productos"],
        })
    return jsonify(arbol)


@productos_bp.route("/categorias/<int:cid>", methods=["PUT"])
def editar_categoria(cid):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400
    with db_session() as conn:
        conn.execute(
            "UPDATE categorias SET nombre=?, departamento=?, icono=? WHERE id=?",
            (nombre, data.get("departamento", "Otros"), data.get("icono", "📦"), cid)
        )
    return jsonify({"ok": True})


@productos_bp.route("/categorias/<int:cid>", methods=["DELETE"])
def eliminar_categoria(cid):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    mover_a = request.args.get("mover_a", type=int)
    with db_session() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM productos WHERE categoria_id=? AND activo=1", (cid,)
        ).fetchone()[0]
        if total > 0 and not mover_a:
            return jsonify({"error": "tiene_productos", "total": total}), 409
        if mover_a:
            conn.execute(
                "UPDATE productos SET categoria_id=? WHERE categoria_id=?", (mover_a, cid)
            )
        conn.execute("DELETE FROM categorias WHERE id=?", (cid,))
    return jsonify({"ok": True})


@productos_bp.route("/departamentos", methods=["POST"])
def crear_departamento():
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400
    with db_session() as conn:
        existing = conn.execute(
            "SELECT COUNT(*) FROM categorias WHERE departamento=?", (nombre,)
        ).fetchone()[0]
        if existing:
            return jsonify({"error": "El departamento ya existe"}), 409
    return jsonify({"ok": True, "departamento": nombre})


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


# ── EAN-13 a granel ───────────────────────────────────────────────────────────

@productos_bp.route("/leer-granel", methods=["POST"])
def leer_granel():
    """Decodifica EAN-13 interno con prefijo 2 para productos a granel.
    Formato: 2 + codigo_producto(5 dígitos) + peso_gramos(5 dígitos) + verificador(1)
    Ejemplo: 2 00001 00350 X  → producto 1, 350g
    """
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    codigo = str(data.get("codigo", "")).strip()

    if len(codigo) != 13 or not codigo.startswith("2"):
        return jsonify({"error": "No es un EAN-13 interno de granel (debe empezar con 2)"}), 400

    try:
        producto_id = int(codigo[1:6])
        peso_gramos = int(codigo[6:11])
    except ValueError:
        return jsonify({"error": "Código inválido"}), 400

    with db_session() as conn:
        prod = conn.execute(
            "SELECT * FROM productos WHERE id=? AND activo=1 AND es_granel=1",
            (producto_id,)
        ).fetchone()
        if not prod:
            return jsonify({"error": f"Producto granel #{producto_id} no encontrado"}), 404

        precio_por_kg = float(prod["precio"])
        precio = round(precio_por_kg * peso_gramos / 1000)
        unidad = prod["unidad_medida"] or "kg"

        return jsonify({
            "ok": True,
            "producto_id": producto_id,
            "nombre":      prod["nombre"],
            "peso_gramos": peso_gramos,
            "peso_display": f"{peso_gramos}g" if peso_gramos < 1000 else f"{peso_gramos/1000:.3f}kg",
            "precio_unit": precio_por_kg,
            "precio":      precio,
            "unidad":      unidad,
        })


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
