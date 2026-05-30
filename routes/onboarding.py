import json
import logging
from pathlib import Path
from flask import Blueprint, jsonify, request, session
from database import db_session

onboarding_bp = Blueprint("onboarding", __name__, url_prefix="/api/onboarding")
logger = logging.getLogger("zero_pos.onboarding")

BASE_DIR = Path(__file__).parent.parent
DATA_FILE = BASE_DIR / "data" / "productos_base.json"


def _load_data() -> dict:
    if not DATA_FILE.exists():
        return {}
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


@onboarding_bp.route("/estado", methods=["GET"])
def estado():
    """Detecta si el negocio ya fue configurado."""
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
    """Lista los tipos de negocio disponibles."""
    data = _load_data()
    return jsonify([
        {"id": k, "nombre": v["nombre"], "icono": v["icono"]}
        for k, v in data.items()
    ])


@onboarding_bp.route("/setup", methods=["POST"])
def setup():
    """Carga categorías y productos base para el tipo de negocio elegido."""
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    body = request.get_json(silent=True) or {}
    tipo   = body.get("tipo", "").strip()
    subtipo = body.get("subtipo", "").strip()
    if not tipo:
        return jsonify({"error": "tipo requerido"}), 400

    data = _load_data()
    if tipo not in data:
        tipo = "otro"
    if tipo not in data:
        return jsonify({"error": "Datos de productos no disponibles"}), 500

    config = data[tipo]
    uid = session.get("usuario_id")

    # Defaults de módulos según tipo de negocio
    _MODULOS = {
        "cafe":       {"modulo_delivery": "1", "modo_mesas": "1"},
        "sushi":      {"modulo_delivery": "1", "modo_mesas": "1"},
        "panaderia":  {"modulo_delivery": "1", "modo_mesas": "1"},
        "foodtruck":  {"modulo_delivery": "1", "modo_mesas": "0"},
        "almacen":    {"modulo_delivery": "0", "modo_mesas": "0"},
        "minimarket": {"modulo_delivery": "0", "modo_mesas": "0"},
        "botilleria": {"modulo_delivery": "0", "modo_mesas": "0"},
        "peluqueria": {"modulo_delivery": "0", "modo_mesas": "0"},
        "otro":       {"modulo_delivery": "0", "modo_mesas": "0"},
    }
    modulos = _MODULOS.get(tipo, {"modulo_delivery": "0", "modo_mesas": "0"})

    with db_session() as conn:
        # Guardar tipo en config
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

        # Crear categorías y subcategorías
        cat_ids = {}     # nombre -> id
        subcat_ids = {}  # (cat_id, nombre) -> id

        for cat in config.get("categorias", []):
            cur = conn.execute(
                "INSERT OR IGNORE INTO categorias (nombre, icono, color) VALUES (?,?,?)",
                (cat["nombre"], cat.get("icono", "📦"), cat.get("color", "#6366f1"))
            )
            if cur.lastrowid:
                cat_id = cur.lastrowid
            else:
                row = conn.execute(
                    "SELECT id FROM categorias WHERE nombre=?", (cat["nombre"],)
                ).fetchone()
                cat_id = row["id"]
            cat_ids[cat["nombre"]] = cat_id

            for sub in cat.get("subcategorias", []):
                cur2 = conn.execute(
                    "INSERT OR IGNORE INTO subcategorias (categoria_id, nombre) VALUES (?,?)",
                    (cat_id, sub["nombre"])
                )
                if cur2.lastrowid:
                    sid = cur2.lastrowid
                else:
                    row2 = conn.execute(
                        "SELECT id FROM subcategorias WHERE categoria_id=? AND nombre=?",
                        (cat_id, sub["nombre"])
                    ).fetchone()
                    sid = row2["id"]
                subcat_ids[(cat_id, sub["nombre"])] = sid

        # Determina modo_stock según tipo de negocio y categoría
        _BEBIDA_RE = r'bebida|agua|jugo|gaseosa|cerveza|vino|licor|ron|gin|pisco|whisky|champa'

        def _inferir_modo_stock(prod_def_: dict, cat_nombre_: str) -> str:
            if "modo_stock" in prod_def_:
                return prod_def_["modo_stock"]
            cn = cat_nombre_.lower()
            if tipo in ("sushi", "cafe", "restaurante"):
                import re
                return "normal" if re.search(_BEBIDA_RE, cn) else "sin_stock"
            elif tipo == "panaderia":
                return "produccion"
            elif tipo == "foodtruck":
                import re
                return "normal" if re.search(_BEBIDA_RE, cn) else "sin_stock"
            return "normal"

        # Crear productos y variantes
        creados = 0
        for prod_def in config.get("productos", []):
            cat_nombre = prod_def.get("categoria", "")
            cat_id = cat_ids.get(cat_nombre)

            subcat_nombre = prod_def.get("subcategoria", "")
            subcat_id = subcat_ids.get((cat_id, subcat_nombre)) if subcat_nombre and cat_id else None

            variantes = prod_def.get("variantes", [])
            tiene_variantes = 1 if len(variantes) > 1 else 0

            # Precio y stock del producto padre = primera variante
            precio_base = variantes[0]["precio"] if variantes else 0
            stock_base = variantes[0]["stock"] if variantes else 0
            modo_stock = _inferir_modo_stock(prod_def, cat_nombre)
            stock_inicial = 0 if (tiene_variantes or modo_stock == "sin_stock") else stock_base

            cur = conn.execute(
                """INSERT OR IGNORE INTO productos
                   (nombre, precio, stock, categoria_id, subcategoria_id,
                    tiene_variantes, activo, stock_minimo, modo_stock)
                   VALUES (?,?,?,?,?,?,1,5,?)""",
                (prod_def["nombre"], precio_base, stock_inicial,
                 cat_id, subcat_id, tiene_variantes, modo_stock)
            )
            if not cur.lastrowid:
                continue  # ya existía
            prod_id = cur.lastrowid

            # Registrar movimiento de stock inicial
            if not tiene_variantes and stock_base > 0 and modo_stock != "sin_stock":
                conn.execute(
                    """INSERT INTO stock_movimientos
                       (producto_id, tipo, cantidad, motivo, usuario_id)
                       VALUES (?,?,?,?,?)""",
                    (prod_id, "entrada", stock_base, "stock_inicial", uid)
                )

            # Crear variantes
            for v in variantes:
                conn.execute(
                    """INSERT OR IGNORE INTO producto_variantes
                       (producto_id, nombre, precio, stock, stock_minimo, activo)
                       VALUES (?,?,?,?,5,1)""",
                    (prod_id, v["nombre"], v["precio"], v.get("stock", 0))
                )
            creados += 1

    logger.info(f"Onboarding '{tipo}': {creados} productos cargados")
    return jsonify({"ok": True, "tipo": tipo, "productos_cargados": creados})


@onboarding_bp.route("/reset", methods=["POST"])
def reset():
    """Admin puede resetear onboarding para cambiar tipo de negocio."""
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    with db_session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (clave, valor) VALUES ('onboarding_completado','0')"
        )
    return jsonify({"ok": True})
