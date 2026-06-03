import json
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, session
from database import db_session
from utils.consultas_rapidas import (
    ventas_hoy as _cq_ventas_hoy,
    producto_mas_vendido as _cq_top_prod,
    stock_bajo as _cq_stock_bajo,
)

reportes_bp = Blueprint("reportes", __name__, url_prefix="/api/reportes")
logger = logging.getLogger("zero_pos.reportes")


def _require_admin():
    return session.get("usuario_rol") == "admin"


@reportes_bp.route("/ventas/dia", methods=["GET"])
def ventas_dia():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    fecha = request.args.get("fecha", datetime.now().strftime("%Y-%m-%d"))
    sucursal_id = session.get("sucursal_id")

    suc_filter = " AND sucursal_id=?" if sucursal_id else ""
    suc_param  = [sucursal_id] if sucursal_id else []

    with db_session() as conn:
        resumen = conn.execute(
            f"""SELECT
                COUNT(*) as num_ventas,
                COALESCE(SUM(total), 0) as total,
                COALESCE(SUM(descuento), 0) as total_descuentos,
                COALESCE(AVG(total), 0) as ticket_promedio,
                metodo_pago, COUNT(*) as cnt
               FROM ventas
               WHERE DATE(creado_en)=? AND estado='completada'{suc_filter}
               GROUP BY metodo_pago""",
            [fecha] + suc_param
        ).fetchall()

        por_hora = conn.execute(
            f"""SELECT strftime('%H', creado_en) as hora,
                COUNT(*) as ventas,
                COALESCE(SUM(total), 0) as total
               FROM ventas
               WHERE DATE(creado_en)=? AND estado='completada'{suc_filter}
               GROUP BY hora ORDER BY hora""",
            [fecha] + suc_param
        ).fetchall()

        top_productos = conn.execute(
            f"""SELECT p.nombre, SUM(vi.cantidad) as unidades, SUM(vi.subtotal) as total
               FROM venta_items vi
               JOIN ventas v ON vi.venta_id=v.id
               JOIN productos p ON vi.producto_id=p.id
               WHERE DATE(v.creado_en)=? AND v.estado='completada'{suc_filter}
               GROUP BY vi.producto_id
               ORDER BY unidades DESC LIMIT 10""",
            [fecha] + suc_param
        ).fetchall()

        return jsonify({
            "por_metodo": [dict(r) for r in resumen],
            "por_hora": [dict(r) for r in por_hora],
            "top_productos": [dict(r) for r in top_productos],
        })


@reportes_bp.route("/ventas/semana", methods=["GET"])
def ventas_semana():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        rows = conn.execute(
            """SELECT DATE(creado_en) as fecha,
                COUNT(*) as num_ventas,
                COALESCE(SUM(total), 0) as total
               FROM ventas
               WHERE creado_en >= DATE('now', '-7 days') AND estado='completada'
               GROUP BY fecha ORDER BY fecha""",
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@reportes_bp.route("/ventas/mes", methods=["GET"])
def ventas_mes():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    mes = request.args.get("mes", datetime.now().strftime("%Y-%m"))

    with db_session() as conn:
        rows = conn.execute(
            """SELECT DATE(creado_en) as fecha,
                COUNT(*) as num_ventas,
                COALESCE(SUM(total), 0) as total
               FROM ventas
               WHERE strftime('%Y-%m', creado_en)=? AND estado='completada'
               GROUP BY fecha ORDER BY fecha""",
            (mes,)
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@reportes_bp.route("/productos/rentabilidad", methods=["GET"])
def rentabilidad():
    if not _require_admin():
        return jsonify({"error": "Sin permisos"}), 403

    with db_session() as conn:
        rows = conn.execute(
            """SELECT
                p.nombre,
                p.precio,
                p.precio_costo,
                p.precio - p.precio_costo as margen_unitario,
                CASE WHEN p.precio > 0
                     THEN ROUND((p.precio - p.precio_costo) * 100.0 / p.precio, 2)
                     ELSE 0 END as margen_pct,
                COALESCE(SUM(vi.cantidad), 0) as unidades_vendidas,
                COALESCE(SUM(vi.subtotal), 0) as revenue_total
               FROM productos p
               LEFT JOIN venta_items vi ON vi.producto_id=p.id
               LEFT JOIN ventas v ON vi.venta_id=v.id AND v.estado='completada'
               WHERE p.activo=1
               GROUP BY p.id
               ORDER BY revenue_total DESC""",
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@reportes_bp.route("/ia/analisis", methods=["POST"])
def analisis_ia():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    data = request.get_json(silent=True) or {}
    pregunta = str(data.get("pregunta", "")).strip()

    with db_session() as conn:
        vh = _cq_ventas_hoy(conn)
        top_prod = _cq_top_prod(conn, dias=7)
        bajo = _cq_stock_bajo(conn)
        alertas_n = conn.execute(
            "SELECT COUNT(*) as n FROM alertas_stock WHERE leida=0"
        ).fetchone()["n"]

    contexto = {
        "ventas_hoy": {"n": vh["num_ventas"], "t": int(vh["total"])},
        "top_producto_semana": top_prod,
        "stock_bajo_count": len(bajo),
        "alertas_stock_activas": alertas_n,
    }

    respuesta = _llamar_tinyllama(pregunta, contexto)
    return jsonify({"respuesta": respuesta, "contexto": contexto})


def _llamar_tinyllama(pregunta: str, contexto: dict) -> str:
    top_nombre = contexto.get('top_producto_semana', {})
    top_txt = top_nombre.get('nombre', '—') if isinstance(top_nombre, dict) else '—'
    prompt = f"""Eres el asistente de ZERO POS, un sistema de punto de venta.
Datos actuales del negocio:
- Ventas hoy: {contexto['ventas_hoy']['n']} ventas por ${contexto['ventas_hoy']['t']:,.0f}
- Alertas de stock sin atender: {contexto['alertas_stock_activas']}
- Producto más vendido esta semana: {top_txt}

Pregunta del dueño: {pregunta if pregunta else '¿Cómo va el negocio hoy?'}

Responde en español, de forma breve y útil (máximo 3 oraciones)."""

    try:
        import urllib.request
        payload = json.dumps({
            "model": "tinyllama",
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 200},
        }).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("response", "").strip()
    except Exception as e:
        logger.warning(f"TinyLlama no disponible: {e}")
        return _analisis_sin_ia(contexto, pregunta)


@reportes_bp.route("/metricas", methods=["GET"])
def metricas_rapidas():
    """Retorna métricas precalculadas. periodo=dia|semana|mes (default: dia)."""
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    periodo = request.args.get("periodo", "dia")

    with db_session() as conn:
        if periodo == "semana":
            rows = conn.execute(
                "SELECT * FROM metricas_semanales ORDER BY anio DESC, semana DESC LIMIT 12"
            ).fetchall()
            return jsonify([dict(r) for r in rows])

        if periodo == "mes":
            rows = conn.execute(
                "SELECT * FROM metricas_mensuales ORDER BY anio DESC, mes DESC LIMIT 13"
            ).fetchall()
            return jsonify([dict(r) for r in rows])

        # dia (default)
        fecha = request.args.get("fecha", datetime.now().strftime("%Y-%m-%d"))
        row = conn.execute(
            "SELECT * FROM metricas_diarias WHERE fecha=?", (fecha,)
        ).fetchone()

        if row:
            return jsonify(dict(row))

        # Si no hay precalculado, calcula on-demand (fallback)
        stats = conn.execute("""
            SELECT COUNT(*) as num_ventas,
                   COALESCE(SUM(total),0) as total_ventas,
                   COALESCE(AVG(total),0) as ticket_promedio,
                   COALESCE(SUM(CASE WHEN metodo_pago='efectivo'      THEN total ELSE 0 END),0) as metodo_efectivo,
                   COALESCE(SUM(CASE WHEN metodo_pago='tarjeta'       THEN total ELSE 0 END),0) as metodo_tarjeta,
                   COALESCE(SUM(CASE WHEN metodo_pago='transferencia' THEN total ELSE 0 END),0) as metodo_transferencia
            FROM ventas WHERE DATE(creado_en)=? AND estado='completada'
        """, (fecha,)).fetchone()
        top = conn.execute("""
            SELECT p.id as producto_top_id, p.nombre as producto_top_nombre,
                   SUM(vi.cantidad) as producto_top_cant
            FROM venta_items vi
            JOIN productos p ON p.id=vi.producto_id
            JOIN ventas v ON v.id=vi.venta_id
            WHERE DATE(v.creado_en)=? AND v.estado='completada'
            GROUP BY p.id ORDER BY producto_top_cant DESC LIMIT 1
        """, (fecha,)).fetchone()

        return jsonify({
            "fecha": fecha,
            "num_ventas": stats["num_ventas"],
            "total_ventas": stats["total_ventas"],
            "ticket_promedio": int(stats["ticket_promedio"]),
            "metodo_efectivo": stats["metodo_efectivo"],
            "metodo_tarjeta": stats["metodo_tarjeta"],
            "metodo_transferencia": stats["metodo_transferencia"],
            "producto_top_id": top["producto_top_id"] if top else None,
            "producto_top_nombre": top["producto_top_nombre"] if top else None,
            "producto_top_cant": top["producto_top_cant"] if top else 0,
            "_source": "live",
        })


def _analisis_sin_ia(contexto: dict, pregunta: str) -> str:
    v = contexto["ventas_hoy"]
    alertas = contexto["alertas_stock_activas"]
    top = contexto.get("top_producto_semana")

    partes = []
    if v["n"] > 0:
        partes.append(f"Hoy llevas {v['n']} venta(s) por ${v['t']:,.0f}.")
    else:
        partes.append("Aún no hay ventas registradas hoy.")
    if alertas > 0:
        partes.append(f"Tienes {alertas} alerta(s) de stock bajo — revísalas en inventario.")
    if top and isinstance(top, dict):
        partes.append(f"Tu producto estrella esta semana: {top['nombre']}.")
    return " ".join(partes)
