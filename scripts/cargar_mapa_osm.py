# scripts/cargar_mapa_osm.py
#!/usr/bin/env python3
"""
Descarga y carga el mapa OSM de una región en la DB local de ZERO POS.
Ejecutar UNA VEZ al instalar o cuando se quiera actualizar el mapa.

Uso:
  python scripts/cargar_mapa_osm.py --comuna "Angol"
  python scripts/cargar_mapa_osm.py --comuna "Temuco" --region "Araucania"
  python scripts/cargar_mapa_osm.py --listar
"""
import argparse
import sys
import os
import sqlite3
import unicodedata
import urllib.request
import urllib.parse
import json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "zero_pos.db")


def normalizar(texto: str) -> str:
    if not texto:
        return ""
    texto = texto.lower().strip()
    texto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def cargar_desde_overpass(comuna: str) -> list:
    """Descarga calles de una comuna vía Overpass API (requiere internet)."""
    print(f"Descargando calles de {comuna} desde Overpass API...")

    query = f"""
    [out:json][timeout:90];
    area["name"="{comuna}"]["admin_level"~"7|8"]->.searchArea;
    way["highway"]["name"](area.searchArea);
    out tags;
    """

    url  = "https://overpass-api.de/api/interpreter"
    data = urllib.parse.urlencode({"data": query}).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"User-Agent": "ZERO-POS/1.0 (mapa offline local)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            resultado = json.loads(resp.read())
            elementos = resultado.get("elements", [])
            print(f"   Recibidos {len(elementos)} elementos de Overpass.")
            return elementos
    except urllib.error.HTTPError as e:
        print(f"Error HTTP {e.code}: {e.reason}")
        return []
    except Exception as e:
        print(f"Error de conexión: {e}")
        return []


def cargar_desde_nominatim(calle: str, comuna: str) -> list:
    """Búsqueda puntual de una calle vía Nominatim (fallback)."""
    params = urllib.parse.urlencode({
        "q":             f"{calle}, {comuna}, Chile",
        "format":        "json",
        "limit":         5,
        "addressdetails": 1,
    })
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "ZERO-POS/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return []


def cargar_en_db(elementos: list, comuna: str) -> int:
    """Guarda los elementos en geografia_local y retorna el número insertado."""
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()

    c.execute("DELETE FROM geografia_local WHERE LOWER(comuna) = LOWER(?)", (comuna,))

    insertados = 0
    for elem in elementos:
        tags   = elem.get("tags", {})
        nombre = tags.get("name", "")
        if not nombre:
            continue
        c.execute(
            """INSERT INTO geografia_local
               (comuna, calle_nombre, calle_limpia, tipo_via)
               VALUES (?, ?, ?, ?)""",
            (comuna, nombre, normalizar(nombre), tags.get("highway", "street"))
        )
        insertados += 1

    conn.commit()
    conn.close()
    return insertados


def listar_comunas() -> None:
    """Muestra las comunas cargadas en la base de datos."""
    if not os.path.exists(DB_PATH):
        print("Base de datos no encontrada. Inicia ZERO POS al menos una vez.")
        return
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT comuna, COUNT(*) as n FROM geografia_local GROUP BY LOWER(comuna) ORDER BY n DESC"
    ).fetchall()
    conn.close()
    if not rows:
        print("Sin datos de calles. Usa --comuna para cargar una.")
        return
    print(f"{'COMUNA':<25} {'CALLES':>8}")
    print("-" * 35)
    for com, n in rows:
        print(f"{com:<25} {n:>8,}")
    print(f"\nTotal: {sum(n for _, n in rows):,} calles en {len(rows)} comunas")


def main():
    parser = argparse.ArgumentParser(
        description="Carga calles de OpenStreetMap en la DB local de ZERO POS."
    )
    parser.add_argument("--comuna",  help="Nombre de la comuna (ej: Angol)")
    parser.add_argument("--region",  default="", help="Región (informativo)")
    parser.add_argument("--listar",  action="store_true", help="Listar comunas cargadas")
    args = parser.parse_args()

    if args.listar:
        listar_comunas()
        return

    if not args.comuna:
        parser.print_help()
        sys.exit(1)

    if not os.path.exists(DB_PATH):
        print(f"Base de datos no encontrada en {DB_PATH}")
        print("Inicia ZERO POS al menos una vez para crear la DB.")
        sys.exit(1)

    elementos = cargar_desde_overpass(args.comuna)
    if not elementos:
        print("\nSin datos o sin conexión a internet.")
        print("Las calles se agregarán al cache cuando haya internet (Nominatim).")
        sys.exit(0)

    insertados = cargar_en_db(elementos, args.comuna)
    print(f"\n✅ {insertados:,} calles cargadas para {args.comuna}")
    print(f"DB: {DB_PATH}")


if __name__ == "__main__":
    main()
