import json
import logging
import re
import urllib.request
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, session
from database import db_session

voz_bp = Blueprint("voz", __name__, url_prefix="/api/voz")
logger = logging.getLogger("zero_pos.voz")


# ── Ollama helpers ────────────────────────────────────────────────────────────

def _ollama_ok() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
        return True
    except Exception:
        return False


def _ollama(prompt: str, system: str = "", max_tokens: int = 200) -> str | None:
    payload = json.dumps({
        "model": "tinyllama",
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": max_tokens},
    }).encode()
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode()).get("response", "").strip()
    except Exception as e:
        logger.debug(f"Ollama: {e}")
        return None


# ── Interpretar ───────────────────────────────────────────────────────────────

@voz_bp.route("/interpretar", methods=["POST"])
def interpretar():
    """Convierte texto libre en acción estructurada JSON."""
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    body = request.get_json(silent=True) or {}
    texto = str(body.get("texto", "")).strip()
    if not texto:
        return jsonify({"error": "texto requerido"}), 400

    accion = None
    if _ollama_ok():
        system = (
            "Eres un asistente de punto de venta. Dado un comando de voz en español, "
            "extrae la intención. Responde ÚNICAMENTE con JSON válido, sin texto extra.\n"
            'Formato exacto: {"accion":"agregar|quitar|cobrar|consultar|limpiar",'
            '"producto":"nombre del producto o vacío","cantidad":1,"variante":""}'
        )
        raw = _ollama(f'Comando: "{texto}"', system, 120)
        if raw:
            m = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
            if m:
                try:
                    accion = json.loads(m.group())
                except Exception:
                    pass

    if not accion:
        accion = _parsear_keywords(texto)

    uid = session.get("usuario_id")
    with db_session() as conn:
        conn.execute(
            "INSERT INTO voz_historial (texto, accion, usuario_id) VALUES (?,?,?)",
            (texto, json.dumps(accion, ensure_ascii=False), uid),
        )

    return jsonify(accion)


def _parsear_keywords(texto: str) -> dict:
    t = texto.lower()

    if any(p in t for p in ["agrega", "agregar", "suma", "sumar", "añade", "añadir", "pon ", "poner", "mete", "meter"]):
        accion = "agregar"
    elif any(p in t for p in ["quita", "quitar", "elimina", "eliminar", "saca", "sacar", "borra", "borrar", "remueve"]):
        accion = "quitar"
    elif any(p in t for p in ["cobra", "cobrar", "paga", "pagar", "cobro", "cobro"]):
        accion = "cobrar"
    elif any(p in t for p in ["limpia", "limpiar", "vacía", "vaciar", "borra todo", "borrar todo", "nuevo cliente"]):
        accion = "limpiar"
    elif any(p in t for p in ["cuánto va", "cuanto va", "total", "cuánto llevo", "cuanto llevo", "cuánto hay"]):
        accion = "consultar"
    else:
        accion = "desconocido"

    # Cantidad
    numeros = {"un ": 1, "una ": 1, "dos": 2, "tres": 3, "cuatro": 4,
               "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
    cantidad = 1
    for palabra, num in numeros.items():
        if palabra in t:
            cantidad = num
            break
    m = re.search(r'\b(\d+)\b', t)
    if m:
        cantidad = int(m.group(1))

    # Variante por tamaño
    variante = ""
    for patron, nombre in [
        (r"350\s*m?l", "350ml"), (r"500\s*m?l|media\s*litro|medio\s*litro", "500ml"),
        (r"1[.,]5\s*l|litro\s*y\s*medio|1\s*y\s*medio", "1.5L"),
        (r"2\s*litros?|2\s*l\b", "2L"), (r"3\s*litros?", "3L"),
        (r"\bun\s*litro|\b1\s*litro", "1L"),
        (r"\bgrande\b|\bgrands\b", "grande"),
        (r"\bchic[ao]\b|\bpequeñ[ao]\b|\bmini\b", "chico"),
        (r"\blat[ai]\b", "lata"),
    ]:
        if re.search(patron, t, re.IGNORECASE):
            variante = nombre
            break

    # Producto: eliminar palabras de comando
    stop = {
        "zero", "hal", "jarvis", "nova",
        "agrega", "agregar", "suma", "sumar", "añade", "añadir", "pon", "poner", "mete",
        "quita", "quitar", "elimina", "eliminar", "saca", "borra",
        "cobra", "cobrar", "limpia", "limpiar",
        "un", "una", "uno", "dos", "tres", "cuatro", "cinco",
        "el", "la", "los", "las", "de", "del", "al", "por", "favor",
        "me", "te", "se", "que", "y", "a", "en",
    }
    palabras = [p for p in t.split() if p not in stop and not p.isdigit() and len(p) > 1]
    producto = " ".join(palabras).strip()

    return {"accion": accion, "producto": producto, "cantidad": cantidad, "variante": variante}


# ── Consulta ──────────────────────────────────────────────────────────────────

@voz_bp.route("/consulta", methods=["POST"])
def consulta():
    """Responde preguntas sobre el negocio consultando la DB."""
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    body = request.get_json(silent=True) or {}
    texto = str(body.get("texto", "")).strip()
    ctx_prod = str(body.get("contexto_producto", "")).strip()
    if not texto:
        return jsonify({"error": "texto requerido"}), 400

    datos = _consultar_db(texto, ctx_prod)
    template = datos.pop("template", "No tengo esa información ahora.")

    if _ollama_ok() and datos.get("datos"):
        system = (
            "Eres ZERO, el asistente del punto de venta. "
            "Responde en español, breve y natural (1-2 oraciones). "
            "Solo usa los datos dados, no inventes."
        )
        datos_str = json.dumps(datos.get("datos"), ensure_ascii=False)
        raw = _ollama(f'Pregunta: "{texto}"\nDatos: {datos_str}\nRespuesta breve:', system, 80)
        respuesta = raw if raw else template
    else:
        respuesta = template

    uid = session.get("usuario_id")
    with db_session() as conn:
        conn.execute(
            "INSERT INTO voz_historial (texto, accion, usuario_id) VALUES (?,?,?)",
            (texto, json.dumps({"consulta": respuesta}, ensure_ascii=False), uid),
        )

    return jsonify({"respuesta": respuesta, **datos})


def _consultar_db(texto: str, ctx: str) -> dict:
    t = texto.lower()

    with db_session() as conn:
        cfg = {r["clave"]: r["valor"]
               for r in conn.execute("SELECT clave, valor FROM config").fetchall()}
        moneda = cfg.get("moneda", "CLP")

        # ── Ventas de hoy ─────────────────────────────────────────────
        if any(k in t for k in ["hoy", "vendí hoy", "vendi hoy", "cuánto hoy", "cuanto hoy"]):
            row = conn.execute(
                "SELECT COUNT(*) as n, COALESCE(SUM(total),0) as tot "
                "FROM ventas WHERE DATE(creado_en)=DATE('now') AND estado='completada'"
            ).fetchone()
            t_, n_ = int(row["tot"]), row["n"]
            resp = f"Hoy llevas ${t_:,.0f} en {n_} {'venta' if n_==1 else 'ventas'}.".replace(",", ".")
            return {"datos": {"total": t_, "num_ventas": n_}, "template": resp}

        # ── Stock bajo ────────────────────────────────────────────────
        if any(k in t for k in ["agotarse", "agotar", "stock bajo", "poco stock", "por agotarse",
                                  "crítico", "critico", "bajos"]):
            rows = conn.execute(
                "SELECT nombre, stock, stock_minimo FROM productos "
                "WHERE activo=1 AND tiene_variantes=0 AND stock<=stock_minimo LIMIT 8"
            ).fetchall()
            vrows = conn.execute(
                "SELECT p.nombre||' '||pv.nombre as nombre, pv.stock, pv.stock_minimo "
                "FROM producto_variantes pv JOIN productos p ON pv.producto_id=p.id "
                "WHERE pv.activo=1 AND pv.stock<=pv.stock_minimo LIMIT 8"
            ).fetchall()
            todos = [dict(r) for r in rows] + [dict(r) for r in vrows]
            if not todos:
                resp = "Todos los productos tienen stock suficiente."
            else:
                nombres = ", ".join(r["nombre"] for r in todos[:4])
                resp = f"Hay {len(todos)} producto{'s' if len(todos)>1 else ''} con stock bajo: {nombres}."
            return {"datos": todos, "template": resp}

        # ── Ventas semanales de un producto ───────────────────────────
        if any(k in t for k in ["cuánto vendo", "cuántos vendo", "por semana", "a la semana",
                                  "vendemos", "vendo de", "cuánto vendemos"]):
            stop = {"zero", "cuánto", "cuántos", "vendo", "vendemos", "por", "semana",
                    "la", "a", "de", "en", "el", "la", "los", "las"}
            palabras = [w for w in t.split() if w not in stop and len(w) > 2]
            prod_q = " ".join(palabras[:3]) if palabras else ctx
            if prod_q:
                hace4 = (datetime.now() - timedelta(weeks=4)).strftime("%Y-%m-%d")
                row = conn.execute(
                    "SELECT p.nombre, SUM(vi.cantidad) as tot "
                    "FROM venta_items vi JOIN productos p ON vi.producto_id=p.id "
                    "JOIN ventas v ON vi.venta_id=v.id "
                    "WHERE p.nombre LIKE ? AND v.estado='completada' AND DATE(v.creado_en)>=? "
                    "GROUP BY p.id LIMIT 1",
                    (f"%{prod_q}%", hace4)
                ).fetchone()
                if row:
                    prom = round(row["tot"] / 4)
                    resp = f"Vendes en promedio {prom} {row['nombre']} por semana."
                    return {"datos": dict(row), "template": resp}

        # ── Predicción mañana ──────────────────────────────────────────
        if any(k in t for k in ["mañana", "manana", "necesito", "próxima semana", "proxima semana",
                                  "cuánto comprar", "comprar"]):
            dia = str((datetime.now().weekday() + 1) % 7)
            hace8 = (datetime.now() - timedelta(weeks=8)).strftime("%Y-%m-%d")
            rows = conn.execute(
                "SELECT p.nombre, AVG(d.c) as prom "
                "FROM ("
                "  SELECT vi.producto_id, SUM(vi.cantidad) as c "
                "  FROM venta_items vi JOIN ventas v ON vi.venta_id=v.id "
                "  WHERE v.estado='completada' AND DATE(v.creado_en)>=? "
                "    AND strftime('%w',v.creado_en)=? "
                "  GROUP BY DATE(v.creado_en), vi.producto_id"
                ") d JOIN productos p ON d.producto_id=p.id "
                "GROUP BY d.producto_id ORDER BY prom DESC LIMIT 5",
                (hace8, dia)
            ).fetchall()
            if rows:
                items = [(r["nombre"], round(r["prom"])) for r in rows]
                resp = "Para mañana sugiero: " + ", ".join(f"{n} ~{v}u" for n, v in items) + "."
                return {"datos": items, "template": resp}

        # ── Top productos ──────────────────────────────────────────────
        if any(k in t for k in ["más vendido", "mas vendido", "mejor", "top", "popular"]):
            rows = conn.execute(
                "SELECT p.nombre, SUM(vi.cantidad) as v "
                "FROM venta_items vi JOIN productos p ON vi.producto_id=p.id "
                "JOIN ventas vn ON vi.venta_id=vn.id "
                "WHERE vn.estado='completada' AND DATE(vn.creado_en)>=DATE('now','-30 days') "
                "GROUP BY vi.producto_id ORDER BY v DESC LIMIT 5"
            ).fetchall()
            if rows:
                items = [(r["nombre"], r["v"]) for r in rows]
                resp = "Los más vendidos del mes: " + ", ".join(f"{n} ({v})" for n, v in items) + "."
                return {"datos": items, "template": resp}

        # ── Stock de producto específico ──────────────────────────────
        prod_buscar = ctx
        for kw in ["cuánto", "cuánta", "cuántos", "cuántas", "cuanto", "cuanta",
                   "cuantos", "cuantas", "quedan", "queda", "stock", "hay"]:
            if kw in t:
                parte = t
                for sw in [kw, "zero", "hal", "jarvis", "nova", "quedan", "queda",
                           "hay", "de", "la", "el", "los", "las", "me", "te"]:
                    parte = parte.replace(sw, " ")
                parte = " ".join(p for p in parte.split() if len(p) > 2)
                if parte:
                    prod_buscar = parte
                break

        if prod_buscar:
            prod = conn.execute(
                "SELECT id, nombre, stock, tiene_variantes FROM productos "
                "WHERE activo=1 AND nombre LIKE ? LIMIT 1",
                (f"%{prod_buscar}%",)
            ).fetchone()
            if prod:
                if prod["tiene_variantes"]:
                    vvs = conn.execute(
                        "SELECT nombre, stock FROM producto_variantes WHERE producto_id=? AND activo=1",
                        (prod["id"],)
                    ).fetchall()
                    detalle = ", ".join(f"{v['nombre']}: {v['stock']}" for v in vvs)
                    resp = f"{prod['nombre']}: {detalle}."
                else:
                    resp = f"Quedan {prod['stock']} {prod['nombre']}."
                return {"datos": dict(prod), "template": resp}

    return {"datos": None, "template": "No encontré esa información. Intenta ser más específico."}


# ── Saludo matutino ───────────────────────────────────────────────────────────

@voz_bp.route("/saludo", methods=["GET"])
def saludo():
    """Saludo con resumen del negocio (ventas ayer, stock bajo, turno)."""
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        ayer = conn.execute(
            "SELECT COUNT(*) as n, COALESCE(SUM(total),0) as tot "
            "FROM ventas WHERE DATE(creado_en)=DATE('now','-1 day') AND estado='completada'"
        ).fetchone()
        sem_ant = conn.execute(
            "SELECT COALESCE(SUM(total),0) as tot "
            "FROM ventas WHERE DATE(creado_en)=DATE('now','-8 days') AND estado='completada'"
        ).fetchone()
        bajo_prod = conn.execute(
            "SELECT nombre, stock FROM productos "
            "WHERE activo=1 AND stock<=stock_minimo LIMIT 5"
        ).fetchall()
        bajo_var = conn.execute(
            "SELECT p.nombre||' '||pv.nombre as nombre, pv.stock "
            "FROM producto_variantes pv JOIN productos p ON pv.producto_id=p.id "
            "WHERE pv.activo=1 AND pv.stock<=pv.stock_minimo LIMIT 5"
        ).fetchall()
        bajo = [dict(r) for r in bajo_prod] + [dict(r) for r in bajo_var]
        turno = conn.execute(
            "SELECT id FROM turnos WHERE estado='abierto' LIMIT 1"
        ).fetchone()

    tot_ayer = int(ayer["tot"])
    n_ayer = ayer["n"]
    tot_sem = int(sem_ant["tot"])

    diff_txt = ""
    if tot_sem > 0:
        diff = ((tot_ayer - tot_sem) / tot_sem) * 100
        if diff >= 5:
            diff_txt = f", un {abs(diff):.0f}% más que la semana pasada"
        elif diff <= -5:
            diff_txt = f", un {abs(diff):.0f}% menos que la semana pasada"

    bajo_txt = ""
    if bajo:
        nombres = ", ".join(b["nombre"] for b in bajo[:3])
        bajo_txt = f" Hay {len(bajo)} producto{'s' if len(bajo)>1 else ''} con stock bajo: {nombres}."

    turno_txt = "" if turno else " No hay turno abierto. ¿Abrimos la caja?"
    n_txt = f"{n_ayer} {'venta' if n_ayer == 1 else 'ventas'}"
    template = f"Buenos días. Ayer vendiste ${tot_ayer:,.0f} en {n_txt}{diff_txt}.{bajo_txt}{turno_txt}".replace(",", ".")

    respuesta = template
    if _ollama_ok():
        system = (
            "Eres ZERO, el asistente del punto de venta. "
            "Saluda al cajero de manera breve, natural y motivadora en español. "
            "Máximo 2 oraciones. Solo usa los datos dados."
        )
        datos_str = json.dumps({
            "ventas_ayer": tot_ayer, "num_ventas": n_ayer,
            "ventas_semana_anterior": tot_sem, "productos_bajo_stock": len(bajo),
            "turno_abierto": turno is not None,
        }, ensure_ascii=False)
        raw = _ollama(f"Datos: {datos_str}\nGenera saludo:", system, 100)
        if raw:
            respuesta = raw

    return jsonify({
        "respuesta": respuesta,
        "datos": {
            "ventas_ayer": tot_ayer, "num_ventas_ayer": n_ayer,
            "ventas_semana_ant": tot_sem, "bajo_stock": len(bajo),
            "turno": bool(turno),
        },
    })


# ── Config ────────────────────────────────────────────────────────────────────

_VOZ_KEYS = {"voz_activa", "voz_palabra_clave", "voz_velocidad", "voz_tono"}


@voz_bp.route("/config", methods=["GET"])
def config_get():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute("SELECT clave, valor FROM config WHERE clave LIKE 'voz_%'").fetchall()
        cfg = {r["clave"]: r["valor"] for r in rows}
    return jsonify({
        "voz_activa": cfg.get("voz_activa", "1"),
        "voz_palabra_clave": cfg.get("voz_palabra_clave", "ZERO"),
        "voz_velocidad": cfg.get("voz_velocidad", "1.0"),
        "voz_tono": cfg.get("voz_tono", "1.0"),
    })


@voz_bp.route("/config", methods=["POST"])
def config_post():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    data = request.get_json(silent=True) or {}
    with db_session() as conn:
        for clave, valor in data.items():
            if clave in _VOZ_KEYS:
                conn.execute(
                    "INSERT OR REPLACE INTO config (clave, valor) VALUES (?,?)",
                    (clave, str(valor))
                )
    return jsonify({"ok": True})


# ── Historial ──────────────────────────────────────────────────────────────────

@voz_bp.route("/historial", methods=["GET"])
def historial():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute(
            "SELECT vh.id, vh.texto, vh.accion, vh.creado_en, u.nombre as usuario "
            "FROM voz_historial vh LEFT JOIN usuarios u ON vh.usuario_id=u.id "
            "WHERE DATE(vh.creado_en)=DATE('now') "
            "ORDER BY vh.creado_en DESC LIMIT 50"
        ).fetchall()
        return jsonify([dict(r) for r in rows])
