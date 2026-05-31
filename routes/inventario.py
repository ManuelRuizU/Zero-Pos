import logging
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
        import anthropic as _anthropic
    except ImportError:
        return jsonify({"error": "Librería anthropic no instalada. Ejecuta: pip install anthropic"}), 500

    try:
        import base64
        import io
        import json

        data = file.read()
        content_type = (file.content_type or "").lower()

        if "pdf" in content_type:
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(data)) as pdf:
                    if not pdf.pages:
                        return jsonify({"error": "PDF vacío"}), 400
                    img_obj = pdf.pages[0].to_image(resolution=150)
                    buf = io.BytesIO()
                    img_obj.original.save(buf, format="PNG")
                    data = buf.getvalue()
                    media_type = "image/png"
            except Exception as e:
                return jsonify({"error": f"No se pudo convertir PDF: {e}"}), 400
        else:
            media_type = content_type if content_type.startswith("image/") else "image/jpeg"

        b64 = base64.standard_b64encode(data).decode("utf-8")

        PROMPT = (
            "Eres un asistente especializado en leer facturas comerciales chilenas.\n"
            "Extrae la información de la imagen y responde ÚNICAMENTE con un JSON válido con esta estructura:\n\n"
            "{\n"
            '  "proveedor": {\n'
            '    "nombre": "empresa vendedora",\n'
            '    "rut": "RUT formato XX.XXX.XXX-X o null",\n'
            '    "vendedor_nombre": "nombre del vendedor si aparece o null",\n'
            '    "vendedor_telefono": "teléfono de contacto si aparece o null"\n'
            "  },\n"
            '  "folio": "número de factura o null",\n'
            '  "fecha": "YYYY-MM-DD o null",\n'
            '  "total": 12345,\n'
            '  "productos": [\n'
            "    {\n"
            '      "nombre": "descripción del producto",\n'
            '      "codigo_barras": "código EAN/UPC si aparece o null",\n'
            '      "cantidad": 1,\n'
            '      "precio_unitario": 1000,\n'
            '      "subtotal": 1000\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Reglas: total, precio_unitario y subtotal como enteros CLP sin decimales. "
            "Si un campo no aparece en la factura usa null. "
            "Responde SOLO el JSON, sin texto adicional, sin markdown."
        )

        client = _anthropic.Anthropic()
        msg = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64},
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }],
        )

        text = msg.content[0].text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else parts[0]
            if text.startswith("json"):
                text = text[4:]
        datos = json.loads(text.strip())

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

        return jsonify({"ok": True, "datos": datos})

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
