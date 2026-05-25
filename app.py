import os
import sys
import socket
import threading
import logging
from pathlib import Path
from flask import Flask, redirect, url_for, send_from_directory
from flask_cors import CORS
from flask_session import Session

BASE_DIR = Path(__file__).parent
SECRET_KEY_FILE = BASE_DIR / ".secret_key"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("zero_pos")


def get_or_create_secret_key() -> bytes:
    if SECRET_KEY_FILE.exists():
        key = SECRET_KEY_FILE.read_bytes().strip()
        if key:
            return key
    key = os.urandom(32)
    SECRET_KEY_FILE.write_bytes(key)
    SECRET_KEY_FILE.chmod(0o600)
    return key


def get_ip_local() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def find_free_port(preferred: int = 5000) -> int:
    for port in (preferred, preferred + 1):
        if is_port_free(port):
            return port
    return preferred


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="/static")

    app.config.update(
        SECRET_KEY=get_or_create_secret_key(),
        SESSION_TYPE="filesystem",
        SESSION_FILE_DIR=str(BASE_DIR / "flask_sessions"),
        SESSION_PERMANENT=True,
        SESSION_USE_SIGNER=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,
    )

    (BASE_DIR / "flask_sessions").mkdir(exist_ok=True)
    Session(app)
    CORS(app, supports_credentials=True)

    from database import init_db
    init_db()

    from routes.auth import auth_bp
    from routes.ventas import ventas_bp
    from routes.productos import productos_bp
    from routes.reportes import reportes_bp
    from routes.impresora import impresora_bp
    from routes.backup import backup_bp
    from routes.inventario import inventario_bp
    from routes.facturas import facturas_bp
    from routes.comprobante import comprobante_bp
    from routes.qr import qr_bp
    from routes.khipu import khipu_bp
    from routes.multi import multi_bp
    from routes.config import config_bp
    from routes.onboarding import onboarding_bp
    from routes.voz import voz_bp

    for bp in (
        auth_bp, ventas_bp, productos_bp, reportes_bp,
        impresora_bp, backup_bp, inventario_bp, facturas_bp,
        comprobante_bp, qr_bp, khipu_bp, multi_bp, config_bp,
        onboarding_bp, voz_bp,
    ):
        app.register_blueprint(bp)

    @app.route("/")
    def index():
        return redirect(url_for("static", filename="login.html"))

    @app.route("/health")
    def health():
        return {"status": "ok", "version": "1.0.0"}

    return app


def start_backup_scheduler(app: Flask):
    try:
        import schedule
        import time
        from utils.backup import run_scheduled_backup

        schedule.every().day.at("03:00").do(run_scheduled_backup, app=app)
        logger.info("Backup scheduler iniciado (03:00 diario)")

        def loop():
            while True:
                schedule.run_pending()
                time.sleep(60)

        t = threading.Thread(target=loop, daemon=True, name="BackupScheduler")
        t.start()
    except ImportError:
        logger.warning("schedule no disponible — backup automático desactivado")


if __name__ == "__main__":
    app = create_app()
    start_backup_scheduler(app)

    port = find_free_port(5000)
    local_ip = get_ip_local()

    logger.info("=" * 60)
    logger.info("  ZERO POS  —  Sin internet. Sin comisiones. Tuyo.")
    logger.info("=" * 60)
    logger.info(f"  Local :  http://127.0.0.1:{port}")
    logger.info(f"  Red   :  http://{local_ip}:{port}")
    logger.info("=" * 60)

    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
