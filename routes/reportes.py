import json
import logging
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, session
from database import db_session

reportes_bp = Blueprint("reportes", __name__, url_prefix="/api/reportes")
logger = logging.getLogger("zero_pos.reportes")


def _require_admin():
    return session.get("usuario_rol") == "admin"


@reportes_bp.route("/ventas/dia", methods=["GET"])
def ventas_dia():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    fecha = request.args.get("fecha", datetime.now().strftime("%Y-%m-%d"))

    with db_session() as conn:
        resumen = conn.execute(
            """SELECT
                COUNT(*) as num_ventas,
                COALESCE(SUM(total), 0) as total,
                COALESCE(SUM(descuento), 0) as total_descuentos,
                COALESCE(AVG(total), 0) as ticket_promedio,
                metodo_pago, COUNT(*) as cnt
               FROM ventas
               WHERE DATE(creado_en)=? AND estado='completada'
               GROUP BY metodo_pago""",
            (fecha,)
        ).fetchall()

        por_hora = conn.execute(
            """SELECT strftime('%H', creado_en) as hora,
                COUNT(*) as ventas,
                COALESCE(SUM(total), 0) as total
               FROM ventas
               WHERE DATE(creado_en)=? AND estado='completada'
               GROUP BY hora ORDER BY hora""",
            (fecha,)
        ).fetchall()

        top_productos = conn.execute(
            """SELECT p.nombre, SUM(vi.cantidad) as unidades, SUM(vi.subtotal) as total
               FROM venta_items vi
               JOIN ventas v ON vi.venta_id=v.id
               JOIN productos p ON vi.producto_id=p.id
               WHERE DATE(v.creado_en)=? AND v.estado='completada'
               GROUP BY vi.producto_id
               ORDER BY unidades DESC LIMIT 10""",
            (fecha,)
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
        ventas_hoy = conn.execute(
            """SELECT COUNT(*) as n, COALESCE(SUM(total),0) as t
               FROM ventas WHERE DATE(creado_en)=DATE('now') AND estado='completada'"""
        ).fetchone()
        top5 = conn.execute(
            """SELECT p.nombre, SUM(vi.cantidad) as u
               FROM venta_items vi
               JOIN ventas v ON vi.venta_id=v.id
               JOIN productos p ON vi.producto_id=p.id
               WHERE v.estado='completada' AND v.creado_en >= DATE('now','-7 days')
               GROUP BY vi.producto_id ORDER BY u DESC LIMIT 5"""
        ).fetchall()
        alertas = conn.execute(
            "SELECT COUNT(*) as n FROM alertas_stock WHERE leida=0"
        ).fetchone()

    contexto = {
        "ventas_hoy": dict(ventas_hoy),
        "top_productos_semana": [dict(r) for r in top5],
        "alertas_stock_activas": alertas["n"],
    }

    respuesta = _llamar_tinyllama(pregunta, contexto)
    return jsonify({"respuesta": respuesta, "contexto": contexto})


def _llamar_tinyllama(pregunta: str, contexto: dict) -> str:
    prompt = f"""Eres el asistente de ZERO POS, un sistema de punto de venta.
Datos actuales del negocio:
- Ventas hoy: {contexto['ventas_hoy']['n']} ventas por ${contexto['ventas_hoy']['t']:,.0f}
- Alertas de stock sin atender: {contexto['alertas_stock_activas']}
- Top productos esta semana: {', '.join(p['nombre'] for p in contexto['top_productos_semana'][:3])}

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


def _analisis_sin_ia(contexto: dict, pregunta: str) -> str:
    v = contexto["ventas_hoy"]
    alertas = contexto["alertas_stock_activas"]
    top = contexto["top_productos_semana"]

    partes = []
    if v["n"] > 0:
        partes.append(f"Hoy llevas {v['n']} venta(s) por ${v['t']:,.0f}.")
    else:
        partes.append("Aún no hay ventas registradas hoy.")
    if alertas > 0:
        partes.append(f"Tienes {alertas} alerta(s) de stock bajo — revísalas en inventario.")
    if top:
        partes.append(f"Tus productos estrella esta semana: {top[0]['nombre']}.")
    return " ".join(partes)
