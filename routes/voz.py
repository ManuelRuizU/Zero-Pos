import json
import logging
import re
import unicodedata
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


# ── Parser de intenciones por keywords (sin LLM) ─────────────────────────────

_WAKE_WORDS = frozenset({'zero', 'jarvis', 'hal', 'nova', 'oye', 'hola', 'hey'})

_PAT_AGREGAR = re.compile(
    r'\b(agrega|agrega|agregame|agregame|pon(?:me|le|nos|te)?|'
    r'annade|anade|suma|quiero|dame|deme|metele|meteme|trae|traeme|dale|agrega)\b', re.I
)
_PAT_QUITAR = re.compile(
    r'\b(quita|quitame|saca|elimina|borra(?!\s+todo)\b|remueve|quitar|sacar)\b', re.I
)
_PAT_COBRAR = re.compile(
    r'\b(cobra|cobrar|a\s+cobrar|cerramos|eso\s+es\s+todo|eso\s+nomas?|'
    r'listo\b|pagar|paga|factura|boleta|cuanto\s+va|cuanto\s+es|el\s+total)\b', re.I
)
_PAT_LIMPIAR = re.compile(
    r'\b(limpia|vacia|borra\s+todo|de\s+nuevo|empezar\s+de\s+nuevo|'
    r'nuevo\s+cliente|limpiar|vaciar)\b', re.I
)
_PAT_VENTAS = re.compile(
    r'\b(cuanto\s+vendi|vendi\s+hoy|ventas\s+hoy|total\s+del\s+dia|cuanto\s+llevamos)\b', re.I
)
_PAT_STOCK = re.compile(
    r'\b(cuanto\s+queda|cuantos\s+quedan|quedan\s+de|hay\s+de|stock\s+de)\b', re.I
)

_VARIANTE_EXACTA = [
    (re.compile(r'3\s*(?:litros?|l\b)|tres\s*litros?|3000\s*(?:ml|cc)?', re.I), '3L'),
    (re.compile(r'2\s*(?:litros?|l\b)|dos\s*litros?|2000\s*(?:ml|cc)?|familiar\b|mega\b', re.I), '2L'),
    (re.compile(r'1[.,]5\s*(?:litros?|l\b)?|1500\s*(?:ml|cc)?|litro\s+y\s+medio|uno\s+(?:y\s+)?medio|uno\s+coma\s+cinco', re.I), '1.5L'),
    (re.compile(r'\bun\s*litro\b|1000\s*(?:ml|cc)?|\b1\s*l\b|de\s+litro\b', re.I), '1L'),
    (re.compile(r'500\s*(?:ml|cc)?|medio\s*litro|botella\s+chica\b', re.I), '500ml'),
    (re.compile(r'35[05]\s*(?:ml|cc)?|en\s+lata\b|\blata\b', re.I), '350ml'),
    # Weight — medio kilo before kilo so "medio kilo" doesn't match bare "kilo"
    (re.compile(r'medio\s+kilo|500\s*(?:g|gr|gramos?)', re.I), '500g'),
    (re.compile(r'un\s+cuarto|250\s*(?:g|gr|gramos?)', re.I), '250g'),
    (re.compile(r'\bun\s*kilo\b|\b1\s*kg\b|\bkilo\b', re.I), '1kg'),
]
_VARIANTE_RELATIVA = [
    # patterns work on accent-stripped text (ñ→n, etc.)
    (re.compile(r'\bchic[ao]s?\b|\bpeque[nñ][ao]s?\b|\bmini\b|\bchiquit[ao]s?\b', re.I), 'pequeña'),
    (re.compile(r'\bmedian[ao]s?\b|\bdel\s+medio\b', re.I), 'mediana'),
    (re.compile(r'\bgrandes?\b|\bfamiliar\b|\bmega\b', re.I), 'grande'),
]

# Phrases to strip before quantity detection so "tres litros" isn't counted as qty=3
_SIZE_STRIP_PATS = [
    re.compile(r'\b(?:tres|dos|un(?:o|a)?)\s+litros?\b', re.I),
    re.compile(r'\btres\s+kilos?\b|\bdos\s+kilos?\b', re.I),
    re.compile(r'\d+\s*(?:ml|cc|litros?|kilos?|kg|gr|gramos?)\b', re.I),
    re.compile(r'litro\s+y\s+medio\b', re.I),
    re.compile(r'medio\s+kilo\b', re.I),
    re.compile(r'un\s+cuarto\b', re.I),
]

def _strip_size_phrases(t: str) -> str:
    for pat in _SIZE_STRIP_PATS:
        t = pat.sub(' ', t)
    return ' '.join(t.split())
_NUMEROS_PALABRAS = [
    (re.compile(r'\buna\s+docena\b', re.I), 12),
    (re.compile(r'\bmedia\s+docena\b', re.I), 6),
    (re.compile(r'\bdiez\b', re.I), 10), (re.compile(r'\bnueve\b', re.I), 9),
    (re.compile(r'\bocho\b', re.I), 8),  (re.compile(r'\bsiete\b', re.I), 7),
    (re.compile(r'\bseis\b', re.I), 6),  (re.compile(r'\bcinco\b', re.I), 5),
    (re.compile(r'\bcuatro\b', re.I), 4),(re.compile(r'\btres\b', re.I), 3),
    (re.compile(r'\bun\s+par\b', re.I), 2),(re.compile(r'\bdos\b', re.I), 2),
    (re.compile(r'\bun[ao]?\b', re.I), 1),
]
_SIZE_DIGITS = frozenset({350, 355, 500, 1000, 1500, 2000, 3000})


def _normalizar(t: str) -> str:
    t = t.lower()
    t = unicodedata.normalize('NFD', t)
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    return ' '.join(t.split())


def _detectar_accion(t: str) -> str:
    # Check unambiguous actions first so "dame el total y cobra" → cobrar, not agregar
    if _PAT_LIMPIAR.search(t): return 'limpiar'
    if _PAT_COBRAR.search(t):  return 'cobrar'
    if _PAT_VENTAS.search(t):  return 'ventas_hoy'
    if _PAT_STOCK.search(t):   return 'stock'
    if _PAT_QUITAR.search(t):  return 'quitar'
    if _PAT_AGREGAR.search(t): return 'agregar'
    return 'desconocido'


def _detectar_cantidad(t: str) -> int:
    for pat, n in _NUMEROS_PALABRAS:
        if pat.search(t):
            return n
    m = re.search(r'\b(\d+)\b', t)
    if m:
        n = int(m.group(1))
        if n not in _SIZE_DIGITS:
            return max(1, min(n, 99))
    return 1


def _detectar_variante_hint(t: str) -> dict | None:
    for pat, val in _VARIANTE_EXACTA:
        if pat.search(t):
            return {'tipo': 'exacta', 'valor': val}
    for pat, tipo in _VARIANTE_RELATIVA:
        if pat.search(t):
            return {'tipo': tipo, 'valor': None}
    return None


def _match_productos(t_norm: str, conn) -> list[dict]:
    """Fuzzy-match products by word overlap. Threshold 60%."""
    rows = conn.execute(
        "SELECT id, nombre, precio, tiene_variantes FROM productos WHERE activo=1"
    ).fetchall()
    matches = []
    for p in rows:
        palabras = [w for w in _normalizar(p['nombre']).split() if len(w) > 2]
        if not palabras:
            continue
        hits = sum(1 for w in palabras if w in t_norm)
        score = hits / len(palabras)
        if score >= 0.6:
            matches.append({
                'id': p['id'],
                'nombre': p['nombre'],
                'precio': float(p['precio']),
                'tiene_variantes': bool(p['tiene_variantes']),
                'score': round(score, 2),
            })
    matches.sort(key=lambda x: (-x['score'], -len(x['nombre'])))
    return matches


def _parsear_v2(texto: str, conn) -> dict:
    t = _normalizar(texto)
    # Strip leading wake words
    words = t.split()
    while words and words[0] in _WAKE_WORDS:
        words.pop(0)
    t = ' '.join(words)

    accion = _detectar_accion(t)
    hint = _detectar_variante_hint(t)
    cantidad = _detectar_cantidad(_strip_size_phrases(t))
    matches = _match_productos(t, conn)

    resultado: dict = {
        'accion': accion,
        'cantidad': cantidad,
        'variante': hint['valor'] if hint and hint['tipo'] == 'exacta' else '',
        'variante_hint': hint,
        'producto': '',
        'producto_id': None,
        'candidatos': [],
        'ambiguo': False,
    }

    if len(matches) == 1:
        resultado['producto'] = matches[0]['nombre']
        resultado['producto_id'] = matches[0]['id']
    elif len(matches) > 1:
        gap = matches[0]['score'] - matches[1]['score']
        if gap >= 0.35:
            resultado['producto'] = matches[0]['nombre']
            resultado['producto_id'] = matches[0]['id']
        else:
            resultado['candidatos'] = [{'id': m['id'], 'nombre': m['nombre']} for m in matches[:3]]
            resultado['ambiguo'] = True

    return resultado


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

    uid = session.get("usuario_id")
    with db_session() as conn:
        resultado = _parsear_v2(texto, conn)
        conn.execute(
            "INSERT INTO voz_historial (texto, accion, usuario_id) VALUES (?,?,?)",
            (texto, json.dumps(resultado, ensure_ascii=False), uid),
        )

    # TinyLlama only as last resort for completely unrecognized commands
    if resultado['accion'] == 'desconocido' and not resultado['producto_id'] and _ollama_ok():
        system = (
            "Eres un asistente de punto de venta. Dado un comando de voz en español, "
            "extrae la intención. Responde ÚNICAMENTE con JSON válido, sin texto extra.\n"
            'Formato: {"accion":"agregar|quitar|cobrar|consultar|limpiar","producto":"nombre","cantidad":1,"variante":""}'
        )
        raw = _ollama(f'Comando: "{texto}"', system, 120)
        if raw:
            m = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
            if m:
                try:
                    llm = json.loads(m.group())
                    if llm.get('accion') and llm['accion'] != 'desconocido':
                        resultado['accion'] = llm['accion']
                    if not resultado['producto']:
                        resultado['producto'] = llm.get('producto', '')
                    if not resultado['variante']:
                        resultado['variante'] = llm.get('variante', '')
                except Exception:
                    pass

    return jsonify(resultado)


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
