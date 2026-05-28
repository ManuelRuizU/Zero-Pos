import logging
import threading
from pathlib import Path
from flask import Blueprint, request, jsonify, session, send_file, current_app
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

    base    = (Path(current_app.root_path) / "backups").resolve()
    archivo = (base / nombre).resolve()
    if not archivo.is_relative_to(base):
        return jsonify({"error": "Acceso denegado"}), 403
    if not archivo.exists():
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
    if not archivo or not archivo.filename:
        return jsonify({"error": "No se seleccionó archivo"}), 400

    # Guardar en /tmp y reiniciar en frío — la DB no puede restaurarse
    # mientras Flask la tiene abierta
    pending = Path("/tmp/restore_pending.zip")
    archivo.save(str(pending))
    Path("restore.flag").write_text(archivo.filename)

    def _reiniciar():
        import time, os, sys
        time.sleep(1)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    threading.Thread(target=_reiniciar, daemon=True).start()
    return jsonify({
        "ok": True,
        "mensaje": "Reiniciando para restaurar... El sistema estará listo en 10 segundos."
    })
