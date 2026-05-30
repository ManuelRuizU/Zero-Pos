#!/usr/bin/env python3
"""
Descarga productos chilenos desde Open Food Facts
y genera data/productos_base_minimarket.json
Uso: python scripts/descargar_productos_chile.py
"""

import json
import urllib.request
import urllib.parse
import time
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(BASE_DIR, "data", "productos_base_minimarket.json")

CATEGORIAS = [
    ("beverages", "Bebidas"),
    ("dairy-products", "Lácteos"),
    ("snacks", "Snacks"),
    ("pastas", "Pastas y Arroz"),
    ("cereals-and-potatoes", "Cereales"),
    ("groceries", "Abarrotes"),
    ("cleaning-products", "Limpieza"),
    ("breads", "Pan y Panadería"),
    ("oils-and-fats", "Aceites"),
    ("canned-foods", "Conservas"),
    ("condiments", "Condimentos"),
    ("beverages-and-beverages-preparations", "Bebidas"),
]

def descargar_categoria(categoria_api, categoria_nombre):
    url = (
        "https://world.openfoodfacts.org/cgi/search.pl"
        f"?action=process"
        f"&tagtype_0=countries&tag_contains_0=contains&tag_0=chile"
        f"&tagtype_1=categories&tag_contains_1=contains&tag_1={categoria_api}"
        f"&json=1&page_size=100&fields="
        f"code,product_name,brands,categories_tags,"
        f"quantity,image_front_url"
    )
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "ZERO-POS/1.0 (contacto@zeropos.cl)"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            productos = []
            for p in data.get("products", []):
                codigo = p.get("code", "").strip()
                nombre = p.get("product_name", "").strip()
                if not codigo or not nombre or len(codigo) < 8:
                    continue
                productos.append({
                    "codigo_barras": codigo,
                    "nombre": nombre,
                    "marca": p.get("brands", "").split(",")[0].strip(),
                    "categoria": categoria_nombre,
                    "precio_sugerido": 0,
                    "unidad": p.get("quantity", ""),
                    "imagen_url": p.get("image_front_url", ""),
                    "fuente": "openfoodfacts"
                })
            return productos
    except Exception as e:
        print(f"  ⚠️ Error en {categoria_api}: {e}")
        return []

# Productos curados manualmente
# Los que Open Food Facts no tiene bien para Chile
PRODUCTOS_CURADOS = [
    {"codigo_barras": "2000001000016", "nombre": "Huevo",
     "marca": "", "categoria": "Lácteos y Huevos",
     "precio_sugerido": 150, "unidad": "unidad",
     "imagen_url": "", "fuente": "curado"},
    {"codigo_barras": "2000001000023", "nombre": "Pan Marraqueta",
     "marca": "", "categoria": "Pan y Panadería",
     "precio_sugerido": 150, "unidad": "unidad",
     "imagen_url": "", "fuente": "curado"},
    {"codigo_barras": "2000001000030", "nombre": "Pan Hallulla",
     "marca": "", "categoria": "Pan y Panadería",
     "precio_sugerido": 150, "unidad": "unidad",
     "imagen_url": "", "fuente": "curado"},
    {"codigo_barras": "2000001000047", "nombre": "Gas Licuado 5kg",
     "marca": "", "categoria": "Otros",
     "precio_sugerido": 8500, "unidad": "5kg",
     "imagen_url": "", "fuente": "curado"},
    {"codigo_barras": "2000001000054", "nombre": "Gas Licuado 11kg",
     "marca": "", "categoria": "Otros",
     "precio_sugerido": 16000, "unidad": "11kg",
     "imagen_url": "", "fuente": "curado"},
    {"codigo_barras": "2000001000061", "nombre": "Vela",
     "marca": "", "categoria": "Otros",
     "precio_sugerido": 500, "unidad": "unidad",
     "imagen_url": "", "fuente": "curado"},
    {"codigo_barras": "2000001000078", "nombre": "Pilas AA",
     "marca": "", "categoria": "Otros",
     "precio_sugerido": 990, "unidad": "par",
     "imagen_url": "", "fuente": "curado"},
    {"codigo_barras": "2000001000085", "nombre": "Fósforos",
     "marca": "", "categoria": "Otros",
     "precio_sugerido": 300, "unidad": "caja",
     "imagen_url": "", "fuente": "curado"},
]

if __name__ == "__main__":
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    todos = list(PRODUCTOS_CURADOS)
    codigos_vistos = {p["codigo_barras"] for p in todos}

    for cat_api, cat_nombre in CATEGORIAS:
        print(f"Descargando {cat_nombre}...")
        prods = descargar_categoria(cat_api, cat_nombre)
        nuevos = 0
        for p in prods:
            if p["codigo_barras"] not in codigos_vistos:
                todos.append(p)
                codigos_vistos.add(p["codigo_barras"])
                nuevos += 1
        print(f"  ✅ {nuevos} productos nuevos")
        time.sleep(1)  # Respetar el rate limit de OFF

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Total: {len(todos)} productos")
    print(f"📁 Guardado en: {OUTPUT}")

    # Resumen por categoría
    from collections import Counter
    cats = Counter(p["categoria"] for p in todos)
    for cat, n in cats.most_common():
        print(f"  {cat}: {n}")
