import logging
from pathlib import Path
from flask import Blueprint, request, jsonify, session
from database import db_session

inventario_bp = Blueprint("inventario", __name__, url_prefix="/api/inventario")
logger = logging.getLogger("zero_pos.inventario")


def _auth():
    return session.get("usuario_id")


# ── Proveedores ───────────────────────────────────────────────────────────────

@inventario_bp.route("/proveedores", methods=["GET"])
def listar_proveedores():
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM proveedores WHERE activo=1 ORDER BY nombre"
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@inventario_bp.route("/proveedores", methods=["POST"])
def crear_proveedor():
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    nombre = str(data.get("nombre", "")).strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400
    with db_session() as conn:
        cur = conn.execute(
            """INSERT INTO proveedores (nombre, rut, contacto, telefono, email, direccion, notas)
               VALUES (?,?,?,?,?,?,?)""",
            (nombre, data.get("rut"), data.get("contacto"),
             data.get("telefono"), data.get("email"),
             data.get("direccion"), data.get("notas"))
        )
        return jsonify({"ok": True, "id": cur.lastrowid}), 201


@inventario_bp.route("/proveedores/<int:pid>", methods=["PUT"])
def actualizar_proveedor(pid):
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    campos = {k: v for k, v in data.items()
              if k in ("nombre", "rut", "contacto", "telefono", "email", "direccion", "notas")}
    if not campos:
        return jsonify({"error": "Sin datos"}), 400
    set_clause = ", ".join(f"{k}=?" for k in campos)
    with db_session() as conn:
        conn.execute(f"UPDATE proveedores SET {set_clause} WHERE id=?",
                     list(campos.values()) + [pid])
        return jsonify({"ok": True})


@inventario_bp.route("/proveedores/<int:pid>", methods=["DELETE"])
def eliminar_proveedor(pid):
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    with db_session() as conn:
        conn.execute("UPDATE proveedores SET activo=0 WHERE id=?", (pid,))
        return jsonify({"ok": True})


# ── Órdenes de compra ─────────────────────────────────────────────────────────

@inventario_bp.route("/ordenes", methods=["GET"])
def listar_ordenes():
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute(
            """SELECT o.*, p.nombre as proveedor_nombre
               FROM ordenes_compra o LEFT JOIN proveedores p ON o.proveedor_id=p.id
               ORDER BY o.creado_en DESC LIMIT 100"""
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@inventario_bp.route("/ordenes", methods=["POST"])
def crear_orden():
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    items = data.get("items", [])
    if not items:
        return jsonify({"error": "Sin productos"}), 400

    with db_session() as conn:
        total = sum(float(it.get("precio_unit", 0)) * int(it.get("cantidad", 1))
                    for it in items)
        cur = conn.execute(
            "INSERT INTO ordenes_compra (proveedor_id, usuario_id, total, notas) VALUES (?,?,?,?)",
            (data.get("proveedor_id"), uid, round(total, 2), data.get("notas"))
        )
        oid = cur.lastrowid
        for it in items:
            qty = int(it.get("cantidad", 1))
            pu = float(it.get("precio_unit", 0))
            conn.execute(
                "INSERT INTO orden_items (orden_id, producto_id, cantidad, precio_unit, subtotal) VALUES (?,?,?,?,?)",
                (oid, it["producto_id"], qty, pu, round(qty * pu, 2))
            )
        return jsonify({"ok": True, "id": oid}), 201


@inventario_bp.route("/ordenes/<int:oid>/recibir", methods=["POST"])
def recibir_orden(oid):
    uid = session.get("usuario_id")
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        orden = conn.execute(
            "SELECT * FROM ordenes_compra WHERE id=? AND estado='enviada'", (oid,)
        ).fetchone()
        if not orden:
            return jsonify({"error": "Orden no encontrada o no enviada"}), 404

        items = conn.execute(
            "SELECT * FROM orden_items WHERE orden_id=?", (oid,)
        ).fetchall()
        for it in items:
            conn.execute(
                "UPDATE productos SET stock = stock + ?, actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
                (it["cantidad"], it["producto_id"])
            )
            conn.execute(
                """INSERT INTO stock_movimientos (producto_id, tipo, cantidad, referencia, usuario_id)
                   VALUES (?,?,?,?,?)""",
                (it["producto_id"], "entrada", it["cantidad"], f"OC-{oid}", uid)
            )
        conn.execute(
            "UPDATE ordenes_compra SET estado='recibida', recibido_en=CURRENT_TIMESTAMP WHERE id=?",
            (oid,)
        )
        return jsonify({"ok": True})


# ── Márgenes / análisis ───────────────────────────────────────────────────────

@inventario_bp.route("/margenes", methods=["GET"])
def margenes():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    with db_session() as conn:
        rows = conn.execute(
            """SELECT id, nombre, precio, precio_costo,
                precio - precio_costo as margen_abs,
                CASE WHEN precio > 0
                     THEN ROUND((precio - precio_costo)*100.0/precio, 2)
                     ELSE 0 END as margen_pct
               FROM productos WHERE activo=1
               ORDER BY margen_pct"""
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@inventario_bp.route("/movimientos/<int:producto_id>", methods=["GET"])
def movimientos_producto(producto_id):
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute(
            """SELECT sm.*, u.nombre as usuario_nombre
               FROM stock_movimientos sm
               LEFT JOIN usuarios u ON sm.usuario_id=u.id
               WHERE sm.producto_id=?
               ORDER BY sm.creado_en DESC LIMIT 100""",
            (producto_id,)
        ).fetchall()
        return jsonify([dict(r) for r in rows])


# ── Lector de facturas con Claude Vision ─────────────────────────────────────

@inventario_bp.route("/leer-factura", methods=["POST"])
def leer_factura():
    uid = _auth()
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    file = request.files.get("factura")
    if not file:
        return jsonify({"error": "Archivo requerido"}), 400

    try:
        from utils.lector_facturas import procesar_factura

        data = file.read()
        content_type = (file.content_type or "").lower()

        resultado = procesar_factura(data, content_type)
        if not resultado["ok"]:
            return jsonify(resultado), 400

        datos = resultado["datos"]

        with db_session() as conn:
            for prod in datos.get("productos", []):
                barras = (prod.get("codigo_barras") or "").strip()
                if barras:
                    row = conn.execute(
                        "SELECT id FROM productos WHERE codigo_barras=? AND activo=1", (barras,)
                    ).fetchone()
                    prod["existe"] = bool(row)
                    prod["producto_id"] = row["id"] if row else None
                else:
                    prod["existe"] = False
                    prod["producto_id"] = None

        return jsonify({"ok": True, "datos": datos, "fuente": datos.get("_fuente", "")})

    except Exception as e:
        logger.error(f"leer_factura: {e}")
        return jsonify({"error": str(e)}), 500


@inventario_bp.route("/importar-factura", methods=["POST"])
def importar_factura():
    uid = _auth()
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    prov_data = data.get("proveedor", {})
    productos = data.get("productos", [])
    folio = data.get("folio")
    fecha = data.get("fecha")
    total = int(data.get("total") or 0)

    if not productos:
        return jsonify({"error": "Sin productos"}), 400

    with db_session() as conn:
        # Upsert proveedor
        proveedor_id = None
        rut = (prov_data.get("rut") or "").strip()
        nombre_prov = (prov_data.get("nombre") or "").strip()

        if rut:
            row = conn.execute("SELECT id FROM proveedores WHERE rut=?", (rut,)).fetchone()
            if row:
                proveedor_id = row["id"]
                if nombre_prov:
                    conn.execute("UPDATE proveedores SET nombre=?, activo=1 WHERE id=?",
                                 (nombre_prov, proveedor_id))
            else:
                cur = conn.execute(
                    "INSERT INTO proveedores (nombre, rut, contacto, telefono) VALUES (?,?,?,?)",
                    (nombre_prov or "Sin nombre", rut,
                     prov_data.get("vendedor_nombre"), prov_data.get("vendedor_telefono"))
                )
                proveedor_id = cur.lastrowid
        elif nombre_prov:
            row = conn.execute("SELECT id FROM proveedores WHERE nombre=?", (nombre_prov,)).fetchone()
            if row:
                proveedor_id = row["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO proveedores (nombre, rut, contacto, telefono) VALUES (?,?,?,?)",
                    (nombre_prov, None,
                     prov_data.get("vendedor_nombre"), prov_data.get("vendedor_telefono"))
                )
                proveedor_id = cur.lastrowid

        cur = conn.execute(
            "INSERT INTO compras (proveedor_id, folio, fecha, total, usuario_id) VALUES (?,?,?,?,?)",
            (proveedor_id, folio, fecha, total, uid)
        )
        compra_id = cur.lastrowid

        creados = 0
        actualizados = 0
        sin_precio = []

        for prod in productos:
            nombre = (prod.get("nombre") or "").strip()
            barras = (prod.get("codigo_barras") or "").strip() or None
            cantidad = int(prod.get("cantidad") or 1)
            precio_unit = int(prod.get("precio_unitario") or 0)
            subtotal = int(prod.get("subtotal") or cantidad * precio_unit)

            producto_id = None

            if barras:
                row = conn.execute(
                    "SELECT id, precio FROM productos WHERE codigo_barras=?", (barras,)
                ).fetchone()
                if row:
                    producto_id = row["id"]
                    conn.execute(
                        "UPDATE productos SET precio_costo=?, stock=stock+?, actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
                        (precio_unit, cantidad, producto_id)
                    )
                    actualizados += 1
                    if not row["precio"]:
                        sin_precio.append(nombre)
                else:
                    cur2 = conn.execute(
                        """INSERT INTO productos
                           (nombre, codigo_barras, precio_costo, precio, stock, activo, pendiente_verificar, modo_stock)
                           VALUES (?,?,?,0,?,0,1,'normal')""",
                        (nombre, barras, precio_unit, cantidad)
                    )
                    producto_id = cur2.lastrowid
                    sin_precio.append(nombre)
                    creados += 1
            else:
                cur2 = conn.execute(
                    """INSERT INTO productos
                       (nombre, precio_costo, precio, stock, activo, pendiente_verificar, modo_stock)
                       VALUES (?,?,0,?,0,1,'normal')""",
                    (nombre, precio_unit, cantidad)
                )
                producto_id = cur2.lastrowid
                sin_precio.append(nombre)
                creados += 1

            conn.execute(
                """INSERT INTO compra_items
                   (compra_id, producto_id, nombre_original, cantidad, precio_unitario, subtotal)
                   VALUES (?,?,?,?,?,?)""",
                (compra_id, producto_id, nombre, cantidad, precio_unit, subtotal)
            )

        return jsonify({
            "ok": True,
            "compra_id": compra_id,
            "creados": creados,
            "actualizados": actualizados,
            "sin_precio": sin_precio,
        })


def _corregir_orientacion(img):
    """Aplica la orientación EXIF. Los móviles guardan la rotación en metadatos."""
    try:
        from PIL import ImageOps
        return ImageOps.exif_transpose(img)
    except Exception:
        return img


def _guardar_imagen_producto(codigo_barras: str, imagen_bytes: bytes) -> str:
    """Optimiza y guarda la foto del producto. Retorna la URL relativa."""
    import os
    from PIL import Image as _PIL
    import io as _io

    BASE_DIR = Path(__file__).parent.parent
    directorio = os.path.join(BASE_DIR, "static", "productos_img")
    os.makedirs(directorio, exist_ok=True)

    img = _PIL.open(_io.BytesIO(imagen_bytes))
    img = _corregir_orientacion(img)
    img = img.convert("RGB")
    w, h = img.size
    lado = min(w, h)
    x, y = (w - lado) // 2, (h - lado) // 2
    img = img.crop((x, y, x + lado, y + lado)).resize((400, 400), _PIL.LANCZOS)

    nombre = f"{codigo_barras}.jpg"
    img.save(os.path.join(directorio, nombre), "JPEG", quality=85)
    return f"/static/productos_img/{nombre}"


def _buscar_open_food_facts(codigo_barras: str) -> dict | None:
    """Capa 1: consulta Open Food Facts. Requiere internet. Sin API key."""
    try:
        import urllib.request as _urllib
        import json as _json

        url = f"https://world.openfoodfacts.org/api/v0/product/{codigo_barras}.json"
        req = _urllib.Request(url, headers={"User-Agent": "ZERO-POS/1.0"})
        with _urllib.urlopen(req, timeout=3) as resp:
            data = _json.loads(resp.read())

        if data.get("status") != 1:
            return None
        p = data.get("product", {})

        nombre = (
            p.get("product_name_es")
            or p.get("product_name")
            or p.get("generic_name_es")
            or p.get("generic_name")
            or ""
        ).strip()
        if not nombre:
            return None

        marca = (p.get("brands") or "").split(",")[0].strip() or None
        contenido = (p.get("quantity") or "").strip() or None

        # Clasificar usando nombre + tags de OFF
        cats_str = " ".join(
            tag.split(":", 1)[-1].replace("-", " ")
            for tag in p.get("categories_tags", [])
        )
        try:
            from scripts.clasificar_productos import clasificar_producto
            categoria, departamento = clasificar_producto(nombre + " " + cats_str)
        except Exception:
            categoria, departamento = "Sin categoría", "Alimentación"

        logger.info(f"OFF: '{nombre}' marca={marca} cat={categoria}")
        return {
            "nombre": nombre,
            "marca": marca,
            "contenido": contenido,
            "categoria_sugerida": categoria if categoria != "Sin categoría" else None,
            "departamento": departamento if departamento != "Otros" else "Alimentación",
            "imagen_url_externa": p.get("image_front_url") or None,
            "fuente": "open_food_facts",
        }
    except Exception as e:
        logger.debug(f"OFF no disponible: {e}")
        return None


def _leer_etiqueta_ocr(imagen_bytes: bytes) -> dict | None:
    """Capa 2: OCR local con Tesseract. Prueba 4 rotaciones, elige la mejor."""
    try:
        import pytesseract
        from PIL import Image as _PIL, ImageEnhance, ImageFilter
        import io as _io
        import re

        img = _PIL.open(_io.BytesIO(imagen_bytes))
        img = _corregir_orientacion(img)
        if img.mode != "RGB":
            img = img.convert("RGB")

        def _preprocesar(imagen):
            gris = imagen.convert("L")
            gris = ImageEnhance.Contrast(gris).enhance(2.0)
            gris = gris.filter(ImageFilter.SHARPEN)
            w, h = gris.size
            if w < 800:
                gris = gris.resize((w * 2, h * 2), _PIL.LANCZOS)
            return gris

        def _extraer(img_proc):
            try:
                return pytesseract.image_to_string(
                    img_proc, lang="spa", config="--oem 3 --psm 3"
                )
            except Exception:
                try:
                    return pytesseract.image_to_string(img_proc, config="--oem 3 --psm 3")
                except Exception:
                    return ""

        def _puntaje(texto):
            return sum(
                1 for p in texto.split()
                if len(p) >= 3 and sum(1 for c in p if c.isalpha()) >= 2
            )

        # Probar las 4 rotaciones y quedarse con la que produce más texto legible
        mejor_texto, mejor_puntaje = "", 0
        for angulo in (0, 90, 180, 270):
            rotada = img if angulo == 0 else img.rotate(angulo, expand=True)
            texto = _extraer(_preprocesar(rotada))
            pts   = _puntaje(texto)
            logger.info(f"OCR {angulo}°: puntaje={pts} '{texto[:80].strip()!r}'")
            if pts > mejor_puntaje:
                mejor_puntaje, mejor_texto = pts, texto

        if mejor_puntaje < 2:
            logger.warning("OCR: no encontró texto legible en ninguna rotación")
            return None

        lineas = [
            l.strip() for l in mejor_texto.split("\n")
            if len(l.strip()) >= 3 and sum(1 for c in l if c.isalpha()) >= 2
        ]
        if not lineas:
            return None

        # Las primeras 5 líneas suelen contener el nombre del producto.
        # Dentro de ellas, la más corta evita capturar texto legal largo.
        primeras = lineas[:5]
        nombre = min(primeras, key=lambda l: len(l))[:60]

        # Buscar peso/volumen
        _pat = re.compile(
            r"(\d+[\.,]?\d*)\s*(ml|ML|cl|CL|L|lt|g|gr|GR|Gr|kg|KG|Kg|cc|CC|oz)",
            re.IGNORECASE,
        )
        texto_completo = " ".join(lineas)
        m = _pat.search(texto_completo)
        contenido = m.group(0).strip() if m else None

        # Clasificar con reglas de palabras clave
        try:
            from scripts.clasificar_productos import clasificar_producto
            categoria, departamento = clasificar_producto(nombre or texto_completo)
        except Exception:
            categoria, departamento = "Sin categoría", "Otros"

        logger.info(f"OCR OK: nombre='{nombre}' contenido={contenido} cat={categoria}")
        return {
            "nombre": nombre,
            "marca": None,
            "contenido": contenido,
            "categoria_sugerida": categoria if categoria != "Sin categoría" else None,
            "departamento": departamento if departamento != "Otros" else "Alimentación",
            "fuente": "ocr_local",
        }
    except Exception as e:
        import traceback as _tb
        logger.error(f"OCR error: {e}")
        logger.error(_tb.format_exc())
        return None


def _buscar_off_por_texto(texto: str) -> list | None:
    """Busca en OFF por nombre cuando no hay código de barras."""
    try:
        import urllib.request as _urllib
        import urllib.parse as _parse
        import json as _json

        query = _parse.quote(texto.strip())
        url = (
            f"https://world.openfoodfacts.org/cgi/search.pl"
            f"?search_terms={query}&search_simple=1&action=process"
            f"&json=1&page_size=5"
            f"&tagtype_0=countries&tag_contains_0=contains&tag_0=chile"
        )
        req = _urllib.Request(url, headers={"User-Agent": "ZERO-POS/1.0"})
        with _urllib.urlopen(req, timeout=3) as resp:
            data = _json.loads(resp.read())

        productos = []
        for p in data.get("products", [])[:3]:
            nombre = (
                p.get("product_name_es") or p.get("product_name") or ""
            ).strip()
            if not nombre:
                continue
            productos.append({
                "nombre": nombre,
                "marca": (p.get("brands") or "").split(",")[0].strip() or None,
                "codigo_barras": p.get("code") or None,
                "contenido": (p.get("quantity") or "").strip() or None,
            })

        return productos if productos else None
    except Exception as e:
        logger.debug(f"OFF texto: {e}")
        return None


@inventario_bp.route("/leer-producto", methods=["POST"])
def leer_producto():
    """Identifica un producto por código de barras (OFF) o foto (OCR).
    Sin API key. Funciona offline con la capa OCR."""
    uid = _auth()
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    codigo_barras = request.form.get("codigo_barras", "").strip()
    files = request.files.getlist("imagenes")
    single = request.files.get("imagen")
    if not files and single:
        files = [single]

    img_bytes = files[0].read() if files else None

    producto = None

    # Capa 1: Open Food Facts (requiere barcode + internet)
    if codigo_barras:
        logger.info(f"leer_producto: buscando OFF código={codigo_barras}")
        producto = _buscar_open_food_facts(codigo_barras)
        if producto:
            producto["codigo_barras"] = codigo_barras

    # Capa 2: OCR local (requiere imagen, funciona offline)
    if not producto and img_bytes:
        logger.info("leer_producto: OCR local")
        producto = _leer_etiqueta_ocr(img_bytes)
        if producto and codigo_barras:
            producto["codigo_barras"] = codigo_barras

    # Guardar imagen optimizada si la recibimos
    if img_bytes:
        import time as _time
        img_id = codigo_barras if codigo_barras else f"tmp_{int(_time.time())}"
        try:
            imagen_url = _guardar_imagen_producto(img_id, img_bytes)
            if producto:
                producto["imagen_url"] = imagen_url
                producto["imagen_id"]  = img_id
        except Exception as img_err:
            logger.warning(f"leer_producto: guardar_imagen: {img_err}")

    if not producto:
        logger.info("leer_producto: sin resultado")
        return jsonify({"ok": False})

    fuente = producto.get("fuente", "")
    logger.info(f"leer_producto: OK nombre='{producto.get('nombre')}' fuente={fuente}")

    # Capa 2.5: si OCR encontró nombre pero sin barcode, sugerir productos similares de OFF
    sugerencias = None
    if fuente == "ocr_local" and not codigo_barras and producto.get("nombre"):
        sugerencias = _buscar_off_por_texto(producto["nombre"])
        if sugerencias:
            logger.info(f"leer_producto: {len(sugerencias)} sugerencias OFF por texto")

    return jsonify({"ok": True, "producto": producto, "fuente": fuente, "sugerencias": sugerencias})


# Alias para compatibilidad con versiones anteriores del frontend
@inventario_bp.route("/leer-producto-ia", methods=["POST"])
def leer_producto_ia():
    return leer_producto()
