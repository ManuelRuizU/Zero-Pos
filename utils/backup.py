import io
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
