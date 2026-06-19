# factura.py

import json
import logging
from flask import Blueprint, request, jsonify, session
from database import db_session

facturas_bp = Blueprint("facturas", __name__, url_prefix="/api/facturas")
logger = logging.getLogger("zero_pos.facturas")


@facturas_bp.route("/subir", methods=["POST"])
def subir_factura():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Se requiere un archivo PDF"}), 400

    proveedor_id = request.form.get("proveedor_id")
    datos_json = request.form.get("datos_json")
    if datos_json:
        try:
            json.loads(datos_json)
        except (json.JSONDecodeError, TypeError):
            return jsonify({"error": "datos_json inválido"}), 400

    from utils.lector_facturas import procesar_pdf_factura
    resultado = procesar_pdf_factura(archivo, proveedor_id)
    return jsonify(resultado)


@facturas_bp.route("", methods=["GET"])
def listar():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401
    with db_session() as conn:
        rows = conn.execute(
            """SELECT f.*, p.nombre as proveedor_nombre
               FROM facturas_proveedor f
               LEFT JOIN proveedores p ON f.proveedor_id=p.id
               ORDER BY f.creado_en DESC LIMIT 100"""
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@facturas_bp.route("/<int:fid>/procesar", methods=["POST"])
def procesar(fid):
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    with db_session() as conn:
        factura = conn.execute(
            "SELECT * FROM facturas_proveedor WHERE id=?", (fid,)
        ).fetchone()
        if not factura:
            return jsonify({"error": "Factura no encontrada"}), 404

        conn.execute(
            "UPDATE facturas_proveedor SET procesada=1 WHERE id=?", (fid,)
        )
        return jsonify({"ok": True})
