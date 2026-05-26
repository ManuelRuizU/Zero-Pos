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
    conn.execute("PRAGMA cache_size=-32000")   # 32 MB page cache
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=268435456") # 256 MB memory-mapped I/O
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
        _migrate_columns(conn)
        _seed_defaults(conn)

    logger.info(f"Base de datos inicializada: {DB_PATH}")


def _migrate_columns(conn: sqlite3.Connection):
    """Agrega columnas nuevas a tablas existentes sin romper instancias ya creadas."""
    cols_productos  = {r[1] for r in conn.execute("PRAGMA table_info(productos)").fetchall()}
    cols_vitems     = {r[1] for r in conn.execute("PRAGMA table_info(venta_items)").fetchall()}
    cols_aprendizaje = {r[1] for r in conn.execute("PRAGMA table_info(voz_aprendizaje)").fetchall()}

    if "subcategoria_id" not in cols_productos:
        conn.execute("ALTER TABLE productos ADD COLUMN subcategoria_id INTEGER REFERENCES subcategorias(id)")
    if "tiene_variantes" not in cols_productos:
        conn.execute("ALTER TABLE productos ADD COLUMN tiene_variantes INTEGER NOT NULL DEFAULT 0")
    if "variante_id" not in cols_vitems:
        conn.execute("ALTER TABLE venta_items ADD COLUMN variante_id INTEGER REFERENCES producto_variantes(id)")
    if "nombre_variante" not in cols_vitems:
        conn.execute("ALTER TABLE venta_items ADD COLUMN nombre_variante TEXT")
    if "tipo" not in cols_aprendizaje:
        conn.execute("ALTER TABLE voz_aprendizaje ADD COLUMN tipo TEXT NOT NULL DEFAULT 'accion'")


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

    _seed_montos_chilenos(conn)


def _seed_montos_chilenos(conn: sqlite3.Connection):
    """Pre-carga modismos chilenos para montos de dinero (funcionan desde el día 1)."""
    montos = [
        ('die luca',    '10000'), ('die lucas',   '10000'),
        ('vente luca',  '20000'), ('vente lucas', '20000'),
        ('tre luca',    '3000'),  ('tre lucas',   '3000'),
        ('luca y meia', '1500'),  ('meia luca',   '500'),
    ]
    try:
        for palabra, valor in montos:
            conn.execute(
                """INSERT OR IGNORE INTO voz_aprendizaje
                   (palabra, accion, tipo, confirmado, veces_usado)
                   VALUES (?, ?, 'monto', 1, 0)""",
                (palabra, valor),
            )
    except Exception as e:
        logger.debug(f"seed_montos_chilenos: {e}")
