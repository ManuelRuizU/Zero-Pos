import secrets
import logging
from datetime import date, timedelta
from flask import Blueprint, request, jsonify, session
from database import db_session

fiado_bp = Blueprint("fiado", __name__, url_prefix="/api/fiado")
logger = logging.getLogger("zero_pos.fiado")


def generar_qr_token() -> str:
    return secrets.token_urlsafe(16)


def calcular_proximo_vencimiento(frecuencia, fecha_fija=None, dia_pago=None):
    hoy = date.today()
    if dia_pago:
        import calendar
        dia = int(dia_pago)
        try:
            venc = hoy.replace(day=dia)
            if venc <= hoy:
                if hoy.month == 12:
                    venc = venc.replace(year=hoy.year + 1, month=1)
                else:
                    venc = venc.replace(month=hoy.month + 1)
            return venc
        except ValueError:
            ultimo = calendar.monthrange(hoy.year, hoy.month)[1]
            return hoy.replace(day=ultimo)
    if frecuencia == 'semanal':
        return hoy + timedelta(days=7)
    elif frecuencia == 'quincenal':
        return hoy + timedelta(days=15)
    elif frecuencia == 'fecha_fija' and fecha_fija:
        if isinstance(fecha_fija, str):
            from datetime import datetime
            return datetime.strptime(fecha_fija[:10], '%Y-%m-%d').date()
        return fecha_fija
    return hoy + timedelta(days=30)  # mensual default


def generar_qr_base64(contenido: str):
    try:
        import qrcode, io, base64
        qr = qrcode.QRCode(version=1, error_correction=qrcode.ERROR_CORRECT_M, box_size=6, border=2)
        qr.add_data(contenido)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _estado_cliente(c) -> dict:
    if not isinstance(c, dict):
        c = dict(c)
    hoy = date.today()
    deuda = c.get('deuda_actual', 0) or 0
    limite = c.get('limite_credito', 10000) or 10000
    disponible = max(0, limite - deuda)
    pct = min(int((deuda / limite) * 100), 100) if limite > 0 else 0

    dias_restantes = None
    estado = 'al_dia'
    venc_str = c.get('proximo_vencimiento')
    if venc_str and deuda > 0:
        try:
            venc = date.fromisoformat(str(venc_str)[:10])
            dias_restantes = (venc - hoy).days
            if dias_restantes < 0:
                estado = 'vencido'
            elif dias_restantes <= 7:
                estado = 'por_vencer'
        except ValueError:
            pass

    return {
        'disponible': disponible,
        'pct_usado': pct,
        'dias_restantes': dias_restantes,
        'puede_comprar': estado != 'vencido' and disponible > 0,
        'estado': estado,
    }


def _get_ip_local():
    try:
        with db_session() as conn:
            row = conn.execute("SELECT valor FROM config WHERE clave='ip_local'").fetchone()
        if row and row['valor'] and row['valor'] not in ('127.0.0.1', 'localhost'):
            return row['valor']
    except Exception:
        pass
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '192.168.1.1'


@fiado_bp.route("/clientes", methods=["POST"])
def crear_cliente():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    nombre = (data.get('nombre') or '').strip()
    if not nombre:
        return jsonify({"error": "Nombre requerido"}), 400

    dia_pago = data.get('dia_pago')
    if dia_pago:
        dia_pago = int(dia_pago)
    frecuencia_raw = data.get('frecuencia_pago', 'mensual')
    # Normalizar 'dia_fijo' → 'mensual' para respetar la constraint de la DB
    frecuencia = 'mensual' if frecuencia_raw == 'dia_fijo' else frecuencia_raw
    fecha_fija = data.get('fecha_pago_fija')
    proximo = calcular_proximo_vencimiento(frecuencia, fecha_fija, dia_pago)
    qr_token = generar_qr_token()

    with db_session() as conn:
        cur = conn.execute("""
            INSERT INTO clientes_fiado
              (nombre, apellido, telefono, email, rut, direccion,
               limite_credito, frecuencia_pago, fecha_pago_fija,
               proximo_vencimiento, qr_token, notas, dia_pago)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (nombre, data.get('apellido'), data.get('telefono'), data.get('email'),
              data.get('rut'), data.get('direccion'),
              int(data.get('limite_credito', 10000)),
              frecuencia, fecha_fija, proximo.isoformat(), qr_token, data.get('notas'),
              dia_pago))
        cliente_id = cur.lastrowid
        cliente = dict(conn.execute("SELECT * FROM clientes_fiado WHERE id=?", (cliente_id,)).fetchone())

    ip = _get_ip_local()
    url_portal = f"http://{ip}:5000/credit/{qr_token}"
    qr_img = generar_qr_base64(url_portal)
    logger.info(f"Cliente fiado creado: {nombre} (id={cliente_id})")
    return jsonify({**cliente, 'qr_imagen': qr_img, 'url_portal': url_portal}), 201


@fiado_bp.route("/clientes", methods=["GET"])
def listar_clientes():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    q = request.args.get('q', '').strip()
    estado_filtro = request.args.get('estado')

    with db_session() as conn:
        sql = "SELECT * FROM clientes_fiado WHERE activo=1"
        params = []
        if q:
            sql += " AND (nombre LIKE ? OR apellido LIKE ? OR telefono LIKE ?)"
            pat = f"%{q}%"
            params = [pat, pat, pat]
        sql += " ORDER BY nombre"
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    result = []
    for r in rows:
        info = _estado_cliente(r)
        if estado_filtro and info['estado'] != estado_filtro:
            continue
        result.append({**r, **info})
    return jsonify(result)


@fiado_bp.route("/clientes/<int:cid>", methods=["GET"])
def obtener_cliente(cid):
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        c = conn.execute("SELECT * FROM clientes_fiado WHERE id=?", (cid,)).fetchone()
        if not c:
            return jsonify({"error": "No encontrado"}), 404
        c = dict(c)
        movs = [dict(m) for m in conn.execute(
            "SELECT * FROM fiado_movimientos WHERE cliente_id=? ORDER BY creado_en DESC LIMIT 20",
            (cid,)
        ).fetchall()]
    return jsonify({**c, **_estado_cliente(c), 'movimientos': movs})


@fiado_bp.route("/token/<qr_token>", methods=["GET"])
def buscar_por_token(qr_token):
    with db_session() as conn:
        c = conn.execute(
            "SELECT * FROM clientes_fiado WHERE qr_token=? AND activo=1", (qr_token,)
        ).fetchone()
    if not c:
        return jsonify({"error": "No encontrado"}), 404
    cliente = dict(c)
    info = _estado_cliente(cliente)
    return jsonify({'id': cliente['id'], 'nombre': cliente['nombre'],
                    'apellido': cliente.get('apellido'), 'deuda_actual': cliente['deuda_actual'],
                    'limite_credito': cliente['limite_credito'], **info})


@fiado_bp.route("/buscar", methods=["GET"])
def buscar_cliente():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    pat = f"%{q}%"
    with db_session() as conn:
        rows = conn.execute("""
            SELECT id, nombre, apellido, telefono, deuda_actual, limite_credito,
                   proximo_vencimiento, qr_token
            FROM clientes_fiado WHERE activo=1 AND (nombre LIKE ? OR apellido LIKE ? OR telefono LIKE ?)
            ORDER BY nombre LIMIT 10
        """, (pat, pat, pat)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        result.append({**d, **_estado_cliente(d)})
    return jsonify(result)


@fiado_bp.route("/cargo", methods=["POST"])
def registrar_cargo():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    cliente_id = data.get('cliente_id')
    monto = int(data.get('monto', 0))
    venta_id = data.get('venta_id')
    usuario_id = session.get('usuario_id')
    if not cliente_id or monto <= 0:
        return jsonify({"error": "cliente_id y monto requeridos"}), 400

    with db_session() as conn:
        c = conn.execute("SELECT * FROM clientes_fiado WHERE id=? AND activo=1", (cliente_id,)).fetchone()
        if not c:
            return jsonify({"error": "Cliente no encontrado"}), 404
        c = dict(c)
        deuda_antes = c['deuda_actual']
        deuda_despues = deuda_antes + monto
        if deuda_despues > c['limite_credito']:
            disponible = c['limite_credito'] - deuda_antes
            return jsonify({"error": "limite_superado",
                            "mensaje": f"Solo puede fiarse ${disponible:,} más",
                            "disponible": max(0, disponible),
                            "deuda_actual": deuda_antes,
                            "limite": c['limite_credito']}), 400

        proximo = None
        if deuda_antes == 0:
            proximo = calcular_proximo_vencimiento(c['frecuencia_pago'], c['fecha_pago_fija'], c.get('dia_pago'))

        if proximo:
            conn.execute(
                "UPDATE clientes_fiado SET deuda_actual=?, total_compras=total_compras+?, "
                "proximo_vencimiento=?, actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
                (deuda_despues, monto, proximo.isoformat(), cliente_id))
        else:
            conn.execute(
                "UPDATE clientes_fiado SET deuda_actual=?, total_compras=total_compras+?, "
                "actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
                (deuda_despues, monto, cliente_id))
        conn.execute("""
            INSERT INTO fiado_movimientos (cliente_id, venta_id, tipo, monto, deuda_antes, deuda_despues, usuario_id)
            VALUES (?,?,?,?,?,?,?)
        """, (cliente_id, venta_id, 'cargo', monto, deuda_antes, deuda_despues, usuario_id))

    logger.info(f"Cargo fiado: cliente={cliente_id} monto={monto} nueva_deuda={deuda_despues}")
    return jsonify({"ok": True, "deuda_anterior": deuda_antes, "deuda_nueva": deuda_despues})


@fiado_bp.route("/abono", methods=["POST"])
def registrar_abono():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    data = request.get_json(silent=True) or {}
    cliente_id = data.get('cliente_id')
    monto = int(data.get('monto', 0))
    descripcion = data.get('descripcion', 'Abono en tienda')
    usuario_id = session.get('usuario_id')
    if not cliente_id or monto <= 0:
        return jsonify({"error": "cliente_id y monto requeridos"}), 400

    with db_session() as conn:
        c = conn.execute("SELECT * FROM clientes_fiado WHERE id=? AND activo=1", (cliente_id,)).fetchone()
        if not c:
            return jsonify({"error": "Cliente no encontrado"}), 404
        c = dict(c)
        deuda_antes = c['deuda_actual']
        if monto > deuda_antes:
            return jsonify({"error": f"No puede abonar más de la deuda actual (${deuda_antes:,})"}), 400
        deuda_despues = deuda_antes - monto
        proximo = None
        if deuda_despues == 0:
            proximo = calcular_proximo_vencimiento(c['frecuencia_pago'], c['fecha_pago_fija'], c.get('dia_pago'))

        if proximo:
            conn.execute(
                "UPDATE clientes_fiado SET deuda_actual=?, total_abonos=total_abonos+?, "
                "proximo_vencimiento=?, actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
                (deuda_despues, monto, proximo.isoformat(), cliente_id))
        else:
            conn.execute(
                "UPDATE clientes_fiado SET deuda_actual=?, total_abonos=total_abonos+?, "
                "actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
                (deuda_despues, monto, cliente_id))
        conn.execute("""
            INSERT INTO fiado_movimientos (cliente_id, tipo, monto, deuda_antes, deuda_despues, descripcion, usuario_id)
            VALUES (?,?,?,?,?,?,?)
        """, (cliente_id, 'abono', monto, deuda_antes, deuda_despues, descripcion, usuario_id))

    logger.info(f"Abono fiado: cliente={cliente_id} monto={monto} nueva_deuda={deuda_despues}")
    return jsonify({"ok": True, "deuda_anterior": deuda_antes, "deuda_nueva": deuda_despues})


@fiado_bp.route("/clientes/<int:cid>", methods=["PUT"])
def editar_cliente(cid):
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    data = request.get_json(silent=True) or {}
    campos = {k: data[k] for k in ['nombre', 'apellido', 'telefono', 'email', 'rut', 'direccion',
                                    'limite_credito', 'frecuencia_pago', 'fecha_pago_fija',
                                    'dia_pago', 'notas']
              if k in data}
    if not campos:
        return jsonify({"error": "Sin campos"}), 400

    # Recalcular proximo_vencimiento si cambia algún campo que lo determina
    recalc_keys = {'frecuencia_pago', 'fecha_pago_fija', 'dia_pago'}
    if recalc_keys & campos.keys():
        with db_session() as conn:
            base = dict(conn.execute("SELECT * FROM clientes_fiado WHERE id=?", (cid,)).fetchone() or {})
        frecuencia = campos.get('frecuencia_pago', base.get('frecuencia_pago'))
        fecha_fija = campos.get('fecha_pago_fija', base.get('fecha_pago_fija'))
        dia_pago   = campos.get('dia_pago', base.get('dia_pago'))
        campos['proximo_vencimiento'] = calcular_proximo_vencimiento(frecuencia, fecha_fija, dia_pago).isoformat()

    set_sql = ", ".join(f"{k}=?" for k in campos) + ", actualizado_en=CURRENT_TIMESTAMP"
    with db_session() as conn:
        conn.execute(f"UPDATE clientes_fiado SET {set_sql} WHERE id=?", [*campos.values(), cid])
        c = dict(conn.execute("SELECT * FROM clientes_fiado WHERE id=?", (cid,)).fetchone())
    return jsonify(c)


@fiado_bp.route("/clientes/<int:cid>", methods=["DELETE"])
def desactivar_cliente(cid):
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403
    with db_session() as conn:
        conn.execute("UPDATE clientes_fiado SET activo=0, actualizado_en=CURRENT_TIMESTAMP WHERE id=?", (cid,))
    return jsonify({"ok": True})


@fiado_bp.route("/resumen", methods=["GET"])
def resumen():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    hoy = date.today().isoformat()
    pronto = (date.today() + timedelta(days=7)).isoformat()
    with db_session() as conn:
        r = conn.execute("""
            SELECT
                COALESCE(SUM(deuda_actual),0) as total_deuda,
                COUNT(*) as total_clientes,
                SUM(CASE WHEN proximo_vencimiento < ? AND deuda_actual > 0 THEN 1 ELSE 0 END) as vencidos,
                SUM(CASE WHEN proximo_vencimiento < ? AND deuda_actual > 0 THEN deuda_actual ELSE 0 END) as vencidos_monto,
                SUM(CASE WHEN proximo_vencimiento BETWEEN ? AND ? AND deuda_actual > 0 THEN 1 ELSE 0 END) as por_vencer_7,
                SUM(CASE WHEN deuda_actual = 0 THEN 1 ELSE 0 END) as al_dia
            FROM clientes_fiado WHERE activo=1
        """, (hoy, hoy, hoy, pronto)).fetchone()
        cobrado = conn.execute(
            "SELECT COALESCE(SUM(monto),0) as t FROM fiado_movimientos WHERE tipo='abono' AND DATE(creado_en)=?",
            (hoy,)
        ).fetchone()
    return jsonify({**dict(r), 'cobrado_hoy': cobrado['t'] if cobrado else 0})


@fiado_bp.route("/clientes/<int:cid>/tarjeta", methods=["POST"])
def generar_tarjeta(cid):
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        c = conn.execute("SELECT * FROM clientes_fiado WHERE id=?", (cid,)).fetchone()
        cfg_rows = conn.execute(
            "SELECT clave,valor FROM config WHERE clave IN ('nombre_negocio','direccion_negocio','ip_local')"
        ).fetchall()
    if not c:
        return jsonify({"error": "No encontrado"}), 404
    c = dict(c)
    negocio = {r['clave']: r['valor'] for r in cfg_rows}
    ip = negocio.get('ip_local', '127.0.0.1')
    url = f"http://{ip}:5000/credit/{c['qr_token']}"
    qr_img = generar_qr_base64(url)
    lines = [
        "=" * 32, "       ZERO CREDIT", "=" * 32, "",
        f"  {c['nombre']} {c.get('apellido') or ''}".strip(),
        f"  Tel: {c.get('telefono') or '—'}", "",
        f"  Límite:  ${c['limite_credito']:,}",
        f"  Pago:    {c['frecuencia_pago'].title()}", "",
        "       [QR CODE]", f"  {url}", "",
        "=" * 32,
        f"  {negocio.get('nombre_negocio', 'Mi Negocio')}",
        f"  {negocio.get('direccion_negocio', '')}",
        "=" * 32, "  Escanea el QR para", "  ver tu cuenta online",
    ]
    return jsonify({"ok": True, "texto": "\n".join(lines), "qr_imagen": qr_img, "url_portal": url})


@fiado_bp.route("/clientes/<int:cid>/imprimir_tarjeta", methods=["POST"])
def imprimir_tarjeta(cid):
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        c = conn.execute("SELECT * FROM clientes_fiado WHERE id=?", (cid,)).fetchone()
        if c:
            c = dict(c)
        cfg_rows = conn.execute("SELECT clave,valor FROM config").fetchall()
    if not c:
        return jsonify({"error": "No encontrado"}), 404
    config = {r['clave']: r['valor'] for r in cfg_rows}
    from utils.impresora import imprimir_tarjeta_credit
    return jsonify(imprimir_tarjeta_credit(c, config))
