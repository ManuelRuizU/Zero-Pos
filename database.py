import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "zero_pos.db"

logger = logging.getLogger("zero_pos.db")


def pesos(valor) -> int:
    """Convierte cualquier valor monetario a entero CLP (sin decimales)."""
    return int(round(float(valor or 0)))


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
    schema_inv  = BASE_DIR / "models" / "schema_inventario.sql"

    # Bloque 1: schema principal — executescript() maneja sus propios commits
    if schema_main.exists():
        try:
            conn = get_connection()
            conn.executescript(schema_main.read_text())
            conn.close()
        except Exception as e:
            logger.error(f"init_db schema principal: {e}")
            raise

    # Bloque 2: schema inventario — independiente del bloque 1
    if schema_inv.exists():
        try:
            conn = get_connection()
            conn.executescript(schema_inv.read_text())
            conn.close()
        except Exception as e:
            logger.warning(f"init_db schema inventario: {e}")

    # Bloque 3: migraciones y seeds — independiente de los bloques anteriores
    try:
        with db_session() as conn:
            _migrate_montos(conn)
            _migrate_columns(conn)
            _seed_defaults(conn)
    except Exception as e:
        logger.error(f"init_db migraciones/seeds: {e}")
        raise

    # Bloque 4: recreación de tabla pedidos (requiere FK OFF fuera de transacción)
    try:
        conn = get_connection()
        _migrate_pedidos_estados(conn)
        conn.close()
    except Exception as e:
        logger.warning(f"init_db migrate pedidos estados: {e}")

    logger.info(f"Base de datos inicializada: {DB_PATH}")


def _migrate_montos(conn: sqlite3.Connection):
    """Convierte a INTEGER todos los campos monetarios que pudieran tener decimales REAL."""
    stmts = [
        "UPDATE productos          SET precio        = CAST(ROUND(precio)        AS INTEGER) WHERE precio        != CAST(ROUND(precio)        AS INTEGER)",
        "UPDATE productos          SET precio_costo  = CAST(ROUND(precio_costo)  AS INTEGER) WHERE precio_costo  != CAST(ROUND(precio_costo)  AS INTEGER)",
        "UPDATE producto_variantes SET precio        = CAST(ROUND(precio)        AS INTEGER) WHERE precio        != CAST(ROUND(precio)        AS INTEGER)",
        "UPDATE producto_variantes SET precio_costo  = CAST(ROUND(precio_costo)  AS INTEGER) WHERE precio_costo  != CAST(ROUND(precio_costo)  AS INTEGER)",
        "UPDATE ventas             SET total         = CAST(ROUND(total)         AS INTEGER) WHERE total         != CAST(ROUND(total)         AS INTEGER)",
        "UPDATE ventas             SET descuento     = CAST(ROUND(descuento)     AS INTEGER) WHERE descuento     != CAST(ROUND(descuento)     AS INTEGER)",
        "UPDATE ventas             SET impuesto      = CAST(ROUND(impuesto)      AS INTEGER) WHERE impuesto      != CAST(ROUND(impuesto)      AS INTEGER)",
        "UPDATE venta_items        SET precio_unit   = CAST(ROUND(precio_unit)   AS INTEGER) WHERE precio_unit   != CAST(ROUND(precio_unit)   AS INTEGER)",
        "UPDATE venta_items        SET descuento     = CAST(ROUND(descuento)     AS INTEGER) WHERE descuento     != CAST(ROUND(descuento)     AS INTEGER)",
        "UPDATE venta_items        SET subtotal      = CAST(ROUND(subtotal)      AS INTEGER) WHERE subtotal      != CAST(ROUND(subtotal)      AS INTEGER)",
        "UPDATE devoluciones       SET monto         = CAST(ROUND(monto)         AS INTEGER) WHERE monto         != CAST(ROUND(monto)         AS INTEGER)",
        "UPDATE turnos             SET fondo_inicial  = CAST(ROUND(fondo_inicial) AS INTEGER) WHERE fondo_inicial  != CAST(ROUND(fondo_inicial) AS INTEGER)",
        "UPDATE turnos             SET fondo_final    = CAST(ROUND(fondo_final)   AS INTEGER) WHERE fondo_final    != CAST(ROUND(fondo_final)   AS INTEGER)",
        "UPDATE caja_movimientos   SET monto         = CAST(ROUND(monto)         AS INTEGER) WHERE monto         != CAST(ROUND(monto)         AS INTEGER)",
        "UPDATE pagos_khipu        SET monto         = CAST(ROUND(monto)         AS INTEGER) WHERE monto         != CAST(ROUND(monto)         AS INTEGER)",
        "UPDATE clientes           SET total_gastado  = CAST(ROUND(total_gastado) AS INTEGER) WHERE total_gastado  != CAST(ROUND(total_gastado) AS INTEGER)",
        "UPDATE pedidos            SET total         = CAST(ROUND(total)         AS INTEGER) WHERE total         != CAST(ROUND(total)         AS INTEGER)",
        "UPDATE pedido_items       SET precio        = CAST(ROUND(precio)        AS INTEGER) WHERE precio        != CAST(ROUND(precio)        AS INTEGER)",
        "UPDATE pedido_items       SET subtotal      = CAST(ROUND(subtotal)      AS INTEGER) WHERE subtotal      != CAST(ROUND(subtotal)      AS INTEGER)",
        "UPDATE ordenes_compra     SET total         = CAST(ROUND(total)         AS INTEGER) WHERE total         != CAST(ROUND(total)         AS INTEGER)",
        "UPDATE orden_items        SET precio_unit   = CAST(ROUND(precio_unit)   AS INTEGER) WHERE precio_unit   != CAST(ROUND(precio_unit)   AS INTEGER)",
        "UPDATE orden_items        SET subtotal      = CAST(ROUND(subtotal)      AS INTEGER) WHERE subtotal      != CAST(ROUND(subtotal)      AS INTEGER)",
        "UPDATE facturas_proveedor SET total         = CAST(ROUND(total)         AS INTEGER) WHERE total         != CAST(ROUND(total)         AS INTEGER)",
    ]
    for stmt in stmts:
        try:
            conn.execute(stmt)
        except Exception as e:
            logger.debug(f"migrate_montos skip: {e}")


def _migrate_pedidos_estados(conn: sqlite3.Connection):
    """Recrea tabla pedidos si el CHECK constraint no incluye 'en_espera'."""
    # Verificar si ya soporta en_espera usando SAVEPOINT
    try:
        conn.execute("SAVEPOINT _chk_en_espera")
        conn.execute(
            "INSERT INTO pedidos (numero, tipo, estado, origen, cliente_nombre, total, metodo_pago, usuario_id)"
            " VALUES (-99, 'local', 'en_espera', 'pos', '_test_', 0, 'efectivo', 1)"
        )
        conn.execute("DELETE FROM pedidos WHERE numero=-99 AND cliente_nombre='_test_'")
        conn.execute("RELEASE SAVEPOINT _chk_en_espera")
        # Asegurar columna 'origen' si no existe (puede existir sin constraint)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(pedidos)").fetchall()}
        if "origen" not in cols:
            conn.execute("ALTER TABLE pedidos ADD COLUMN origen TEXT NOT NULL DEFAULT 'pos'")
            conn.commit()
        return
    except Exception:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT _chk_en_espera")
        except Exception:
            pass

    # Recrear tabla con nuevo CHECK constraint (requiere FK OFF)
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.executescript("""
        CREATE TABLE _pedidos_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            numero          INTEGER NOT NULL,
            tipo            TEXT NOT NULL,
            estado          TEXT NOT NULL DEFAULT 'nuevo',
            origen          TEXT NOT NULL DEFAULT 'pos',
            cliente_id      INTEGER,
            cliente_nombre  TEXT NOT NULL DEFAULT '',
            cliente_tel     TEXT,
            cliente_tel2    TEXT,
            cliente_email   TEXT,
            direccion       TEXT,
            depto           TEXT,
            referencia      TEXT,
            comuna          TEXT,
            notas           TEXT,
            total           INTEGER NOT NULL DEFAULT 0,
            metodo_pago     TEXT NOT NULL DEFAULT 'efectivo',
            usuario_id      INTEGER,
            creado_en       DATETIME DEFAULT CURRENT_TIMESTAMP,
            actualizado_en  DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO _pedidos_new
            (id,numero,tipo,estado,cliente_id,cliente_nombre,cliente_tel,
             cliente_tel2,cliente_email,direccion,depto,referencia,
             comuna,notas,total,metodo_pago,usuario_id,creado_en,actualizado_en)
        SELECT id,numero,tipo,estado,cliente_id,cliente_nombre,cliente_tel,
               cliente_tel2,cliente_email,direccion,depto,referencia,
               comuna,notas,total,metodo_pago,usuario_id,creado_en,actualizado_en
        FROM pedidos;
        DROP TABLE pedidos;
        ALTER TABLE _pedidos_new RENAME TO pedidos;
        CREATE INDEX IF NOT EXISTS idx_pedidos_estado  ON pedidos(estado);
        CREATE INDEX IF NOT EXISTS idx_pedidos_fecha   ON pedidos(creado_en);
        CREATE INDEX IF NOT EXISTS idx_pedidos_cliente ON pedidos(cliente_id);
    """)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    logger.info("Tabla pedidos recreada con estados en_espera/completado")


def _migrate_columns(conn: sqlite3.Connection):
    """Agrega columnas e índices nuevos a tablas existentes sin romper instancias ya creadas."""
    cols_productos   = {r[1] for r in conn.execute("PRAGMA table_info(productos)").fetchall()}
    cols_vitems      = {r[1] for r in conn.execute("PRAGMA table_info(venta_items)").fetchall()}
    cols_aprendizaje = {r[1] for r in conn.execute("PRAGMA table_info(voz_aprendizaje)").fetchall()}
    cols_ventas      = {r[1] for r in conn.execute("PRAGMA table_info(ventas)").fetchall()}

    if "subcategoria_id" not in cols_productos:
        conn.execute("ALTER TABLE productos ADD COLUMN subcategoria_id INTEGER REFERENCES subcategorias(id)")
    if "tiene_variantes" not in cols_productos:
        conn.execute("ALTER TABLE productos ADD COLUMN tiene_variantes INTEGER NOT NULL DEFAULT 0")
    if "es_granel" not in cols_productos:
        conn.execute("ALTER TABLE productos ADD COLUMN es_granel INTEGER NOT NULL DEFAULT 0")
    if "unidad_medida" not in cols_productos:
        conn.execute("ALTER TABLE productos ADD COLUMN unidad_medida TEXT NOT NULL DEFAULT 'unidad'")
    if "precio_por" not in cols_productos:
        conn.execute("ALTER TABLE productos ADD COLUMN precio_por TEXT NOT NULL DEFAULT 'unidad'")
    if "variante_id" not in cols_vitems:
        conn.execute("ALTER TABLE venta_items ADD COLUMN variante_id INTEGER REFERENCES producto_variantes(id)")
    if "nombre_variante" not in cols_vitems:
        conn.execute("ALTER TABLE venta_items ADD COLUMN nombre_variante TEXT")
    if "tipo" not in cols_aprendizaje:
        conn.execute("ALTER TABLE voz_aprendizaje ADD COLUMN tipo TEXT NOT NULL DEFAULT 'accion'")
    if "pedido_id" not in cols_ventas:
        conn.execute("ALTER TABLE ventas ADD COLUMN pedido_id INTEGER REFERENCES pedidos(id)")

    # Unique index en voz_sinonimos_variante — silencioso si ya existe o hay duplicados
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_vsv_unique "
            "ON voz_sinonimos_variante(palabra, producto_id, variante_id)"
        )
    except Exception as e:
        logger.debug(f"migrate idx_vsv_unique: {e}")


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

    import bcrypt
    pin_default = b"1234"
    hashed = bcrypt.hashpw(pin_default, bcrypt.gensalt()).decode()
    conn.execute(
        """INSERT OR IGNORE INTO usuarios (nombre, pin_hash, rol, activo)
           VALUES (?, ?, ?, 1)""",
        ("Admin", hashed, "admin")
    )
    if conn.execute("SELECT changes()").fetchone()[0]:
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
