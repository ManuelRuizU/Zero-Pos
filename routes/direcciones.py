import json
import logging
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from flask import Blueprint, jsonify, request, session
from database import db_session

direcciones_bp = Blueprint("direcciones", __name__, url_prefix="/api")
logger = logging.getLogger("zero_pos.direcciones")


def _norm(texto: str) -> str:
    if not texto:
        return ""
    texto = unicodedata.normalize("NFD", texto.lower().strip())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def _hay_internet() -> bool:
    try:
        urllib.request.urlopen("https://nominatim.openstreetmap.org", timeout=2)
        return True
    except Exception:
        return False


# ── GET /api/direcciones/buscar ───────────────────────────────────────────────
@direcciones_bp.route("/direcciones/buscar", methods=["GET"])
def buscar_direccion():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    q      = request.args.get("q", "").strip()
    comuna = request.args.get("comuna", "").strip()
    if len(q) < 3:
        return jsonify([])

    q_norm = _norm(q)

    with db_session() as conn:
        # Capa 1: geografia_local (offline, <1 ms)
        rows = conn.execute(
            """SELECT DISTINCT calle_nombre, tipo_via, comuna
               FROM geografia_local
               WHERE calle_limpia LIKE ?
                 AND (? = '' OR LOWER(comuna) = LOWER(?))
               ORDER BY
                 CASE WHEN calle_limpia = ?       THEN 0
                      WHEN calle_limpia LIKE ?     THEN 1
                      ELSE 2 END
               LIMIT 6""",
            (f"%{q_norm}%", comuna, comuna, q_norm, f"{q_norm}%"),
        ).fetchall()

        if rows:
            return jsonify([
                {"display": f"{r['calle_nombre']}, {r['comuna']}",
                 "calle":   r["calle_nombre"],
                 "comuna":  r["comuna"],
                 "fuente":  "local"}
                for r in rows
            ])

        # Capa 2: Nominatim (si hay internet)
        try:
            params = urllib.parse.urlencode({
                "q":             f"{q}, {comuna}, Chile" if comuna else f"{q}, Chile",
                "format":        "json",
                "limit":         5,
                "addressdetails": 1,
            })
            req = urllib.request.Request(
                f"https://nominatim.openstreetmap.org/search?{params}",
                headers={"User-Agent": "ZERO-POS/1.0"},
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())

            resultados = []
            for item in data:
                addr  = item.get("address", {})
                calle = (addr.get("road") or addr.get("pedestrian")
                         or addr.get("path") or "")
                if not calle:
                    continue
                com   = (addr.get("city") or addr.get("town")
                         or addr.get("village") or comuna)
                parts = item.get("display_name", "").split(",")[:3]
                resultados.append({
                    "display": ", ".join(p.strip() for p in parts),
                    "calle":   calle,
                    "comuna":  com,
                    "fuente":  "nominatim",
                })
                # Guardar en cache local para uso offline futuro
                conn.execute(
                    """INSERT OR IGNORE INTO geografia_local
                       (comuna, calle_nombre, calle_limpia, tipo_via)
                       VALUES (?, ?, ?, 'nominatim')""",
                    (com, calle, _norm(calle)),
                )
            return jsonify(resultados)

        except Exception:
            return jsonify([])


# ── POST /api/direcciones/validar ─────────────────────────────────────────────
@direcciones_bp.route("/direcciones/validar", methods=["POST"])
def validar_direccion():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    data      = request.get_json(silent=True) or {}
    calle_raw = (data.get("calle") or "").strip()
    calle     = _norm(calle_raw)
    comuna    = (data.get("comuna") or "").strip()

    if not calle:
        return jsonify({"valida": True})

    with db_session() as conn:
        exacta = conn.execute(
            """SELECT calle_nombre FROM geografia_local
               WHERE calle_limpia = ?
                 AND (? = '' OR LOWER(comuna) = LOWER(?))""",
            (calle, comuna, comuna),
        ).fetchone()
        if exacta:
            return jsonify({"valida": True, "nombre_oficial": exacta["calle_nombre"]})

        similares = conn.execute(
            """SELECT calle_nombre FROM geografia_local
               WHERE calle_limpia LIKE ?
                 AND (? = '' OR LOWER(comuna) = LOWER(?))
               LIMIT 3""",
            (f"%{calle}%", comuna, comuna),
        ).fetchall()
        if similares:
            return jsonify({
                "valida":      False,
                "alerta":      "Calle no encontrada. ¿Quisiste decir?",
                "sugerencias": [r["calle_nombre"] for r in similares],
            })

        total_q = ("SELECT COUNT(*) as n FROM geografia_local WHERE LOWER(comuna) = LOWER(?)"
                   if comuna else "SELECT COUNT(*) as n FROM geografia_local")
        total_p = (comuna,) if comuna else ()
        total   = conn.execute(total_q, total_p).fetchone()["n"]

        if total == 0:
            return jsonify({
                "valida": True,
                "alerta": "Sin mapa local para esta comuna. La dirección no fue verificada.",
            })

        etiqueta = f"en {comuna}" if comuna else "en el mapa local"
        return jsonify({
            "valida":      False,
            "alerta":      f"'{calle_raw}' no encontrada {etiqueta}.",
            "sugerencias": [],
        })


# ── POST /api/mapa/cargar-comuna ──────────────────────────────────────────────
@direcciones_bp.route("/mapa/cargar-comuna", methods=["POST"])
def mapa_cargar_comuna():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403

    data   = request.get_json(silent=True) or {}
    comuna = (data.get("comuna") or "").strip()
    if not comuna:
        return jsonify({"error": "comuna requerida"}), 400

    try:
        elementos = _overpass_descargar(comuna)
        if not elementos:
            return jsonify({"ok": False, "error": "Sin datos o sin conexión a internet"}), 503
        calles = _guardar_en_db(elementos, comuna)
        logger.info(f"Mapa cargado: {calles} calles para {comuna}")
        return jsonify({"ok": True, "calles": calles, "comuna": comuna})
    except Exception as e:
        logger.warning(f"mapa cargar-comuna {comuna}: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ── GET /api/mapa/comunas ─────────────────────────────────────────────────────
@direcciones_bp.route("/mapa/comunas", methods=["GET"])
def mapa_comunas():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute(
            """SELECT comuna, COUNT(*) as calles
               FROM geografia_local
               GROUP BY LOWER(comuna)
               ORDER BY calles DESC"""
        ).fetchall()
    return jsonify([{"comuna": r["comuna"], "calles": r["calles"]} for r in rows])


# ── Helpers ───────────────────────────────────────────────────────────────────
def _overpass_descargar(comuna: str) -> list:
    query = (
        f'[out:json][timeout:90];'
        f'area["name"="{comuna}"]["admin_level"~"7|8"]->.a;'
        f'way["highway"]["name"](area.a);'
        f'out tags;'
    )
    url  = "https://overpass-api.de/api/interpreter"
    body = urllib.parse.urlencode({"data": query}).encode()
    req  = urllib.request.Request(
        url, data=body,
        headers={"User-Agent": "ZERO-POS/1.0 (mapa offline local)"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read()).get("elements", [])


def _guardar_en_db(elementos: list, comuna: str) -> int:
    with db_session() as conn:
        conn.execute(
            "DELETE FROM geografia_local WHERE LOWER(comuna) = LOWER(?)", (comuna,)
        )
        n = 0
        for elem in elementos:
            tags   = elem.get("tags", {})
            nombre = tags.get("name", "")
            if not nombre:
                continue
            conn.execute(
                """INSERT INTO geografia_local
                   (comuna, calle_nombre, calle_limpia, tipo_via)
                   VALUES (?, ?, ?, ?)""",
                (comuna, nombre, _norm(nombre), tags.get("highway", "street")),
            )
            n += 1
    return n
