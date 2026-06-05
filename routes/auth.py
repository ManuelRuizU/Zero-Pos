import logging
import time
from collections import defaultdict
from flask import Blueprint, request, jsonify, session
from database import db_session

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
logger = logging.getLogger("zero_pos.auth")

_MAX_INTENTOS = 10
_BLOQUEO_SEGUNDOS = 300  # 5 minutos

_intentos: dict[str, int]   = defaultdict(int)
_bloqueado_hasta: dict[str, float] = {}


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


def _contar_sesiones_activas() -> int:
    """Cuenta sesiones activas en flask_sessions (archivos con sesión válida)."""
    try:
        from flask import current_app
        session_dir = current_app.config.get("SESSION_FILE_DIR", "flask_sessions")
        import os, time
        count = 0
        now = time.time()
        for f in os.listdir(session_dir):
            path = os.path.join(session_dir, f)
            try:
                # Considerar sesiones activas si fueron modificadas en las últimas 8h
                if now - os.path.getmtime(path) < 8 * 3600:
                    count += 1
            except OSError:
                pass
        return count
    except Exception:
        return 0


@auth_bp.route("/login", methods=["POST"])
def login():
    ip = request.remote_addr or "unknown"
    ahora = time.time()

    if _bloqueado_hasta.get(ip, 0) > ahora:
        restante = int(_bloqueado_hasta[ip] - ahora)
        logger.warning(f"Login bloqueado por fuerza bruta: ip={ip} restante={restante}s")
        return jsonify({"error": f"Demasiados intentos. Espera {restante} segundos."}), 429

    data = request.get_json(silent=True) or {}
    pin = str(data.get("pin", "")).strip()

    if not pin or len(pin) != 4 or not pin.isdigit():
        return jsonify({"error": "PIN inválido"}), 400

    import bcrypt
    usuario_id = data.get("usuario_id")

    with db_session() as conn:
        if usuario_id:
            u = conn.execute(
                "SELECT * FROM usuarios WHERE id=? AND activo=1", (usuario_id,)
            ).fetchone()
            candidatos = [u] if u else []
        else:
            candidatos = conn.execute(
                "SELECT * FROM usuarios WHERE activo=1"
            ).fetchall()

        for u in candidatos:
            try:
                if not bcrypt.checkpw(pin.encode(), u["pin_hash"].encode()):
                    continue

                # Límite de sesiones simultáneas solo para rol 'cajero'
                ROLES_CON_LIMITE = ("cajero",)
                if u["rol"] in ROLES_CON_LIMITE:
                    max_cfg = conn.execute(
                        "SELECT valor FROM config WHERE clave='max_cajeros'"
                    ).fetchone()
                    max_cajeros = int(max_cfg["valor"]) if max_cfg else 2
                    activas = _contar_sesiones_activas()
                    if activas >= max_cajeros:
                        logger.warning(
                            f"Límite cajeros alcanzado ({activas}/{max_cajeros}), "
                            f"usuario={u['nombre']} rol={u['rol']}"
                        )
                        return jsonify({
                            "error": "Límite de cajeros alcanzado",
                            "upgrade": True,
                        }), 403

                # Login exitoso — limpiar contador
                _intentos.pop(ip, None)
                _bloqueado_hasta.pop(ip, None)

                session["usuario_id"]       = u["id"]
                session["usuario_nombre"]   = u["nombre"]
                session["usuario_rol"]      = u["rol"]
                suc_id = u["sucursal_id"] if "sucursal_id" in u.keys() else None
                if suc_id:
                    session["sucursal_id"] = suc_id
                else:
                    session.pop("sucursal_id", None)
                permisos_raw = u["permisos"] if "permisos" in u.keys() else None
                session["usuario_permisos"] = permisos_raw

                from database import permisos_efectivos
                perms = permisos_efectivos(dict(session))
                logger.info(f"Login exitoso: {u['nombre']} (rol={u['rol']}, sucursal={suc_id})")
                return jsonify({
                    "ok": True,
                    "usuario": {
                        "id":         u["id"],
                        "nombre":     u["nombre"],
                        "rol":        u["rol"],
                        "sucursal_id": suc_id,
                        "permisos":   perms,
                    }
                })
            except Exception:
                continue

    _intentos[ip] += 1
    if _intentos[ip] >= _MAX_INTENTOS:
        _bloqueado_hasta[ip] = time.time() + _BLOQUEO_SEGUNDOS
        _intentos.pop(ip, None)
        logger.warning(f"IP bloqueada por fuerza bruta: {ip}")
        return jsonify({"error": f"Demasiados intentos. Bloqueado por {_BLOQUEO_SEGUNDOS // 60} minutos."}), 429

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
        from database import permisos_efectivos
        perms = permisos_efectivos(dict(session))
        return jsonify({
            "id":         u["id"],
            "nombre":     u["nombre"],
            "rol":        u["rol"],
            "sucursal_id": u["sucursal_id"] if "sucursal_id" in u.keys() else None,
            "permisos":   perms,
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

    from database import ROLES_VALIDOS
    if rol not in ROLES_VALIDOS:
        return jsonify({"error": "Rol inválido"}), 400

    sucursal_id = data.get("sucursal_id") or None
    permisos_json = None
    if "permisos" in data and isinstance(data["permisos"], dict):
        import json as _json
        permisos_json = _json.dumps(data["permisos"])

    import bcrypt
    hashed = bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()

    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO usuarios (nombre, pin_hash, rol, sucursal_id, permisos) VALUES (?,?,?,?,?)",
            (nombre, hashed, rol, sucursal_id, permisos_json)
        )
        return jsonify({"ok": True, "id": cur.lastrowid}), 201


@auth_bp.route("/usuarios/<int:uid>", methods=["DELETE"])
def eliminar_usuario(uid):
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    if uid == session.get("usuario_id"):
        return jsonify({"error": "No puedes eliminarte a ti mismo"}), 400
    with db_session() as conn:
        conn.execute("UPDATE usuarios SET activo=0 WHERE id=?", (uid,))
        return jsonify({"ok": True})


# ── Sucursales ────────────────────────────────────────────────────────────────

@auth_bp.route("/sucursales", methods=["GET"])
def listar_sucursales():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM sucursales ORDER BY id"
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@auth_bp.route("/sucursales", methods=["POST"])
def crear_sucursal():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400
    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO sucursales (nombre, direccion, telefono) VALUES (?,?,?)",
            (nombre, data.get("direccion", ""), data.get("telefono", ""))
        )
        return jsonify({"ok": True, "id": cur.lastrowid}), 201


@auth_bp.route("/sucursales/<int:sid>", methods=["PUT"])
def actualizar_sucursal(sid):
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    data = request.get_json(silent=True) or {}
    with db_session() as conn:
        if "nombre" in data:
            conn.execute("UPDATE sucursales SET nombre=? WHERE id=?", (data["nombre"], sid))
        if "direccion" in data:
            conn.execute("UPDATE sucursales SET direccion=? WHERE id=?", (data["direccion"], sid))
        if "telefono" in data:
            conn.execute("UPDATE sucursales SET telefono=? WHERE id=?", (data["telefono"], sid))
        if "activa" in data:
            conn.execute("UPDATE sucursales SET activa=? WHERE id=?", (int(data["activa"]), sid))
        return jsonify({"ok": True})


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

        from database import ROLES_VALIDOS
        if "nombre" in data:
            conn.execute("UPDATE usuarios SET nombre=? WHERE id=?", (data["nombre"], uid))
        if "rol" in data and data["rol"] in ROLES_VALIDOS:
            conn.execute("UPDATE usuarios SET rol=? WHERE id=?", (data["rol"], uid))
        if "activo" in data:
            conn.execute("UPDATE usuarios SET activo=? WHERE id=?", (int(data["activo"]), uid))
        if "sucursal_id" in data:
            conn.execute("UPDATE usuarios SET sucursal_id=? WHERE id=?",
                         (data["sucursal_id"] or None, uid))
        if "permisos" in data:
            import json as _json
            pj = _json.dumps(data["permisos"]) if isinstance(data["permisos"], dict) else None
            conn.execute("UPDATE usuarios SET permisos=? WHERE id=?", (pj, uid))

        return jsonify({"ok": True})
