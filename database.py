import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "zero_pos.db"

logger = logging.getLogger("zero_pos.db")


def ensure_column(conn, tabla: str, columna: str, tipo: str, default: str = None) -> bool:
    """Agrega una columna a una tabla si no existe. Retorna True si la agregó."""
    try:
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({tabla})")]
        if columna not in cols:
            sql = f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}"
            if default is not None:
                sql += f" DEFAULT {default}"
            conn.execute(sql)
            logger.info(f"DB: columna {tabla}.{columna} agregada")
            return True
        return False
    except Exception as e:
        logger.warning(f"DB: error ensure_column {tabla}.{columna}: {e}")
        return False


def ensure_index(conn, nombre: str, tabla: str, columnas: str) -> bool:
    """Crea un índice si no existe. columnas: string con columnas separadas por coma."""
    try:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {nombre} ON {tabla} ({columnas})")
        return True
    except Exception as e:
        logger.warning(f"DB: error ensure_index {nombre}: {e}")
        return False


def log_event(conn, entidad: str, accion: str,
              entidad_id: int = None,
              payload: dict = None,
              usuario_id: int = None,
              usuario_nombre: str = None,
              device_id: str = None):
    """Registra un evento en event_log (auditoría no bloqueante)."""
    import json
    try:
        conn.execute(
            """INSERT INTO event_log
               (entidad, entidad_id, accion, payload,
                usuario_id, usuario_nombre, device_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (entidad, entidad_id, accion,
             json.dumps(payload, ensure_ascii=False) if payload else None,
             usuario_id, usuario_nombre, device_id)
        )
    except Exception as e:
        logger.warning(f"event_log: error registrando {entidad}.{accion}: {e}")


def pesos(valor) -> int:
    """Convierte cualquier valor monetario a entero CLP (sin decimales)."""
    return int(round(float(valor or 0)))


def registrar_movimiento_stock(conn, producto_id, variante_id, tipo, cantidad,
                                motivo, usuario_id=None, *, venta_id=None,
                                pedido_id=None, compra_id=None, devolucion_id=None,
                                notas=None):
    """Actualiza stock Y registra trazabilidad en stock_movimientos.

    tipo: 'salida' | 'entrada' | 'devolucion' | 'ajuste'
    Para 'ajuste', cantidad es el nuevo stock absoluto.
    """
    if variante_id:
        row = conn.execute(
            "SELECT stock FROM producto_variantes WHERE id=?", (variante_id,)
        ).fetchone()
        stock_antes = int(row["stock"]) if row else 0
        if tipo == "salida":
            conn.execute("UPDATE producto_variantes SET stock=stock-? WHERE id=?",
                         (cantidad, variante_id))
            stock_despues = stock_antes - cantidad
        elif tipo == "ajuste":
            conn.execute("UPDATE producto_variantes SET stock=? WHERE id=?",
                         (cantidad, variante_id))
            stock_despues = cantidad
            cantidad = abs(cantidad - stock_antes)
        else:
            conn.execute("UPDATE producto_variantes SET stock=stock+? WHERE id=?",
                         (cantidad, variante_id))
            stock_despues = stock_antes + cantidad
    else:
        row = conn.execute(
            "SELECT stock FROM productos WHERE id=?", (producto_id,)
        ).fetchone()
        stock_antes = int(row["stock"]) if row else 0
        if tipo == "salida":
            conn.execute(
                "UPDATE productos SET stock=stock-?, actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
                (cantidad, producto_id))
            stock_despues = stock_antes - cantidad
        elif tipo == "ajuste":
            conn.execute(
                "UPDATE productos SET stock=?, actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
                (cantidad, producto_id))
            stock_despues = cantidad
            cantidad = abs(cantidad - stock_antes)
        else:
            conn.execute(
                "UPDATE productos SET stock=stock+?, actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
                (cantidad, producto_id))
            stock_despues = stock_antes + cantidad

    try:
        conn.execute("""
            INSERT INTO stock_movimientos
                (producto_id, variante_id, tipo, cantidad, motivo, usuario_id,
                 stock_antes, stock_despues, venta_id, pedido_id, compra_id, devolucion_id, notas)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (producto_id, variante_id, tipo, cantidad, motivo, usuario_id,
              stock_antes, stock_despues, venta_id, pedido_id, compra_id, devolucion_id, notas))
    except Exception:
        conn.execute(
            "INSERT INTO stock_movimientos (producto_id, tipo, cantidad, motivo, usuario_id)"
            " VALUES (?,?,?,?,?)",
            (producto_id, tipo, cantidad, motivo, usuario_id)
        )


def actualizar_proveedor_producto(conn, proveedor_id, producto_id, precio_compra, fecha=None):
    """Upsert en proveedor_productos con el precio y fecha de la última compra."""
    from datetime import date as _date
    if fecha is None:
        fecha = _date.today().isoformat()
    try:
        conn.execute("""
            INSERT INTO proveedor_productos
                (proveedor_id, producto_id, precio_ultima_compra, fecha_ultima_compra,
                 precio_referencia)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(proveedor_id, producto_id) DO UPDATE SET
                precio_ultima_compra = excluded.precio_ultima_compra,
                fecha_ultima_compra  = excluded.fecha_ultima_compra,
                precio_referencia    = COALESCE(precio_referencia, excluded.precio_ultima_compra)
        """, (proveedor_id, producto_id, precio_compra, fecha, precio_compra))
    except Exception as e:
        logger.debug(f"actualizar_proveedor_producto: {e}")


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


# ── P0.4: Sistema de migraciones versionado ───────────────────────────────────

def _m001_stock_trazabilidad(conn):
    """Añade columnas de trazabilidad a stock_movimientos."""
    for col, defn in [
        ("variante_id",   "INTEGER"),
        ("stock_antes",   "INTEGER"),
        ("stock_despues", "INTEGER"),
        ("venta_id",      "INTEGER"),
        ("pedido_id",     "INTEGER"),
        ("compra_id",     "INTEGER"),
        ("devolucion_id", "INTEGER"),
        ("notas",         "TEXT"),
    ]:
        ensure_column(conn, 'stock_movimientos', col, defn)
    ensure_index(conn, 'idx_smov_venta', 'stock_movimientos', 'venta_id')
    ensure_index(conn, 'idx_smov_compra', 'stock_movimientos', 'compra_id')


def _m002_proveedor_productos(conn):
    """Crea tabla proveedor_productos si no existe."""
    conn.execute("""CREATE TABLE IF NOT EXISTS proveedor_productos (
        id                    INTEGER PRIMARY KEY AUTOINCREMENT,
        proveedor_id          INTEGER NOT NULL REFERENCES proveedores(id),
        producto_id           INTEGER NOT NULL REFERENCES productos(id),
        codigo_proveedor      TEXT,
        precio_referencia     INTEGER,
        precio_ultima_compra  INTEGER,
        fecha_ultima_compra   DATE,
        unidad_compra         TEXT DEFAULT 'unidad',
        minimo_pedido         INTEGER DEFAULT 1,
        activo                INTEGER NOT NULL DEFAULT 1,
        UNIQUE(proveedor_id, producto_id)
    )""")
    ensure_index(conn, 'idx_pp_proveedor', 'proveedor_productos', 'proveedor_id')
    ensure_index(conn, 'idx_pp_producto', 'proveedor_productos', 'producto_id')


def _m003_indices_analiticos(conn):
    """Índices para queries de reportes y analíticas."""
    for name, tabla, defn in [
        ("idx_ventas_fecha_total",   "ventas",           "(creado_en, total)"),
        ("idx_vitems_producto",      "venta_items",      "(producto_id)"),
        ("idx_productos_categoria",  "productos",        "(categoria_id) WHERE activo=1"),
        ("idx_productos_stock_bajo", "productos",        "(stock, stock_minimo) WHERE activo=1"),
        ("idx_smov_prod_fecha",      "stock_movimientos","(producto_id, creado_en)"),
    ]:
        try:
            conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {tabla}{defn}")
        except Exception:
            pass


def _m007_lotes_vencimientos(conn):
    """Crea tablas de lotes y mermas; agrega columnas de soporte en productos y venta_items."""
    conn.execute("""CREATE TABLE IF NOT EXISTS lotes (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id       INTEGER NOT NULL REFERENCES productos(id),
        numero_lote       TEXT,
        cantidad_inicial  INTEGER NOT NULL DEFAULT 0,
        cantidad_actual   INTEGER NOT NULL DEFAULT 0,
        fecha_vencimiento DATE,
        estado            TEXT NOT NULL DEFAULT 'activo'
                          CHECK(estado IN ('activo','agotado','vencido','retirado')),
        notas             TEXT,
        creado_en         DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS mermas (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        lote_id     INTEGER REFERENCES lotes(id),
        producto_id INTEGER NOT NULL REFERENCES productos(id),
        cantidad    INTEGER NOT NULL DEFAULT 1,
        motivo      TEXT NOT NULL DEFAULT 'vencimiento',
        usuario_id  INTEGER REFERENCES usuarios(id),
        notas       TEXT,
        creado_en   DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    ensure_index(conn, 'idx_lotes_producto', 'lotes', 'producto_id, estado')
    ensure_index(conn, 'idx_lotes_venc', 'lotes', 'fecha_vencimiento')
    ensure_index(conn, 'idx_mermas_producto', 'mermas', 'producto_id')

    # Columna tiene_lotes en productos (0 = sin control de lotes, 1 = activado)
    ensure_column(conn, 'productos', 'tiene_lotes', 'INTEGER NOT NULL DEFAULT 0')

    # Columna lote_id en venta_items para trazabilidad
    ensure_column(conn, 'venta_items', 'lote_id', 'INTEGER REFERENCES lotes(id)')


def _m006_cola_impresion(conn):
    """Crea tabla de cola de impresión persistente."""
    conn.execute("""CREATE TABLE IF NOT EXISTS cola_impresion (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        venta_id       INTEGER REFERENCES ventas(id),
        contenido      TEXT NOT NULL,
        intentos       INTEGER DEFAULT 0,
        estado         TEXT DEFAULT 'pendiente'
                       CHECK(estado IN ('pendiente','imprimiendo','completado','fallido')),
        impresora_id   TEXT,
        error_msg      TEXT,
        creado_en      DATETIME DEFAULT CURRENT_TIMESTAMP,
        actualizado_en DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    ensure_index(conn, 'idx_cola_estado', 'cola_impresion', 'estado, creado_en')


def _m004_metricas_agregadas(conn):
    """Crea tablas de métricas precalculadas si no existen."""
    conn.execute("""CREATE TABLE IF NOT EXISTS metricas_diarias (
        id                    INTEGER PRIMARY KEY,
        fecha                 DATE NOT NULL UNIQUE,
        total_ventas          INTEGER DEFAULT 0,
        num_ventas            INTEGER DEFAULT 0,
        ticket_promedio       INTEGER DEFAULT 0,
        total_pedidos         INTEGER DEFAULT 0,
        producto_top_id       INTEGER REFERENCES productos(id),
        producto_top_nombre   TEXT,
        producto_top_cant     INTEGER DEFAULT 0,
        metodo_efectivo       INTEGER DEFAULT 0,
        metodo_tarjeta        INTEGER DEFAULT 0,
        metodo_transferencia  INTEGER DEFAULT 0,
        creado_en             DATETIME DEFAULT CURRENT_TIMESTAMP,
        actualizado_en        DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS metricas_semanales (
        id              INTEGER PRIMARY KEY,
        anio            INTEGER NOT NULL,
        semana          INTEGER NOT NULL,
        fecha_inicio    DATE NOT NULL,
        fecha_fin       DATE NOT NULL,
        total_ventas    INTEGER DEFAULT 0,
        num_ventas      INTEGER DEFAULT 0,
        ticket_promedio INTEGER DEFAULT 0,
        dia_mejor       TEXT,
        dia_mejor_total INTEGER DEFAULT 0,
        UNIQUE(anio, semana)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS metricas_mensuales (
        id              INTEGER PRIMARY KEY,
        anio            INTEGER NOT NULL,
        mes             INTEGER NOT NULL,
        total_ventas    INTEGER DEFAULT 0,
        num_ventas      INTEGER DEFAULT 0,
        ticket_promedio INTEGER DEFAULT 0,
        crecimiento_pct REAL DEFAULT 0,
        UNIQUE(anio, mes)
    )""")


def _m005_usuarios_permisos_sucursal(conn):
    """Agrega sucursal_id y permisos a usuarios."""
    ensure_column(conn, 'usuarios', 'sucursal_id', 'INTEGER REFERENCES sucursales(id)')
    ensure_column(conn, 'usuarios', 'permisos', 'TEXT', 'NULL')


def _m008_vocabulario_local(conn):
    """Vocabulario coloquial aprendido: expresiones libres → producto/consulta."""
    conn.execute("""CREATE TABLE IF NOT EXISTS vocabulario_local (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        expresion    TEXT NOT NULL UNIQUE,
        producto_id  INTEGER REFERENCES productos(id),
        categoria    TEXT,
        consulta_tipo TEXT,
        usos         INTEGER NOT NULL DEFAULT 1,
        creado_en    DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_vocab_expresion ON vocabulario_local(expresion)"
    )


def _m010_zero_credit(conn):
    """ZERO CREDIT — sistema de fiado avanzado."""
    conn.execute("""CREATE TABLE IF NOT EXISTS clientes_fiado (
        id                  INTEGER PRIMARY KEY,
        nombre              TEXT NOT NULL,
        apellido            TEXT,
        telefono            TEXT,
        email               TEXT,
        direccion           TEXT,
        rut                 TEXT,
        limite_credito      INTEGER DEFAULT 10000,
        deuda_actual        INTEGER DEFAULT 0,
        frecuencia_pago     TEXT DEFAULT 'mensual' CHECK(frecuencia_pago IN ('semanal','quincenal','mensual','fecha_fija')),
        fecha_pago_fija     DATE,
        proximo_vencimiento DATE,
        qr_token            TEXT UNIQUE NOT NULL,
        activo              INTEGER DEFAULT 1,
        puntos              INTEGER DEFAULT 0,
        total_compras       INTEGER DEFAULT 0,
        total_abonos        INTEGER DEFAULT 0,
        notas               TEXT,
        creado_en           DATETIME DEFAULT CURRENT_TIMESTAMP,
        actualizado_en      DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS fiado_movimientos (
        id            INTEGER PRIMARY KEY,
        cliente_id    INTEGER NOT NULL REFERENCES clientes_fiado(id),
        venta_id      INTEGER REFERENCES ventas(id),
        tipo          TEXT NOT NULL CHECK(tipo IN ('cargo','abono','ajuste')),
        monto         INTEGER NOT NULL,
        deuda_antes   INTEGER NOT NULL,
        deuda_despues INTEGER NOT NULL,
        descripcion   TEXT,
        usuario_id    INTEGER REFERENCES usuarios(id),
        creado_en     DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fiado_cliente ON fiado_movimientos(cliente_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fiado_vencimiento ON clientes_fiado(proximo_vencimiento)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fiado_deuda ON clientes_fiado(deuda_actual) WHERE deuda_actual > 0")


def _m009_modificadores(conn):
    """Modificadores (toppings, salsas, puntos cocción) para sushi/food trucks."""
    conn.execute("""CREATE TABLE IF NOT EXISTS modificadores (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre    TEXT NOT NULL,
        tipo      TEXT NOT NULL DEFAULT 'opcional' CHECK(tipo IN ('opcional','obligatorio')),
        seleccion TEXT NOT NULL DEFAULT 'unico'    CHECK(seleccion IN ('unico','multiple')),
        activo    INTEGER NOT NULL DEFAULT 1,
        creado_en DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS modificador_opciones (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        modificador_id INTEGER NOT NULL REFERENCES modificadores(id) ON DELETE CASCADE,
        nombre         TEXT NOT NULL,
        precio_extra   INTEGER NOT NULL DEFAULT 0
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS producto_modificadores (
        producto_id    INTEGER NOT NULL REFERENCES productos(id)    ON DELETE CASCADE,
        modificador_id INTEGER NOT NULL REFERENCES modificadores(id) ON DELETE CASCADE,
        PRIMARY KEY (producto_id, modificador_id)
    )""")
    # Columna tiene_modificadores en productos para evitar join en listado POS
    ensure_column(conn, 'productos', 'tiene_modificadores', 'INTEGER NOT NULL DEFAULT 0')
    # Columna modificadores_desc en venta_items para persistir selecciones en ticket
    ensure_column(conn, 'venta_items', 'modificadores_desc', 'TEXT')


def _m011_dia_pago(conn):
    """Agrega columna dia_pago a clientes_fiado para cobros mensuales en día fijo."""
    ensure_column(conn, 'clientes_fiado', 'dia_pago', 'INTEGER', '15')


def _m012_publicidad(conn):
    """Tabla publicidad: slides configurables para pantalla cliente."""
    conn.execute("""CREATE TABLE IF NOT EXISTS publicidad (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        titulo      TEXT    DEFAULT '',
        subtitulo   TEXT    DEFAULT '',
        imagen_url  TEXT,
        color       TEXT    DEFAULT '#6366f1',
        color2      TEXT    DEFAULT '#8b5cf6',
        orden       INTEGER DEFAULT 0,
        activo      INTEGER DEFAULT 1,
        duracion    INTEGER DEFAULT 5,
        creado_en   DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")


def _m013_publicidad_plantillas(conn):
    """Agrega columnas plantilla_id y datos_plantilla a publicidad."""
    ensure_column(conn, 'publicidad', 'plantilla_id', 'TEXT', 'NULL')
    ensure_column(conn, 'publicidad', 'datos_plantilla', 'TEXT', "'{}'")


def _m014_event_log(conn):
    """Tabla de auditoría de eventos: ventas, precios, stock."""
    conn.execute("""CREATE TABLE IF NOT EXISTS event_log (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid           TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))),
        entidad        TEXT NOT NULL,
        entidad_id     INTEGER,
        entidad_uuid   TEXT,
        accion         TEXT NOT NULL,
        payload        TEXT,
        usuario_id     INTEGER,
        usuario_nombre TEXT,
        device_id      TEXT,
        created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
        pending_sync   INTEGER DEFAULT 1
    )""")
    ensure_index(conn, 'idx_event_log_entidad', 'event_log', 'entidad, entidad_id')
    ensure_index(conn, 'idx_event_log_pending', 'event_log', 'pending_sync, created_at')


_MIGRACIONES = [
    (1, "stock_movimientos: variante_id, stock_antes/despues, venta_id, notas", _m001_stock_trazabilidad),
    (2, "proveedor_productos: relación explícita proveedor-producto",            _m002_proveedor_productos),
    (3, "índices analíticos para reportes y POS",                                _m003_indices_analiticos),
    (4, "métricas precalculadas diarias/semanales/mensuales",                    _m004_metricas_agregadas),
    (5, "usuarios: sucursal_id y permisos JSON",                                 _m005_usuarios_permisos_sucursal),
    (6, "cola_impresion: tickets persistentes con reintentos",                   _m006_cola_impresion),
    (7, "lotes y mermas: control opcional de vencimientos por producto",          _m007_lotes_vencimientos),
    (8, "vocabulario_local: expresiones coloquiales aprendidas sin TinyLlama",   _m008_vocabulario_local),
    (9, "modificadores: toppings y opciones para sushi/food trucks",             _m009_modificadores),
    (10, "ZERO CREDIT: clientes_fiado y fiado_movimientos",                      _m010_zero_credit),
    (11, "dia_pago: día de cobro fijo mensual en clientes_fiado",               _m011_dia_pago),
    (12, "publicidad: slides configurables para pantalla cliente",               _m012_publicidad),
    (13, "publicidad: plantilla_id y datos_plantilla para plantillas HTML",       _m013_publicidad_plantillas),
    (14, "event_log: auditoría de eventos (ventas, precios, stock)",              _m014_event_log),
]


def aplicar_migraciones(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_version (
        version     INTEGER PRIMARY KEY,
        descripcion TEXT,
        aplicada_en DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    aplicadas = {r[0] for r in conn.execute("SELECT version FROM schema_version").fetchall()}
    for version, descripcion, fn in _MIGRACIONES:
        if version not in aplicadas:
            try:
                fn(conn)
                conn.execute(
                    "INSERT INTO schema_version (version, descripcion) VALUES (?,?)",
                    (version, descripcion)
                )
                logger.info(f"Migración {version} aplicada: {descripcion}")
            except Exception as e:
                logger.error(f"Migración {version} falló: {e}")


def _migrate_stock_model(conn):
    """P0.1: Marca con stock=-1 los productos que tienen variantes activas."""
    conn.execute("""
        UPDATE productos
        SET stock = -1
        WHERE id IN (
            SELECT DISTINCT producto_id FROM producto_variantes WHERE activo = 1
        )
        AND stock != -1
    """)


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
            aplicar_migraciones(conn)   # P0.4: migraciones versionadas
            _migrate_stock_model(conn)  # P0.1: stock=-1 para productos con variantes
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
    # Tabla marcas (nueva — segura si ya existe)
    conn.execute("""CREATE TABLE IF NOT EXISTS marcas (
        id          INTEGER PRIMARY KEY,
        nombre      TEXT NOT NULL UNIQUE,
        fabricante  TEXT,
        pais_origen TEXT DEFAULT 'Chile',
        sitio_web   TEXT,
        creado_en   DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")

    ensure_column(conn, 'productos', 'subcategoria_id', 'INTEGER REFERENCES subcategorias(id)')
    ensure_column(conn, 'productos', 'tiene_variantes', 'INTEGER NOT NULL DEFAULT 0')
    ensure_column(conn, 'productos', 'es_granel', 'INTEGER NOT NULL DEFAULT 0')
    ensure_column(conn, 'productos', 'unidad_medida', "TEXT NOT NULL DEFAULT 'unidad'")
    ensure_column(conn, 'productos', 'precio_por', "TEXT NOT NULL DEFAULT 'unidad'")
    ensure_column(conn, 'productos', 'modo_stock', "TEXT NOT NULL DEFAULT 'normal'")
    ensure_column(conn, 'productos', 'hora_reset_stock', "TEXT NOT NULL DEFAULT '06:00'")
    ensure_column(conn, 'venta_items', 'variante_id', 'INTEGER REFERENCES producto_variantes(id)')
    ensure_column(conn, 'venta_items', 'nombre_variante', 'TEXT')
    ensure_column(conn, 'venta_items', 'notas', 'TEXT')
    ensure_column(conn, 'voz_aprendizaje', 'tipo', "TEXT NOT NULL DEFAULT 'accion'")
    ensure_column(conn, 'ventas', 'pedido_id', 'INTEGER REFERENCES pedidos(id)')
    ensure_column(conn, 'productos', 'pendiente_verificar', 'INTEGER NOT NULL DEFAULT 0')
    ensure_column(conn, 'productos', 'tiene_impuesto_adicional', 'INTEGER NOT NULL DEFAULT 0')
    ensure_column(conn, 'productos', 'tasa_impuesto_adicional', 'REAL NOT NULL DEFAULT 0')
    ensure_column(conn, 'productos', 'marca_id', 'INTEGER REFERENCES marcas(id)')

    if ensure_column(conn, 'productos', 'sku', 'TEXT'):
        import unicodedata as _ud
        def _mk_sku(cat, pid):
            clean = "".join(c for c in _ud.normalize("NFKD", (cat or "").upper()) if c.isascii() and c.isalpha())
            return f"{clean[:3] or 'PRD'}-{pid:05d}"
        rows = conn.execute(
            "SELECT p.id, COALESCE(c.nombre,'') as cn FROM productos p LEFT JOIN categorias c ON p.categoria_id=c.id"
        ).fetchall()
        for r in rows:
            conn.execute("UPDATE productos SET sku=? WHERE id=?", (_mk_sku(r["cn"], r["id"]), r["id"]))

    ensure_column(conn, 'pedidos', 'receptor_nombre', 'TEXT')
    ensure_column(conn, 'pedidos', 'receptor_tel', 'TEXT')
    ensure_column(conn, 'geografia_local', 'direcciones_frecuentes', 'TEXT')

    # Unique index en voz_sinonimos_variante — silencioso si ya existe o hay duplicados
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_vsv_unique "
            "ON voz_sinonimos_variante(palabra, producto_id, variante_id)"
        )
    except Exception as e:
        logger.debug(f"migrate idx_vsv_unique: {e}")

    # Columna apodo en proveedores (para búsqueda coloquial por voz)
    ensure_column(conn, 'proveedores', 'apodo', 'TEXT')

    # Departamento en categorías (jerarquía 3 niveles)
    try:
        if ensure_column(conn, 'categorias', 'departamento', "TEXT DEFAULT 'Alimentación'"):
            conn.execute("UPDATE categorias SET departamento='Bebidas con Alcohol' WHERE nombre IN ('Bebidas Alcohólicas','Vinos','Cervezas')")
            conn.execute("UPDATE categorias SET departamento='Cuidado Personal' WHERE nombre IN ('Higiene','Cuidado Personal','Farmacia')")
            conn.execute("UPDATE categorias SET departamento='Limpieza del Hogar' WHERE nombre IN ('Limpieza','Limpieza e Higiene','Detergentes')")
            conn.execute("UPDATE categorias SET departamento='Mascotas' WHERE nombre IN ('Mascotas','Alimentos Mascotas')")
    except Exception as e:
        logger.debug(f"migrate categorias.departamento: {e}")

    # Columna activo en categorias + unificar bebidas
    try:
        ensure_column(conn, 'categorias', 'activo', 'INTEGER DEFAULT 1')
        conn.execute("UPDATE categorias SET activo=1 WHERE activo IS NULL")
        # Unificar bebidas alcohólicas y no alcohólicas en departamento "Bebidas"
        conn.execute(
            "UPDATE categorias SET departamento='Bebidas'"
            " WHERE nombre='Bebidas' AND departamento='Alimentación'"
        )
        conn.execute(
            "UPDATE categorias SET departamento='Bebidas'"
            " WHERE departamento='Bebidas con Alcohol'"
        )
    except Exception as e:
        logger.debug(f"migrate categorias.activo+bebidas: {e}")

    # Índices de código de barras para escaneo O(1)
    ensure_index(conn, 'idx_productos_barras', 'productos', 'codigo_barras')
    ensure_index(conn, 'idx_variantes_barras', 'producto_variantes', 'codigo_barras')

    # Limpiar admins duplicados (bug: INSERT OR IGNORE sin constraint en DBs antiguas)
    conn.execute(
        """DELETE FROM usuarios
           WHERE nombre = 'Admin'
           AND id NOT IN (SELECT MIN(id) FROM usuarios WHERE nombre = 'Admin')"""
    )

    # Unique index en usuarios.nombre (DBs antiguas pueden no tener el constraint)
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_nombre ON usuarios(nombre)"
        )
    except Exception as e:
        logger.debug(f"migrate idx_usuarios_nombre: {e}")


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

    # Nuevos campos de ticket — INSERT OR IGNORE para DBs existentes
    for _clave in ("whatsapp_negocio", "direccion_negocio", "telefono_negocio",
                   "impresora_cocina_ip", "impresora_cocina_tipo", "impresora_cocina_puerto",
                   "comuna_negocio", "subtipo_negocio",
                   "nombre_responsable", "email_negocio", "sii_activo",
                   "responsable_nombre", "responsable_telefono", "responsable_email",
                   "razon_social", "giro",
                   "delivery_tarifa_tipo", "delivery_precio_fijo",
                   "delivery_precio_km1", "delivery_precio_km3",
                   "delivery_precio_km5", "delivery_precio_mas5",
                   "delivery_texto"):
        conn.execute(
            "INSERT OR IGNORE INTO config (clave, valor) VALUES (?, ?)",
            (_clave, "")
        )
    conn.execute(
        "INSERT OR IGNORE INTO config (clave, valor) VALUES ('tipo_negocio', 'store')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO config (clave, valor) VALUES ('mensaje_ticket', '¡Gracias por preferirnos!')"
    )

    import bcrypt
    pin_default = b"1234"
    hashed = bcrypt.hashpw(pin_default, bcrypt.gensalt()).decode()
    conn.execute(
        """INSERT INTO usuarios (nombre, pin_hash, rol, activo)
           SELECT 'Admin', ?, 'admin', 1
           WHERE NOT EXISTS (SELECT 1 FROM usuarios WHERE rol = 'admin')""",
        (hashed,)
    )
    if conn.execute("SELECT changes()").fetchone()[0]:
        logger.info("Usuario admin creado con PIN por defecto: 1234")

    _seed_montos_chilenos(conn)

    # Árbol completo de categorías — inspirado en Jumbo/Líder Chile
    _cats = [
        # Alimentación
        ('Bebidas',               'Alimentación',               '🥤'),
        ('Lácteos y Huevos',      'Alimentación',               '🥛'),
        ('Snacks',                'Alimentación',               '🍿'),
        ('Cereales',              'Alimentación',               '🌾'),
        ('Pastas y Arroz',        'Alimentación',               '🍝'),
        ('Pan y Panadería',       'Alimentación',               '🍞'),
        ('Conservas',             'Alimentación',               '🥫'),
        ('Condimentos',           'Alimentación',               '🧂'),
        ('Abarrotes',             'Alimentación',               '🛒'),
        ('Congelados',            'Alimentación',               '🧊'),
        ('Carnes y Fiambres',     'Alimentación',               '🥩'),
        ('Frutas y Verduras',     'Alimentación',               '🥦'),
        ('Desayuno',              'Alimentación',               '🍳'),
        # Bebidas con Alcohol
        ('Cervezas',              'Bebidas con Alcohol',        '🍺'),
        ('Vinos',                 'Bebidas con Alcohol',        '🍷'),
        ('Licores',               'Bebidas con Alcohol',        '🥃'),
        # Belleza y Cuidado Personal
        ('Higiene Personal',      'Belleza y Cuidado Personal', '🧴'),
        ('Cuidado Cabello',       'Belleza y Cuidado Personal', '💆'),
        ('Afeitado y Depilación', 'Belleza y Cuidado Personal', '🪒'),
        ('Cuidado Femenino',      'Belleza y Cuidado Personal', '🌸'),
        ('Cosmética',             'Belleza y Cuidado Personal', '💄'),
        ('Salud Básica',          'Belleza y Cuidado Personal', '💊'),
        # Limpieza del Hogar
        ('Detergentes',           'Limpieza del Hogar',         '🧺'),
        ('Limpiadores',           'Limpieza del Hogar',         '🧹'),
        ('Papel y Descartables',  'Limpieza del Hogar',         '🧻'),
        ('Insecticidas',          'Limpieza del Hogar',         '🐛'),
        # Mundo Bebé
        ('Pañales y Toallitas',   'Mundo Bebé',                 '👶'),
        ('Alimentación Infantil', 'Mundo Bebé',                 '🍼'),
        # Mascotas
        ('Alimentos Mascotas',    'Mascotas',                   '🐾'),
        ('Accesorios Mascotas',   'Mascotas',                   '🦴'),
        # Manualidades y Hogar
        ('Costura y Tejido',      'Manualidades y Hogar',       '🧵'),
        ('Papelería',             'Manualidades y Hogar',       '📝'),
        ('Pilas y Velas',         'Manualidades y Hogar',       '🕯️'),
        # Juguetes y Entretencion
        ('Juguetes',              'Juguetes y Entretencion',    '🎮'),
        # Ferretería Básica
        ('Ferretería',            'Ferretería Básica',          '🔧'),
        ('Electricidad',          'Ferretería Básica',          '💡'),
        # Tabaco
        ('Cigarrillos',           'Tabaco',                     '🚬'),
        # Otros
        ('Otros',                 'Otros',                      '📦'),
        ('Venta Rápida',          'Otros',                      '⚡'),
        ('Sin categoría',         'Otros',                      '📦'),
    ]
    for _nombre, _depto, _icono in _cats:
        conn.execute(
            "INSERT OR IGNORE INTO categorias (nombre, departamento, icono) VALUES (?,?,?)",
            (_nombre, _depto, _icono)
        )

    # Actualizar departamentos de categorías existentes con nombre conocido
    _depto_map = [
        ('Alimentación', (
            'Bebidas', 'Lácteos', 'Lácteos y Huevos', 'Snacks', 'Cereales',
            'Pastas y Arroz', 'Pan y Panadería', 'Conservas', 'Condimentos',
            'Abarrotes', 'Despensa', 'Congelados', 'Carnes y Fiambres',
            'Frutas y Verduras', 'Desayuno',
        )),
        ('Bebidas con Alcohol', (
            'Bebidas Alcohólicas', 'Vinos', 'Cervezas', 'Licores',
        )),
        ('Belleza y Cuidado Personal', (
            'Higiene', 'Cuidado Personal', 'Farmacia',
            'Higiene Personal', 'Cuidado Cabello',
        )),
        ('Limpieza del Hogar', (
            'Limpieza', 'Limpieza e Higiene', 'Detergentes',
            'Limpiadores', 'Papel y Descartables',
        )),
        ('Mascotas', (
            'Mascotas', 'Alimentos Mascotas', 'Accesorios Mascotas',
        )),
        ('Otros', (
            'Otros', 'Venta Rápida', 'Sin categoría',
        )),
    ]
    for _depto, _nombres in _depto_map:
        _ph = ','.join('?' * len(_nombres))
        conn.execute(
            f"UPDATE categorias SET departamento=? WHERE nombre IN ({_ph})",
            (_depto, *_nombres)
        )

    # Fusionar categorías duplicadas — idempotente
    # (orig_nombre, dest_nombre, dest_departamento, dest_icono)
    _fusiones = [
        ('Lácteos',  'Lácteos y Huevos',  'Alimentación',      '🥛'),
        ('Limpieza', 'Limpieza del Hogar', 'Limpieza del Hogar', '🧹'),
        ('Despensa', 'Abarrotes',          'Alimentación',      '🛒'),
    ]
    for _orig_nom, _dest_nom, _dest_depto, _dest_ico in _fusiones:
        _orig = conn.execute(
            "SELECT id FROM categorias WHERE nombre=?", (_orig_nom,)
        ).fetchone()
        if not _orig:
            continue
        _dest = conn.execute(
            "SELECT id FROM categorias WHERE nombre=?", (_dest_nom,)
        ).fetchone()
        if not _dest:
            _cur = conn.execute(
                "INSERT INTO categorias (nombre, departamento, icono) VALUES (?,?,?)",
                (_dest_nom, _dest_depto, _dest_ico)
            )
            _dest_id = _cur.lastrowid
        else:
            _dest_id = _dest["id"]
        conn.execute(
            "UPDATE productos SET categoria_id=? WHERE categoria_id=?",
            (_dest_id, _orig["id"])
        )
        conn.execute(
            """UPDATE productos SET subcategoria_id=NULL
               WHERE subcategoria_id IN (
                   SELECT id FROM subcategorias WHERE categoria_id=?
               )""",
            (_orig["id"],)
        )
        conn.execute("DELETE FROM subcategorias WHERE categoria_id=?", (_orig["id"],))
        conn.execute("DELETE FROM categorias WHERE id=?", (_orig["id"],))


def encolar_ticket(conn, venta_id: int, contenido: str, impresora_id: str = None) -> int:
    """Inserta un ticket en la cola de impresión. Retorna el id de la fila."""
    cur = conn.execute(
        """INSERT INTO cola_impresion (venta_id, contenido, impresora_id, estado)
           VALUES (?, ?, ?, 'pendiente')""",
        (venta_id, contenido, impresora_id)
    )
    return cur.lastrowid


def marcar_ticket_impreso(conn, cola_id: int):
    conn.execute(
        "UPDATE cola_impresion SET estado='completado', actualizado_en=CURRENT_TIMESTAMP WHERE id=?",
        (cola_id,)
    )


def marcar_ticket_fallido(conn, cola_id: int, error: str):
    conn.execute(
        """UPDATE cola_impresion
           SET intentos = intentos + 1,
               error_msg = ?,
               estado = CASE WHEN intentos + 1 >= 10 THEN 'fallido' ELSE 'pendiente' END,
               actualizado_en = CURRENT_TIMESTAMP
           WHERE id=?""",
        (error[:500], cola_id)
    )


_PERMISOS_ROL = {
    "supervisor": {
        "puede_anular_ventas":    True,
        "puede_ver_reportes":     True,
        "puede_editar_precios":   True,
        "puede_gestionar_stock":  True,
        "puede_hacer_descuentos": True,
        "descuento_maximo_pct":   20,
    },
    "cajero": {
        "puede_anular_ventas":    False,
        "puede_ver_reportes":     False,
        "puede_editar_precios":   False,
        "puede_gestionar_stock":  False,
        "puede_hacer_descuentos": True,
        "descuento_maximo_pct":   5,
    },
    "vendedor": {
        "puede_anular_ventas":    False,
        "puede_ver_reportes":     False,
        "puede_editar_precios":   False,
        "puede_gestionar_stock":  False,
        "puede_hacer_descuentos": False,
        "descuento_maximo_pct":   0,
    },
    "bodega": {
        "puede_anular_ventas":    False,
        "puede_ver_reportes":     True,
        "puede_editar_precios":   False,
        "puede_gestionar_stock":  True,
        "puede_hacer_descuentos": False,
        "descuento_maximo_pct":   0,
    },
    "delivery": {
        "puede_anular_ventas":    False,
        "puede_ver_reportes":     False,
        "puede_editar_precios":   False,
        "puede_gestionar_stock":  False,
        "puede_hacer_descuentos": False,
        "descuento_maximo_pct":   0,
    },
    "cocina": {
        "puede_anular_ventas":    False,
        "puede_ver_reportes":     False,
        "puede_editar_precios":   False,
        "puede_gestionar_stock":  False,
        "puede_hacer_descuentos": False,
        "descuento_maximo_pct":   0,
    },
}

ROLES_VALIDOS = ("admin", "supervisor", "cajero", "vendedor", "bodega", "delivery", "cocina")


def tiene_permiso(session_data: dict, permiso: str):
    """Verifica si el usuario de sesión tiene un permiso específico.

    Los permisos JSON en la columna `permisos` sobreescriben los defaults del rol.
    """
    import json as _json
    rol = session_data.get("usuario_rol", "")
    if rol == "admin":
        if permiso == "descuento_maximo_pct":
            return 100
        return True

    permisos_base = _PERMISOS_ROL.get(rol, {})
    permisos_custom = {}
    raw = session_data.get("usuario_permisos")
    if raw:
        try:
            permisos_custom = _json.loads(raw)
        except Exception:
            pass

    merged = {**permisos_base, **permisos_custom}
    return merged.get(permiso, False)


def permisos_efectivos(session_data: dict) -> dict:
    """Devuelve el dict completo de permisos para el usuario de sesión."""
    import json as _json
    rol = session_data.get("usuario_rol", "")
    if rol == "admin":
        return {k: True for k in next(iter(_PERMISOS_ROL.values()))} | {"descuento_maximo_pct": 100}

    permisos_base = dict(_PERMISOS_ROL.get(rol, {}))
    raw = session_data.get("usuario_permisos")
    if raw:
        try:
            permisos_base.update(_json.loads(raw))
        except Exception:
            pass
    return permisos_base


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
