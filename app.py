import os
import sys
import socket
import threading
import logging
from pathlib import Path
from flask import Flask, redirect, url_for, send_from_directory, request
from flask_cors import CORS
from flask_session import Session

SSL_DIR = Path(__file__).parent / "ssl"
SSL_CERT = SSL_DIR / "cert.pem"
SSL_KEY  = SSL_DIR / "key.pem"

BASE_DIR = Path(__file__).parent
SECRET_KEY_FILE = BASE_DIR / ".secret_key"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("zero_pos")

def get_or_create_ssl_cert() -> tuple[Path, Path]:
    """Generate a persistent self-signed cert (only on first run)."""
    SSL_DIR.mkdir(exist_ok=True)
    if SSL_CERT.exists() and SSL_KEY.exists():
        return SSL_CERT, SSL_KEY
    try:
        import datetime
        import ipaddress
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        logger.warning("cryptography no disponible — iniciando sin HTTPS")
        return None, None

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    local_ip = get_ip_local()
    san_ips = {ipaddress.IPv4Address("127.0.0.1")}
    try:
        san_ips.add(ipaddress.IPv4Address(local_ip))
    except ValueError:
        pass

    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "zero-pos-local")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=5 * 365))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost")]
                + [x509.IPAddress(ip) for ip in san_ips]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    SSL_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    SSL_KEY.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    SSL_CERT.chmod(0o644)
    SSL_KEY.chmod(0o600)
    logger.info(f"Certificado SSL generado → {SSL_CERT} (SAN: localhost, {local_ip})")
    return SSL_CERT, SSL_KEY


def get_or_create_secret_key() -> bytes:
    if SECRET_KEY_FILE.exists():
        key = SECRET_KEY_FILE.read_bytes().strip()
        if key:
            return key
    key = os.urandom(32)
    SECRET_KEY_FILE.write_bytes(key)
    SECRET_KEY_FILE.chmod(0o600)
    return key


HOTSPOT_IP = "192.168.4.1"


def is_hotspot_mode() -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((HOTSPOT_IP, 0))
        s.close()
        return True
    except Exception:
        return False


def get_ip_local() -> str:
    if is_hotspot_mode():
        return HOTSPOT_IP
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
        # Flask-Compress
        COMPRESS_MIMETYPES=[
            "text/html", "text/css", "application/javascript",
            "application/json", "text/plain",
        ],
        COMPRESS_LEVEL=6,
        COMPRESS_MIN_SIZE=512,
    )

    (BASE_DIR / "flask_sessions").mkdir(exist_ok=True)
    Session(app)
    CORS(app, supports_credentials=True)

    try:
        from flask_compress import Compress
        Compress(app)
        logger.info("Flask-Compress activo (gzip)")
    except ImportError:
        logger.warning("flask-compress no disponible — respuestas sin comprimir")

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
    from routes.pedidos import pedidos_bp
    from routes.direcciones import direcciones_bp

    for bp in (
        auth_bp, ventas_bp, productos_bp, reportes_bp,
        impresora_bp, backup_bp, inventario_bp, facturas_bp,
        comprobante_bp, qr_bp, khipu_bp, multi_bp, config_bp,
        onboarding_bp, voz_bp, pedidos_bp, direcciones_bp,
    ):
        app.register_blueprint(bp)

    @app.route("/")
    def index():
        return redirect(url_for("static", filename="login.html"))

    @app.route("/health")
    def health():
        return {"status": "ok", "version": "1.0.0"}

    @app.route("/manifest.json")
    def manifest():
        return send_from_directory("static", "manifest.json",
                                   mimetype="application/manifest+json")

    @app.route("/sw.js")
    def service_worker():
        response = send_from_directory("static", "sw.js",
                                       mimetype="application/javascript")
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache"
        return response

    # Cache static files in the browser for 1 hour
    @app.after_request
    def add_cache_headers(response):
        if request.path.startswith("/static/"):
            response.cache_control.max_age = 3600
            response.cache_control.public = True
        return response

    return app


def _reset_stock_produccion():
    from database import get_connection
    try:
        conn = get_connection()
        conn.execute("UPDATE productos SET stock = 0 WHERE modo_stock = 'produccion' AND activo = 1")
        conn.commit()
        conn.close()
        logger.info("Stock de produccion reseteado")
    except Exception as e:
        logger.warning(f"reset_stock_produccion error: {e}")


def start_backup_scheduler(app: Flask):
    try:
        import schedule
        import time
        from utils.backup import run_scheduled_backup

        schedule.every().day.at("03:00").do(run_scheduled_backup, app=app)
        schedule.every().day.at("06:00").do(_reset_stock_produccion)
        logger.info("Backup scheduler iniciado (03:00) + reset produccion (06:00)")

        def loop():
            while True:
                schedule.run_pending()
                time.sleep(60)

        t = threading.Thread(target=loop, daemon=True, name="BackupScheduler")
        t.start()
    except ImportError:
        logger.warning("schedule no disponible — backup automático desactivado")


def get_hardware_fingerprint() -> str:
    import hashlib, uuid, platform
    datos = [
        str(uuid.getnode()),   # MAC address
        platform.node(),       # hostname
        platform.machine(),    # arquitectura
    ]
    raw = "|".join(datos)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def verificar_licencia() -> bool:
    fingerprint = get_hardware_fingerprint()
    license_file = BASE_DIR / ".license"

    if not license_file.exists():
        license_file.write_text(fingerprint)
        logger.info(f"Licencia registrada para este hardware: {fingerprint}")
        return True

    saved = license_file.read_text().strip()
    if saved != fingerprint:
        print("=" * 60)
        print("  ZERO POS — Hardware no autorizado")
        print(f"  Fingerprint esperado : {saved}")
        print(f"  Fingerprint actual   : {fingerprint}")
        print("  Contacta soporte: mrruiz.u@gmail.com")
        print("=" * 60)
        return False
    return True


if __name__ == "__main__":
    if not verificar_licencia():
        sys.exit(1)

    # Restauración en frío — antes de create_app() para que la DB esté libre
    _flag = BASE_DIR / ".restaurar_flag"
    _incoming = BASE_DIR / "temp" / "backup_incoming.zip"
    if _flag.exists() and _incoming.exists():
        _nombre = _flag.read_text().strip()
        _flag.unlink()
        try:
            from utils.backup import restaurar_backup_cifrado
            restaurar_backup_cifrado(_incoming)
            _incoming.unlink()
            print(f"[ZERO POS] Base de datos restaurada desde '{_nombre}' exitosamente")
        except Exception as _e:
            print(f"[ZERO POS] Error al restaurar backup: {_e}")

    app = create_app()
    start_backup_scheduler(app)

    cert_path, key_path = get_or_create_ssl_cert()
    ssl_ctx = (str(cert_path), str(key_path)) if cert_path else None

    port = find_free_port(5001 if ssl_ctx else 5000)
    local_ip = get_ip_local()
    scheme = "https" if ssl_ctx else "http"
    hotspot = local_ip == HOTSPOT_IP

    logger.info("=" * 60)
    logger.info("  ZERO POS  —  Sin internet. Sin comisiones. Tuyo.")
    logger.info("=" * 60)
    logger.info(f"  Local :  {scheme}://127.0.0.1:{port}")
    logger.info(f"  Red   :  {scheme}://{local_ip}:{port}")
    if hotspot:
        logger.info("  Modo hotspot activo")
        logger.info("  Red WiFi: ZEROPOS  |  zeropos.local")
        logger.info(f"  IP fija: {HOTSPOT_IP}")
        logger.info(f"  URL: {scheme}://{HOTSPOT_IP}:{port}")
    if ssl_ctx:
        logger.info("  HTTPS activo — acepta el certificado en Chrome una vez")
    else:
        logger.info("  HTTP (micrófono solo en localhost)")
    logger.info("=" * 60)

    if ssl_ctx:
        # Waitress no soporta SSL nativo — Werkzeug maneja HTTPS
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False,
                ssl_context=ssl_ctx)
    else:
        try:
            from waitress import serve
            print(f"[ZERO POS] Servidor producción (Waitress) → puerto {port}")
            serve(app, host="0.0.0.0", port=port, threads=8)
        except ImportError:
            print("[ZERO POS] Waitress no disponible, usando Werkzeug")
            app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
