#routes/onboarding.py

import json
import logging
from pathlib import Path
from flask import Blueprint, jsonify, request, session
from database import db_session
from scripts.clasificar_productos import clasificar_producto, obtener_o_crear_categoria

onboarding_bp = Blueprint("onboarding", __name__, url_prefix="/api/onboarding")
logger = logging.getLogger("zero_pos.onboarding")

BASE_DIR = Path(__file__).parent.parent
DATA_FILE            = BASE_DIR / "data" / "productos_base.json"
DATA_FILE_MINIMARKET = BASE_DIR / "data" / "productos_base_minimarket.json"

_MINIMARKET_SUBTIPOS = frozenset({'almacen', 'minimarket', 'botilleria', 'kiosco'})

_ZERO_A_BASE_MAP = {
    'store':   'almacen',
    'food':    'foodtruck',
    'resto':   'cafe',
    'service': 'peluqueria',
}

_MODULOS_ZERO = {
    'store':   {'modulo_delivery': '0', 'modo_mesas': '0'},
    'food':    {'modulo_delivery': '1', 'modo_mesas': '0'},
    'resto':   {'modulo_delivery': '1', 'modo_mesas': '1'},
    'service': {'modulo_delivery': '0', 'modo_mesas': '0'},
}

_MODULOS_BASE = {
    'cafe':       {'modulo_delivery': '1', 'modo_mesas': '1'},
    'sushi':      {'modulo_delivery': '1', 'modo_mesas': '1'},
    'panaderia':  {'modulo_delivery': '1', 'modo_mesas': '1'},
    'foodtruck':  {'modulo_delivery': '1', 'modo_mesas': '0'},
    'almacen':    {'modulo_delivery': '0', 'modo_mesas': '0'},
    'minimarket': {'modulo_delivery': '0', 'modo_mesas': '0'},
    'botilleria': {'modulo_delivery': '0', 'modo_mesas': '0'},
    'peluqueria': {'modulo_delivery': '0', 'modo_mesas': '0'},
    'otro':       {'modulo_delivery': '0', 'modo_mesas': '0'},
}


def _load_data() -> dict:
    if not DATA_FILE.exists():
        return {}
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _cargar_productos_flat(conn, uid: int) -> int:
    """Carga productos desde productos_base_minimarket.json (lista plana de Open Food Facts)."""
    if not DATA_FILE_MINIMARKET.exists():
        logger.info("productos_base_minimarket.json no disponible — fallback a almacen")
        return _cargar_productos_estructurado("almacen", conn, uid)

    try:
        productos = json.loads(DATA_FILE_MINIMARKET.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Error leyendo productos_base_minimarket.json: {e}")
        return _cargar_productos_estructurado("almacen", conn, uid)

    cat_cache  = {}
    insertados = 0

    for p in productos:
        try:
            nombre_prod = p.get("nombre", "").strip()
            # Clasificar por palabras clave; fallback al campo "categoria" del JSON
            cat_kw, depto_kw = clasificar_producto(nombre_prod)
            if cat_kw != 'Sin categoría':
                cat_nombre, depto = cat_kw, depto_kw
            else:
                cat_nombre = p.get("categoria", "General")
                depto = 'Alimentación'
            if cat_nombre not in cat_cache:
                cat_cache[cat_nombre] = obtener_o_crear_categoria(conn, cat_nombre, depto)
            cat_id = cat_cache[cat_nombre]

            codigo = p.get("codigo_barras", "").strip()
            nombre = p.get("nombre", "").strip()
            if not nombre:
                continue

            if codigo and conn.execute(
                "SELECT id FROM productos WHERE codigo_barras=?", (codigo,)
            ).fetchone():
                continue

            conn.execute(
                """INSERT OR IGNORE INTO productos
                   (nombre, precio, codigo_barras, categoria_id, activo, modo_stock, stock_minimo)
                   VALUES (?,?,?,?,1,'normal',5)""",
                (nombre, p.get("precio_sugerido", 0), codigo or None, cat_id)
            )
            insertados += 1
        except Exception:
            continue

    return insertados


def _cargar_productos_estructurado(tipo_base: str, conn, uid: int) -> int:
    """Carga productos desde productos_base.json (formato estructurado con categorías y variantes)."""
    data = _load_data()
    if tipo_base not in data:
        tipo_base = "otro"
    if tipo_base not in data:
        return 0

    cfg = data[tipo_base]
    _BEBIDA_RE = r'bebida|agua|jugo|gaseosa|cerveza|vino|licor|ron|gin|pisco|whisky|champa'

    def _inferir_modo_stock(prod_def_: dict, cat_nombre_: str) -> str:
        if "modo_stock" in prod_def_:
            return prod_def_["modo_stock"]
        cn = cat_nombre_.lower()
        if tipo_base in ("sushi", "cafe", "restaurante"):
            import re
            return "normal" if re.search(_BEBIDA_RE, cn) else "sin_stock"
        if tipo_base == "panaderia":
            return "produccion"
        if tipo_base == "foodtruck":
            import re
            return "normal" if re.search(_BEBIDA_RE, cn) else "sin_stock"
        return "normal"

    cat_ids    = {}
    subcat_ids = {}

    for cat in cfg.get("categorias", []):
        cur = conn.execute(
            "INSERT OR IGNORE INTO categorias (nombre, icono, color) VALUES (?,?,?)",
            (cat["nombre"], cat.get("icono", "📦"), cat.get("color", "#6366f1"))
        )
        if cur.lastrowid:
            cat_id = cur.lastrowid
        else:
            cat_id = conn.execute(
                "SELECT id FROM categorias WHERE nombre=?", (cat["nombre"],)
            ).fetchone()["id"]
        cat_ids[cat["nombre"]] = cat_id

        for sub in cat.get("subcategorias", []):
            cur2 = conn.execute(
                "INSERT OR IGNORE INTO subcategorias (categoria_id, nombre) VALUES (?,?)",
                (cat_id, sub["nombre"])
            )
            if cur2.lastrowid:
                sid = cur2.lastrowid
            else:
                sid = conn.execute(
                    "SELECT id FROM subcategorias WHERE categoria_id=? AND nombre=?",
                    (cat_id, sub["nombre"])
                ).fetchone()["id"]
            subcat_ids[(cat_id, sub["nombre"])] = sid

    creados = 0
    for prod_def in cfg.get("productos", []):
        cat_nombre  = prod_def.get("categoria", "")
        cat_id      = cat_ids.get(cat_nombre)
        # Si no hay cat_id del JSON, intentar clasificar por palabras clave
        if not cat_id:
            cat_kw, depto_kw = clasificar_producto(prod_def.get("nombre", ""))
            if cat_kw != 'Sin categoría':
                cat_id = obtener_o_crear_categoria(conn, cat_kw, depto_kw)
        subcat_nombre = prod_def.get("subcategoria", "")
        subcat_id   = subcat_ids.get((cat_id, subcat_nombre)) if subcat_nombre and cat_id else None
        variantes   = prod_def.get("variantes", [])
        tiene_var   = 1 if len(variantes) > 1 else 0
        precio_base = variantes[0]["precio"] if variantes else 0
        stock_base  = variantes[0]["stock"] if variantes else 0
        modo_stock  = _inferir_modo_stock(prod_def, cat_nombre)
        stock_init  = 0 if (tiene_var or modo_stock == "sin_stock") else stock_base

        cur = conn.execute(
            """INSERT OR IGNORE INTO productos
               (nombre, precio, stock, categoria_id, subcategoria_id,
                tiene_variantes, activo, stock_minimo, modo_stock)
               VALUES (?,?,?,?,?,?,1,5,?)""",
            (prod_def["nombre"], precio_base, stock_init,
             cat_id, subcat_id, tiene_var, modo_stock)
        )
        if not cur.lastrowid:
            continue
        prod_id = cur.lastrowid

        if not tiene_var and stock_base > 0 and modo_stock != "sin_stock":
            conn.execute(
                """INSERT INTO stock_movimientos
                   (producto_id, tipo, cantidad, motivo, usuario_id)
                   VALUES (?,?,?,?,?)""",
                (prod_id, "entrada", stock_base, "stock_inicial", uid)
            )

        for v in variantes:
            conn.execute(
                """INSERT OR IGNORE INTO producto_variantes
                   (producto_id, nombre, precio, stock, stock_minimo, activo)
                   VALUES (?,?,?,?,5,1)""",
                (prod_id, v["nombre"], v["precio"], v.get("stock", 0))
            )
        creados += 1

    return creados


# ── Endpoints ──────────────────────────────────────────────────────────────────

@onboarding_bp.route("/estado", methods=["GET"])
def estado():
    with db_session() as conn:
        hay_productos = conn.execute(
            "SELECT COUNT(*) FROM productos WHERE activo=1"
        ).fetchone()[0]
        completado = conn.execute(
            "SELECT valor FROM config WHERE clave='onboarding_completado'"
        ).fetchone()
        tipo = conn.execute(
            "SELECT valor FROM config WHERE clave='tipo_negocio'"
        ).fetchone()

    return jsonify({
        "completado": bool(completado and completado["valor"] == "1"),
        "hay_productos": hay_productos > 0,
        "tipo_negocio": tipo["valor"] if tipo else None,
    })


@onboarding_bp.route("/tipos", methods=["GET"])
def tipos():
    data = _load_data()
    return jsonify([
        {"id": k, "nombre": v["nombre"], "icono": v["icono"]}
        for k, v in data.items()
    ])


@onboarding_bp.route("/setup", methods=["POST"])
def setup():
    """Carga productos base por tipo_base (legacy — lo llama el onboarding anterior)."""
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    body    = request.get_json(silent=True) or {}
    tipo    = body.get("tipo", "").strip()
    subtipo = body.get("subtipo", "").strip()
    if not tipo:
        return jsonify({"error": "tipo requerido"}), 400

    data = _load_data()
    if tipo not in data:
        tipo = "otro"
    if tipo not in data:
        return jsonify({"error": "Datos de productos no disponibles"}), 500

    uid     = session.get("usuario_id")
    modulos = _MODULOS_BASE.get(tipo, {"modulo_delivery": "0", "modo_mesas": "0"})

    with db_session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES ('tipo_negocio', ?)", (tipo,)
        )
        if subtipo:
            conn.execute(
                "INSERT OR REPLACE INTO config (clave, valor) VALUES ('subtipo_negocio', ?)",
                (subtipo,)
            )
        conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES ('onboarding_completado', '1')"
        )
        conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES ('modulo_delivery', ?)",
            (modulos["modulo_delivery"],)
        )
        conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES ('modo_mesas', ?)",
            (modulos["modo_mesas"],)
        )
        creados = _cargar_productos_estructurado(tipo, conn, uid)

    logger.info(f"Onboarding setup '{tipo}': {creados} productos")
    return jsonify({"ok": True, "tipo": tipo, "productos_cargados": creados})


@onboarding_bp.route("/completar", methods=["POST"])
def completar():
    """Endpoint del nuevo onboarding de 4 pasos.
    Recibe tipo ZERO (store/food/resto/service) y subtipo opcional.
    Decide qué productos cargar y activa los módulos correctos.
    """
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    body      = request.get_json(silent=True) or {}
    tipo_zero = body.get("tipo", "store").strip()
    subtipo   = body.get("subtipo", "").strip()
    uid       = session.get("usuario_id")

    modulos   = _MODULOS_ZERO.get(tipo_zero, {"modulo_delivery": "0", "modo_mesas": "0"})

    with db_session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES ('tipo_negocio', ?)", (tipo_zero,)
        )
        conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES ('modulo_delivery', ?)",
            (modulos["modulo_delivery"],)
        )
        conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES ('modo_mesas', ?)",
            (modulos["modo_mesas"],)
        )

        if subtipo in _MINIMARKET_SUBTIPOS:
            creados = _cargar_productos_flat(conn, uid)
        else:
            tipo_base = _ZERO_A_BASE_MAP.get(tipo_zero, "almacen")
            creados   = _cargar_productos_estructurado(tipo_base, conn, uid)

        conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES ('onboarding_completado', '1')"
        )

    logger.info(f"Onboarding completar: tipo_zero={tipo_zero} subtipo={subtipo} creados={creados}")
    return jsonify({"ok": True, "productos_cargados": creados})


@onboarding_bp.route("/reset", methods=["POST"])
def reset():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    with db_session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES ('onboarding_completado','0')"
        )
    return jsonify({"ok": True})
