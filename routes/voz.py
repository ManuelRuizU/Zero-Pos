import json
import logging
import re
import unicodedata
import urllib.request
from datetime import datetime, timedelta
from difflib import SequenceMatcher
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

    # Learned product synonym fallback
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
                    if not resultado['producto']:
                        resultado['producto'] = llm.get('producto', '')
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
