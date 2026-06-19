import io
import logging
import shutil
import sqlite3 as _sqlite3
import tempfile
import threading
from pathlib import Path
from flask import Blueprint, request, jsonify, session, send_file, current_app
from database import db_session
from routes.config import upsert_config

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

    base_resolved = (Path(current_app.root_path) / "backups").resolve()
    archivo       = (base_resolved / nombre).resolve()
    if not archivo.exists() or base_resolved not in archivo.parents:
        return jsonify({"error": "Archivo inválido"}), 404

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

    from utils.backup import restaurar_backup_cifrado

    tmp_dir = Path(tempfile.mkdtemp())
    tmp_db  = tmp_dir / "test_restore.db"

    # 1. Descifrar a directorio temporal
    resultado = restaurar_backup_cifrado(io.BytesIO(archivo.read()), destino_path=tmp_db)
    if not resultado.get("ok"):
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify(resultado), 400

    # 2. Validar que la DB restaurada abre y tiene tablas clave
    try:
        test_conn = _sqlite3.connect(str(tmp_db))
        test_conn.execute("SELECT COUNT(*) FROM ventas")
        test_conn.execute("SELECT COUNT(*) FROM productos")
        test_conn.execute("SELECT COUNT(*) FROM usuarios")
        test_conn.close()
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return jsonify({"error": f"Backup corrupto o incompatible: {e}"}), 400

    # 3. Respaldar DB actual antes de pisar
    db_actual = Path(current_app.root_path) / "zero_pos.db"
    if db_actual.exists():
        shutil.copy2(db_actual, db_actual.with_suffix(".db.pre-restore"))
        logger.info("DB actual respaldada como .db.pre-restore")

    # 4. Reemplazar DB con la restaurada
    shutil.move(str(tmp_db), str(db_actual))
    shutil.rmtree(tmp_dir, ignore_errors=True)

    logger.info("DB restaurada exitosamente desde backup")
    return jsonify({
        "ok": True,
        "msg": "Restaurado exitosamente. Reinicia el sistema."
    })


@backup_bp.route("/estado", methods=["GET"])
def estado_backup():
    if not session.get("usuario_id"):
        return jsonify({"error": "No autenticado"}), 401

    from utils.backup import detectar_pendrives

    with db_session() as conn:
        rows = conn.execute(
            "SELECT clave, valor FROM config WHERE clave LIKE 'backup_%' OR clave IN ('smtp_host','smtp_user','smtp_password')"
        ).fetchall()
    cfg = {r["clave"]: r["valor"] for r in rows}

    base = Path(current_app.root_path) / "backups"
    archivos = sorted(base.glob("*.zip"), key=lambda f: f.stat().st_mtime, reverse=True) if base.exists() else []
    ultimo_local = archivos[0].name if archivos else None

    pendrives = detectar_pendrives()

    import subprocess
    try:
        rclone_ok = subprocess.run(["rclone", "version"], capture_output=True, timeout=3).returncode == 0
    except Exception:
        rclone_ok = False

    destinos_activos = [d.strip() for d in cfg.get("backup_destinos", "local").split(",") if d.strip()]
    email_configurado = bool(cfg.get("smtp_host") and cfg.get("smtp_user") and cfg.get("smtp_password"))

    return jsonify({
        "local": {"activo": "local" in destinos_activos, "ultimo": ultimo_local},
        "pendrive": {
            "activo": "pendrive" in destinos_activos,
            "detectado": len(pendrives) > 0,
            "ruta": pendrives[0] if pendrives else None,
        },
        "email": {
            "activo": "email" in destinos_activos,
            "configurado": email_configurado,
            "email": cfg.get("backup_email_destino"),
        },
        "rclone": {
            "activo": "rclone" in destinos_activos,
            "instalado": rclone_ok,
            "remote": cfg.get("backup_rclone_remote", "gdrive"),
        },
    })


@backup_bp.route("/ahora", methods=["POST"])
def backup_ahora():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403

    from utils.backup import ejecutar_backup_completo
    resultados = ejecutar_backup_completo()
    return jsonify({"ok": True, "resultados": resultados})


@backup_bp.route("/probar-email", methods=["POST"])
def probar_email():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403

    data = request.get_json(silent=True) or {}
    email_destino = data.get("email_destino")
    if not email_destino:
        with db_session() as conn:
            row = conn.execute("SELECT valor FROM config WHERE clave='backup_email_destino'").fetchone()
            email_destino = row["valor"] if row else None

    if not email_destino:
        return jsonify({"ok": False, "error": "No hay email de destino configurado"})

    from utils.backup import backup_por_email
    db_path = Path(current_app.root_path) / "zero_pos.db"
    ok, msg = backup_por_email(str(db_path), "zero_test.db", email_destino)
    return jsonify({"ok": ok, "mensaje": msg})


@backup_bp.route("/config", methods=["PUT"])
def guardar_config_backup():
    if session.get("usuario_rol") != "admin":
        return jsonify({"error": "Sin permisos"}), 403

    data = request.get_json(silent=True) or {}
    mapeo = {
        "hora": "backup_hora",
        "retener_dias": "backup_retener_dias",
        "email_destino": "backup_email_destino",
        "smtp_provider": "smtp_provider",
        "smtp_host": "smtp_host",
        "smtp_port": "smtp_port",
        "smtp_user": "smtp_user",
        "rclone_remote": "backup_rclone_remote",
    }
    config_data = {}
    for k, col in mapeo.items():
        if k in data and data[k] is not None:
            config_data[col] = str(data[k])

    # Destinos como string CSV
    if "destinos" in data and isinstance(data["destinos"], list):
        config_data["backup_destinos"] = ",".join(data["destinos"])

    # Contraseña solo si no es placeholder
    pwd = data.get("smtp_password", "")
    if pwd and "••" not in pwd:
        config_data["smtp_password"] = pwd

    with db_session() as conn:
        upsert_config(conn, config_data)

    logger.info(f"Config backup actualizada: {list(config_data.keys())}")
    return jsonify({"ok": True})
