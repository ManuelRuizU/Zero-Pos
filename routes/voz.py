import json
import logging
import re
import unicodedata
import urllib.request
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from flask import Blueprint, request, jsonify, session
from database import db_session
from utils.consultas_rapidas import (
    ventas_hoy as _cq_ventas_hoy,
    ventas_ayer as _cq_ventas_ayer,
    ventas_semana as _cq_ventas_semana,
    mejor_cajero_hoy as _cq_cajero,
    hora_pico_hoy as _cq_hora_pico,
    stock_bajo as _cq_stock_bajo,
    vencimientos_proximos as _cq_vencimientos,
    prediccion_agotamiento as _cq_prediccion,
    producto_mas_vendido as _cq_top_prod,
)

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
        "options": {
            "temperature": 0.1,
            "num_predict": max_tokens,
            "num_ctx": 512,
            "top_p": 0.9,
            "repeat_penalty": 1.1,
        },
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
    r'\b('
    r'agregar?|agrega(?:me|nos|le)?|agregu(?:e|eme|enos)|'  # agregar/agrega/agregue/agregueme
    r'poner|pon(?:me|le|nos|te|gan)?|pong(?:a|ame|anos)|'   # poner/ponme/pongan/póngame
    r'an[aá]d(?:e|ir)|an[aá]deme|'                          # añadir/añade
    r'sumar?|'                                               # sumar/suma
    r'necesito|quisiera|quiero|'                             # necesito/quisiera/quiero
    r'dame|d[eé]me|dar|'                                     # dame/déme/dar
    r'met(?:er|e|ele|eme)|'                                  # meter/mete/métele
    r'traer|traeme?|'                                        # traer/traeme
    r'incluir|incluye|'                                      # incluir/incluye
    r'coloc(?:ar?|a(?:me|le|nos)?|amos|que(?:me|nos)?)|'    # colocar/coloca/coloque
    r'dale'                                                  # dale
    r')\b', re.I
)
_PAT_QUITAR = re.compile(
    r'\b('
    r'quitar?|quita(?:me|nos)?|'                # quitar / quita / quitame
    r'sacar?|saca(?:me|nos)?|'                  # sacar / saca / sacame
    r'eliminar?|'                               # eliminar / elimina
    r'borrar?(?!\s+todo)|borra(?!\s+todo)|'     # borrar/borra (no "borrar todo")
    r'remover?|remueve|'                        # remover / remueve
    r'descontar?'                               # descontar / desconta
    r')\b', re.I
)
_PAT_COBRAR = re.compile(
    r'\b('
    r'cobrar?|'                                           # cobrar / cobra
    r'a\s+(?:cobrar|pagar)|para\s+pagar|'                 # a cobrar / a pagar / para pagar
    r'cerrar?(?:mos)?|'                                   # cerrar / cerramos
    r'eso\s+es\s+todo|eso\s+nomas?|'                      # eso es todo / eso nomás
    r'ya\s+(?:est[aá]|listo)|listo\b|'                    # ya está / ya listo / listo
    r'pagar?|paga\b|pagamos|pagan|'                       # pagar/paga/pagamos/pagan
    r'factura|boleta|'                                    # factura / boleta
    r'cu[aá]nto\s+(?:va|es|sale)|el\s+total|total\b'     # cuánto va/es/sale / el total
    r')\b', re.I
)

# ── Detección de método de pago ──────────────────────────────────────────────
_PAT_PAGO_EFECTIVO      = re.compile(r'\b(efectivo|cash|billetes?)\b', re.I)
_PAT_PAGO_TRANSFERENCIA = re.compile(r'\b(transferencia|transfe|transfer)\b', re.I)
_PAT_PAGO_TARJETA       = re.compile(r'\b(tarjeta|d[eé]bito|cr[eé]dito)\b', re.I)


def _detectar_metodo_pago(t: str) -> str | None:
    if _PAT_PAGO_EFECTIVO.search(t):      return 'efectivo'
    if _PAT_PAGO_TRANSFERENCIA.search(t): return 'transferencia'
    if _PAT_PAGO_TARJETA.search(t):       return 'tarjeta'
    return None
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

# ── Keywords para detección rápida de intents (sin TinyLlama) ────────────────
# Queries SIMPLES → respuesta SQL directa, sin narrativa de IA
KEYWORDS_VENTAS  = {'vendí', 'vendi', 'ventas', 'vendiste', 'cuánto', 'cuanto', 'total',
                    'hoy', 'ayer', 'semana', 'mes'}
KEYWORDS_STOCK   = {'queda', 'quedan', 'stock', 'tengo', 'hay', 'inventario', 'quedan'}
KEYWORDS_PRODUCTO = {'más vendido', 'mas vendido', 'popular', 'estrella', 'top', 'mejor producto'}
KEYWORDS_CAJERO  = {'cajero', 'vendedor', 'empleado', 'quien vendió', 'quien vendio',
                    'quién vendió', 'quien vendio'}
KEYWORDS_HORA    = {'hora', 'momento', 'horario', 'pico', 'movido', 'concurrido'}

# Queries COMPLEJAS → requieren narrativa de TinyLlama
_QUERIES_COMPLEJAS = {
    'comparado', 'comparar', 'comparación', 'comparacion',
    'buen día', 'buen dia', 'fue bueno', 'estuvo bueno',
    'debería pedir', 'deberia pedir', 'qué pedir', 'que pedir',
    'debería comprar', 'deberia comprar',
    'cómo voy', 'como voy', 'cómo estamos', 'como estamos',
}


def _es_consulta_compleja(texto: str) -> bool:
    t = texto.lower()
    return any(k in t for k in _QUERIES_COMPLEJAS)


def _buscar_vocabulario_local(texto_norm: str, conn) -> dict | None:
    """Busca expresión aprendida en vocabulario_local. Retorna producto_id si existe."""
    try:
        for row in conn.execute(
            "SELECT expresion, producto_id, consulta_tipo FROM vocabulario_local ORDER BY usos DESC"
        ).fetchall():
            if row['expresion'] in texto_norm:
                conn.execute(
                    "UPDATE vocabulario_local SET usos=usos+1 WHERE expresion=?",
                    (row['expresion'],)
                )
                return dict(row)
    except Exception:
        pass
    return None


def _guardar_vocabulario_local(expresion: str, producto_id: int | None,
                                consulta_tipo: str | None, conn) -> None:
    if not expresion or len(expresion) < 4:
        return
    try:
        conn.execute(
            "INSERT INTO vocabulario_local(expresion, producto_id, consulta_tipo, usos) "
            "VALUES(?,?,?,1) ON CONFLICT(expresion) DO UPDATE SET usos=usos+1",
            (expresion, producto_id, consulta_tipo)
        )
    except Exception:
        pass


# Flat keyword → accion map — used for difflib similarity matching on unknown words
_ALL_KEYWORDS: dict[str, str] = {
    **{k: 'agregar' for k in (
        'agrega', 'agregar', 'agregame', 'agregue', 'agregueme',
        'poner', 'ponme', 'ponle', 'pongan', 'pongame',
        'anadir', 'anade', 'anademe', 'sumar', 'suma',
        'necesito', 'quisiera', 'quiero', 'dame', 'deme', 'dar',
        'meter', 'mete', 'metele', 'traer', 'traeme',
        'incluir', 'incluye', 'dale',
        'colocar', 'coloca', 'colocame', 'coloque', 'coloqueme',
    )},
    **{k: 'quitar' for k in (
        'quitar', 'quita', 'quitame', 'sacar', 'saca', 'sacame',
        'eliminar', 'elimina', 'borrar', 'borra', 'remover', 'remueve', 'descontar',
    )},
    **{k: 'cobrar' for k in (
        'cobrar', 'cobra', 'cerrar', 'cerramos',
        'listo', 'pagar', 'paga', 'pagamos', 'pagan',
        'factura', 'boleta', 'total',
    )},
    **{k: 'limpiar' for k in ('limpia', 'limpiar', 'vaciar', 'vacia', 'nuevo')},
}

# ── Atributos de presentación de variantes ────────────────────────────────────

# Attribute keyword → synonyms list (all normalized/accent-free)
_ATRIBUTOS_VARIANTE: dict[str, list[str]] = {
    'retornable': ['retornable'],
    'desechable': ['desechable', 'descartable'],
    'lata':       ['lata', 'en lata'],
    'vidrio':     ['vidrio', 'de vidrio'],
    'light':      ['light', 'zero', 'sin azucar'],
    'familiar':   ['familiar'],
    'personal':   ['personal'],
    'grande':     ['grande'],
    'chico':      ['chico', 'peque', 'mini'],
    'mediano':    ['mediano'],
}


def _extraer_atributos(nombre: str) -> list[str]:
    """Extract presentation attributes from a variant name."""
    t = _normalizar(nombre)
    return [attr for attr, kws in _ATRIBUTOS_VARIANTE.items() if any(kw in t for kw in kws)]


def _atributo_usuario(texto: str) -> str | None:
    """Detect the first attribute keyword in what the user said."""
    t = _normalizar(texto)
    for attr, kws in _ATRIBUTOS_VARIANTE.items():
        if any(kw in t for kw in kws):
            return attr
    return None


_PAT_AFIRMAR = re.compile(
    r'\b(si|s[ií]|correcto|exacto|eso|afirmativo|dale|claro|ok|okay|sip|'
    r'exactamente|genial|perfecto|bueno|va|sale|anda)\b', re.I
)
_PAT_NEGAR = re.compile(
    r'\b(no|negativo|incorrecto|otro|otra|equivocado|error|nop|nope|para)\b', re.I
)


def _es_afirmacion(t: str) -> bool:
    return bool(_PAT_AFIRMAR.search(t)) and not bool(_PAT_NEGAR.search(t))


def _es_negacion(t: str) -> bool:
    return bool(_PAT_NEGAR.search(t)) and not bool(_PAT_AFIRMAR.search(t))


_VARIANTE_EXACTA = [
    # Volume — units are REQUIRED to avoid matching bare numbers like "3g" or "2000g"
    (re.compile(r'3\s*(?:litros?|l\b)|tres\s*litros?|3000\s*(?:ml|cc)', re.I), '3L'),
    (re.compile(r'2\s*(?:litros?|l\b)|dos\s*litros?|2000\s*(?:ml|cc)|familiar\b|mega\b', re.I), '2L'),
    (re.compile(r'1[.,]5\s*(?:litros?|l\b)|1500\s*(?:ml|cc)|litro\s+y\s+medio|1\s+l\s+y\s+medio|uno\s+(?:y\s+)?medio|uno\s+coma\s+cinco', re.I), '1.5L'),
    (re.compile(r'\bun\s+(?:litro|l)\b|1000\s*(?:ml|cc)|\b1\s*l\b|de\s+litro\b', re.I), '1L'),
    (re.compile(r'500\s*(?:ml|cc)|medio\s*litro|botella\s+chica\b', re.I), '500ml'),
    (re.compile(r'35[05]\s*(?:ml|cc)|en\s+lata\b|\blata\b', re.I), '350ml'),
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

# Dynamic weight patterns for arbitrary gram/ml values ("100g", "200ml", etc.)
# Checked AFTER _VARIANTE_EXACTA so specific values (500ml, 1kg) take precedence.
_PAT_PESO_DINAMICO = re.compile(r'\b(\d+)\s*(?:g|gr|gramos?)\b', re.I)
_PAT_ML_DINAMICO   = re.compile(r'\b(\d+)\s*(?:ml|cc)\b', re.I)

# Phrases to strip before quantity detection so "tres litros" / "100g" isn't counted as qty
_SIZE_STRIP_PATS = [
    re.compile(r'\b(?:tres|dos|un(?:o|a)?)\s+litros?\b', re.I),
    re.compile(r'\btres\s+kilos?\b|\bdos\s+kilos?\b', re.I),
    # \b before digit, then number+unit — includes bare "g" to cover "100g"
    re.compile(r'\d+\s*(?:ml|cc|litros?|kilos?|kg|g(?:r(?:amos?)?)?\b)', re.I),
    re.compile(r'litro\s+y\s+medio\b', re.I),
    re.compile(r'medio\s+kilo\b', re.I),
    re.compile(r'un\s+cuarto\b', re.I),
    # Strip "N lucas/luca" so price hints don't get counted as product quantities
    re.compile(r'\b\d+\s*lucas?\b', re.I),
    re.compile(
        r'\b(?:una?|dos|tres|tre|cuatro|cinco|seis|siete|ocho|nueve|'
        r'diez|die|once|doce|quince|veinte|vente|treinta|cuarenta|cincuenta|cien)\s+lucas?\b',
        re.I
    ),
]

def _strip_size_phrases(t: str) -> str:
    for pat in _SIZE_STRIP_PATS:
        t = pat.sub(' ', t)
    return ' '.join(t.split())
_NUMEROS_PALABRAS = [
    # Pack/docena compuestos — van ANTES que los números simples para no ambigüar
    (re.compile(r'\buna?\s+docena\b|\b12\s+pack\b|\bdoce\s+pack\b', re.I), 12),
    (re.compile(r'\bmedia\s+docena\b|\bsix\s+pack\b|\bseis\s+pack\b|\b6\s+pack\b', re.I), 6),
    (re.compile(r'\bun\s+pack\b|\b1\s+pack\b', re.I), 1),
    # Números simples
    (re.compile(r'\bdoce\b', re.I), 12), (re.compile(r'\bonce\b', re.I), 11),
    (re.compile(r'\bdiez\b', re.I), 10), (re.compile(r'\bnueve\b', re.I), 9),
    (re.compile(r'\bocho\b', re.I), 8),  (re.compile(r'\bsiete\b', re.I), 7),
    (re.compile(r'\bseis\b', re.I), 6),  (re.compile(r'\bcinco\b', re.I), 5),
    (re.compile(r'\bcuatro\b', re.I), 4),(re.compile(r'\btres\b', re.I), 3),
    (re.compile(r'\bun\s+par\b', re.I), 2),(re.compile(r'\bdos\b', re.I), 2),
    (re.compile(r'\bun[ao]?\b', re.I), 1),
]
_SIZE_DIGITS = frozenset({350, 355, 500, 1000, 1500, 2000, 3000})

# Detect pack-only commands ("seis pack", "six pack") with no product context — BUG 3
_PAT_PACK_SOLO = re.compile(
    r'\b(?:six|seis|doce|un|una|dos|tres|cuatro|cinco|\d+)\s+packs?\b', re.I
)


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
    # Dynamic weight: "100g", "200gr", "150 gramos" → variante "100g" etc.
    m = _PAT_PESO_DINAMICO.search(t)
    if m:
        return {'tipo': 'exacta', 'valor': f'{m.group(1)}g'}
    # Dynamic ml: "330ml", "473cc" → variante "330ml" etc.
    m = _PAT_ML_DINAMICO.search(t)
    if m:
        return {'tipo': 'exacta', 'valor': f'{m.group(1)}ml'}
    return None


def _match_productos(t_norm: str, conn) -> list[dict]:
    """Fuzzy-match products by word overlap (≥60%). Falls back to SQL LIKE."""
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

    # SQL LIKE fallback when fuzzy finds nothing
    if not matches:
        words = [w for w in t_norm.split() if len(w) > 2]
        if words:
            conds = ' OR '.join(
                "LOWER(REPLACE(REPLACE(nombre,'-',' '),',',' ')) LIKE ?" for _ in words
            )
            params = [f'%{w}%' for w in words]
            for p in conn.execute(
                f"SELECT id, nombre, precio, tiene_variantes FROM productos WHERE activo=1 AND ({conds})",
                params,
            ).fetchall():
                matches.append({
                    'id': p['id'], 'nombre': p['nombre'],
                    'precio': float(p['precio']),
                    'tiene_variantes': bool(p['tiene_variantes']),
                    'score': 0.5,
                })
            matches.sort(key=lambda x: -len(x['nombre']))

    # Learned product synonym fallback (voz_sinonimos_producto)
    if not matches:
        try:
            seen_ids = set()
            for row in conn.execute(
                "SELECT palabra, producto_id FROM voz_sinonimos_producto"
            ).fetchall():
                if row['palabra'] in t_norm and row['producto_id'] not in seen_ids:
                    p = conn.execute(
                        "SELECT id, nombre, precio, tiene_variantes FROM productos WHERE id=? AND activo=1",
                        (row['producto_id'],)
                    ).fetchone()
                    if p:
                        seen_ids.add(p['id'])
                        matches.append({
                            'id': p['id'], 'nombre': p['nombre'],
                            'precio': float(p['precio']),
                            'tiene_variantes': bool(p['tiene_variantes']),
                            'score': 0.9,
                        })
        except Exception:
            pass

    # vocabulario_local fallback — multi-word colloquial expressions ("la grande de coca")
    if not matches:
        vocab = _buscar_vocabulario_local(t_norm, conn)
        if vocab and vocab.get('producto_id'):
            p = conn.execute(
                "SELECT id, nombre, precio, tiene_variantes FROM productos WHERE id=? AND activo=1",
                (vocab['producto_id'],)
            ).fetchone()
            if p:
                matches.append({
                    'id': p['id'], 'nombre': p['nombre'],
                    'precio': float(p['precio']),
                    'tiene_variantes': bool(p['tiene_variantes']),
                    'score': 0.95,
                })

    return matches


# ── Conversión de montos en texto → número ────────────────────────────────────

# Word → integer for lucas patterns (Chilean variants: "die"=10, "vente"=20, "tre"=3)
_NUM_ES: dict[str, int] = {
    'una': 1, 'un': 1, 'uno': 1,
    'dos': 2, 'tres': 3, 'tre': 3,
    'cuatro': 4, 'cinco': 5, 'seis': 6,
    'siete': 7, 'ocho': 8, 'nueve': 9,
    'diez': 10, 'die': 10,
    'once': 11, 'doce': 12, 'trece': 13,
    'catorce': 14, 'quince': 15,
    'dieciseis': 16, 'diecisiete': 17, 'dieciocho': 18, 'diecinueve': 19,
    'veinte': 20, 'vente': 20, 'veintiuno': 21, 'veintidos': 22,
    'veintitres': 23, 'veinticuatro': 24, 'veinticinco': 25,
    'veintiseis': 26, 'veintisiete': 27, 'veintiocho': 28, 'veintinueve': 29,
    'treinta': 30, 'cuarenta': 40, 'cincuenta': 50,
    'sesenta': 60, 'setenta': 70, 'ochenta': 80, 'noventa': 90, 'cien': 100,
}

_MONTOS_PALABRAS: list[tuple[str, int]] = sorted([
    ('ciento cincuenta mil', 150000), ('cien mil', 100000),
    ('noventa mil', 90000),  ('ochenta mil', 80000),  ('setenta mil', 70000),
    ('sesenta mil', 60000),  ('cincuenta mil', 50000), ('cuarenta mil', 40000),
    ('treinta y cinco mil', 35000), ('treinta mil', 30000),
    ('veinticinco mil', 25000), ('veinte mil', 20000),
    ('dieciseis mil', 16000), ('quince mil', 15000), ('catorce mil', 14000),
    ('trece mil', 13000), ('doce mil', 12000), ('once mil', 11000),
    ('diez mil', 10000), ('nueve mil', 9000), ('ocho mil', 8000),
    ('siete mil', 7000), ('seis mil', 6000), ('cinco mil', 5000),
    ('cuatro mil', 4000), ('tres mil', 3000), ('dos mil', 2000),
    ('mil quinientos', 1500), ('mil y medio', 1500), ('mil y media', 1500), ('mil', 1000),
    ('novecientos', 900), ('ochocientos', 800), ('setecientos', 700),
    ('seiscientos', 600), ('quinientos', 500), ('cuatrocientos', 400),
    ('trescientos', 300), ('doscientos', 200), ('ciento', 100), ('cien', 100),
], key=lambda x: -len(x[0]))


def _texto_a_numero(texto: str, conn=None) -> int | None:
    """Parse a Chilean Spanish money amount. Returns pesos (CLP) or None."""
    # 0. DB lookup — user-taught montos (tipo='monto')
    if conn is not None:
        try:
            t_db = _normalizar(texto)
            for row in conn.execute(
                "SELECT palabra, accion FROM voz_aprendizaje WHERE tipo='monto' AND confirmado=1"
            ).fetchall():
                if row['palabra'] in t_db:
                    return int(row['accion'])
        except Exception:
            pass

    # 1. Digit-first: strip thousand separators then find 3–7 digit run
    raw = re.sub(r'[.,\s]', '', texto)
    m = re.search(r'(\d{3,7})', raw)
    if m:
        n = int(m.group(1))
        if 100 <= n <= 9_999_999:
            return n

    t = _normalizar(texto)

    # 2. "un palo" = 1,000,000 CLP
    if re.search(r'\bun\s+palo\b', t):
        return 1_000_000

    # 3. Lucas (1 luca = 1,000 CLP) — handles "die", "vente", "tre" variants
    # "media luca" / "meia luca" → 500
    if re.search(r'\b(media|meia)\s+luca\b', t):
        return 500
    # "luca y media/meia" → 1,500
    if re.search(r'\bluca\s+y\s+(media|meia)\b', t):
        return 1_500
    # "N lucas y media/meia" → N×1000 + 500
    m = re.search(r'\b(\w+)\s+lucas?\s+y\s+(media|meia)\b', t)
    if m:
        factor = _NUM_ES.get(m.group(1))
        if factor is None:
            try: factor = int(m.group(1))
            except (ValueError, TypeError): pass
        if factor:
            return factor * 1000 + 500
    # "N lucas" / "N luca" → N×1000
    m = re.search(r'\b(\w+)\s+lucas?\b', t)
    if m:
        factor = _NUM_ES.get(m.group(1))
        if factor is None:
            try: factor = int(m.group(1))
            except (ValueError, TypeError): pass
        if factor:
            return factor * 1000

    # 4. "N mil quinientos" / "N mil y medio|media" → N×1000 + 500
    m = re.search(r'\b(\w+)\s+mil\s+(?:quinientos|y\s+(?:medio|media))\b', t)
    if m:
        factor = _NUM_ES.get(m.group(1))
        if factor is None:
            try: factor = int(m.group(1))
            except (ValueError, TypeError): pass
        if factor:
            return factor * 1000 + 500

    # 5. Bare digit before "mil" ("5 mil", "3 mil")
    m = re.search(r'\b(\d+)\s+mil\b', t)
    if m:
        return int(m.group(1)) * 1000

    # 6. _MONTOS_PALABRAS — longest-match table for all standard amounts
    for phrase, value in _MONTOS_PALABRAS:
        if phrase in t:
            return value

    return None


def _fmt_pesos(n: int | float) -> str:
    return f"${int(n):,}".replace(',', '.')


def _precio_hint_de_texto(texto: str) -> int | None:
    """Detect a price filter embedded in a command ('de dos lucas', 'a 2000')."""
    t = _normalizar(texto)
    # Look for "de/a/la de + [amount_words]"
    m = re.search(r'\b(?:de|a|la\s+de|como)\s+((?:[\w.]+\s+){0,3}(?:lucas?|mil|pesos?))', t)
    if m:
        n = _texto_a_numero(m.group(1).strip())
        if n and n >= 100:
            return n
    return None


# ── Número → texto en español para TTS (vuelto en voz) ───────────────────────

_UNIDADES_VOZ: dict[int, str] = {
    1: 'uno', 2: 'dos', 3: 'tres', 4: 'cuatro', 5: 'cinco',
    6: 'seis', 7: 'siete', 8: 'ocho', 9: 'nueve',
    10: 'diez', 11: 'once', 12: 'doce', 13: 'trece', 14: 'catorce',
    15: 'quince', 16: 'dieciseis', 17: 'diecisiete', 18: 'dieciocho', 19: 'diecinueve',
    20: 'veinte', 21: 'veintiuno', 22: 'veintidos', 23: 'veintitres',
    24: 'veinticuatro', 25: 'veinticinco', 26: 'veintiseis',
    27: 'veintisiete', 28: 'veintiocho', 29: 'veintinueve',
}
_DECENAS_VOZ: dict[int, str] = {
    30: 'treinta', 40: 'cuarenta', 50: 'cincuenta',
    60: 'sesenta', 70: 'setenta', 80: 'ochenta', 90: 'noventa',
}
_CENTENAS_VOZ: dict[int, str] = {
    100: 'cien', 200: 'doscientos', 300: 'trescientos', 400: 'cuatrocientos',
    500: 'quinientos', 600: 'seiscientos', 700: 'setecientos',
    800: 'ochocientos', 900: 'novecientos',
}


def _num_menor_mil(n: int) -> str:
    if n <= 0:
        return ''
    parts = []
    c = (n // 100) * 100
    if c:
        if c == 100 and n % 100 != 0:
            parts.append('ciento')
        else:
            parts.append(_CENTENAS_VOZ[c])
    resto = n % 100
    if resto:
        if resto in _UNIDADES_VOZ:
            parts.append(_UNIDADES_VOZ[resto])
        else:
            dec = (resto // 10) * 10
            uni = resto % 10
            parts.append(_DECENAS_VOZ[dec] + (f' y {_UNIDADES_VOZ[uni]}' if uni else ''))
    return ' '.join(parts)


def _numero_a_texto(n: int) -> str:
    """Convert a peso amount to natural Spanish words for TTS."""
    n = abs(int(round(n)))
    if n == 0:
        return 'cero pesos'
    if n >= 1_000_000:
        return _fmt_pesos(n)
    miles = n // 1000
    resto = n % 1000
    parts: list[str] = []
    if miles == 1:
        parts.append('mil')
    elif miles > 1:
        parts.append(f'{_num_menor_mil(miles)} mil')
    if resto:
        parts.append(_num_menor_mil(resto))
    return ' '.join(parts) + ' pesos'


# ── Resolución de variantes por atributos y precio ───────────────────────────

def _frase_variante_candidatos(candidatos: list, nombre_producto: str) -> str:
    """Build a natural Spanish clarification question for variant ties."""
    partes = []
    for v in candidatos[:4]:
        atrs = ', '.join(v.get('atributos', []))
        label = atrs if atrs else v['nombre']
        partes.append(f"la {label} a {_fmt_pesos(v['precio'])}")

    if len(partes) == 2:
        return f"Tengo {nombre_producto}: {partes[0]} y {partes[1]}. ¿Cuál es?"
    opciones = ', '.join(partes[:-1]) + f' o {partes[-1]}'
    return f"Tengo {nombre_producto} en: {opciones}. ¿Cuál quieres?"


def _resolver_variante_db(producto_id: int, variante_hint, precio_hint: int | None) -> dict:
    """
    Resolves which variant to use for an agregar command.
    Returns:
      {'variante_id': X, 'variante': '...', 'clarificacion': False}  — unique match
      {'clarificacion': True, 'candidatos': [...]}                    — need user input
      {}                                                               — no variants found
    """
    try:
        with db_session() as conn:
            rows = conn.execute(
                "SELECT id, nombre, precio FROM producto_variantes "
                "WHERE producto_id=? AND activo=1 ORDER BY precio",
                (producto_id,)
            ).fetchall()
            if not rows:
                return {}

            variantes = [{'id': r['id'], 'nombre': r['nombre'],
                          'precio': float(r['precio']),
                          'atributos': _extraer_atributos(r['nombre'])} for r in rows]

            # 0. Learned attribute → variante for this product
            aprendidos = conn.execute(
                "SELECT palabra, variante_id FROM voz_sinonimos_variante WHERE producto_id=?",
                (producto_id,)
            ).fetchall()
    except Exception:
        return {}

    # 1. Filter by learned attributes that appear in any candidate name
    for row in aprendidos:
        matched_v = next((v for v in variantes if v['id'] == row['variante_id']), None)
        if matched_v:
            return {'variante_id': matched_v['id'], 'variante': matched_v['nombre'],
                    'clarificacion': False}

    candidatos = variantes

    # 2. Filter by variante_hint
    if variante_hint:
        val = (variante_hint.get('valor') or '').lower()
        if val:
            filtradas = [v for v in variantes if val in _normalizar(v['nombre'])]
            if filtradas:
                candidatos = filtradas

    # 3. Filter by price hint (±25%)
    if precio_hint and len(candidatos) > 1:
        rango = [v for v in candidatos
                 if precio_hint * 0.75 <= v['precio'] <= precio_hint * 1.25]
        if rango:
            candidatos = rango

    # 4. Single match → done
    if len(candidatos) == 1:
        v = candidatos[0]
        return {'variante_id': v['id'], 'variante': v['nombre'], 'clarificacion': False}

    # 5. Price tie check among top-2
    candidatos.sort(key=lambda v: v['precio'])
    if len(candidatos) >= 2:
        p1, p2 = candidatos[0]['precio'], candidatos[1]['precio']
        pmax = max(p1, p2, 1)
        empate = (abs(p1 - p2) / pmax) < 0.10
        return {'clarificacion': True, 'es_empate': empate, 'candidatos': candidatos[:4]}

    return {}


def _guardar_aprendizaje_variante(palabra: str, producto_id: int, variante_id: int) -> None:
    """Persist attribute → variante_id mapping for a specific product."""
    try:
        with db_session() as conn:
            existing = conn.execute(
                "SELECT id FROM voz_sinonimos_variante WHERE palabra=? AND producto_id=?",
                (palabra, producto_id)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE voz_sinonimos_variante SET variante_id=?, veces_usado=veces_usado+1 WHERE id=?",
                    (variante_id, existing['id'])
                )
            else:
                conn.execute(
                    "INSERT INTO voz_sinonimos_variante (palabra, producto_id, variante_id, veces_usado) "
                    "VALUES (?,?,?,1)",
                    (palabra, producto_id, variante_id)
                )
    except Exception as e:
        logger.warning(f"[variante] Error guardando aprendizaje: {e}")


def _parsear_v2(texto: str, conn) -> dict:
    t = _normalizar(texto)
    # Strip leading wake words
    words = t.split()
    while words and words[0] in _WAKE_WORDS:
        words.pop(0)
    t = ' '.join(words)

    logger.info(f"[voz] texto_norm='{t}'")
    accion = _detectar_accion(t)
    metodo = _detectar_metodo_pago(t)
    if metodo:
        accion = 'seleccionar_pago'

    # Apply learned action words from DB when still unknown
    if accion == 'desconocido':
        try:
            for row in conn.execute(
                "SELECT palabra, accion FROM voz_aprendizaje WHERE confirmado=1 AND tipo='accion'"
            ).fetchall():
                if row['palabra'] in t.split():
                    accion = row['accion']
                    logger.info(f"[aprendizaje] '{row['palabra']}' → {accion}")
                    break
        except Exception:
            pass  # table may not exist on first run before init_db

    logger.info(f"[voz] accion='{accion}' metodo={metodo}")
    hint = _detectar_variante_hint(t)
    cantidad = _detectar_cantidad(_strip_size_phrases(t))

    # BUG 2 — Acciones de cobro/consulta tienen prioridad: no buscar productos
    _ACCIONES_SIN_PRODUCTO = frozenset({
        'seleccionar_pago', 'cobrar', 'ventas_hoy', 'stock', 'limpiar',
    })
    if accion in _ACCIONES_SIN_PRODUCTO:
        matches = []
    else:
        matches = _match_productos(t, conn)
        logger.info(f"[voz] matches={[(m['nombre'], m['score']) for m in matches[:3]]}")

    # BUG 3 — Extraer monto recibido cuando el método de pago es efectivo
    monto_recibido = None
    if accion == 'seleccionar_pago' and metodo == 'efectivo':
        monto_recibido = _texto_a_numero(texto, conn)

    resultado: dict = {
        'accion':         accion,
        'metodo':         metodo,
        'monto_recibido': monto_recibido,
        'cantidad':       cantidad,
        'variante':       hint['valor'] if hint and hint['tipo'] == 'exacta' else '',
        'variante_hint':  hint,
        'producto':       '',
        'producto_id':    None,
        'candidatos':     [],
        'ambiguo':        False,
    }

    if len(matches) == 1:
        resultado['producto']        = matches[0]['nombre']
        resultado['producto_id']     = matches[0]['id']
        resultado['tiene_variantes'] = bool(matches[0].get('tiene_variantes', 0))
    elif len(matches) > 1:
        gap = matches[0]['score'] - matches[1]['score']
        if gap >= 0.35:
            resultado['producto']        = matches[0]['nombre']
            resultado['producto_id']     = matches[0]['id']
            resultado['tiene_variantes'] = bool(matches[0].get('tiene_variantes', 0))
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

    logger.info(f"[voz] interpretar texto='{texto}'")
    uid = session.get("usuario_id")

    total_carrito = float(body.get('total_carrito', 0) or 0)

    # ── Confirmación pendiente ────────────────────────────────────────────────
    pendiente = session.get('voz_pendiente')
    if pendiente:
        tipo_pend = pendiente.get('tipo', 'accion')

        # BUG 3 — Esperando monto en efectivo
        if tipo_pend == 'esperando_monto':
            with db_session() as _conn:
                monto = _texto_a_numero(texto, _conn)
            if monto:
                session.pop('voz_pendiente', None)
                metodo = pendiente['metodo']
                vuelto = round(monto - total_carrito) if total_carrito else None
                r = {
                    'accion': 'seleccionar_pago', 'metodo': metodo,
                    'monto_recibido': monto, 'vuelto': vuelto,
                    'cantidad': 1, 'variante': '', 'variante_hint': None,
                    'producto': '', 'producto_id': None, 'candidatos': [], 'ambiguo': False,
                }
                r['respuesta_voz'] = _build_respuesta_voz(r)
                return jsonify(r)
            # Can't parse — keep waiting
            return jsonify({
                'accion': 'esperando_monto', 'metodo': pendiente['metodo'],
                'respuesta_voz': '¿Cuánto te dieron? Di el monto, por ejemplo "diez mil"',
                'cantidad': 1, 'variante': '', 'variante_hint': None,
                'producto': '', 'producto_id': None, 'candidatos': [], 'ambiguo': False,
            })

        # Resolución de variante por atributo ("la desechable", "la retornable")
        if tipo_pend == 'seleccion_variante':
            prod_id   = pendiente.get('producto_id')
            prod_nom  = pendiente.get('producto_nombre', '')
            accion_pv = pendiente.get('accion', 'agregar')
            candidatos_v = pendiente.get('variantes_candidatas', [])
            cantidad_v   = pendiente.get('cantidad', 1)
            atributo = _atributo_usuario(texto)
            t_norm_v = _normalizar(texto)

            matched_v = []
            if atributo:
                matched_v = [v for v in candidatos_v if atributo in v.get('atributos', [])]
            if not matched_v:
                # Try substring match on variant name
                matched_v = [v for v in candidatos_v if t_norm_v in _normalizar(v['nombre'])]

            if len(matched_v) == 1:
                v = matched_v[0]
                session.pop('voz_pendiente', None)
                if atributo:
                    _guardar_aprendizaje_variante(atributo, prod_id, v['id'])
                r = {
                    'accion': accion_pv, 'metodo': None, 'monto_recibido': None,
                    'cantidad': cantidad_v,
                    'variante': v['nombre'], 'variante_id': v['id'], 'variante_hint': None,
                    'producto': prod_nom, 'producto_id': prod_id,
                    'candidatos': [], 'ambiguo': False, 'tiene_variantes': True,
                }
                r['respuesta_voz'] = _build_respuesta_voz(r)
                session['voz_ultimo_producto'] = {'id': prod_id, 'nombre': prod_nom}
                return jsonify(r)

            # Still ambiguous — narrow to matched subset or re-ask full list
            nuevos = matched_v if matched_v else candidatos_v
            pendiente['variantes_candidatas'] = nuevos
            session['voz_pendiente'] = pendiente
            return jsonify({
                'accion': 'desconocido',
                'respuesta_voz': _frase_variante_candidatos(nuevos, prod_nom),
                'candidatos': nuevos, 'ambiguo': True,
                'metodo': None, 'cantidad': 1, 'variante': '', 'variante_hint': None,
                'producto': prod_nom, 'producto_id': prod_id,
            })

        # BUG 1 — Selección de producto entre candidatos
        if tipo_pend == 'seleccion_producto':
            opciones_ids = set(pendiente.get('opciones', []))
            accion_pend  = pendiente.get('accion', 'agregar')
            with db_session() as _conn:
                matched = [m for m in _match_productos(_normalizar(texto), _conn)
                           if m['id'] in opciones_ids]
            if matched:
                session.pop('voz_pendiente', None)
                prod = matched[0]
                hint = pendiente.get('variante_hint')
                r = {
                    'accion': accion_pend,
                    'metodo': None, 'monto_recibido': None,
                    'cantidad': pendiente.get('cantidad', 1),
                    'variante': hint['valor'] if hint and hint.get('tipo') == 'exacta' else '',
                    'variante_hint': hint,
                    'producto': prod['nombre'],
                    'producto_id': prod['id'],
                    'candidatos': [], 'ambiguo': False,
                }
                r['respuesta_voz'] = _build_respuesta_voz(r)
                if accion_pend == 'agregar':
                    session['voz_ultimo_producto'] = {'id': prod['id'], 'nombre': prod['nombre']}
                return jsonify(r)
            # No match among options — re-ask
            nombres = ' o '.join(pendiente.get('opciones_nombres', [])[:2])
            return jsonify({
                'accion': 'desconocido',
                'respuesta_voz': f"¿Cuál de estos? {nombres}",
                'candidatos': [{'id': i, 'nombre': n} for i, n in zip(
                    pendiente.get('opciones', []), pendiente.get('opciones_nombres', []))],
                'ambiguo': True, 'metodo': None, 'cantidad': 1,
                'variante': '', 'variante_hint': None, 'producto': '', 'producto_id': None,
            })

        # Sí / No
        t_norm = _normalizar(texto)
        if _es_afirmacion(t_norm):
            return _ejecutar_confirmacion(pendiente, uid)
        elif _es_negacion(t_norm):
            session.pop('voz_pendiente', None)
            return jsonify({
                'accion': 'desconocido', 'metodo': None, 'cantidad': 1,
                'variante': '', 'variante_hint': None,
                'producto': '', 'producto_id': None, 'candidatos': [], 'ambiguo': False,
                'respuesta_voz': '¿Qué quisiste decir? Prueba: agrega, quita o cobra',
            })
        # Not a yes/no — clear pending and process the new command normally
        session.pop('voz_pendiente', None)

    # ── Parseo principal ──────────────────────────────────────────────────────
    with db_session() as conn:
        resultado = _parsear_v2(texto, conn)
        conn.execute(
            "INSERT INTO voz_historial (texto, accion, usuario_id) VALUES (?,?,?)",
            (texto, json.dumps(resultado, ensure_ascii=False), uid),
        )

    # ── BUG 3 — Flujo cobro con efectivo ─────────────────────────────────────
    if resultado['accion'] == 'seleccionar_pago' and resultado.get('metodo') == 'efectivo':
        monto = resultado.get('monto_recibido')
        if monto:
            vuelto = round(monto - total_carrito) if total_carrito else None
            resultado['vuelto'] = vuelto
        else:
            # No monto in text → ask for it
            session['voz_pendiente'] = {'tipo': 'esperando_monto', 'metodo': 'efectivo'}
            return jsonify({
                'accion': 'esperando_monto', 'metodo': 'efectivo',
                'respuesta_voz': '¿Cuánto te dieron?',
                'monto_recibido': None, 'vuelto': None,
                'cantidad': 1, 'variante': '', 'variante_hint': None,
                'producto': '', 'producto_id': None, 'candidatos': [], 'ambiguo': False,
            })

    # ── Resolución de variantes: precio similar o variante ambigua ───────────────
    if (resultado['accion'] == 'agregar' and resultado.get('producto_id')
            and resultado.get('tiene_variantes')):
        precio_hint  = _precio_hint_de_texto(texto)
        variante_hint = resultado.get('variante_hint')
        res_v = _resolver_variante_db(resultado['producto_id'], variante_hint, precio_hint)

        if res_v.get('clarificacion'):
            session['voz_pendiente'] = {
                'tipo':               'seleccion_variante',
                'producto_id':        resultado['producto_id'],
                'producto_nombre':    resultado['producto'],
                'accion':             'agregar',
                'variantes_candidatas': res_v['candidatos'],
                'cantidad':           resultado.get('cantidad', 1),
            }
            resp = _frase_variante_candidatos(res_v['candidatos'], resultado['producto'])
            return jsonify({**resultado, 'accion': 'desconocido', 'ambiguo': True,
                            'respuesta_voz': resp})

        elif res_v.get('variante_id'):
            resultado['variante']    = res_v['variante']
            resultado['variante_id'] = res_v['variante_id']

    # ── TinyLlama: last resort for truly unknown commands ─────────────────────
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
                    prod_nombre_llm = llm.get('producto', '')
                    if not resultado['producto'] and prod_nombre_llm:
                        resultado['producto'] = prod_nombre_llm
                        # Intentar hallar producto en DB y guardar en vocabulario_local
                        try:
                            with db_session() as _vc:
                                p_row = _vc.execute(
                                    "SELECT id FROM productos WHERE activo=1 AND nombre LIKE ? LIMIT 1",
                                    (f"%{prod_nombre_llm}%",)
                                ).fetchone()
                                if p_row:
                                    resultado['producto_id'] = p_row['id']
                                    t_norm_orig = _normalizar(texto)
                                    _guardar_vocabulario_local(t_norm_orig, p_row['id'], None, _vc)
                        except Exception:
                            pass
                    if not resultado['variante']:
                        resultado['variante'] = llm.get('variante', '')
                except Exception:
                    pass

    # ── BUG 1 — Producto ambiguo: guardar contexto de selección ─────────────────
    if resultado.get('ambiguo') and resultado.get('candidatos'):
        accion_inf = resultado['accion'] if resultado['accion'] != 'desconocido' else 'agregar'
        session['voz_pendiente'] = {
            'tipo': 'seleccion_producto',
            'accion': accion_inf,
            'opciones': [c['id'] for c in resultado['candidatos']],
            'opciones_nombres': [c['nombre'] for c in resultado['candidatos']],
            'variante_hint': resultado.get('variante_hint'),
            'cantidad': resultado.get('cantidad', 1),
        }
        opts = ' o '.join(c['nombre'] for c in resultado['candidatos'][:2])
        return jsonify({**resultado, 'respuesta_voz': f"Tengo {opts}. ¿Cuál quieres?"})

    # ── BUG 2+3 — Sólo variante/pack: aplicar al último producto conocido ────────
    if resultado['accion'] == 'desconocido' and not resultado['producto_id']:
        hint     = resultado.get('variante_hint')
        cantidad = resultado.get('cantidad', 1)
        is_variant_only = hint is not None or bool(_PAT_PACK_SOLO.search(_normalizar(texto)))
        if is_variant_only:
            ultimo = session.get('voz_ultimo_producto')
            if ultimo:
                r = {
                    'accion': 'agregar',
                    'metodo': None, 'monto_recibido': None,
                    'cantidad': cantidad,
                    'variante': hint['valor'] if hint and hint.get('tipo') == 'exacta' else '',
                    'variante_hint': hint,
                    'producto': ultimo['nombre'],
                    'producto_id': ultimo['id'],
                    'candidatos': [], 'ambiguo': False,
                }
                r['respuesta_voz'] = _build_respuesta_voz(r)
                session['voz_ultimo_producto'] = ultimo  # keep context alive
                return jsonify(r)
            return jsonify({
                'accion': 'variante_ultimo',
                'variante': hint['valor'] if hint and hint.get('tipo') == 'exacta' else '',
                'variante_hint': hint,
                'cantidad': cantidad,
                'respuesta_voz': '¿Eso es para qué producto?',
                'metodo': None, 'monto_recibido': None,
                'producto': '', 'producto_id': None, 'candidatos': [], 'ambiguo': False,
            })

    # ── Sugerencia inteligente (siempre responde, threshold 0.65) ────────────────
    if resultado['accion'] == 'desconocido':
        sugerencia = _sugerir_correccion(texto, resultado)
        logger.info(f"[aprendizaje] Sugerencia: '{sugerencia['respuesta_voz']}'")
        return jsonify(sugerencia)

    resultado['respuesta_voz'] = _build_respuesta_voz(resultado)

    # Guardar último producto agregado para contexto de variante (BUG 2)
    if resultado['accion'] == 'agregar' and resultado.get('producto_id'):
        session['voz_ultimo_producto'] = {
            'id': resultado['producto_id'],
            'nombre': resultado['producto'],
        }

    logger.info(f"[voz] resultado final accion={resultado['accion']} producto_id={resultado['producto_id']} respuesta='{resultado['respuesta_voz']}'")
    return jsonify(resultado)


def _build_respuesta_voz(r: dict) -> str:
    accion  = r.get('accion', 'desconocido')
    nombre  = r.get('producto', '')
    cantidad = r.get('cantidad', 1)
    variante = r.get('variante', '')
    if r.get('ambiguo') and r.get('candidatos'):
        opts = ' o '.join(c['nombre'] for c in r['candidatos'][:2])
        return f"Tengo {opts}. ¿Cuál quieres?"
    if accion == 'agregar':
        if nombre:
            qty_str = f"{cantidad}x " if cantidad > 1 else ""
            var_str = f" {variante}" if variante else ""
            return f"Agregando {qty_str}{nombre}{var_str}"
        return "¿Qué producto quieres agregar?"
    if accion == 'quitar':
        return f"Quitando {nombre}" if nombre else "¿Qué quieres quitar?"
    if accion == 'cobrar':
        return "Abriendo cobro"
    if accion == 'limpiar':
        return "¿Limpiar el carrito?"
    if accion in ('ventas_hoy', 'stock', 'consultar'):
        return "Consultando..."
    if accion == 'seleccionar_pago':
        metodo = r.get('metodo', '')
        monto  = r.get('monto_recibido')
        vuelto = r.get('vuelto')
        if metodo in ('transferencia', 'tarjeta'):
            return f"Pagando con {metodo}"
        if monto and vuelto is not None:
            monto_txt = _numero_a_texto(monto)
            if vuelto == 0:
                return f"Recibiste {monto_txt}. Monto exacto"
            elif vuelto > 0:
                return f"Recibiste {monto_txt}. Vuelto: {_numero_a_texto(vuelto)}"
            else:
                return f"Recibiste {monto_txt}. Faltan {_numero_a_texto(-vuelto)}"
        if monto:
            return f"Recibiste {_numero_a_texto(monto)}"
        return "¿Cuánto te dieron?"
    if accion == 'esperando_monto':
        return "¿Cuánto te dieron?"
    return "No entendí. Prueba: agrega, quita o cobra"


def _sugerir_correccion(texto: str, resultado: dict) -> dict:
    """BUG 1 — Always returns a response. Uses threshold 0.65 for suggestions.
    Below threshold returns a message with the actual word the user said."""
    t = _normalizar(texto)
    words = [w for w in t.split() if w not in _WAKE_WORDS and len(w) > 2]

    mejor_score = 0.0
    mejor_kw    = None
    mejor_accion = None
    mejor_palabra = None

    for word in words:
        for kw, accion in _ALL_KEYWORDS.items():
            score = SequenceMatcher(None, word, kw).ratio()
            if score > mejor_score:
                mejor_score = score
                mejor_kw    = kw
                mejor_accion = accion
                mejor_palabra = word

    _base = {
        'metodo': None, 'cantidad': resultado.get('cantidad', 1),
        'variante': resultado.get('variante', ''), 'variante_hint': resultado.get('variante_hint'),
        'producto': resultado.get('producto', ''), 'producto_id': resultado.get('producto_id'),
        'candidatos': [], 'ambiguo': False,
    }

    if mejor_score >= 0.65:
        nombre_prod   = resultado.get('producto', '')
        prod_id       = resultado.get('producto_id')
        palabra_dicha = mejor_palabra or (words[0] if words else texto[:20])

        if nombre_prod:
            respuesta = f"No entendí '{palabra_dicha}'. ¿Quisiste decir {mejor_accion.upper()} {nombre_prod}?"
        else:
            respuesta = f"No entendí '{palabra_dicha}'. ¿Quisiste decir '{mejor_kw}'?"

        session['voz_pendiente'] = {
            'tipo':          'accion',
            'accion':        mejor_accion,
            'metodo':        None,
            'producto':      nombre_prod,
            'producto_id':   prod_id,
            'variante_id':   None,
            'variante':      resultado.get('variante', ''),
            'variante_hint': resultado.get('variante_hint'),
            'cantidad':      resultado.get('cantidad', 1),
            'palabra_aprender': mejor_palabra,
            'kw_conocida':   mejor_kw,
        }
        return {**_base, 'accion': 'esperando_confirmacion', 'estado': 'esperando_confirmacion',
                'respuesta_voz': respuesta}

    return {**_base, 'accion': 'desconocido',
            'respuesta_voz': "No entendí. Prueba con: agrega, quita o cobra"}


def _ejecutar_confirmacion(pendiente: dict, uid: int):
    """Execute a pending voice confirmation and save the learned word."""
    session.pop('voz_pendiente', None)
    tipo    = pendiente.get('tipo', 'accion')
    palabra = pendiente.get('palabra_aprender', '')
    accion  = pendiente.get('accion', 'desconocido')
    kw      = pendiente.get('kw_conocida', accion)
    nombre  = pendiente.get('producto', '')
    prod_id = pendiente.get('producto_id')

    if tipo == 'accion' and palabra:
        try:
            with db_session() as conn:
                conn.execute(
                    """INSERT INTO voz_aprendizaje (palabra, accion, confirmado, veces_usado)
                       VALUES (?,?,1,1)
                       ON CONFLICT(palabra) DO UPDATE SET
                         accion=excluded.accion, confirmado=1, veces_usado=veces_usado+1""",
                    (palabra, accion),
                )
            logger.info(f"[aprendizaje] Aprendido: '{palabra}' → {accion}")
        except Exception as e:
            logger.warning(f"[aprendizaje] Error guardando '{palabra}': {e}")

    if nombre:
        accion_pp = {'agregar': 'agregado', 'quitar': 'quitado', 'cobrar': 'cobrar', 'limpiar': 'limpiar'}.get(accion, accion)
        resp = f"Listo. {nombre} {accion_pp}. Aprendí que '{palabra}' es {kw}."
    else:
        resp = f"Listo. Aprendí que '{palabra}' significa {kw}."

    resultado = {
        'accion':        accion,
        'metodo':        pendiente.get('metodo'),
        'cantidad':      pendiente.get('cantidad', 1),
        'variante':      pendiente.get('variante', ''),
        'variante_hint': pendiente.get('variante_hint'),
        'producto':      nombre,
        'producto_id':   prod_id,
        'candidatos':    [],
        'ambiguo':       False,
        'aprendido':     True,
        'respuesta_voz': resp,
    }
    return jsonify(resultado)


def _tiempo_relativo(dt_str: str) -> str:
    if not dt_str:
        return '—'
    try:
        dt = datetime.fromisoformat(str(dt_str))
        mins = int((datetime.now() - dt).total_seconds() / 60)
        if mins < 60:  return f"hace {mins} min"
        if mins < 1440: return f"hace {mins // 60} h"
        return f"hace {mins // 1440} días"
    except Exception:
        return '—'


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
    es_complejo = datos.pop("es_complejo", False)

    # TinyLlama solo para consultas complejas que requieren narrativa comparativa
    if es_complejo and _ollama_ok() and datos.get("datos"):
        system = (
            "Eres ZERO, el asistente del punto de venta. "
            "Responde en español, breve y natural (máximo 3 oraciones). "
            "Solo usa los datos dados, no inventes. Tono amigable y directo."
        )
        datos_str = json.dumps(datos.get("datos"), ensure_ascii=False)
        raw = _ollama(
            f'Pregunta: "{texto}"\nDatos: {datos_str}\nResumen breve en 3 líneas:',
            system, 120
        )
        respuesta = raw if raw else template
    else:
        # Consulta simple → respuesta SQL directa, sin esperar a TinyLlama
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
    complejo = _es_consulta_compleja(texto)

    with db_session() as conn:
        cfg = {r["clave"]: r["valor"]
               for r in conn.execute("SELECT clave, valor FROM config").fetchall()}

        # ── vocabulario_local: expresiones coloquiales aprendidas ─────
        t_norm_vc = _normalizar(texto)
        vocab_hit = _buscar_vocabulario_local(t_norm_vc, conn)
        if vocab_hit and vocab_hit.get('consulta_tipo'):
            t = vocab_hit['consulta_tipo'] + ' ' + t  # enrich query with learned type

        # ── Ventas de hoy ─────────────────────────────────────────────
        if any(k in t for k in ["hoy", "vendí hoy", "vendi hoy", "cuánto hoy", "cuanto hoy"]):
            row = _cq_ventas_hoy(conn)
            t_, n_ = int(row["total"]), row["num_ventas"]
            resp = f"Hoy llevas ${t_:,.0f} en {n_} {'venta' if n_==1 else 'ventas'}.".replace(",", ".")
            return {"datos": {"total": t_, "num_ventas": n_}, "template": resp, "es_complejo": False}

        # ── Stock bajo ────────────────────────────────────────────────
        if any(k in t for k in ["agotarse", "agotar", "stock bajo", "poco stock", "por agotarse",
                                  "crítico", "critico", "bajos"]):
            todos = _cq_stock_bajo(conn)
            if not todos:
                resp = "Todos los productos tienen stock suficiente."
            else:
                nombres = ", ".join(r["nombre"] for r in todos[:4])
                resp = f"Hay {len(todos)} producto{'s' if len(todos)>1 else ''} con stock bajo: {nombres}."
            return {"datos": todos, "template": resp, "es_complejo": False}

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
                    return {"datos": dict(row), "template": resp, "es_complejo": False}

        # ── Ayer ──────────────────────────────────────────────────────
        if any(k in t for k in ["ayer", "vendí ayer", "vendi ayer", "cuánto ayer", "cuanto ayer"]):
            row = _cq_ventas_ayer(conn)
            t_, n_ = int(row["total"]), row["num_ventas"]
            resp = f"Ayer vendiste ${t_:,.0f} en {n_} {'venta' if n_==1 else 'ventas'}.".replace(",", ".")
            return {"datos": {"total": t_, "num_ventas": n_}, "template": resp, "es_complejo": False}

        # ── Mejor cajero ──────────────────────────────────────────────
        if any(k in t for k in KEYWORDS_CAJERO):
            caj = _cq_cajero(conn)
            if caj:
                resp = f"{caj['nombre']} lidera hoy con ${int(caj['total']):,.0f} en {caj['ventas']} ventas.".replace(",", ".")
                return {"datos": caj, "template": resp, "es_complejo": False}
            return {"datos": None, "template": "Aún no hay ventas hoy.", "es_complejo": False}

        # ── Hora pico ─────────────────────────────────────────────────
        if any(k in t for k in KEYWORDS_HORA):
            hp = _cq_hora_pico(conn)
            if hp:
                resp = f"La hora con más movimiento hoy fue las {hp['hora']}:00 hrs con {hp['ventas']} ventas."
                return {"datos": hp, "template": resp, "es_complejo": False}
            return {"datos": None, "template": "Aún no hay ventas hoy.", "es_complejo": False}

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
                return {"datos": items, "template": resp, "es_complejo": True}

        # ── Top productos ──────────────────────────────────────────────
        if any(k in t for k in ["más vendido", "mas vendido", "mejor", "top", "popular"]):
            top = _cq_top_prod(conn, dias=30)
            if top:
                resp = f"El producto más vendido del mes es {top['nombre']} con {top['unidades']} unidades."
                return {"datos": top, "template": resp, "es_complejo": False}

        # ── Mejor día esta semana ──────────────────────────────────────
        if any(k in t for k in ["mejor día", "mejor dia", "cuál fue el mejor", "cual fue el mejor",
                                  "mejor semana"]):
            hace7 = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            row = conn.execute(
                "SELECT DATE(creado_en) as fecha, SUM(total) as tot, COUNT(*) as n "
                "FROM ventas WHERE estado='completada' AND DATE(creado_en)>=? "
                "GROUP BY DATE(creado_en) ORDER BY tot DESC LIMIT 1",
                (hace7,)
            ).fetchone()
            if row:
                _dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
                try:
                    _dt = datetime.strptime(str(row["fecha"]), "%Y-%m-%d")
                    dia_nom = _dias[_dt.weekday()]
                except Exception:
                    dia_nom = str(row["fecha"])
                resp = (f"El mejor día fue el {dia_nom} con "
                        f"${int(row['tot']):,.0f} en {row['n']} ventas.").replace(",", ".")
                return {"datos": dict(row), "template": resp, "es_complejo": False}
            return {"datos": None, "template": "No hay ventas esta semana.", "es_complejo": False}

        # ── Resumen del día / cierra el día ─── complejo: merece narrativa
        if any(k in t for k in ["resumen", "cierra el día", "cierra el dia", "cómo vamos",
                                  "como vamos", "cuánto va", "cuanto va",
                                  "fue un buen día", "fue un buen dia", "buen día", "buen dia"]):
            row_tot = _cq_ventas_hoy(conn)
            metodos = conn.execute(
                "SELECT metodo_pago, COUNT(*) as n, SUM(total) as tot "
                "FROM ventas WHERE DATE(creado_en)=DATE('now') AND estado='completada' "
                "GROUP BY metodo_pago"
            ).fetchall()
            top_prod = conn.execute(
                "SELECT p.nombre, SUM(vi.cantidad) as cant "
                "FROM venta_items vi JOIN productos p ON vi.producto_id=p.id "
                "JOIN ventas v ON vi.venta_id=v.id "
                "WHERE DATE(v.creado_en)=DATE('now') AND v.estado='completada' "
                "GROUP BY vi.producto_id ORDER BY cant DESC LIMIT 3"
            ).fetchall()
            ayer_row = _cq_ventas_ayer(conn)
            n_, tot_ = row_tot["num_ventas"], int(row_tot["total"])
            if n_ == 0:
                return {"datos": {"total": 0, "ventas": 0},
                        "template": "Hoy no hay ventas registradas.", "es_complejo": False}
            met_txt = ", ".join(
                f"{r['metodo_pago']} ${int(r['tot']):,.0f}".replace(",", ".") for r in metodos
            ) or "—"
            top_txt = ", ".join(f"{r['nombre']} ({r['cant']})" for r in top_prod)
            resp = (f"Hoy: ${tot_:,.0f} en {n_} {'venta' if n_==1 else 'ventas'}. "
                    f"Métodos: {met_txt}. Más vendido: {top_txt}.").replace(",", ".")
            return {"datos": {
                "total": tot_, "ventas": n_,
                "total_ayer": int(ayer_row["total"]),
                "metodos": [dict(r) for r in metodos],
                "top_productos": [dict(r) for r in top_prod],
            }, "template": resp, "es_complejo": True}

        # ── Predicción de compras ─── complejo: requiere razonamiento
        if any(k in t for k in ["qué necesito pedir", "que necesito pedir", "qué pedir",
                                  "que pedir", "lista de compras", "qué comprar", "que comprar",
                                  "cuánto comprar", "cuanto comprar", "debo pedir", "necesito pedir"]):
            hace4 = (datetime.now() - timedelta(weeks=4)).strftime("%Y-%m-%d")
            rows_pred = conn.execute(
                "SELECT p.nombre, p.stock, p.stock_minimo, "
                "  (SELECT COALESCE(AVG(d.c),0) FROM ("
                "    SELECT SUM(vi.cantidad) as c FROM venta_items vi "
                "    JOIN ventas v ON vi.venta_id=v.id "
                "    WHERE vi.producto_id=p.id AND v.estado='completada' "
                "    AND DATE(v.creado_en)>=? GROUP BY DATE(v.creado_en)"
                "  ) d) as prom_diario "
                "FROM productos p "
                "WHERE p.activo=1 AND p.modo_stock='normal' AND p.tiene_variantes=0 "
                "  AND p.stock<=p.stock_minimo ORDER BY p.stock ASC LIMIT 8",
                (hace4,)
            ).fetchall()
            if rows_pred:
                items_pred = []
                for r in rows_pred:
                    prom = float(r["prom_diario"] or 0)
                    sugerido = int(max(round(prom * 7), r["stock_minimo"] * 2, 1))
                    items_pred.append(f"{r['nombre']}: pedir ~{sugerido} (tienes {r['stock']})")
                resp = "Necesitas pedir: " + ". ".join(items_pred[:5]) + "."
                return {"datos": [dict(r) for r in rows_pred], "template": resp, "es_complejo": True}
            return {"datos": None, "template": "No hay productos con stock bajo.", "es_complejo": False}

        # ── Búsqueda por proveedor ─────────────────────────────────────
        _PROV_TRIGGERS = ["vendedor de", "proveedor de", "el de las", "el de los", "el de la",
                          "el de", "qué le pido al", "que le pido al", "qué le pido a",
                          "que le pido a", "productos de", "pedido de", "llegó el", "llego el"]
        for _trigger in _PROV_TRIGGERS:
            if _trigger in t:
                nombre_buscar = t.split(_trigger, 1)[1].strip().split()[0:3]
                nombre_buscar = " ".join(nombre_buscar)
                if len(nombre_buscar) < 2:
                    break
                prov = conn.execute(
                    "SELECT * FROM proveedores WHERE activo=1 "
                    "AND (LOWER(nombre) LIKE ? OR LOWER(COALESCE(apodo,'')) LIKE ?) LIMIT 1",
                    (f"%{nombre_buscar}%", f"%{nombre_buscar}%")
                ).fetchone()
                if not prov:
                    # Buscar por productos que provee
                    prov = conn.execute(
                        "SELECT DISTINCT pr.* FROM proveedores pr "
                        "JOIN ordenes_compra oc ON oc.proveedor_id=pr.id "
                        "JOIN orden_items oi ON oi.orden_id=oc.id "
                        "JOIN productos p ON p.id=oi.producto_id "
                        "WHERE pr.activo=1 AND LOWER(p.nombre) LIKE ? LIMIT 1",
                        (f"%{nombre_buscar}%",)
                    ).fetchone()
                if prov:
                    prov_id = prov["id"]
                    prov_nombre = prov["nombre"]
                    prods_prov = conn.execute(
                        "SELECT p.nombre, p.stock, p.stock_minimo FROM productos p "
                        "JOIN orden_items oi ON oi.producto_id=p.id "
                        "JOIN ordenes_compra oc ON oc.id=oi.orden_id "
                        "WHERE oc.proveedor_id=? AND p.activo=1 "
                        "GROUP BY p.id ORDER BY p.stock ASC LIMIT 10",
                        (prov_id,)
                    ).fetchall()
                    last_oc = conn.execute(
                        "SELECT creado_en FROM ordenes_compra "
                        "WHERE proveedor_id=? ORDER BY creado_en DESC LIMIT 1",
                        (prov_id,)
                    ).fetchone()
                    low = [dict(r) for r in prods_prov if r["stock"] <= r["stock_minimo"]]
                    all_p = [dict(r) for r in prods_prov]
                    last_txt = _tiempo_relativo(last_oc["creado_en"]) if last_oc else "sin pedidos"
                    if low:
                        det = ", ".join(f"{p['nombre']}: {p['stock']} u" for p in low[:5])
                        resp = (f"El proveedor {prov_nombre} tiene stock bajo en: "
                                f"{det}. Último pedido {last_txt}.")
                    elif all_p:
                        det = ", ".join(f"{p['nombre']}: {p['stock']} u" for p in all_p[:5])
                        resp = (f"{prov_nombre}: {det}. Último pedido {last_txt}.")
                    else:
                        resp = f"{prov_nombre}: sin productos registrados. Último pedido {last_txt}."
                    return {"datos": {"proveedor": prov_nombre, "low_stock": low, "productos": all_p},
                            "template": resp, "es_complejo": False}
                else:
                    return {"datos": None,
                            "template": f"No encontré proveedor que coincida con '{nombre_buscar}'.",
                            "es_complejo": False}
                break

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
                return {"datos": dict(prod), "template": resp, "es_complejo": False}

    return {"datos": None, "template": "No encontré esa información. Intenta ser más específico.",
            "es_complejo": False}


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

_VOZ_KEYS = {"voz_activa", "voz_palabra_clave", "voz_velocidad", "voz_tono", "voz_nombre", "voz_volumen"}


@voz_bp.route("/config", methods=["GET"])
def config_get():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute("SELECT clave, valor FROM config WHERE clave LIKE 'voz_%'").fetchall()
        cfg = {r["clave"]: r["valor"] for r in rows}
    return jsonify({
        "voz_activa":      cfg.get("voz_activa", "1"),
        "voz_palabra_clave": cfg.get("voz_palabra_clave", "ZERO"),
        "voz_velocidad":   cfg.get("voz_velocidad", "0.8"),
        "voz_tono":        cfg.get("voz_tono", "1.0"),
        "voz_nombre":      cfg.get("voz_nombre", ""),
        "voz_volumen":     cfg.get("voz_volumen", "1.0"),
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


# ── Aprendizaje ───────────────────────────────────────────────────────────────

@voz_bp.route("/aprendizaje", methods=["GET"])
def listar_aprendizaje():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        try:
            acciones = [
                {
                    'id': r['id'], 'palabra': r['palabra'],
                    'significa': r['accion'], 'veces_usado': r['veces_usado'],
                    'aprendido': _tiempo_relativo(r['creado_en']),
                }
                for r in conn.execute(
                    "SELECT id, palabra, accion, veces_usado, creado_en "
                    "FROM voz_aprendizaje WHERE confirmado=1 ORDER BY veces_usado DESC"
                ).fetchall()
            ]
            productos = [
                {
                    'id': r['id'], 'palabra': r['palabra'],
                    'significa': r['nombre'], 'veces_usado': r['veces_usado'],
                    'aprendido': _tiempo_relativo(r['creado_en']),
                }
                for r in conn.execute(
                    "SELECT s.id, s.palabra, p.nombre, s.veces_usado, s.creado_en "
                    "FROM voz_sinonimos_producto s JOIN productos p ON s.producto_id=p.id "
                    "ORDER BY s.veces_usado DESC"
                ).fetchall()
            ]
            variantes = [
                {
                    'id': r['id'], 'palabra': r['palabra'],
                    'significa': (r['vnombre'] or '?') + (f" ({r['pnombre']})" if r['pnombre'] else ''),
                    'veces_usado': r['veces_usado'],
                    'aprendido': _tiempo_relativo(r['creado_en']),
                }
                for r in conn.execute(
                    "SELECT s.id, s.palabra, v.nombre as vnombre, p.nombre as pnombre, "
                    "s.veces_usado, s.creado_en "
                    "FROM voz_sinonimos_variante s "
                    "LEFT JOIN producto_variantes v ON s.variante_id=v.id "
                    "LEFT JOIN productos p ON s.producto_id=p.id "
                    "ORDER BY s.veces_usado DESC"
                ).fetchall()
            ]
        except Exception as e:
            logger.warning(f"[aprendizaje] Error leyendo tablas: {e}")
            acciones, productos, variantes = [], [], []
    return jsonify({'acciones': acciones, 'productos': productos, 'variantes': variantes})


@voz_bp.route("/aprendizaje/<int:aid>", methods=["DELETE"])
def olvidar_palabra(aid):
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    tipo = request.args.get("tipo", "accion")
    with db_session() as conn:
        if tipo == "producto":
            conn.execute("DELETE FROM voz_sinonimos_producto WHERE id=?", (aid,))
        elif tipo == "variante":
            conn.execute("DELETE FROM voz_sinonimos_variante WHERE id=?", (aid,))
        else:
            conn.execute("DELETE FROM voz_aprendizaje WHERE id=?", (aid,))
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
