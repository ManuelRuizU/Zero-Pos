import json
import logging
import re
import unicodedata
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


def _extraer_calle(texto: str) -> str:
    """Quita el número del final: 'sevilla 632' → 'sevilla'."""
    t = texto.strip()
    t = re.sub(r"\s+(nro?|n°|#)\s*\d+\s*$", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"\s+\d+\s*$", "", t).strip()
    return t if t else texto.strip()


# ── GET /api/direcciones/buscar ───────────────────────────────────────────────
@direcciones_bp.route("/direcciones/buscar", methods=["GET"])
def buscar_direccion():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    q      = request.args.get("q", "").strip()
    comuna = request.args.get("comuna", "").strip()
    if len(q) < 3:
        return jsonify([])

    q_norm      = _norm(q)
    q_sin_num   = _extraer_calle(q_norm)
    tiene_digit = any(c.isdigit() for c in q_norm)

    with db_session() as conn:
        # ── Capa 1: frecuentes con número (solo si la query tiene dígito) ────
        frecuentes = []
        if tiene_digit and q_sin_num:
            base_rows = conn.execute(
                """SELECT id, calle_nombre, comuna, direcciones_frecuentes
                   FROM geografia_local
                   WHERE calle_limpia LIKE ?
                     AND (? = '' OR LOWER(comuna) = LOWER(?))
                   LIMIT 10""",
                (f"%{q_sin_num}%", comuna, comuna),
            ).fetchall()

            for row in base_rows:
                if not row["direcciones_frecuentes"]:
                    # Lazy-build desde historial de pedidos
                    _poblar_frecuentes(conn, row["id"], row["calle_nombre"],
                                       row["calle_limpia"], row["comuna"])
                    row = conn.execute(
                        "SELECT id, calle_nombre, comuna, direcciones_frecuentes "
                        "FROM geografia_local WHERE id=?", (row["id"],)
                    ).fetchone()

                frecs = json.loads(row["direcciones_frecuentes"] or "[]")
                for addr in frecs:
                    if q_norm in _norm(addr):
                        frecuentes.append({
                            "display":      f"{addr}, {row['comuna']}",
                            "calle":        addr,
                            "comuna":       row["comuna"],
                            "fuente":       "local",
                            "es_frecuente": True,
                        })

        # ── Capa 1: calles genéricas (búsqueda en calle_limpia) ──────────────
        term = q_sin_num if tiene_digit else q_norm
        rows = conn.execute(
            """SELECT DISTINCT calle_nombre, tipo_via, comuna
               FROM geografia_local
               WHERE calle_limpia LIKE ?
                 AND (? = '' OR LOWER(comuna) = LOWER(?))
               ORDER BY
                 CASE WHEN calle_limpia = ?   THEN 0
                      WHEN calle_limpia LIKE ? THEN 1
                      ELSE 2 END
               LIMIT 6""",
            (f"%{term}%", comuna, comuna, term, f"{term}%"),
        ).fetchall()

        genericas = [
            {"display": f"{r['calle_nombre']}, {r['comuna']}",
             "calle":   r["calle_nombre"],
             "comuna":  r["comuna"],
             "fuente":  "local"}
            for r in rows
        ]

        # Frecuentes primero; genéricas deduplicadas al final
        if frecuentes or genericas:
            vistos = {f["calle"] for f in frecuentes}
            extra  = [g for g in genericas if g["calle"] not in vistos]
            return jsonify(frecuentes + extra)

        # ── Capa 2: Nominatim (fallback online) ──────────────────────────────
        try:
            params = urllib.parse.urlencode({
                "q":              f"{q}, {comuna}, Chile" if comuna else f"{q}, Chile",
                "format":         "json",
                "limit":          5,
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
    calle_n   = _norm(calle_raw)
    calle_sin = _extraer_calle(calle_n)   # sin número del final
    comuna    = (data.get("comuna") or "").strip()

    if not calle_n:
        return jsonify({"valida": True})

    with db_session() as conn:
        # Buscar con texto completo o sin número
        exacta = conn.execute(
            """SELECT calle_nombre FROM geografia_local
               WHERE (calle_limpia = ? OR calle_limpia = ?)
                 AND (? = '' OR LOWER(comuna) = LOWER(?))
               LIMIT 1""",
            (calle_n, calle_sin, comuna, comuna),
        ).fetchone()
        if exacta:
            return jsonify({"valida": True, "nombre_oficial": exacta["calle_nombre"]})

        # Buscar similares para sugerir
        similares = conn.execute(
            """SELECT calle_nombre FROM geografia_local
               WHERE calle_limpia LIKE ?
                 AND (? = '' OR LOWER(comuna) = LOWER(?))
               LIMIT 3""",
            (f"%{calle_sin}%", comuna, comuna),
        ).fetchall()
        if similares:
            return jsonify({
                "valida":      False,
                "alerta":      "Calle no encontrada. ¿Quisiste decir?",
                "sugerencias": [r["calle_nombre"] for r in similares],
            })

        total_q = ("SELECT COUNT(*) as n FROM geografia_local WHERE LOWER(comuna) = LOWER(?)"
                   if comuna else "SELECT COUNT(*) as n FROM geografia_local")
        total   = conn.execute(total_q, (comuna,) if comuna else ()).fetchone()["n"]

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


# ── Helpers internos ──────────────────────────────────────────────────────────
def _poblar_frecuentes(conn, row_id: int, calle_nombre: str,
                       calle_limpia: str, comuna: str):
    """Construye direcciones_frecuentes desde el historial de pedidos (lazy)."""
    rows = conn.execute(
        """SELECT direccion, COUNT(*) as c
           FROM pedidos
           WHERE direccion IS NOT NULL AND direccion != ''
             AND (? = '' OR LOWER(comuna) = LOWER(?))
           GROUP BY LOWER(direccion)
           ORDER BY c DESC
           LIMIT 50""",
        (comuna, comuna),
    ).fetchall()

    frecs = []
    for r in rows:
        dir_norm = _norm(r["direccion"])
        if _extraer_calle(dir_norm) == calle_limpia or calle_limpia in dir_norm:
            frecs.append(" ".join(r["direccion"].strip().split()))
            if len(frecs) >= 20:
                break

    if frecs:
        conn.execute(
            "UPDATE geografia_local SET direcciones_frecuentes=? WHERE id=?",
            (json.dumps(frecs, ensure_ascii=False), row_id),
        )


def registrar_direccion_pedido(conn, direccion: str, comuna: str):
    """
    Llamar después de guardar un pedido para actualizar frecuentes.
    Importar desde routes/pedidos.py.
    """
    if not direccion:
        return
    calle_limpia = _extraer_calle(_norm(direccion))
    row = conn.execute(
        """SELECT id, direcciones_frecuentes FROM geografia_local
           WHERE calle_limpia = ?
             AND (? = '' OR LOWER(comuna) = LOWER(?))
           LIMIT 1""",
        (calle_limpia, comuna, comuna),
    ).fetchone()
    if not row:
        return
    frecs   = json.loads(row["direcciones_frecuentes"] or "[]")
    addr_ok = " ".join(direccion.strip().split())
    if addr_ok not in frecs:
        frecs = [addr_ok] + [f for f in frecs if f != addr_ok]
        frecs = frecs[:20]
        conn.execute(
            "UPDATE geografia_local SET direcciones_frecuentes=? WHERE id=?",
            (json.dumps(frecs, ensure_ascii=False), row["id"]),
        )


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
