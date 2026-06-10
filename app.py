import os
import sys
import socket
import threading
import logging
from pathlib import Path
from flask import Flask, redirect, url_for, send_from_directory, request
from flask_cors import CORS
from flask_session import Session

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

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


def _run_mux(host: str, mux_port: int, https_int_port: int, http_port: int) -> None:
    """
    Protocol multiplexer (blocks forever).
    TLS connections  → TCP-proxied to 127.0.0.1:https_int_port (HTTPS interno)
    HTTP connections → 301 redirect a http://<host>:http_port<path>
    """
    mux = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    mux.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    mux.bind((host, mux_port))
    mux.listen(256)
    logger.info(f"Mux :{mux_port}  HTTP→:{http_port}  TLS→:127.0.0.1:{https_int_port}")

    def _pipe(src: socket.socket, dst: socket.socket) -> None:
        try:
            while chunk := src.recv(32768):
                dst.sendall(chunk)
        except Exception:
            pass
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass

    def _redirect(conn: socket.socket, client_ip: str) -> None:
        try:
            conn.settimeout(5)
            raw = b""
            while b"\r\n\r\n" not in raw and len(raw) < 8192:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                raw += chunk
            path, host_hdr = "/", client_ip
            for i, line in enumerate(raw.decode("utf-8", "replace").split("\r\n")):
                if i == 0:
                    parts = line.split()
                    if len(parts) >= 2:
                        path = parts[1]
                elif line.lower().startswith("host:"):
                    host_hdr = line.split(":", 1)[1].strip().split(":")[0]
            conn.sendall((
                f"HTTP/1.1 301 Moved Permanently\r\n"
                f"Location: http://{host_hdr}:{http_port}{path}\r\n"
                f"Content-Length: 0\r\nConnection: close\r\n\r\n"
            ).encode())
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _handle(conn: socket.socket, addr: tuple) -> None:
        try:
            probe = conn.recv(1, socket.MSG_PEEK)
            if not probe:
                conn.close()
                return
            if probe[0] == 0x16:   # TLS ClientHello
                try:
                    backend = socket.create_connection(("127.0.0.1", https_int_port), timeout=3)
                    threading.Thread(target=_pipe, args=(conn, backend), daemon=True).start()
                    _pipe(backend, conn)
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
            else:                  # Plain HTTP
                _redirect(conn, addr[0])
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    while True:
        try:
            conn, addr = mux.accept()
            threading.Thread(target=_handle, args=(conn, addr), daemon=True).start()
        except Exception as exc:
            if mux.fileno() == -1:
                break
            logger.warning(f"Mux accept error: {exc}")


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

    from database import init_db, db_session
    init_db()

    # Guardar IP de red real en la DB para usarla en QR tickets
    try:
        _ip = get_ip_local()
        with db_session() as _conn:
            _conn.execute(
                "INSERT INTO config (clave, valor) VALUES ('ip_local', ?) "
                "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
                (_ip,)
            )
        logger.info(f"IP local guardada en config: {_ip}")
    except Exception as _e:
        logger.warning(f"No se pudo guardar ip_local: {_e}")

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
    from routes.modificadores import modificadores_bp
    from routes.fiado import fiado_bp
    from routes.publicidad import publicidad_bp

    for bp in (
        auth_bp, ventas_bp, productos_bp, reportes_bp,
        impresora_bp, backup_bp, inventario_bp, facturas_bp,
        comprobante_bp, qr_bp, khipu_bp, multi_bp, config_bp,
        onboarding_bp, voz_bp, pedidos_bp, direcciones_bp,
        modificadores_bp, fiado_bp, publicidad_bp,
    ):
        app.register_blueprint(bp)

    @app.route('/credit/<qr_token>')
    def portal_credit(qr_token):
        from database import db_session
        from utils.portal_credit import generar_portal_html
        with db_session() as conn:
            c = conn.execute(
                "SELECT * FROM clientes_fiado WHERE qr_token=? AND activo=1", (qr_token,)
            ).fetchone()
            if not c:
                return "Cliente no encontrado", 404
            movs = conn.execute(
                "SELECT * FROM fiado_movimientos WHERE cliente_id=? ORDER BY creado_en DESC LIMIT 20",
                (c['id'],)
            ).fetchall()
            cfg = conn.execute("SELECT clave,valor FROM config").fetchall()
        negocio = {r['clave']: r['valor'] for r in cfg}
        return generar_portal_html(dict(c), negocio, [dict(m) for m in movs])

    @app.route('/credit/manifest/<qr_token>')
    def manifest_credit(qr_token):
        from flask import jsonify
        from database import db_session
        with db_session() as conn:
            cfg = {r['clave']: r['valor'] for r in conn.execute("SELECT clave,valor FROM config").fetchall()}
        nombre = cfg.get('nombre_negocio', 'ZERO POS')
        color = cfg.get('tema_color', '#6366f1')
        resp = jsonify({
            "name": f"ZERO CREDIT — {nombre}",
            "short_name": "Mi Crédito",
            "start_url": f"/credit/{qr_token}",
            "display": "standalone",
            "background_color": "#0f0f1a",
            "theme_color": color,
            "icons": [
                {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
            ]
        })
        resp.headers['Content-Type'] = 'application/manifest+json'
        return resp

    @app.route('/credit/sw/<qr_token>.js')
    def sw_credit(qr_token):
        from flask import Response
        sw_js = f"""
const CACHE = 'zc-{qr_token}-v2';
const URL = '/credit/{qr_token}';

self.addEventListener('install', e => {{
  e.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll([URL]))
  );
  self.skipWaiting();
}});

self.addEventListener('activate', e => {{
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k.startsWith('zc-{qr_token}-') && k !== CACHE)
            .map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
}});

const SIN_CONEXION = `<!DOCTYPE html>
<html lang="es"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>ZERO CREDIT</title>
<style>
body{{background:#0f0f1a;color:#e2e8f0;font-family:-apple-system,sans-serif;
  display:flex;align-items:center;justify-content:center;
  min-height:100vh;margin:0;text-align:center;padding:20px;box-sizing:border-box;}}
.card{{background:#1e1e2e;border-radius:16px;padding:32px 24px;max-width:320px;width:100%;}}
.ico{{font-size:64px;margin-bottom:16px;}}
h2{{margin:0 0 8px;font-size:20px;}}
p{{color:#94a3b8;font-size:14px;line-height:1.6;margin:0;}}
.tip{{margin-top:20px;padding:14px;background:#2d2d44;border-radius:10px;
  font-size:13px;color:#94a3b8;line-height:1.5;}}
</style></head><body>
<div class="card">
  <div class="ico">📵</div>
  <h2>Sin conexión</h2>
  <p>No hay datos guardados aún.<br>
     Visita el almacén para sincronizar<br>
     tu cuenta por primera vez.</p>
  <div class="tip">
    💡 La próxima vez que vayas al almacén
    conéctate a su WiFi y abre esta página.
    Tus datos se guardarán automáticamente.
  </div>
</div></body></html>`;

self.addEventListener('fetch', e => {{
  if (!e.request.url.includes(URL)) return;
  e.respondWith(
    Promise.race([
      fetch(e.request).then(response => {{
        const clone = response.clone();
        caches.open(CACHE).then(cache => cache.put(e.request, clone));
        return response;
      }}),
      new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 3000))
    ]).catch(() =>
      caches.match(e.request).then(cached =>
        cached || new Response(SIN_CONEXION, {{headers: {{'Content-Type': 'text/html'}}}})
      )
    )
  );
}});
""".strip()
        resp = Response(sw_js, mimetype='application/javascript')
        resp.headers['Cache-Control'] = 'no-cache'
        return resp

    @app.route("/api/sistema/tipo")
    def sistema_tipo():
        from database import db_session
        try:
            with db_session() as conn:
                row = conn.execute(
                    "SELECT valor FROM config WHERE clave='tipo_negocio'"
                ).fetchone()
            return {"tipo": row["valor"] if row and row["valor"] else "store"}
        except Exception:
            return {"tipo": "store"}

    @app.route("/")
    def index():
        return redirect(url_for("static", filename="login.html"))

    @app.route("/health")
    def health():
        return {"status": "ok", "version": "1.0.0"}

    @app.route("/api/sistema/version")
    def sistema_version():
        return {"version": "1.0.0"}

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


def calcular_metricas_dia(app: Flask):
    """Calcula y persiste métricas del día en metricas_diarias (corre a las 23:59)."""
    from datetime import date
    from database import db_session
    with app.app_context():
        try:
            with db_session() as conn:
                hoy = date.today().isoformat()

                stats = conn.execute("""
                    SELECT
                        COUNT(*) as num_ventas,
                        COALESCE(SUM(total), 0) as total,
                        COALESCE(AVG(total), 0) as promedio,
                        COALESCE(SUM(CASE WHEN metodo_pago='efectivo'      THEN total ELSE 0 END), 0) as efectivo,
                        COALESCE(SUM(CASE WHEN metodo_pago='tarjeta'       THEN total ELSE 0 END), 0) as tarjeta,
                        COALESCE(SUM(CASE WHEN metodo_pago='transferencia' THEN total ELSE 0 END), 0) as transferencia
                    FROM ventas
                    WHERE DATE(creado_en)=? AND estado='completada'
                """, (hoy,)).fetchone()

                top = conn.execute("""
                    SELECT p.id, p.nombre, SUM(vi.cantidad) as total_cant
                    FROM venta_items vi
                    JOIN productos p ON p.id = vi.producto_id
                    JOIN ventas v ON v.id = vi.venta_id
                    WHERE DATE(v.creado_en)=? AND v.estado='completada'
                    GROUP BY p.id ORDER BY total_cant DESC LIMIT 1
                """, (hoy,)).fetchone()

                conn.execute("""
                    INSERT INTO metricas_diarias
                        (fecha, total_ventas, num_ventas, ticket_promedio,
                         producto_top_id, producto_top_nombre, producto_top_cant,
                         metodo_efectivo, metodo_tarjeta, metodo_transferencia)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(fecha) DO UPDATE SET
                        total_ventas         = excluded.total_ventas,
                        num_ventas           = excluded.num_ventas,
                        ticket_promedio      = excluded.ticket_promedio,
                        producto_top_id      = excluded.producto_top_id,
                        producto_top_nombre  = excluded.producto_top_nombre,
                        producto_top_cant    = excluded.producto_top_cant,
                        metodo_efectivo      = excluded.metodo_efectivo,
                        metodo_tarjeta       = excluded.metodo_tarjeta,
                        metodo_transferencia = excluded.metodo_transferencia,
                        actualizado_en       = CURRENT_TIMESTAMP
                """, (
                    hoy,
                    stats["total"], stats["num_ventas"], int(stats["promedio"]),
                    top["id"] if top else None,
                    top["nombre"] if top else None,
                    top["total_cant"] if top else 0,
                    stats["efectivo"], stats["tarjeta"], stats["transferencia"],
                ))

                # Métricas semanales
                from datetime import date as _d, timedelta
                hoy_d = _d.today()
                anio, semana, _ = hoy_d.isocalendar()
                lunes = hoy_d - timedelta(days=hoy_d.weekday())
                domingo = lunes + timedelta(days=6)

                sem_stats = conn.execute("""
                    SELECT COUNT(*) as n, COALESCE(SUM(total),0) as t,
                           COALESCE(AVG(total),0) as avg
                    FROM ventas
                    WHERE DATE(creado_en) BETWEEN ? AND ? AND estado='completada'
                """, (lunes.isoformat(), domingo.isoformat())).fetchone()

                dia_mejor = conn.execute("""
                    SELECT DATE(creado_en) as d, COALESCE(SUM(total),0) as t
                    FROM ventas
                    WHERE DATE(creado_en) BETWEEN ? AND ? AND estado='completada'
                    GROUP BY d ORDER BY t DESC LIMIT 1
                """, (lunes.isoformat(), domingo.isoformat())).fetchone()

                conn.execute("""
                    INSERT INTO metricas_semanales
                        (anio, semana, fecha_inicio, fecha_fin,
                         total_ventas, num_ventas, ticket_promedio, dia_mejor, dia_mejor_total)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(anio, semana) DO UPDATE SET
                        total_ventas    = excluded.total_ventas,
                        num_ventas      = excluded.num_ventas,
                        ticket_promedio = excluded.ticket_promedio,
                        dia_mejor       = excluded.dia_mejor,
                        dia_mejor_total = excluded.dia_mejor_total
                """, (
                    anio, semana, lunes.isoformat(), domingo.isoformat(),
                    sem_stats["t"], sem_stats["n"], int(sem_stats["avg"]),
                    dia_mejor["d"] if dia_mejor else None,
                    dia_mejor["t"] if dia_mejor else 0,
                ))

                # Métricas mensuales
                mes_str = hoy_d.strftime("%Y-%m")
                mes_stats = conn.execute("""
                    SELECT COUNT(*) as n, COALESCE(SUM(total),0) as t,
                           COALESCE(AVG(total),0) as avg
                    FROM ventas
                    WHERE strftime('%Y-%m', creado_en)=? AND estado='completada'
                """, (mes_str,)).fetchone()

                mes_ant = (hoy_d.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
                mes_ant_total = conn.execute(
                    "SELECT COALESCE(SUM(total),0) as t FROM ventas WHERE strftime('%Y-%m', creado_en)=? AND estado='completada'",
                    (mes_ant,)
                ).fetchone()["t"] or 0
                crecimiento = round(
                    (mes_stats["t"] - mes_ant_total) * 100.0 / mes_ant_total, 2
                ) if mes_ant_total else 0.0

                conn.execute("""
                    INSERT INTO metricas_mensuales
                        (anio, mes, total_ventas, num_ventas, ticket_promedio, crecimiento_pct)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(anio, mes) DO UPDATE SET
                        total_ventas    = excluded.total_ventas,
                        num_ventas      = excluded.num_ventas,
                        ticket_promedio = excluded.ticket_promedio,
                        crecimiento_pct = excluded.crecimiento_pct
                """, (hoy_d.year, hoy_d.month, mes_stats["t"], mes_stats["n"],
                      int(mes_stats["avg"]), crecimiento))

                logger.info(f"Métricas calculadas: {stats['num_ventas']} ventas, ${stats['total']:,}")
        except Exception as e:
            logger.error(f"calcular_metricas_dia error: {e}")


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


def procesar_cola_impresion(app: Flask):
    """Reintenta tickets pendientes/fallidos con menos de 3 intentos."""
    from database import db_session, marcar_ticket_impreso, marcar_ticket_fallido
    with app.app_context():
        try:
            with db_session() as conn:
                cfg_rows = conn.execute(
                    "SELECT clave, valor FROM config WHERE clave LIKE 'impresora_%'"
                ).fetchall()
                cfg = {r["clave"]: r["valor"] for r in cfg_rows}
                pendientes = conn.execute(
                    "SELECT id, contenido FROM cola_impresion "
                    "WHERE estado IN ('pendiente','fallido') AND intentos < 3 "
                    "ORDER BY id ASC LIMIT 10"
                ).fetchall()

            if not pendientes:
                return

            from utils.impresora import enviar_crudo
            config_imp = {
                "tipo":   cfg.get("impresora_tipo", "red"),
                "ip":     cfg.get("impresora_ip", ""),
                "puerto": cfg.get("impresora_puerto", "9100"),
            }
            for row in pendientes:
                resultado = enviar_crudo(config_imp, row["contenido"])
                with db_session() as conn2:
                    if resultado.get("ok"):
                        marcar_ticket_impreso(conn2, row["id"])
                    else:
                        marcar_ticket_fallido(conn2, row["id"], resultado.get("error", ""))
        except Exception as e:
            logger.error(f"procesar_cola_impresion error: {e}")


def revisar_fiados_vencidos(app: Flask):
    with app.app_context():
        from database import db_session
        from datetime import date
        hoy = date.today().isoformat()
        try:
            with db_session() as conn:
                vencidos = conn.execute("""
                    SELECT COUNT(*) as n, COALESCE(SUM(deuda_actual),0) as total
                    FROM clientes_fiado
                    WHERE proximo_vencimiento < ? AND deuda_actual > 0 AND activo = 1
                """, (hoy,)).fetchone()
            if vencidos['n'] > 0:
                logger.warning(
                    f"ZERO CREDIT: {vencidos['n']} fiados vencidos — ${vencidos['total']:,}"
                )
        except Exception as e:
            logger.debug(f"revisar_fiados_vencidos: {e}")


def start_backup_scheduler(app: Flask):
    try:
        import schedule
        import time
        from utils.backup import ejecutar_backup_completo, obtener_config_backup

        hora_backup = obtener_config_backup().get("backup_hora", "03:00")
        schedule.every().day.at(hora_backup).do(ejecutar_backup_completo)
        schedule.every().day.at("06:00").do(_reset_stock_produccion)
        schedule.every().day.at("08:00").do(revisar_fiados_vencidos, app)
        schedule.every().day.at("23:59").do(calcular_metricas_dia, app)
        schedule.every(60).seconds.do(procesar_cola_impresion, app)
        logger.info("Backup scheduler iniciado (03:00) + reset produccion (06:00) + fiados (08:00) + métricas (23:59) + cola impresión (60s)")

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
        logger.info(f"  QR Clientes:  http://{local_ip}:5000/credit/  (HTTP, sin cert)")
        logger.info(f"  QR antiguos:  http://{local_ip}:5001 → redirect automático a :5000")
    else:
        logger.info("  HTTP (micrófono solo en localhost)")
    logger.info("=" * 60)

    if ssl_ctx:
        from werkzeug.serving import make_server as _ws

        # 1. Servidor HTTPS interno (loopback) — proxeado a través del mux
        _int_port = find_free_port(5099)
        _srv_https = _ws("127.0.0.1", _int_port, app, ssl_context=ssl_ctx)
        threading.Thread(
            target=_srv_https.serve_forever, daemon=True, name="HTTPS-int"
        ).start()
        logger.info(f"Servidor HTTPS interno en 127.0.0.1:{_int_port}")

        # 2. Servidor HTTP en puerto 5000 (para QR de clientes — sin cert)
        def _http_5000(flask_app: Flask) -> None:
            try:
                srv = _ws("0.0.0.0", 5000, flask_app)
                logger.info("Servidor HTTP iniciado en :5000 (QR clientes)")
                srv.serve_forever()
            except Exception as exc:
                logger.warning(f"Servidor HTTP :5000 no disponible: {exc}")

        threading.Thread(
            target=_http_5000, args=(app,), daemon=True, name="HTTP-5000"
        ).start()

        # 3. Mux :5001 — detecta HTTP vs TLS y redirige/proxea (bloquea main thread)
        _run_mux("0.0.0.0", port, _int_port, 5000)
    else:
        try:
            from waitress import serve
            print(f"[ZERO POS] Servidor producción (Waitress) → puerto {port}")
            serve(app, host="0.0.0.0", port=port, threads=8)
        except ImportError:
            print("[ZERO POS] Waitress no disponible, usando Werkzeug")
            app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
