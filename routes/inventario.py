import logging
from pathlib import Path
from flask import Blueprint, request, jsonify, session
from database import db_session, registrar_movimiento_stock, actualizar_proveedor_producto

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
                    registrar_movimiento_stock(
                        conn, producto_id, None, "entrada", cantidad,
                        "compra", uid, compra_id=compra_id)
                    conn.execute(
                        "UPDATE productos SET precio_costo=? WHERE id=?",
                        (precio_unit, producto_id))
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
                    try:
                        conn.execute(
                            """INSERT INTO stock_movimientos
                               (producto_id, tipo, cantidad, motivo, usuario_id,
                                stock_antes, stock_despues, compra_id)
                               VALUES (?,?,?,?,?,0,?,?)""",
                            (producto_id, "entrada", cantidad, "compra_nueva", uid,
                             cantidad, compra_id))
                    except Exception:
                        pass
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
                try:
                    conn.execute(
                        """INSERT INTO stock_movimientos
                           (producto_id, tipo, cantidad, motivo, usuario_id,
                            stock_antes, stock_despues, compra_id)
                           VALUES (?,?,?,?,?,0,?,?)""",
                        (producto_id, "entrada", cantidad, "compra_nueva", uid,
                         cantidad, compra_id))
                except Exception:
                    pass
                sin_precio.append(nombre)
                creados += 1

            conn.execute(
                """INSERT INTO compra_items
                   (compra_id, producto_id, nombre_original, cantidad, precio_unitario, subtotal)
                   VALUES (?,?,?,?,?,?)""",
                (compra_id, producto_id, nombre, cantidad, precio_unit, subtotal)
            )

            if proveedor_id and producto_id and precio_unit:
                actualizar_proveedor_producto(conn, proveedor_id, producto_id,
                                              precio_unit, fecha)

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


def _guardar_imagen(imagen_bytes: bytes) -> str | None:
    """Wrapper sin código de barras — genera ID temporal por timestamp."""
    import time as _t
    try:
        url = _guardar_imagen_producto(f"tmp_{int(_t.time() * 1000)}", imagen_bytes)
        logger.info(f"Imagen guardada: {url}")
        return url
    except Exception as e:
        logger.warning(f"_guardar_imagen falló: {e}")
        return None


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
            logger.info(f"OFF: código {codigo_barras} no encontrado en la base de datos")
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
            logger.info(f"OFF: código {codigo_barras} existe pero sin nombre")
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

        # Descargar imagen de OFF y guardarla localmente
        imagen_url_off = None
        img_url = p.get("image_front_small_url") or p.get("image_front_url")
        if img_url:
            try:
                import urllib.request as _ur2
                req2 = _ur2.Request(img_url, headers={"User-Agent": "ZERO-POS/1.0"})
                with _ur2.urlopen(req2, timeout=5) as resp2:
                    img_bytes = resp2.read()
                imagen_url_off = _guardar_imagen(img_bytes)
                logger.info(f"Imagen OFF descargada: {imagen_url_off}")
            except Exception as e:
                logger.info(f"OFF: imagen no descargada ({e})")

        logger.info(f"OFF: nombre encontrado → '{nombre}' marca={marca} cat={categoria}")
        return {
            "nombre": nombre,
            "marca": marca,
            "contenido": contenido,
            "categoria_sugerida": categoria if categoria != "Sin categoría" else None,
            "departamento": departamento if departamento != "Otros" else "Alimentación",
            "imagen_url_off": imagen_url_off,
            "fuente": "open_food_facts",
        }
    except Exception as e:
        logger.info(f"OFF: sin resultado — {type(e).__name__}: {e}")
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
    """Identifica un producto por foto (pyzbar → OFF) o OCR como fallback."""
    uid = _auth()
    if not uid:
        return jsonify({"error": "No autenticado"}), 401

    archivo = request.files.get("imagen") or next(
        iter(request.files.getlist("imagenes")), None
    )
    codigo_manual = request.form.get("codigo_barras", "").strip() or None

    solo_off = request.form.get("solo_off") == "1"
    imagen_bytes = archivo.read() if archivo else None
    imagen_url = None

    # PASO 1: Guardar imagen optimizada
    if imagen_bytes:
        imagen_url = _guardar_imagen(imagen_bytes)
        if imagen_url:
            logger.info(f"leer_producto: foto guardada → {imagen_url}")

    # PASO 2: Detectar código en la foto con pyzbar
    codigo = codigo_manual
    if not codigo and imagen_bytes:
        try:
            from PIL import Image as _PILpz, ImageOps as _IOSpz
            from pyzbar import pyzbar as _pyzbar
            import io as _iopz
            img = _PILpz.open(_iopz.BytesIO(imagen_bytes))
            img = _IOSpz.exif_transpose(img)
            codigos = _pyzbar.decode(img)
            if codigos:
                codigo = codigos[0].data.decode("utf-8")
                logger.info(f"Código detectado en foto: {codigo}")
        except Exception as e:
            logger.debug(f"pyzbar en foto: {e}")

    # PASO 3: Buscar en Open Food Facts (antes de OCR)
    if codigo:
        logger.info(f"leer_producto: consultando OFF para código {codigo}")
        datos_off = _buscar_open_food_facts(codigo)
        if datos_off:
            logger.info(f"OFF encontró: {datos_off['nombre']}")
            return jsonify({
                "ok": True,
                "codigo_detectado": codigo,
                "producto": datos_off,
                "imagen_url": imagen_url,
                "fuente": "open_food_facts",
            })

    # Si solo_off=1, no intentar OCR
    if solo_off:
        return jsonify({"ok": False, "codigo_detectado": codigo, "imagen_url": imagen_url})

    # PASO 4: OCR como fallback
    if imagen_bytes:
        resultado_ocr = _leer_etiqueta_ocr(imagen_bytes)
        if resultado_ocr:
            sugerencias = None
            if not codigo and resultado_ocr.get("nombre"):
                sugerencias = _buscar_off_por_texto(resultado_ocr["nombre"])
                if sugerencias:
                    logger.info(f"leer_producto: {len(sugerencias)} sugerencias OFF por texto")
            return jsonify({
                "ok": True,
                "codigo_detectado": codigo,
                "producto": resultado_ocr,
                "imagen_url": imagen_url,
                "fuente": "ocr_local",
                "sugerencias": sugerencias,
            })

    logger.info("leer_producto: sin resultado")
    return jsonify({
        "ok": False,
        "codigo_detectado": codigo,
        "imagen_url": imagen_url,
    })


# Alias para compatibilidad con versiones anteriores del frontend
@inventario_bp.route("/leer-producto-ia", methods=["POST"])
def leer_producto_ia():
    return leer_producto()


# ── Control de Lotes ──────────────────────────────────────────────────────────

def _generar_qr_lote(lote_id: int, producto_id: int, vencimiento: str | None):
    """Genera imagen PIL con el QR del lote."""
    import qrcode, json as _json
    datos = _json.dumps({"t": "L", "l": lote_id, "p": producto_id, "v": vencimiento or ""},
                        separators=(',', ':'))
    qr = qrcode.QRCode(version=1, error_correction=qrcode.ERROR_CORRECT_M, box_size=4, border=1)
    qr.add_data(datos)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white")


def _generar_pdf_etiquetas(lote: dict, producto: dict, cantidad: int):
    """Genera PDF con etiquetas 30×20 mm listas para imprimir."""
    import io
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader

    ANCHO, ALTO = 30 * mm, 20 * mm
    PAG_W, PAG_H = 210 * mm, 297 * mm
    COLS = int(PAG_W / ANCHO)

    buffer = io.BytesIO()
    c = rl_canvas.Canvas(buffer, pagesize=(PAG_W, PAG_H))
    c.setTitle(f"Etiquetas Lote L-{lote['id']:03d}")

    qr_img = _generar_qr_lote(lote["id"], lote["producto_id"], lote.get("fecha_vencimiento"))
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, "PNG")

    col, fila = 0, 0
    for i in range(cantidad):
        x = col * ANCHO
        y = PAG_H - (fila + 1) * ALTO

        qr_buf.seek(0)
        c.drawImage(ImageReader(qr_buf), x + 1 * mm, y + 1 * mm, width=12 * mm, height=12 * mm)

        nombre = (producto.get("nombre") or "")[:15]
        c.setFont("Helvetica-Bold", 5)
        c.drawString(x + 14 * mm, y + 14 * mm, nombre)

        c.setFont("Helvetica", 4)
        if lote.get("fecha_vencimiento"):
            c.drawString(x + 14 * mm, y + 9 * mm, f"Vence: {lote['fecha_vencimiento']}")
        c.drawString(x + 14 * mm, y + 5 * mm, f"Lote: L-{lote['id']:03d}")

        # Marco sutil
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.rect(x, y, ANCHO, ALTO)

        col += 1
        if col >= COLS:
            col = 0
            fila += 1
            if fila * ALTO >= PAG_H:
                c.showPage()
                fila = 0

    c.save()
    buffer.seek(0)
    return buffer


@inventario_bp.route("/lotes", methods=["GET"])
def listar_lotes():
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    producto_id = request.args.get("producto_id")
    with db_session() as conn:
        q = "SELECT * FROM lotes WHERE 1=1"
        p = []
        if producto_id:
            q += " AND producto_id=?"
            p.append(int(producto_id))
        q += " ORDER BY estado='activo' DESC, fecha_vencimiento ASC NULLS LAST"
        rows = conn.execute(q, p).fetchall()
        return jsonify([dict(r) for r in rows])


@inventario_bp.route("/lotes", methods=["POST"])
def crear_lote():
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    producto_id = data.get("producto_id")
    cantidad = int(data.get("cantidad", 0))
    if not producto_id or cantidad <= 0:
        return jsonify({"error": "producto_id y cantidad son requeridos"}), 400

    with db_session() as conn:
        # Verificar producto existe
        prod = conn.execute("SELECT id, nombre FROM productos WHERE id=?", (producto_id,)).fetchone()
        if not prod:
            return jsonify({"error": "Producto no encontrado"}), 404

        # Auto-numerar el lote
        total_lotes = conn.execute(
            "SELECT COUNT(*) FROM lotes WHERE producto_id=?", (producto_id,)
        ).fetchone()[0]
        num = data.get("numero_lote") or f"L-{prod['id']:03d}-{total_lotes + 1:03d}"

        cur = conn.execute(
            """INSERT INTO lotes (producto_id, numero_lote, cantidad_inicial, cantidad_actual,
                                  fecha_vencimiento, notas)
               VALUES (?,?,?,?,?,?)""",
            (producto_id, num, cantidad, cantidad,
             data.get("fecha_vencimiento") or None,
             data.get("notas") or None)
        )
        lote_id = cur.lastrowid

        # Activar control de lotes en el producto si no estaba
        conn.execute("UPDATE productos SET tiene_lotes=1, actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
                     (producto_id,))

        # También sumar al stock del producto
        conn.execute(
            "UPDATE productos SET stock=stock+?, actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
            (cantidad, producto_id)
        )
        registrar_movimiento_stock(conn, producto_id, None, "entrada", cantidad, "lote_nuevo",
                                   _auth(), notas=f"Lote {num}")

    return jsonify({"ok": True, "lote_id": lote_id, "numero_lote": num}), 201


@inventario_bp.route("/lotes/<int:lote_id>", methods=["GET"])
def obtener_lote(lote_id):
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        lote = conn.execute("SELECT * FROM lotes WHERE id=?", (lote_id,)).fetchone()
        if not lote:
            return jsonify({"error": "Lote no encontrado"}), 404
        return jsonify(dict(lote))


@inventario_bp.route("/lotes/<int:lote_id>/etiquetas/pdf", methods=["GET"])
def etiquetas_pdf(lote_id):
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    cantidad = int(request.args.get("cantidad", 1))
    cantidad = max(1, min(cantidad, 500))

    with db_session() as conn:
        lote = conn.execute("SELECT * FROM lotes WHERE id=?", (lote_id,)).fetchone()
        if not lote:
            return jsonify({"error": "Lote no encontrado"}), 404
        prod = conn.execute("SELECT id, nombre FROM productos WHERE id=?",
                            (lote["producto_id"],)).fetchone()

    from flask import send_file
    pdf_buf = _generar_pdf_etiquetas(dict(lote), dict(prod), cantidad)
    filename = f"etiquetas_L{lote_id:03d}.pdf"
    return send_file(pdf_buf, mimetype="application/pdf",
                     as_attachment=True, download_name=filename)


@inventario_bp.route("/mermas", methods=["POST"])
def registrar_merma():
    if not _auth():
        return jsonify({"error": "No autenticado"}), 401
    uid = _auth()
    data = request.get_json(silent=True) or {}
    lote_id    = data.get("lote_id")
    producto_id = data.get("producto_id")
    cantidad   = int(data.get("cantidad", 1))
    motivo     = data.get("motivo", "vencimiento")

    if not producto_id or cantidad <= 0:
        return jsonify({"error": "producto_id y cantidad son requeridos"}), 400

    with db_session() as conn:
        # Descontar del lote si aplica
        if lote_id:
            lote = conn.execute("SELECT * FROM lotes WHERE id=?", (lote_id,)).fetchone()
            if lote:
                nueva_cant = max(0, lote["cantidad_actual"] - cantidad)
                nuevo_estado = "agotado" if nueva_cant == 0 else lote["estado"]
                conn.execute(
                    "UPDATE lotes SET cantidad_actual=?, estado=? WHERE id=?",
                    (nueva_cant, nuevo_estado, lote_id)
                )

        cur = conn.execute(
            "INSERT INTO mermas (lote_id, producto_id, cantidad, motivo, usuario_id, notas) VALUES (?,?,?,?,?,?)",
            (lote_id, producto_id, cantidad, motivo, uid, data.get("notas"))
        )
        # Descontar stock del producto
        registrar_movimiento_stock(conn, producto_id, None, "salida", cantidad, f"merma_{motivo}", uid,
                                   notas=f"Lote {lote_id}" if lote_id else None)

    return jsonify({"ok": True, "merma_id": cur.lastrowid}), 201
