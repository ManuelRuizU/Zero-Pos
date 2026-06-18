#scripts/descargar_productos_chile.py
#!/usr/bin/env python3
"""
Descarga productos chilenos desde Open Food Facts
y genera data/productos_base_minimarket.json

Filtros aplicados:
  1. Código de barras chileno (780-784) o interno (2xxxxxxx)
  2. Nombre en español (encodeable en latin-1)
  3. Categoría mapeada a nombres de ZERO POS
  4. Sin duplicados por nombre normalizado

Uso: python scripts/descargar_productos_chile.py
"""

import json
import unicodedata
import urllib.request
import time
import os
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT   = os.path.join(BASE_DIR, "data", "productos_base_minimarket.json")

# ── Mapeo de categorías OFF → ZERO POS ────────────────────────────────────────
CATEGORIA_MAP = {
    "beverages":                          "Bebidas",
    "beverages-and-beverages-preparations": "Bebidas",
    "wines":                              "Bebidas",
    "beers":                              "Bebidas",
    "dairy-products":                     "Lácteos",
    "snacks":                             "Snacks",
    "pastas":                             "Pastas y Arroz",
    "rice":                               "Pastas y Arroz",
    "cereals":                            "Cereales",
    "cereals-and-potatoes":               "Cereales",
    "groceries":                          "Abarrotes",
    "cleaning-products":                  "Limpieza e Higiene",
    "breads":                             "Pan y Panadería",
    "oils-and-fats":                      "Aceites",
    "canned-foods":                       "Conservas",
    "condiments":                         "Condimentos",
}

CATEGORIAS = sorted(CATEGORIA_MAP.keys())

# ── Filtros ────────────────────────────────────────────────────────────────────

def es_codigo_chileno(codigo: str) -> bool:
    """Solo acepta códigos con prefijo GS1 de Chile (780-784) o internos (2x)."""
    prefijos_chile   = ("780", "781", "782", "783", "784")
    prefijos_interno = ("2",)
    return (
        codigo.startswith(prefijos_chile)
        or codigo.startswith(prefijos_interno)
    )


def nombre_valido(nombre: str) -> bool:
    """Rechaza nombres con caracteres no latinos (cirílico, chino, árabe, etc.)."""
    if not nombre or len(nombre) < 2:
        return False
    try:
        nombre.encode("latin-1")
        return True
    except UnicodeEncodeError:
        return False


def normalizar(nombre: str) -> str:
    """Normaliza a minúsculas sin acentos para deduplicación."""
    nfkd = unicodedata.normalize("NFKD", nombre.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip()


# ── Descarga ───────────────────────────────────────────────────────────────────

def descargar_categoria(categoria_api: str) -> list:
    categoria_nombre = CATEGORIA_MAP.get(categoria_api, "Abarrotes")
    url = (
        "https://world.openfoodfacts.org/cgi/search.pl"
        "?action=process"
        "&tagtype_0=countries&tag_contains_0=contains&tag_0=chile"
        f"&tagtype_1=categories&tag_contains_1=contains&tag_1={categoria_api}"
        "&json=1&page_size=100"
        "&fields=code,product_name,brands,quantity,image_front_url"
    )
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "ZERO-POS/1.0 (contacto@zeropos.cl)"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data     = json.loads(resp.read())
            aceptados = 0
            rechazados = 0
            productos = []

            for p in data.get("products", []):
                codigo = p.get("code", "").strip()
                nombre = p.get("product_name", "").strip()

                # Filtro 1 — código chileno o interno
                if not codigo or len(codigo) < 8:
                    rechazados += 1
                    continue
                if not es_codigo_chileno(codigo):
                    rechazados += 1
                    continue

                # Filtro 2 — nombre en español
                if not nombre_valido(nombre):
                    rechazados += 1
                    continue

                productos.append({
                    "codigo_barras":  codigo,
                    "nombre":         nombre,
                    "marca":          p.get("brands", "").split(",")[0].strip(),
                    "categoria":      categoria_nombre,
                    "precio_sugerido": 0,
                    "unidad":         p.get("quantity", ""),
                    "imagen_url":     p.get("image_front_url", ""),
                    "fuente":         "openfoodfacts",
                })
                aceptados += 1

            print(f"  → {aceptados} aceptados, {rechazados} rechazados")
            return productos

    except Exception as e:
        print(f"  ⚠️  Error: {e}")
        return []


# ── Productos curados — lo que OFF no tiene bien para Chile ────────────────────
PRODUCTOS_CURADOS = [
    {"codigo_barras": "2000001000016", "nombre": "Huevo",
     "marca": "", "categoria": "Lácteos y Huevos",
     "precio_sugerido": 150, "unidad": "unidad", "imagen_url": "", "fuente": "curado"},
    {"codigo_barras": "2000001000023", "nombre": "Pan Marraqueta",
     "marca": "", "categoria": "Pan y Panadería",
     "precio_sugerido": 150, "unidad": "unidad", "imagen_url": "", "fuente": "curado"},
    {"codigo_barras": "2000001000030", "nombre": "Pan Hallulla",
     "marca": "", "categoria": "Pan y Panadería",
     "precio_sugerido": 150, "unidad": "unidad", "imagen_url": "", "fuente": "curado"},
    {"codigo_barras": "2000001000047", "nombre": "Gas Licuado 5kg",
     "marca": "", "categoria": "Otros",
     "precio_sugerido": 8500, "unidad": "5kg", "imagen_url": "", "fuente": "curado"},
    {"codigo_barras": "2000001000054", "nombre": "Gas Licuado 11kg",
     "marca": "", "categoria": "Otros",
     "precio_sugerido": 16000, "unidad": "11kg", "imagen_url": "", "fuente": "curado"},
    {"codigo_barras": "2000001000061", "nombre": "Vela",
     "marca": "", "categoria": "Otros",
     "precio_sugerido": 500, "unidad": "unidad", "imagen_url": "", "fuente": "curado"},
    {"codigo_barras": "2000001000078", "nombre": "Pilas AA",
     "marca": "", "categoria": "Otros",
     "precio_sugerido": 990, "unidad": "par", "imagen_url": "", "fuente": "curado"},
    {"codigo_barras": "2000001000085", "nombre": "Fósforos",
     "marca": "", "categoria": "Otros",
     "precio_sugerido": 300, "unidad": "caja", "imagen_url": "", "fuente": "curado"},
]


# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)

    todos          = list(PRODUCTOS_CURADOS)
    codigos_vistos = {p["codigo_barras"] for p in todos}
    nombres_vistos = {normalizar(p["nombre"]) for p in todos}

    for cat_api in CATEGORIAS:
        cat_nombre = CATEGORIA_MAP[cat_api]
        print(f"Descargando {cat_nombre} ({cat_api})...")
        prods = descargar_categoria(cat_api)

        nuevos = 0
        for p in prods:
            # Filtro 3 — sin código duplicado
            if p["codigo_barras"] in codigos_vistos:
                continue
            # Filtro 4 — sin nombre duplicado (normalizado)
            nombre_norm = normalizar(p["nombre"])
            if nombre_norm in nombres_vistos:
                continue

            todos.append(p)
            codigos_vistos.add(p["codigo_barras"])
            nombres_vistos.add(nombre_norm)
            nuevos += 1

        print(f"  ✅ {nuevos} productos nuevos agregados")
        time.sleep(1.5)  # Respetar rate limit de Open Food Facts

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Total: {len(todos)} productos guardados")
    print(f"📁 {OUTPUT}\n")

    cats = Counter(p["categoria"] for p in todos)
    for cat, n in cats.most_common():
        print(f"  {cat:<30} {n:>4}")
