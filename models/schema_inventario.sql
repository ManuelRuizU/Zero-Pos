-- =========================================================
-- ZERO POS — Schema inventario / proveedores
-- =========================================================

-- Proveedores
CREATE TABLE IF NOT EXISTS proveedores (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT NOT NULL,
    rut        TEXT,
    contacto   TEXT,
    telefono   TEXT,
    email      TEXT,
    direccion  TEXT,
    notas      TEXT,
    activo     INTEGER NOT NULL DEFAULT 1,
    creado_en  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Órdenes de compra
CREATE TABLE IF NOT EXISTS ordenes_compra (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    proveedor_id  INTEGER NOT NULL REFERENCES proveedores(id),
    usuario_id    INTEGER REFERENCES usuarios(id),
    total         INTEGER NOT NULL DEFAULT 0,
    estado        TEXT NOT NULL DEFAULT 'borrador', -- borrador | enviada | recibida | cancelada
    notas         TEXT,
    creado_en     DATETIME DEFAULT CURRENT_TIMESTAMP,
    recibido_en   DATETIME
);

-- Líneas de orden de compra
CREATE TABLE IF NOT EXISTS orden_items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    orden_id     INTEGER NOT NULL REFERENCES ordenes_compra(id) ON DELETE CASCADE,
    producto_id  INTEGER NOT NULL REFERENCES productos(id),
    cantidad     INTEGER NOT NULL DEFAULT 1,
    precio_unit  INTEGER NOT NULL,
    subtotal     INTEGER NOT NULL
);

-- Movimientos de stock
CREATE TABLE IF NOT EXISTS stock_movimientos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    tipo        TEXT NOT NULL, -- entrada | salida | ajuste | devolucion
    cantidad    INTEGER NOT NULL,
    referencia  TEXT,
    motivo      TEXT,
    usuario_id  INTEGER REFERENCES usuarios(id),
    creado_en   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_stock_mov_producto ON stock_movimientos(producto_id);
CREATE INDEX IF NOT EXISTS idx_stock_mov_fecha ON stock_movimientos(creado_en);

-- Facturas de proveedores (PDF procesadas)
CREATE TABLE IF NOT EXISTS facturas_proveedor (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    proveedor_id    INTEGER REFERENCES proveedores(id),
    numero_factura  TEXT,
    fecha_emision   DATE,
    total           INTEGER,
    archivo_pdf     TEXT,
    procesada       INTEGER NOT NULL DEFAULT 0,
    datos_json      TEXT,
    creado_en       DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Compras (facturas importadas con IA)
CREATE TABLE IF NOT EXISTS compras (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    proveedor_id INTEGER REFERENCES proveedores(id),
    folio        TEXT,
    fecha        DATE,
    total        INTEGER NOT NULL DEFAULT 0,
    usuario_id   INTEGER REFERENCES usuarios(id),
    creado_en    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_compras_proveedor ON compras(proveedor_id);
CREATE INDEX IF NOT EXISTS idx_compras_fecha ON compras(creado_en);

-- Ítems de compras
CREATE TABLE IF NOT EXISTS compra_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    compra_id       INTEGER NOT NULL REFERENCES compras(id) ON DELETE CASCADE,
    producto_id     INTEGER REFERENCES productos(id),
    nombre_original TEXT NOT NULL,
    cantidad        INTEGER NOT NULL DEFAULT 1,
    precio_unitario INTEGER NOT NULL,
    subtotal        INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_compra_items_compra ON compra_items(compra_id);

-- Alertas de stock
CREATE TABLE IF NOT EXISTS alertas_stock (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id INTEGER NOT NULL REFERENCES productos(id),
    tipo        TEXT NOT NULL DEFAULT 'stock_bajo',
    leida       INTEGER NOT NULL DEFAULT 0,
    creado_en   DATETIME DEFAULT CURRENT_TIMESTAMP
);
