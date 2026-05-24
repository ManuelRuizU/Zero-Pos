import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "zero_pos.db"

logger = logging.getLogger("zero_pos.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-32000")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


@contextmanager
def db_session():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    schema_main = BASE_DIR / "models" / "schema.sql"
    schema_inv = BASE_DIR / "models" / "schema_inventario.sql"

    with db_session() as conn:
        if schema_main.exists():
            conn.executescript(schema_main.read_text())
        if schema_inv.exists():
            conn.executescript(schema_inv.read_text())
        _seed_defaults(conn)

    logger.info(f"Base de datos inicializada: {DB_PATH}")


def _seed_defaults(conn: sqlite3.Connection):
    """Inserta configuración inicial solo si la tabla está vacía."""
    existing = conn.execute("SELECT COUNT(*) FROM config").fetchone()[0]
    if existing == 0:
        conn.execute(
            "INSERT INTO config (clave, valor) VALUES (?, ?)",
            ("nombre_negocio", "Mi Negocio")
        )
        conn.execute(
            "INSERT INTO config (clave, valor) VALUES (?, ?)",
            ("moneda", "CLP")
        )
        conn.execute(
            "INSERT INTO config (clave, valor) VALUES (?, ?)",
            ("iva_porcentaje", "19")
        )
        logger.info("Configuración inicial insertada")

    existing_pin = conn.execute(
        "SELECT COUNT(*) FROM usuarios WHERE rol = 'admin'"
    ).fetchone()[0]
    if existing_pin == 0:
        import bcrypt
        pin_default = b"1234"
        hashed = bcrypt.hashpw(pin_default, bcrypt.gensalt()).decode()
        conn.execute(
            """INSERT INTO usuarios (nombre, pin_hash, rol, activo)
               VALUES (?, ?, ?, 1)""",
            ("Admin", hashed, "admin")
        )
        logger.info("Usuario admin creado con PIN por defecto: 1234")
