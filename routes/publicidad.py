# routes/publicidad.py
import os
import uuid
import logging
from pathlib import Path
from flask import Blueprint, request, jsonify, session

from database import db_session

publicidad_bp = Blueprint("publicidad", __name__, url_prefix="/api/publicidad")
logger = logging.getLogger("zero_pos.publicidad")

BASE_DIR = Path(__file__).parent.parent
UPLOAD_DIR = BASE_DIR / "static" / "negocio" / "publicidad"

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4"}


def _require_admin():
    return session.get("usuario_rol") == "admin"


def _save_file(archivo) -> str | None:
    if not archivo or not archivo.filename:
        return None
    ext = Path(archivo.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return None
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    nombre = f"{uuid.uuid4().hex}{ext}"
    archivo.save(str(UPLOAD_DIR / nombre))
    return f"/static/negocio/publicidad/{nombre}"


def _delete_file(url: str | None):
    if not url:
        return
    try:
        ruta = BASE_DIR / url.lstrip("/")
        if ruta.exists():
            ruta.unlink()
    except Exception as e:
        logger.debug(f"_delete_file: {e}")


# ── GET /api/publicidad ───────────────────────────────────────────────────────
@publicidad_bp.route("", methods=["GET"])
def listar():
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM publicidad WHERE activo=1 ORDER BY orden ASC, id ASC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


# ── POST /api/publicidad ──────────────────────────────────────────────────────
@publicidad_bp.route("", methods=["POST"])
def crear():
    if not _require_admin():
        return jsonify({"error": "No autorizado"}), 403

    titulo         = request.form.get("titulo", "")
    subtitulo      = request.form.get("subtitulo", "")
    color          = request.form.get("color", "#6366f1")
    color2         = request.form.get("color2", "#8b5cf6")
    duracion       = int(request.form.get("duracion", 5))
    plantilla_id   = request.form.get("plantilla_id") or None
    datos_plantilla = request.form.get("datos_plantilla", "{}")
    imagen_url     = _save_file(request.files.get("imagen"))

    with db_session() as conn:
        orden = (conn.execute("SELECT COALESCE(MAX(orden),0)+1 FROM publicidad").fetchone()[0])
        conn.execute(
            """INSERT INTO publicidad
               (titulo, subtitulo, imagen_url, color, color2, orden, duracion, plantilla_id, datos_plantilla)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (titulo, subtitulo, imagen_url, color, color2, orden, duracion, plantilla_id, datos_plantilla),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM publicidad WHERE id=last_insert_rowid()"
        ).fetchone()
    return jsonify(dict(row)), 201


# ── PUT /api/publicidad/<id> ──────────────────────────────────────────────────
@publicidad_bp.route("/<int:pub_id>", methods=["PUT"])
def actualizar(pub_id: int):
    if not _require_admin():
        return jsonify({"error": "No autorizado"}), 403

    with db_session() as conn:
        actual = conn.execute(
            "SELECT * FROM publicidad WHERE id=?", (pub_id,)
        ).fetchone()
        if not actual:
            return jsonify({"error": "No encontrado"}), 404

        imagen_url = actual["imagen_url"]
        nuevo_archivo = request.files.get("imagen")
        if nuevo_archivo and nuevo_archivo.filename:
            nueva_url = _save_file(nuevo_archivo)
            if nueva_url:
                _delete_file(imagen_url)
                imagen_url = nueva_url

        titulo          = request.form.get("titulo",          actual["titulo"])
        subtitulo       = request.form.get("subtitulo",       actual["subtitulo"])
        color           = request.form.get("color",           actual["color"])
        color2          = request.form.get("color2",          actual["color2"])
        duracion        = int(request.form.get("duracion",    actual["duracion"]))
        activo          = int(request.form.get("activo",      actual["activo"]))
        plantilla_id    = request.form.get("plantilla_id",    actual.get("plantilla_id")) or None
        datos_plantilla = request.form.get("datos_plantilla", actual.get("datos_plantilla") or "{}")

        conn.execute(
            """UPDATE publicidad
               SET titulo=?, subtitulo=?, imagen_url=?, color=?, color2=?,
                   duracion=?, activo=?, plantilla_id=?, datos_plantilla=?
               WHERE id=?""",
            (titulo, subtitulo, imagen_url, color, color2, duracion, activo,
             plantilla_id, datos_plantilla, pub_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM publicidad WHERE id=?", (pub_id,)).fetchone()
    return jsonify(dict(row))


# ── DELETE /api/publicidad/<id> ───────────────────────────────────────────────
@publicidad_bp.route("/<int:pub_id>", methods=["DELETE"])
def eliminar(pub_id: int):
    if not _require_admin():
        return jsonify({"error": "No autorizado"}), 403

    with db_session() as conn:
        row = conn.execute(
            "SELECT imagen_url FROM publicidad WHERE id=?", (pub_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "No encontrado"}), 404
        _delete_file(row["imagen_url"])
        conn.execute("DELETE FROM publicidad WHERE id=?", (pub_id,))
        conn.commit()
    return jsonify({"ok": True})


# ── PUT /api/publicidad/orden ─────────────────────────────────────────────────
@publicidad_bp.route("/orden", methods=["PUT"])
def reordenar():
    if not _require_admin():
        return jsonify({"error": "No autorizado"}), 403

    ids = request.get_json(force=True, silent=True) or []
    with db_session() as conn:
        for pos, pub_id in enumerate(ids):
            conn.execute(
                "UPDATE publicidad SET orden=? WHERE id=?", (pos, pub_id)
            )
        conn.commit()
    return jsonify({"ok": True})


# ── GET /api/publicidad/config ────────────────────────────────────────────────
@publicidad_bp.route("/config", methods=["GET"])
def get_config():
    claves = ["pub_intervalo", "pub_transicion", "pub_mostrar_texto"]
    with db_session() as conn:
        rows = conn.execute(
            f"SELECT clave, valor FROM config WHERE clave IN ({','.join('?'*len(claves))})",
            claves,
        ).fetchall()
        ts_row = conn.execute(
            "SELECT MAX(creado_en) as ts FROM publicidad WHERE activo=1"
        ).fetchone()
    cfg = {r["clave"]: r["valor"] for r in rows}
    import time as _time
    ts_str = ts_row["ts"] if ts_row and ts_row["ts"] else None
    if ts_str:
        try:
            from datetime import datetime as _dt
            actualizado_en = int(_dt.fromisoformat(ts_str).timestamp() * 1000)
        except Exception:
            actualizado_en = int(_time.time() * 1000)
    else:
        actualizado_en = 0
    return jsonify({
        "intervalo":     int(cfg.get("pub_intervalo", 5)),
        "transicion":    cfg.get("pub_transicion", "fade"),
        "mostrar_texto": cfg.get("pub_mostrar_texto", "1") == "1",
        "actualizado_en": actualizado_en,
    })


# ── PUT /api/publicidad/config ────────────────────────────────────────────────
@publicidad_bp.route("/config", methods=["PUT"])
def put_config():
    if not _require_admin():
        return jsonify({"error": "No autorizado"}), 403

    data = request.get_json(force=True, silent=True) or {}
    mapa = {
        "intervalo":    "pub_intervalo",
        "transicion":   "pub_transicion",
        "mostrar_texto": "pub_mostrar_texto",
    }
    with db_session() as conn:
        for campo, clave in mapa.items():
            if campo in data:
                valor = str(data[campo])
                conn.execute(
                    "INSERT INTO config (clave,valor) VALUES (?,?) "
                    "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
                    (clave, valor),
                )
        conn.commit()
    return jsonify({"ok": True})


# ── GET /api/publicidad/qr  (público, sin auth) ───────────────────────────────
@publicidad_bp.route("/qr", methods=["GET"])
def generar_qr():
    """Genera un QR PNG para cualquier texto. Usado por plantillas (wifi, etc.)."""
    data = request.args.get("d", "")
    if not data:
        return "", 400
    try:
        import io as _io
        import qrcode as _qr
        qr = _qr.QRCode(version=None, box_size=8, border=3)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        from flask import send_file
        return send_file(buf, mimetype="image/png",
                         max_age=3600, conditional=True)
    except Exception as e:
        logger.warning(f"generar_qr: {e}")
        return "", 500
