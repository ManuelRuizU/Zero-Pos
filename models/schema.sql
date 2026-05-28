-- =========================================================
-- ZERO POS — Schema principal (orden FK-safe)
-- =========================================================
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ── Nivel 0: tablas maestras sin dependencias ─────────────

CREATE TABLE IF NOT EXISTS config (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    clave  TEXT NOT NULL UNIQUE,
    valor  TEXT
);

CREATE TABLE IF NOT EXISTS usuarios (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT NOT NULL UNIQUE,
    pin_hash   TEXT NOT NULL,
    rol        TEXT NOT NULL DEFAULT 'cajero', -- admin | cajero | cocina
    activo     INTEGER NOT NULL DEFAULT 1,
    creado_en  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sucursales (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre    TEXT NOT NULL,
    direccion TEXT,
    telefono  TEXT,
    activa    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS categorias (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    color  TEXT DEFAULT '#6366f1',
    icono  TEXT DEFAULT '📦'
);

CREATE TABLE IF NOT EXISTS clientes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre          TEXT NOT NULL,
    telefono        TEXT UNIQUE NOT NULL,
    telefono2       TEXT,
    email           TEXT,
    direccion       TEXT,
    depto           TEXT,
    comuna          TEXT,
    notas           TEXT,
    total_pedidos   INTEGER NOT NULL DEFAULT 0,
    total_gastado   INTEGER NOT NULL DEFAULT 0,
    creado_en       DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_clientes_tel ON clientes(telefono);

-- ── Nivel 1: dependen de nivel 0 ─────────────────────────

CREATE TABLE IF NOT EXISTS turnos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id     INTEGER NOT NULL REFERENCES usuarios(id),
    sucursal_id    INTEGER REFERENCES sucursales(id),
    apertura       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cierre         DATETIME,
    fondo_inicial  INTEGER NOT NULL DEFAULT 0,
    fondo_final    INTEGER,
    estado         TEXT NOT NULL DEFAULT 'abierto' -- abierto | cerrado
);

CREATE TABLE IF NOT EXISTS subcategorias (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    categoria_id INTEGER NOT NULL REFERENCES categorias(id),
    nombre       TEXT NOT NULL,
    icono        TEXT DEFAULT '📦',
    UNIQUE(categoria_id, nombre)
);

CREATE TABLE IF NOT EXISTS productos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre          TEXT NOT NULL,
    descripcion     TEXT,
    precio          INTEGER NOT NULL DEFAULT 0,
    precio_costo    INTEGER DEFAULT 0,
    stock           INTEGER NOT NULL DEFAULT 0,
    stock_minimo    INTEGER NOT NULL DEFAULT 5,
    codigo_barras   TEXT UNIQUE,
    categoria_id    INTEGER REFERENCES categorias(id),
    subcategoria_id INTEGER REFERENCES subcategorias(id),
    sucursal_id     INTEGER REFERENCES sucursales(id),
    tiene_variantes INTEGER NOT NULL DEFAULT 0,
    activo          INTEGER NOT NULL DEFAULT 1,
    imagen_url      TEXT,
    creado_en       DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_productos_barras    ON productos(codigo_barras);
CREATE INDEX IF NOT EXISTS idx_productos_categoria ON productos(categoria_id);

-- ── Nivel 2: dependen de nivel 1 ─────────────────────────

CREATE TABLE IF NOT EXISTS producto_variantes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id   INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    nombre        TEXT NOT NULL,
    precio        INTEGER NOT NULL DEFAULT 0,
    precio_costo  INTEGER DEFAULT 0,
    stock         INTEGER NOT NULL DEFAULT 0,
    stock_minimo  INTEGER NOT NULL DEFAULT 5,
    codigo_barras TEXT UNIQUE,
    activo        INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_variantes_producto ON producto_variantes(producto_id);
CREATE INDEX IF NOT EXISTS idx_variantes_barras   ON producto_variantes(codigo_barras);

CREATE TABLE IF NOT EXISTS ventas (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    turno_id       INTEGER REFERENCES turnos(id),
    usuario_id     INTEGER REFERENCES usuarios(id),
    sucursal_id    INTEGER REFERENCES sucursales(id),
    total          INTEGER NOT NULL DEFAULT 0,
    descuento      INTEGER NOT NULL DEFAULT 0,
    impuesto       INTEGER NOT NULL DEFAULT 0,
    metodo_pago    TEXT NOT NULL DEFAULT 'efectivo', -- efectivo | tarjeta | transferencia | khipu | mixto
    estado         TEXT NOT NULL DEFAULT 'completada', -- completada | anulada | devuelta
    cliente_nombre TEXT,
    cliente_rut    TEXT,
    notas          TEXT,
    creado_en      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(creado_en);
CREATE INDEX IF NOT EXISTS idx_ventas_turno ON ventas(turno_id);

CREATE TABLE IF NOT EXISTS pedidos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    numero          INTEGER NOT NULL,
    tipo            TEXT NOT NULL CHECK(tipo IN ('delivery','retiro','local')),
    estado          TEXT NOT NULL DEFAULT 'nuevo'
                    CHECK(estado IN ('nuevo','preparando','listo','despachado','cancelado')),
    cliente_id      INTEGER REFERENCES clientes(id),
    cliente_nombre  TEXT NOT NULL,
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
    usuario_id      INTEGER REFERENCES usuarios(id),
    creado_en       DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pedidos_estado  ON pedidos(estado);
CREATE INDEX IF NOT EXISTS idx_pedidos_fecha   ON pedidos(creado_en);
CREATE INDEX IF NOT EXISTS idx_pedidos_cliente ON pedidos(cliente_id);

-- ── Nivel 3: dependen de nivel 2 ─────────────────────────

CREATE TABLE IF NOT EXISTS venta_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id        INTEGER NOT NULL REFERENCES ventas(id) ON DELETE CASCADE,
    producto_id     INTEGER NOT NULL REFERENCES productos(id),
    variante_id     INTEGER REFERENCES producto_variantes(id),
    nombre_variante TEXT,
    cantidad        INTEGER NOT NULL DEFAULT 1,
    precio_unit     INTEGER NOT NULL,
    descuento       INTEGER NOT NULL DEFAULT 0,
    subtotal        INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vitems_venta ON venta_items(venta_id);

CREATE TABLE IF NOT EXISTS pedido_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id   INTEGER NOT NULL REFERENCES pedidos(id) ON DELETE CASCADE,
    producto_id INTEGER REFERENCES productos(id),
    variante_id INTEGER REFERENCES producto_variantes(id),
    nombre      TEXT NOT NULL,
    cantidad    INTEGER NOT NULL DEFAULT 1,
    precio      INTEGER NOT NULL,
    subtotal    INTEGER NOT NULL,
    notas       TEXT
);

CREATE INDEX IF NOT EXISTS idx_pitems_pedido ON pedido_items(pedido_id);

CREATE TABLE IF NOT EXISTS devoluciones (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id    INTEGER NOT NULL REFERENCES ventas(id),
    usuario_id  INTEGER REFERENCES usuarios(id),
    motivo      TEXT,
    monto       INTEGER NOT NULL DEFAULT 0,
    creado_en   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pagos_khipu (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id        INTEGER REFERENCES ventas(id),
    payment_id      TEXT UNIQUE,
    payment_url     TEXT,
    monto           INTEGER NOT NULL,
    estado          TEXT NOT NULL DEFAULT 'pendiente', -- pendiente | pagado | rechazado | expirado
    creado_en       DATETIME DEFAULT CURRENT_TIMESTAMP,
    actualizado_en  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS caja_movimientos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    turno_id   INTEGER REFERENCES turnos(id),
    tipo       TEXT NOT NULL, -- ingreso | egreso
    concepto   TEXT NOT NULL,
    monto      INTEGER NOT NULL,
    creado_en  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ── Tablas de voz ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS voz_historial (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    texto      TEXT NOT NULL,
    accion     TEXT,
    usuario_id INTEGER REFERENCES usuarios(id),
    creado_en  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_voz_fecha ON voz_historial(creado_en);

CREATE TABLE IF NOT EXISTS voz_aprendizaje (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    palabra     TEXT NOT NULL UNIQUE,
    accion      TEXT NOT NULL,
    tipo        TEXT NOT NULL DEFAULT 'accion',
    confirmado  INTEGER NOT NULL DEFAULT 0,
    veces_usado INTEGER NOT NULL DEFAULT 0,
    creado_en   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS voz_sinonimos_producto (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    palabra     TEXT NOT NULL UNIQUE,
    producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    veces_usado INTEGER NOT NULL DEFAULT 0,
    creado_en   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS voz_sinonimos_variante (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    palabra     TEXT NOT NULL,
    producto_id INTEGER REFERENCES productos(id) ON DELETE CASCADE,
    variante_id INTEGER REFERENCES producto_variantes(id) ON DELETE CASCADE,
    veces_usado INTEGER NOT NULL DEFAULT 0,
    creado_en   DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(palabra, producto_id, variante_id)
);
