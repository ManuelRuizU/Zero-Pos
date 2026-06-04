import io
import os
import shutil
import zipfile
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("zero_pos.backup")
BASE_DIR = Path(__file__).parent.parent


def _backup_dir() -> Path:
    d = BASE_DIR / "backups"
    d.mkdir(exist_ok=True)
    return d


def crear_backup_cifrado() -> dict:
    db_path = BASE_DIR / "zero_pos.db"
    if not db_path.exists():
        return {"ok": False, "error": "Base de datos no encontrada"}

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"backup_{timestamp}.zip"
    destino = _backup_dir() / nombre

    try:
        clave = _leer_clave_cifrado()
        datos_db = db_path.read_bytes()
        datos_cifrados = _cifrar(datos_db, clave)

        with zipfile.ZipFile(str(destino), "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("zero_pos.db.enc", datos_cifrados)
            zf.writestr("meta.txt", f"ZERO POS Backup\nFecha: {timestamp}\n")

        logger.info(f"Backup creado: {nombre} ({destino.stat().st_size // 1024} KB)")
        return {"ok": True, "nombre": nombre, "tamaño_kb": round(destino.stat().st_size / 1024, 1)}
    except Exception as e:
        logger.error(f"Error backup: {e}")
        return {"ok": False, "error": str(e)}


def restaurar_backup_cifrado(archivo) -> dict:
    try:
        clave = _leer_clave_cifrado()
        contenido = archivo.read()

        with zipfile.ZipFile(io.BytesIO(contenido)) as zf:
            if "zero_pos.db.enc" not in zf.namelist():
                return {"ok": False, "error": "Archivo de backup inválido"}
            datos_cifrados = zf.read("zero_pos.db.enc")

        datos_db = _descifrar(datos_cifrados, clave)
        db_path = BASE_DIR / "zero_pos.db"
        backup_prev = BASE_DIR / "zero_pos.db.prev"
        if db_path.exists():
            db_path.rename(backup_prev)

        db_path.write_bytes(datos_db)
        logger.info("Base de datos restaurada desde backup")
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error restaurar: {e}")
        return {"ok": False, "error": str(e)}


def run_scheduled_backup(app=None):
    logger.info("Ejecutando backup programado...")
    resultado = crear_backup_cifrado()
    if resultado["ok"]:
        _limpiar_backups_antiguos()
    return resultado


def _limpiar_backups_antiguos(mantener: int = 7):
    d = _backup_dir()
    archivos = sorted(d.glob("backup_*.zip"), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in archivos[mantener:]:
        f.unlink()
        logger.info(f"Backup antiguo eliminado: {f.name}")


def _leer_clave_cifrado() -> bytes:
    clave_file = BASE_DIR / ".backup_key"
    if clave_file.exists():
        key = clave_file.read_bytes()
        if len(key) == 32:
            return key
    import os
    key = os.urandom(32)
    clave_file.write_bytes(key)
    clave_file.chmod(0o600)
    return key


def _cifrar(datos: bytes, clave: bytes) -> bytes:
    try:
        from cryptography.fernet import Fernet
        import base64
        import hashlib
        key_b64 = base64.urlsafe_b64encode(hashlib.sha256(clave).digest())
        f = Fernet(key_b64)
        return f.encrypt(datos)
    except ImportError:
        logger.warning("cryptography no instalado — backup sin cifrado")
        return datos


def _descifrar(datos: bytes, clave: bytes) -> bytes:
    try:
        from cryptography.fernet import Fernet
        import base64
        import hashlib
        key_b64 = base64.urlsafe_b64encode(hashlib.sha256(clave).digest())
        f = Fernet(key_b64)
        return f.decrypt(datos)
    except ImportError:
        return datos


# ─── Pendrive ────────────────────────────────────────────────────────────────

def detectar_pendrives() -> list:
    """Detecta pendrives montados en Linux (/media, /mnt)."""
    posibles = []
    for base in ['/media', '/mnt']:
        if not os.path.exists(base):
            continue
        try:
            for d in os.listdir(base):
                ruta = os.path.join(base, d)
                if os.path.ismount(ruta):
                    posibles.append(ruta)
                if os.path.isdir(ruta):
                    try:
                        for sub in os.listdir(ruta):
                            subruta = os.path.join(ruta, sub)
                            if os.path.ismount(subruta):
                                posibles.append(subruta)
                    except PermissionError:
                        pass
        except PermissionError:
            pass
    return posibles


def backup_a_pendrive(db_path, backup_nombre) -> bool:
    pendrives = detectar_pendrives()
    if not pendrives:
        logger.warning("No se encontró pendrive montado")
        return False
    for pendrive in pendrives:
        destino_dir = os.path.join(pendrive, 'ZERO_BACKUP')
        os.makedirs(destino_dir, exist_ok=True)
        destino = os.path.join(destino_dir, backup_nombre)
        shutil.copy2(str(db_path), destino)
        logger.info(f"Backup copiado al pendrive: {destino}")
        return True
    return False


# ─── Email ───────────────────────────────────────────────────────────────────

SMTP_PROVIDERS = {
    'gmail': {
        'host': 'smtp.gmail.com', 'port': 587, 'nombre': 'Gmail', 'icono': '📧',
        'instrucciones': (
            'Necesitas una "Contraseña de aplicación".\n'
            'Gmail → Cuenta → Seguridad → Verificación en dos pasos → Contraseñas de aplicaciones'
        ),
    },
    'outlook': {
        'host': 'smtp.office365.com', 'port': 587, 'nombre': 'Outlook / Hotmail', 'icono': '📨',
        'instrucciones': 'Usa tu contraseña normal de Outlook.',
    },
    'yahoo': {
        'host': 'smtp.mail.yahoo.com', 'port': 587, 'nombre': 'Yahoo Mail', 'icono': '📩',
        'instrucciones': 'Genera una contraseña de aplicación en Yahoo → Seguridad.',
    },
    'custom': {
        'host': '', 'port': 587, 'nombre': 'Otro servidor SMTP', 'icono': '⚙️',
        'instrucciones': 'Ingresa los datos de tu servidor SMTP.',
    },
}


def obtener_config_smtp() -> dict | None:
    """Lee la config SMTP desde la base de datos."""
    try:
        from database import db_session
        with db_session() as conn:
            rows = conn.execute(
                "SELECT clave, valor FROM config "
                "WHERE clave IN ('smtp_host','smtp_port','smtp_user','smtp_password','smtp_from','nombre_negocio')"
            ).fetchall()
        cfg = {r['clave']: r['valor'] for r in rows}
        if not cfg.get('smtp_host') or not cfg.get('smtp_user') or not cfg.get('smtp_password'):
            return None
        if not cfg.get('smtp_from'):
            cfg['smtp_from'] = cfg['smtp_user']
        return cfg
    except Exception as e:
        logger.error(f"obtener_config_smtp: {e}")
        return None


def backup_por_email(db_path, backup_nombre: str, email_destino: str) -> tuple[bool, str]:
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email.mime.text import MIMEText
        from email import encoders
        import gzip
        from datetime import date

        config = obtener_config_smtp()
        if not config:
            logger.error("SMTP no configurado")
            return False, "smtp_no_configurado"

        with open(str(db_path), 'rb') as f:
            datos = f.read()

        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode='wb') as gz:
            gz.write(datos)
        datos_gz = buf.getvalue()

        tamaño_mb = len(datos_gz) / (1024 * 1024)
        if tamaño_mb > 20:
            logger.warning(f"Backup muy grande para email: {tamaño_mb:.1f}MB. Recomendando rclone.")
            return False, "muy_grande"

        msg = MIMEMultipart()
        msg['From'] = config['smtp_from']
        msg['To'] = email_destino
        msg['Subject'] = f"ZERO POS — Backup {date.today()}"

        cuerpo = (
            f"Respaldo automático de ZERO POS.\n\n"
            f"Fecha: {date.today()}\n"
            f"Negocio: {config.get('nombre_negocio', 'Mi negocio')}\n"
            f"Archivo: {backup_nombre}.gz\n\n"
            "Guarda este correo en un lugar seguro.\n— ZERO POS"
        )
        msg.attach(MIMEText(cuerpo, 'plain'))

        adjunto = MIMEBase('application', 'octet-stream')
        adjunto.set_payload(datos_gz)
        encoders.encode_base64(adjunto)
        adjunto.add_header('Content-Disposition', f'attachment; filename="{backup_nombre}.gz"')
        msg.attach(adjunto)

        with smtplib.SMTP(config['smtp_host'], int(config.get('smtp_port', 587))) as server:
            server.starttls()
            password = config['smtp_password'].replace(' ', '')
            server.login(config['smtp_user'], password)
            server.send_message(msg)

        logger.info(f"Backup enviado por email a {email_destino}")
        return True, "ok"
    except Exception as e:
        logger.error(f"Error enviando backup por email: {e}")
        return False, str(e)


# ─── rclone (Google Drive / OneDrive) ────────────────────────────────────────

def backup_rclone(db_path, backup_nombre: str, remote_name: str = 'gdrive') -> tuple[bool, str]:
    import subprocess
    result = subprocess.run(['rclone', 'version'], capture_output=True)
    if result.returncode != 0:
        logger.warning("rclone no instalado")
        return False, "rclone no instalado"

    destino = f"{remote_name}:ZERO_BACKUP/"
    result = subprocess.run(
        ['rclone', 'copy', str(db_path), destino, '--log-level', 'INFO'],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode == 0:
        logger.info(f"Backup subido a {destino}")
        return True, "ok"
    else:
        logger.error(f"Error rclone: {result.stderr}")
        return False, result.stderr


# ─── Orquestador ─────────────────────────────────────────────────────────────

def obtener_config_backup() -> dict:
    """Lee toda la configuración de backup desde la base de datos."""
    try:
        from database import db_session
        with db_session() as conn:
            rows = conn.execute(
                "SELECT clave, valor FROM config "
                "WHERE clave LIKE 'backup_%' OR clave LIKE 'smtp_%'"
            ).fetchall()
        cfg = {r['clave']: r['valor'] for r in rows}
        destinos_str = cfg.get('backup_destinos', 'local')
        cfg['destinos'] = [d.strip() for d in destinos_str.split(',') if d.strip()]
        return cfg
    except Exception as e:
        logger.error(f"obtener_config_backup: {e}")
        return {'destinos': ['local']}


def ejecutar_backup_completo(app=None) -> dict:
    """Backup a todos los destinos activos configurados."""
    from datetime import date as _date
    logger.info("Ejecutando backup completo programado...")

    config = obtener_config_backup()
    destinos = config.get('destinos', ['local'])
    backup_nombre = f"zero_backup_{_date.today()}.db"
    db_path = BASE_DIR / "zero_pos.db"

    resultados: dict = {}

    if 'local' in destinos:
        r = crear_backup_cifrado()
        resultados['local'] = r.get('ok', False)
        if r.get('ok'):
            _limpiar_backups_antiguos(int(config.get('backup_retener_dias', 7)))

    if 'pendrive' in destinos:
        resultados['pendrive'] = backup_a_pendrive(db_path, backup_nombre)

    if 'email' in destinos and config.get('backup_email_destino'):
        ok, _ = backup_por_email(db_path, backup_nombre, config['backup_email_destino'])
        resultados['email'] = ok

    if 'rclone' in destinos:
        remote = config.get('backup_rclone_remote', 'gdrive')
        ok, _ = backup_rclone(db_path, backup_nombre, remote)
        resultados['rclone'] = ok

    logger.info(f"Backup completo finalizado: {resultados}")
    return resultados
