from flask import Blueprint, request, jsonify, session
from database import db_session

modificadores_bp = Blueprint("modificadores", __name__, url_prefix="/api/modificadores")


def _require_auth():
    return bool(session.get("usuario_id"))


# ── Grupos de modificadores ───────────────────────────────────────────────────

@modificadores_bp.route("", methods=["GET"])
def listar_modificadores():
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        mods = conn.execute(
            "SELECT * FROM modificadores WHERE activo=1 ORDER BY nombre"
        ).fetchall()
        result = []
        for m in mods:
            opciones = conn.execute(
                "SELECT * FROM modificador_opciones WHERE modificador_id=? ORDER BY nombre",
                (m["id"],)
            ).fetchall()
            result.append({**dict(m), "opciones": [dict(o) for o in opciones]})
        return jsonify(result)


@modificadores_bp.route("", methods=["POST"])
def crear_modificador():
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    nombre    = str(data.get("nombre", "")).strip()
    tipo      = data.get("tipo", "opcional")
    seleccion = data.get("seleccion", "unico")
    opciones  = data.get("opciones", [])

    if not nombre:
        return jsonify({"error": "nombre requerido"}), 400
    if tipo not in ("opcional", "obligatorio"):
        return jsonify({"error": "tipo inválido"}), 400
    if seleccion not in ("unico", "multiple"):
        return jsonify({"error": "seleccion inválida"}), 400

    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO modificadores (nombre, tipo, seleccion) VALUES (?,?,?)",
            (nombre, tipo, seleccion)
        )
        mid = cur.lastrowid
        for op in opciones:
            op_nombre = str(op.get("nombre", "")).strip()
            if op_nombre:
                conn.execute(
                    "INSERT INTO modificador_opciones (modificador_id, nombre, precio_extra) VALUES (?,?,?)",
                    (mid, op_nombre, int(op.get("precio_extra", 0)))
                )
        return jsonify({"id": mid}), 201


@modificadores_bp.route("/<int:mid>", methods=["PUT"])
def actualizar_modificador(mid):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    with db_session() as conn:
        m = conn.execute("SELECT id FROM modificadores WHERE id=?", (mid,)).fetchone()
        if not m:
            return jsonify({"error": "No encontrado"}), 404

        if "nombre" in data:
            conn.execute("UPDATE modificadores SET nombre=? WHERE id=?", (str(data["nombre"]).strip(), mid))
        if "tipo" in data and data["tipo"] in ("opcional", "obligatorio"):
            conn.execute("UPDATE modificadores SET tipo=? WHERE id=?", (data["tipo"], mid))
        if "seleccion" in data and data["seleccion"] in ("unico", "multiple"):
            conn.execute("UPDATE modificadores SET seleccion=? WHERE id=?", (data["seleccion"], mid))
        if "activo" in data:
            conn.execute("UPDATE modificadores SET activo=? WHERE id=?", (1 if data["activo"] else 0, mid))

        # Replace opciones if provided
        if "opciones" in data:
            conn.execute("DELETE FROM modificador_opciones WHERE modificador_id=?", (mid,))
            for op in data["opciones"]:
                op_nombre = str(op.get("nombre", "")).strip()
                if op_nombre:
                    conn.execute(
                        "INSERT INTO modificador_opciones (modificador_id, nombre, precio_extra) VALUES (?,?,?)",
                        (mid, op_nombre, int(op.get("precio_extra", 0)))
                    )
        return jsonify({"ok": True})


@modificadores_bp.route("/<int:mid>", methods=["DELETE"])
def eliminar_modificador(mid):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        conn.execute("UPDATE modificadores SET activo=0 WHERE id=?", (mid,))
        return jsonify({"ok": True})


# ── Opciones sueltas ──────────────────────────────────────────────────────────

@modificadores_bp.route("/<int:mid>/opciones", methods=["POST"])
def agregar_opcion(mid):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    if not nombre:
        return jsonify({"error": "nombre requerido"}), 400
    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO modificador_opciones (modificador_id, nombre, precio_extra) VALUES (?,?,?)",
            (mid, nombre, int(data.get("precio_extra", 0)))
        )
        return jsonify({"id": cur.lastrowid}), 201


@modificadores_bp.route("/opciones/<int:oid>", methods=["DELETE"])
def eliminar_opcion(oid):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        conn.execute("DELETE FROM modificador_opciones WHERE id=?", (oid,))
        return jsonify({"ok": True})


# ── Modificadores por producto ────────────────────────────────────────────────

@modificadores_bp.route("/por-producto/<int:prod_id>", methods=["GET"])
def modificadores_de_producto(prod_id):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        mods = conn.execute(
            """SELECT m.* FROM modificadores m
               JOIN producto_modificadores pm ON pm.modificador_id=m.id
               WHERE pm.producto_id=? AND m.activo=1
               ORDER BY m.nombre""",
            (prod_id,)
        ).fetchall()
        result = []
        for m in mods:
            opciones = conn.execute(
                "SELECT * FROM modificador_opciones WHERE modificador_id=? ORDER BY nombre",
                (m["id"],)
            ).fetchall()
            result.append({**dict(m), "opciones": [dict(o) for o in opciones]})
        return jsonify(result)


@modificadores_bp.route("/por-producto/<int:prod_id>", methods=["PUT"])
def asignar_modificadores(prod_id):
    if not _require_auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    ids  = [int(i) for i in data.get("modificador_ids", [])]

    with db_session() as conn:
        conn.execute("DELETE FROM producto_modificadores WHERE producto_id=?", (prod_id,))
        for mid in ids:
            conn.execute(
                "INSERT OR IGNORE INTO producto_modificadores (producto_id, modificador_id) VALUES (?,?)",
                (prod_id, mid)
            )
        tiene = 1 if ids else 0
        conn.execute("UPDATE productos SET tiene_modificadores=? WHERE id=?", (tiene, prod_id))
        return jsonify({"ok": True, "asignados": len(ids)})
