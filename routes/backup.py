import logging
from flask import Blueprint, request, jsonify, session, send_file
from database import db_session

backup_bp = Blueprint("backup", __name__, url_prefix="/api/backup")
logger = logging.getLogger("zero_pos.backup")


@backup_bp.route("/crear", methods=["POST"])
def crear_backup():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403

    from utils.backup import crear_backup_cifrado
    resultado = crear_backup_cifrado()
    return jsonify(resultado)


@backup_bp.route("/descargar/<nombre>", methods=["GET"])
def descargar_backup(nombre):
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403

    from pathlib import Path
    from flask import current_app
    base = Path(current_app.root_path) / "backups"
    archivo = base / nombre
    if not archivo.exists() or not archivo.is_relative_to(base):
        return jsonify({"error": "Archivo no encontrado"}), 404

    return send_file(str(archivo), as_attachment=True)


@backup_bp.route("/listar", methods=["GET"])
def listar_backups():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403

    from pathlib import Path
    from flask import current_app
    base = Path(current_app.root_path) / "backups"
    base.mkdir(exist_ok=True)

    archivos = sorted(base.glob("*.zip"), key=lambda f: f.stat().st_mtime, reverse=True)
    return jsonify([
        {"nombre": f.name, "tamaño_kb": round(f.stat().st_size / 1024, 1)}
        for f in archivos[:20]
    ])


@backup_bp.route("/restaurar", methods=["POST"])
def restaurar_backup():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403

    archivo = request.files.get("archivo")
    if not archivo:
        return jsonify({"error": "Archivo requerido"}), 400

    from utils.backup import restaurar_backup_cifrado
    resultado = restaurar_backup_cifrado(archivo)
    return jsonify(resultado)
