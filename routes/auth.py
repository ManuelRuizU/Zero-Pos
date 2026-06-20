import json
import logging
import threading
import time
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Blueprint, request, jsonify, session
from database import db_session, ensure_column

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")
logger = logging.getLogger("zero_pos.auth")

ROLES_VALIDOS = {'admin', 'cajero', 'cocina', 'propietario'}

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
    modo_asistencia = data.get("modo", "entrada")
    _MODOS_VALIDOS = {"entrada", "salida", "salida_colacion", "entrada_colacion"}
    if modo_asistencia not in _MODOS_VALIDOS:
        modo_asistencia = "entrada"

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

                # Bloquear PIN default 1234
                if bcrypt.checkpw(b"1234", u["pin_hash"].encode()):
                    return jsonify({
                        "ok": False,
                        "cambiar_pin": True,
                        "usuario_id":  u["id"],
                        "mensaje":     "Debes cambiar tu PIN antes de continuar",
                    }), 200

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

                from database import permisos_efectivos, log_event
                perms = permisos_efectivos(dict(session))

                # Registrar asistencia
                turno_id_actual = None
                try:
                    t = conn.execute(
                        "SELECT id FROM turnos WHERE usuario_id=? AND estado='abierto'",
                        (u["id"],)
                    ).fetchone()
                    if t:
                        turno_id_actual = t["id"]
                    conn.execute(
                        "INSERT INTO asistencia (usuario_id, tipo, turno_id) VALUES (?,?,?)",
                        (u["id"], modo_asistencia, turno_id_actual)
                    )
                    log_event(conn, 'asistencia', modo_asistencia,
                              entidad_id=u["id"],
                              payload={'hora': datetime.now().isoformat()},
                              usuario_id=u["id"],
                              usuario_nombre=u["nombre"])
                except Exception as _ae:
                    logger.warning(f"Error registrando asistencia: {_ae}")

                logger.info(f"Login exitoso: {u['nombre']} (rol={u['rol']}, sucursal={suc_id}, modo={modo_asistencia})")
                return jsonify({
                    "ok": True,
                    "modo": modo_asistencia,
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

    time.sleep(0.3)  # Evita timing attack — iguala tiempo con "usuario no existe"
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
    denoms = data.get("denominaciones", {})
    if denoms:
        fondo = sum(int(k) * int(v) for k, v in denoms.items() if str(v).isdigit())
    else:
        fondo = float(data.get("fondo_inicial", 0))
    denoms_json = json.dumps(denoms) if denoms else None

    # Backup pre-turno
    try:
        import shutil as _shutil
        from database import DB_PATH as _DB_PATH
        _bak = _DB_PATH.with_suffix('.db.bak')
        _shutil.copy2(_DB_PATH, _bak)
        logger.info(f"Backup pre-turno creado: {_bak}")
    except Exception as _e:
        logger.warning(f"No se pudo crear backup pre-turno: {_e}")

    with db_session() as conn:
        ensure_column(conn, 'turnos', 'denominaciones_apertura', 'TEXT')
        ensure_column(conn, 'turnos', 'denominaciones_cierre', 'TEXT')

        cur = conn.execute(
            """INSERT INTO turnos (usuario_id, fondo_inicial, estado, denominaciones_apertura)
               SELECT ?, ?, 'abierto', ?
               WHERE NOT EXISTS (
                   SELECT 1 FROM turnos
                   WHERE usuario_id=? AND estado='abierto'
               )""",
            (uid, fondo, denoms_json, uid)
        )
        if cur.rowcount == 0:
            abierto = conn.execute(
                "SELECT id FROM turnos WHERE usuario_id=? AND estado='abierto'", (uid,)
            ).fetchone()
            return jsonify({
                "error": "Ya tienes un turno abierto",
                "turno_id": abierto["id"] if abierto else None,
            }), 409
        turno_id = cur.lastrowid
        session["turno_id"] = turno_id

        row = conn.execute(
            """SELECT t.*, u.nombre as cajero
               FROM turnos t JOIN usuarios u ON t.usuario_id=u.id
               WHERE t.id=?""",
            (turno_id,)
        ).fetchone()
        turno_data = dict(row) if row else {"id": turno_id, "fondo_inicial": fondo,
                                            "denominaciones_apertura": denoms_json}

        cfg_rows = conn.execute("SELECT clave, valor FROM config").fetchall()
        config_negocio = {r["clave"]: r["valor"] for r in cfg_rows}
        config_imp = {
            "tipo":   config_negocio.get("impresora_tipo", "red"),
            "ip":     config_negocio.get("impresora_ip", "192.168.1.100"),
            "puerto": config_negocio.get("impresora_puerto", "9100"),
        }

    def _print():
        try:
            from utils.impresora import imprimir_apertura_turno
            imprimir_apertura_turno(turno_data, config_negocio, config_imp)
        except Exception as e:
            logger.warning(f"Error imprimiendo apertura turno: {e}")

    threading.Thread(target=_print, daemon=True,
                     name=f"apertura-turno-{turno_id}").start()

    return jsonify({"ok": True, "turno_id": turno_id})


@auth_bp.route("/turno/cerrar", methods=["POST"])
def cerrar_turno():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    denoms = data.get("denominaciones", {})
    if denoms:
        fondo_final = sum(int(k) * int(v) for k, v in denoms.items() if str(v).isdigit())
    else:
        fondo_final = float(data.get("fondo_final", 0))
    denoms_json = json.dumps(denoms) if denoms else None

    turno_data = None
    ventas_resumen = {}
    config_negocio = {}
    config_imp = {}

    with db_session() as conn:
        turno = conn.execute(
            "SELECT id, fondo_inicial FROM turnos WHERE usuario_id=? AND estado='abierto'",
            (uid,)
        ).fetchone()
        if not turno:
            return jsonify({"error": "No hay turno abierto"}), 404

        turno_id = turno["id"]
        fondo_inicial = int(turno["fondo_inicial"] or 0)

        # Calcular ventas del turno antes de cerrar
        resumen = conn.execute(
            """SELECT COUNT(*) as count,
                      COALESCE(SUM(total), 0) as total,
                      COALESCE(SUM(CASE WHEN metodo_pago='efectivo'
                                   THEN total ELSE 0 END), 0) as efectivo
               FROM ventas
               WHERE turno_id=? AND estado='completada'""",
            (turno_id,)
        ).fetchone()

        ventas_efectivo = int(resumen["efectivo"])
        ventas_total    = int(resumen["total"])
        ventas_count    = int(resumen["count"])

        fondo_esperado = fondo_inicial + ventas_efectivo
        descuadre      = int(fondo_final) - fondo_esperado

        if descuadre != 0:
            logger.warning(
                f"Turno #{turno_id} cerrado con "
                f"{'sobrante' if descuadre > 0 else 'faltante'} "
                f"de ${abs(descuadre):,}"
            )

        conn.execute(
            """UPDATE turnos SET estado='cerrado', cierre=CURRENT_TIMESTAMP,
               fondo_final=?, denominaciones_cierre=?,
               descuadre=?, ventas_efectivo=?, ventas_total=?, ventas_count=?
               WHERE id=?""",
            (fondo_final, denoms_json,
             descuadre, ventas_efectivo, ventas_total, ventas_count,
             turno_id)
        )

        # Turno completo post-UPDATE (cierre ya está seteado)
        row = conn.execute(
            """SELECT t.*, u.nombre as cajero
               FROM turnos t JOIN usuarios u ON t.usuario_id=u.id
               WHERE t.id=?""",
            (turno_id,)
        ).fetchone()
        if row:
            turno_data = dict(row)

        # Ventas del turno agrupadas por método de pago
        rows = conn.execute(
            """SELECT metodo_pago, COALESCE(SUM(total),0) as subtotal, COUNT(*) as n
               FROM ventas WHERE turno_id=? AND estado='completada'
               GROUP BY metodo_pago""",
            (turno_id,)
        ).fetchall()
        for r in rows:
            m = (r["metodo_pago"] or "").lower()
            amt = int(r["subtotal"])
            ventas_resumen["total"] = ventas_resumen.get("total", 0) + amt
            ventas_resumen["ventas_count"] = ventas_resumen.get("ventas_count", 0) + int(r["n"])
            if "efectivo" in m:
                ventas_resumen["efectivo"] = ventas_resumen.get("efectivo", 0) + amt
            elif "tarjeta" in m:
                ventas_resumen["tarjeta"] = ventas_resumen.get("tarjeta", 0) + amt
            elif "transferencia" in m:
                ventas_resumen["transferencia"] = ventas_resumen.get("transferencia", 0) + amt
            else:
                ventas_resumen["credito"] = ventas_resumen.get("credito", 0) + amt

        # Config para ticket e impresora
        cfg_rows = conn.execute("SELECT clave, valor FROM config").fetchall()
        config_negocio = {r["clave"]: r["valor"] for r in cfg_rows}
        config_imp = {
            "tipo":   config_negocio.get("impresora_tipo", "red"),
            "ip":     config_negocio.get("impresora_ip", "192.168.1.100"),
            "puerto": config_negocio.get("impresora_puerto", "9100"),
        }

    session.pop("turno_id", None)

    if turno_data:
        def _print():
            try:
                from utils.impresora import imprimir_cierre_turno
                imprimir_cierre_turno(turno_data, ventas_resumen, config_negocio, config_imp)
            except Exception as e:
                logger.warning(f"Error imprimiendo cierre turno: {e}")

        threading.Thread(target=_print, daemon=True,
                         name=f"cierre-turno-{turno_data.get('id')}").start()

    return jsonify({"ok": True})


@auth_bp.route("/turno/resumen", methods=["GET"])
def turno_resumen():
    """Resumen de ventas del turno abierto actual."""
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        turno = conn.execute(
            "SELECT id FROM turnos WHERE usuario_id=? AND estado='abierto'", (uid,)
        ).fetchone()
        if not turno:
            return jsonify({"ventas_count": 0, "total": 0,
                            "efectivo": 0, "tarjeta": 0,
                            "transferencia": 0, "credito": 0})

        rows = conn.execute(
            """SELECT metodo_pago, COALESCE(SUM(total),0) as subtotal, COUNT(*) as n
               FROM ventas WHERE turno_id=? AND estado='completada'
               GROUP BY metodo_pago""",
            (turno["id"],)
        ).fetchall()

    resumen = {"ventas_count": 0, "total": 0,
               "efectivo": 0, "tarjeta": 0, "transferencia": 0, "credito": 0}
    for r in rows:
        m = (r["metodo_pago"] or "").lower()
        amt = int(r["subtotal"])
        resumen["total"] += amt
        resumen["ventas_count"] += int(r["n"])
        if "efectivo" in m:
            resumen["efectivo"] += amt
        elif "tarjeta" in m:
            resumen["tarjeta"] += amt
        elif "transferencia" in m:
            resumen["transferencia"] += amt
        else:
            resumen["credito"] += amt
    return jsonify(resumen)


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
        if "jornada_horas_semanales" in data:
            jornada = data["jornada_horas_semanales"]
            conn.execute("UPDATE usuarios SET jornada_horas_semanales=? WHERE id=?",
                         (int(jornada) if jornada is not None else 45, uid))

        return jsonify({"ok": True})


# ── Cambio PIN (pre-login, no requiere sesión) ───────────────────────────────

@auth_bp.route("/cambiar-pin", methods=["POST"])
def cambiar_pin():
    data = request.get_json(silent=True) or {}
    usuario_id = data.get("usuario_id")
    pin_nuevo  = str(data.get("pin_nuevo", "")).strip()

    if not usuario_id:
        return jsonify({"error": "usuario_id requerido"}), 400
    if not pin_nuevo or len(pin_nuevo) != 4 or not pin_nuevo.isdigit():
        return jsonify({"error": "PIN debe ser exactamente 4 dígitos"}), 400
    if pin_nuevo == "1234":
        return jsonify({"error": "No puedes usar 1234 como PIN"}), 400

    import bcrypt as _bcrypt
    hashed = _bcrypt.hashpw(pin_nuevo.encode(), _bcrypt.gensalt()).decode()

    with db_session() as conn:
        n = conn.execute(
            "UPDATE usuarios SET pin_hash=? WHERE id=? AND activo=1",
            (hashed, usuario_id)
        ).rowcount

    if not n:
        return jsonify({"error": "Usuario no encontrado"}), 404

    logger.info(f"PIN cambiado para usuario_id={usuario_id}")
    return jsonify({"ok": True})


# ── Asistencia ────────────────────────────────────────────────────────────────

@auth_bp.route("/asistencia", methods=["POST"])
def registrar_asistencia():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    tipo = data.get("tipo")
    if tipo not in ("entrada", "salida", "salida_colacion", "entrada_colacion"):
        return jsonify({"error": "Tipo inválido"}), 400
    with db_session() as conn:
        conn.execute(
            "INSERT INTO asistencia (usuario_id, tipo, turno_id) VALUES (?,?,?)",
            (uid, tipo, session.get("turno_id"))
        )
    return jsonify({"ok": True})


@auth_bp.route("/asistencia", methods=["GET"])
def listar_asistencia():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    semana = request.args.get("semana", "actual")
    hoy = datetime.now().date()
    lunes = hoy - timedelta(days=hoy.weekday())
    domingo = lunes + timedelta(days=6)
    fecha_desde = str(lunes)
    fecha_hasta = str(domingo)

    with db_session() as conn:
        is_admin = session.get("usuario_rol") == "admin"
        if is_admin:
            rows = conn.execute(
                """SELECT a.*, u.nombre as usuario_nombre
                   FROM asistencia a JOIN usuarios u ON a.usuario_id = u.id
                   WHERE date(a.fecha) BETWEEN ? AND ?
                   ORDER BY a.fecha""",
                (fecha_desde, fecha_hasta)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT a.*, u.nombre as usuario_nombre
                   FROM asistencia a JOIN usuarios u ON a.usuario_id = u.id
                   WHERE a.usuario_id = ? AND date(a.fecha) BETWEEN ? AND ?
                   ORDER BY a.fecha""",
                (uid, fecha_desde, fecha_hasta)
            ).fetchall()

        # Agrupar por usuario y fecha
        dias: dict = {}
        for r in rows:
            d = dict(r)
            key = f"{d['usuario_id']}_{d['fecha'][:10]}"
            if key not in dias:
                dias[key] = {
                    "usuario_id":     d["usuario_id"],
                    "usuario_nombre": d["usuario_nombre"],
                    "fecha":          d["fecha"][:10],
                    "entrada":        None,
                    "salida_colacion": None,
                    "entrada_colacion": None,
                    "salida":         None,
                    "horas":          None,
                }
            t = d["tipo"]
            if t == "entrada" and dias[key]["entrada"] is None:
                dias[key]["entrada"] = d["fecha"][11:16]
            elif t == "salida_colacion":
                dias[key]["salida_colacion"] = d["fecha"][11:16]
            elif t == "entrada_colacion":
                dias[key]["entrada_colacion"] = d["fecha"][11:16]
            elif t == "salida":
                dias[key]["salida"] = d["fecha"][11:16]

        # Calcular horas por día
        resultados = []
        for item in dias.values():
            if item["entrada"] and item["salida"]:
                try:
                    base = datetime.now().date()
                    e = datetime.strptime(f"{base} {item['entrada']}", "%Y-%m-%d %H:%M")
                    s = datetime.strptime(f"{base} {item['salida']}", "%Y-%m-%d %H:%M")
                    diff = (s - e).total_seconds() / 3600
                    # Descontar colación si ambos registros existen
                    if item["salida_colacion"] and item["entrada_colacion"]:
                        sc = datetime.strptime(f"{base} {item['salida_colacion']}", "%Y-%m-%d %H:%M")
                        ec = datetime.strptime(f"{base} {item['entrada_colacion']}", "%Y-%m-%d %H:%M")
                        colacion_h = max(0, (ec - sc).total_seconds() / 3600)
                        diff -= colacion_h
                    item["horas"] = round(max(0, diff), 2)
                except Exception:
                    pass
            resultados.append(item)

        return jsonify(sorted(resultados, key=lambda x: (x["fecha"], x["usuario_nombre"])))


@auth_bp.route("/asistencia/resumen", methods=["GET"])
def resumen_asistencia():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    hoy = datetime.now().date()
    lunes = hoy - timedelta(days=hoy.weekday())
    fecha_desde = str(lunes)
    fecha_hasta = str(hoy)

    with db_session() as conn:
        is_admin = session.get("usuario_rol") == "admin"
        usuario_ids = []
        if is_admin:
            rows_u = conn.execute(
                "SELECT id, nombre, jornada_horas_semanales FROM usuarios WHERE activo=1"
            ).fetchall()
            usuario_ids = [dict(r) for r in rows_u]
        else:
            r = conn.execute(
                "SELECT id, nombre, jornada_horas_semanales FROM usuarios WHERE id=?", (uid,)
            ).fetchone()
            if r:
                usuario_ids = [dict(r)]

        resumen = []
        for u_info in usuario_ids:
            u_id = u_info["id"]
            jornada = u_info.get("jornada_horas_semanales") or 45

            filas = conn.execute(
                """SELECT tipo, fecha FROM asistencia
                   WHERE usuario_id=? AND date(fecha) BETWEEN ? AND ?
                   ORDER BY fecha""",
                (u_id, fecha_desde, fecha_hasta)
            ).fetchall()

            # Calcular horas totales de la semana
            dias_trabajados = set()
            ultima_entrada = None
            ultima_salida = None
            horas_totales = 0.0
            pendiente_entrada = None

            for f in filas:
                t = f["tipo"]
                ts = f["fecha"]
                fecha_dia = ts[:10]
                if t == "entrada":
                    pendiente_entrada = ts
                    ultima_entrada = ts
                    dias_trabajados.add(fecha_dia)
                elif t == "salida" and pendiente_entrada:
                    try:
                        e = datetime.strptime(pendiente_entrada, "%Y-%m-%d %H:%M:%S")
                        s = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                        horas_totales += max(0, (s - e).total_seconds() / 3600)
                    except Exception:
                        pass
                    ultima_salida = ts
                    pendiente_entrada = None

            resumen.append({
                "usuario_id":      u_id,
                "usuario_nombre":  u_info["nombre"],
                "horas_semana":    round(horas_totales, 2),
                "dias_trabajados": len(dias_trabajados),
                "jornada_pactada": jornada,
                "ultima_entrada":  ultima_entrada,
                "ultima_salida":   ultima_salida,
            })

        if not is_admin and resumen:
            return jsonify(resumen[0])
        return jsonify(resumen)
