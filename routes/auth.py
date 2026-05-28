import logging
from flask import Blueprint, request, jsonify, session
from database import db_session

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
logger = logging.getLogger("zero_pos.auth")


def _usuario_activo(conn, usuario_id: int):
    return conn.execute(
        "SELECT * FROM usuarios WHERE id=? AND activo=1", (usuario_id,)
    ).fetchone()


@auth_bp.route("/usuarios/publico", methods=["GET"])
def listar_usuarios_publico():
    """Lista nombre+id de usuarios activos para la pantalla de login (sin auth)."""
    with db_session() as conn:
        rows = conn.execute(
            "SELECT id, nombre FROM usuarios WHERE activo=1 ORDER BY nombre"
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    pin = str(data.get("pin", "")).strip()

    if not pin or len(pin) != 4 or not pin.isdigit():
        return jsonify({"error": "PIN inválido"}), 400

    import bcrypt
    usuario_id = data.get("usuario_id")

    with db_session() as conn:
        if usuario_id:
            # O(1): buscar directamente el usuario seleccionado
            u = conn.execute(
                "SELECT * FROM usuarios WHERE id=? AND activo=1", (usuario_id,)
            ).fetchone()
            candidatos = [u] if u else []
        else:
            # Fallback: recorrer todos (compatibilidad hacia atrás)
            candidatos = conn.execute(
                "SELECT * FROM usuarios WHERE activo=1"
            ).fetchall()

        for u in candidatos:
            try:
                if bcrypt.checkpw(pin.encode(), u["pin_hash"].encode()):
                    session["usuario_id"]     = u["id"]
                    session["usuario_nombre"] = u["nombre"]
                    session["usuario_rol"]    = u["rol"]
                    logger.info(f"Login exitoso: {u['nombre']} (rol={u['rol']})")
                    return jsonify({
                        "ok": True,
                        "usuario": {
                            "id":     u["id"],
                            "nombre": u["nombre"],
                            "rol":    u["rol"],
                        }
                    })
            except Exception:
                continue

    return jsonify({"error": "PIN incorrecto"}), 401


@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@auth_bp.route("/me", methods=["GET"])
def me():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        u = _usuario_activo(conn, uid)
        if not u:
            session.clear()
            return jsonify({"error": "Usuario inválido"}), 401
        return jsonify({
            "id": u["id"],
            "nombre": u["nombre"],
            "rol": u["rol"],
        })


# ── Turnos ────────────────────────────────────────────────────────────────────

@auth_bp.route("/turno/abrir", methods=["POST"])
def abrir_turno():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    fondo = float(data.get("fondo_inicial", 0))

    with db_session() as conn:
        abierto = conn.execute(
            "SELECT id FROM turnos WHERE usuario_id=? AND estado='abierto'", (uid,)
        ).fetchone()
        if abierto:
            return jsonify({"error": "Ya tienes un turno abierto", "turno_id": abierto["id"]}), 409

        cur = conn.execute(
            """INSERT INTO turnos (usuario_id, fondo_inicial, estado)
               VALUES (?, ?, 'abierto')""",
            (uid, fondo)
        )
        session["turno_id"] = cur.lastrowid
        return jsonify({"ok": True, "turno_id": cur.lastrowid})


@auth_bp.route("/turno/cerrar", methods=["POST"])
def cerrar_turno():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    fondo_final = float(data.get("fondo_final", 0))

    with db_session() as conn:
        turno = conn.execute(
            "SELECT id FROM turnos WHERE usuario_id=? AND estado='abierto'", (uid,)
        ).fetchone()
        if not turno:
            return jsonify({"error": "No hay turno abierto"}), 404

        conn.execute(
            """UPDATE turnos SET estado='cerrado', cierre=CURRENT_TIMESTAMP, fondo_final=?
               WHERE id=?""",
            (fondo_final, turno["id"])
        )
        session.pop("turno_id", None)
        return jsonify({"ok": True})


@auth_bp.route("/turno/actual", methods=["GET"])
def turno_actual():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        turno = conn.execute(
            """SELECT t.*, u.nombre as cajero
               FROM turnos t JOIN usuarios u ON t.usuario_id=u.id
               WHERE t.usuario_id=? AND t.estado='abierto'""",
            (uid,)
        ).fetchone()
        if not turno:
            return jsonify({"turno": None})
        return jsonify({"turno": dict(turno)})


# ── Usuarios CRUD (admin) ─────────────────────────────────────────────────────

@auth_bp.route("/usuarios", methods=["GET"])
def listar_usuarios():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    with db_session() as conn:
        rows = conn.execute(
            "SELECT id, nombre, rol, activo, creado_en FROM usuarios ORDER BY id"
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@auth_bp.route("/usuarios", methods=["POST"])
def crear_usuario():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403

    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    pin = str(data.get("pin", "")).strip()
    rol = data.get("rol", "cajero")

    if not nombre or len(pin) != 4 or not pin.isdigit():
        return jsonify({"error": "Datos inválidos"}), 400
    if rol not in ("admin", "cajero", "cocina"):
        return jsonify({"error": "Rol inválido"}), 400

    import bcrypt
    hashed = bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()

    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO usuarios (nombre, pin_hash, rol) VALUES (?,?,?)",
            (nombre, hashed, rol)
        )
        return jsonify({"ok": True, "id": cur.lastrowid}), 201


@auth_bp.route("/usuarios/<int:uid>", methods=["PUT"])
def actualizar_usuario(uid):
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403

    data = request.get_json(silent=True) or {}
    with db_session() as conn:
        if "pin" in data:
            pin = str(data["pin"]).strip()
            if len(pin) != 4 or not pin.isdigit():
                return jsonify({"error": "PIN inválido"}), 400
            import bcrypt
            hashed = bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()
            conn.execute("UPDATE usuarios SET pin_hash=? WHERE id=?", (hashed, uid))

        if "nombre" in data:
            conn.execute("UPDATE usuarios SET nombre=? WHERE id=?", (data["nombre"], uid))
        if "rol" in data and data["rol"] in ("admin", "cajero", "cocina"):
            conn.execute("UPDATE usuarios SET rol=? WHERE id=?", (data["rol"], uid))
        if "activo" in data:
            conn.execute("UPDATE usuarios SET activo=? WHERE id=?", (int(data["activo"]), uid))

        return jsonify({"ok": True})
