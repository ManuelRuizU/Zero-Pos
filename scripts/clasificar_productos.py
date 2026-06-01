#!/usr/bin/env python3
"""
Clasifica productos existentes en la DB por departamento y categoría
usando palabras clave. Rápido y sin IA.
Uso: python scripts/clasificar_productos.py
"""

import re
import sqlite3
import unicodedata
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'zero_pos.db')

# Mapa de palabras clave → categoría
# Orden importa: más específico primero
REGLAS = [
    # BEBIDAS CON ALCOHOL
    ('cerveza|escudo|cristal|heineken|corona|'
     'kunstmann|austral|becker|stout|torobayo|monterrey',
     'Cervezas', 'Bebidas con Alcohol'),
    ('vino|cabernet|merlot|carmenere|chardonnay|'
     'sauvignon|pinot|syrah|malbec|rose|rosé',
     'Vinos', 'Bebidas con Alcohol'),
    ('pisco|ron|whisky|vodka|gin|tequila|'
     'brandy|cognac|licor|aguardiente',
     'Licores', 'Bebidas con Alcohol'),

    # BEBIDAS SIN ALCOHOL
    (r'coca.cola|pepsi|fanta|sprite|7up|'
     r'bilz|\bpap\b|kem|ginger|bebida gaseosa',
     'Bebidas', 'Alimentación'),
    ('agua vital|cachantun|benedictus|benedictino|'
     'porvenir|agua mineral|agua purificada|guallarauco|agua lig',
     'Bebidas', 'Alimentación'),
    ('jugo|nectar|watt|ades|'
     'ceres|frugo|tampico|kapo|livean|good drink|bebida',
     'Bebidas', 'Alimentación'),
    ('leche chocolatada|leche con|nesquik',
     'Bebidas', 'Alimentación'),
    (r'cafe|nescafe|tea|\bte\b|milo|ovomaltine|'
     r'cocoa|chocolate en polvo|hierbas|colacao|'
     r'tostadas con',
     'Desayuno', 'Alimentación'),
    (r'energetica|monster|red bull|score|'
     r'rockstar|\bamp\b',
     'Bebidas', 'Alimentación'),

    # LÁCTEOS
    ('leche|soprole|loncoleche|colun|'
     'parmalat|nestle leche|not milk|notmilk',
     'Lácteos', 'Alimentación'),
    ('yogurt|yoghurt|yogu|kefir|danone|activia|'
     'yoplait|chiquitin|vivo line|livean|berries|yoghito|'
     'purita mama',
     'Lácteos', 'Alimentación'),
    ('mantequilla|margarina|manjar|'
     'queso|quesillo|ricotta|crema',
     'Lácteos', 'Alimentación'),
    ('huevo',
     'Lácteos y Huevos', 'Alimentación'),

    # PANADERÍA
    ('pan |marraqueta|hallulla|molde|'
     'bimbo|ideal|pan integral|tortilla|rapidita|'
     'grisine|masa madre|multigrano|artesano',
     'Pan y Panadería', 'Alimentación'),
    ('galleta|cookie|crackers|wafer|'
     'oreo|costa|triton|soda|'
     r'nik |chocman|kuky|kilatte|granjerita|'
     r'oh.{0,2}bleas|mentita|doblon|selz|crackelet|blem|'
     r'rolls |dindon|frac |rigochoc|tuareg|braunichoc|'
     r'chocolate.*jack|chocolatin|quifaro|'
     r'protein bar|helado|\bprotein\b',
     'Snacks', 'Alimentación'),
    ('torta|pastel|muffin|queque',
     'Pan y Panadería', 'Alimentación'),

    # CEREALES Y DESAYUNO
    ('avena|muesli|granola|cereal|salvado|'
     'corn flakes|quaker|nestle cereal|arandano maqui|'
     r'chocapic|check cacao|\bloop\b',
     'Cereales', 'Alimentación'),

    # PASTAS Y ARROZ
    ('spaghetti|spaguetti|espaghetti|fideos|tallarin|pasta|'
     'penne|fusilli|macarron|lasana|lasagna|lasagne|'
     'fettuccine|corbata|espiral|mariposa|rigati|caballito|'
     'gnocchi|noqui|oqui|cuscus|quinoa',
     'Pastas y Arroz', 'Alimentación'),
    ('arroz|tucapel|gato|arroz largo',
     'Pastas y Arroz', 'Alimentación'),

    # ABARROTES
    ('aceite|vegetal|oliva|canola|maravilla',
     'Abarrotes', 'Alimentación'),
    ('azucar|harina|selecta|sal |'
     'sal de|levadura',
     'Abarrotes', 'Alimentación'),
    (r'vinagre|mayonesa|mostaza|ketchup|yellow mustard|'
     r'salsa de tomate|salsa inglesa|salsa soya|salsa de soya|'
     r'salsa bbq|salsa bolonesa|pomarola|notmayo|mayo |mayo$|'
     r'esencia|laurel|star anise|hummus|maizena|'
     r'san remo|\bsalsa\b',
     'Condimentos', 'Alimentación'),
    ('mermelada|manjar|nutella|miel|'
     'dulce de',
     'Abarrotes', 'Alimentación'),

    # CONSERVAS
    ('atun|sardina|jurel|salmon|'
     'seafood|mariscos en lata',
     'Conservas', 'Alimentación'),
    ('tomate en|porotos|lentejas|garbanzos|'
     'choclo|arvejas|durazno|marrasquino|'
     'champinon|champiñon|chapinon|instant noodle',
     'Conservas', 'Alimentación'),

    # SNACKS
    ('lay|doritos|cheetos|pringles|'
     'papas fritas|chips',
     'Snacks', 'Alimentación'),
    ('chocolate|ambrosoli|super 8|'
     'kit kat|snickers',
     'Snacks', 'Alimentación'),
    ('caramelo|chicle|gomita|'
     'confite|dulce',
     'Snacks', 'Alimentación'),

    # CARNES
    ('vacuno|cerdo|pollo|pavo|'
     'fiambre|cecina|salchicha|jamon|'
     'longaniza|chorizo|mortadela',
     'Carnes y Fiambres', 'Alimentación'),

    # FRUTAS Y VERDURAS
    ('manzana|pera|naranja|limon|'
     'platano|uva|frutilla|'
     'tomate|lechuga|zanahoria|papa ',
     'Frutas y Verduras', 'Alimentación'),

    # HIGIENE PERSONAL
    ('shampoo|champu|acondicionador|'
     'tinte|cabello|hair',
     'Cuidado Cabello', 'Belleza y Cuidado Personal'),
    ('jabon|body wash|gel de ducha',
     'Higiene Personal', 'Belleza y Cuidado Personal'),
    ('desodorante|antitranspirante|axe|'
     'rexona|nivea deo',
     'Higiene Personal', 'Belleza y Cuidado Personal'),
    ('pasta dental|cepillo de dientes|'
     'colgate|oral.b|enjuague bucal',
     'Higiene Personal', 'Belleza y Cuidado Personal'),
    ('toalla higienica|tampon|kotex|always|stayfree',
     'Cuidado Femenino', 'Belleza y Cuidado Personal'),
    ('maquinilla|gillette|afeitad|'
     'depilat',
     'Afeitado y Depilación', 'Belleza y Cuidado Personal'),
    ('crema facial|crema corporal|locion|'
     'nivea|pond|neutrogena',
     'Cosmética', 'Belleza y Cuidado Personal'),
    ('paracetamol|ibuprofeno|aspirina|'
     'antigripal|vitamina|'
     'curitas|venda|alcohol |algodon',
     'Salud Básica', 'Belleza y Cuidado Personal'),

    # LIMPIEZA DEL HOGAR
    ('detergente|omo|ariel|skip|'
     'suavizante|vanish',
     'Detergentes', 'Limpieza del Hogar'),
    ('cloro|hipoclorito|lysoform|'
     'desinfectante|multiusos|'
     'limpiador|ajax|cif|lavavajilla|vajilla',
     'Limpiadores', 'Limpieza del Hogar'),
    ('papel higienico|toalla nova|elite|confort|bolsa basura|'
     'papel de cocina',
     'Papel y Descartables', 'Limpieza del Hogar'),
    ('insecticida|raid|baygon|mata',
     'Insecticidas', 'Limpieza del Hogar'),

    # MUNDO BEBÉ
    ('panal|pampers|huggies|'
     'toallita humeda',
     'Pañales y Toallitas', 'Mundo Bebé'),
    ('leche de formula|formula|'
     'papilla|colado|nestum',
     'Alimentación Infantil', 'Mundo Bebé'),

    # MASCOTAS
    ('pedigree|whiskas|'
     'purina|dog chow|felix|alimento.*perro|'
     'alimento.*gato|royal canin',
     'Alimentos Mascotas', 'Mascotas'),

    # MANUALIDADES
    ('lana|hilo de|aguja|tejido|'
     'costura|tela|boton',
     'Costura y Tejido', 'Manualidades y Hogar'),
    ('cuaderno|lapiz|boligrafo|carpeta|tijera|'
     'pegamento|cinta adhesiva',
     'Papelería', 'Manualidades y Hogar'),
    ('vela|bugia|fosforo|'
     'pilas |pila |bateria|linterna',
     'Pilas y Velas', 'Manualidades y Hogar'),

    # FERRETERÍA
    ('ampolleta|foco led|enchufe|'
     'extension|cable elect',
     'Electricidad', 'Ferretería Básica'),
    ('tornillo|clavo|llave|martillo|'
     'cinta|silicona|pegamento industrial',
     'Ferretería', 'Ferretería Básica'),

    # TABACO
    ('cigarro|cigarrillo|marlboro|'
     'camel|philip morris|winston|'
     'tabaco|encendedor',
     'Cigarrillos', 'Tabaco'),

    # CONGELADOS
    ('congelado|pizza prepar|'
     'papas congeladas|nuggets',
     'Congelados', 'Alimentación'),
]


def normalizar(texto: str) -> str:
    texto = texto.lower()
    texto = unicodedata.normalize('NFD', texto)
    return ''.join(c for c in texto if unicodedata.category(c) != 'Mn')


def clasificar_producto(nombre: str) -> tuple[str, str]:
    """Devuelve (categoria, departamento) para el nombre dado."""
    nombre_norm = normalizar(nombre)
    for patron, categoria, departamento in REGLAS:
        if re.search(patron, nombre_norm):
            return categoria, departamento
    return 'Sin categoría', 'Otros'


def obtener_o_crear_categoria(conn, nombre_cat: str, departamento: str) -> int:
    row = conn.execute(
        "SELECT id FROM categorias WHERE nombre=?", (nombre_cat,)
    ).fetchone()
    if row:
        return row[0] if isinstance(row, tuple) else row["id"]
    cur = conn.execute(
        "INSERT INTO categorias (nombre, departamento, icono) VALUES (?,?,?)",
        (nombre_cat, departamento, '📦')
    )
    return cur.lastrowid


if __name__ == '__main__':
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    productos = conn.execute(
        "SELECT id, nombre, categoria_id FROM productos WHERE activo=1"
    ).fetchall()

    clasificados = 0
    sin_categoria = 0
    por_categoria: dict = {}

    for prod in productos:
        cat_nombre, depto = clasificar_producto(prod['nombre'])
        cat_id = obtener_o_crear_categoria(conn, cat_nombre, depto)
        conn.execute(
            "UPDATE productos SET categoria_id=?, pendiente_verificar=? WHERE id=?",
            (cat_id, 0 if cat_nombre != 'Sin categoría' else 1, prod['id'])
        )
        if cat_nombre == 'Sin categoría':
            sin_categoria += 1
            print(f"  ⚠️  Sin clasificar: {prod['nombre']}")
        else:
            clasificados += 1
            por_categoria[cat_nombre] = por_categoria.get(cat_nombre, 0) + 1

    conn.commit()
    conn.close()

    print(f"\n✅ Clasificados: {clasificados}")
    print(f"⚠️  Sin clasificar: {sin_categoria}")
    print("\nPor categoría:")
    for cat, n in sorted(por_categoria.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {n}")
