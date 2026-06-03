"""
SQL-direct metrics — no AI, <5ms each.
All functions accept a sqlite3 connection and return plain dicts / lists of dicts.
"""
from datetime import datetime, timedelta


def ventas_hoy(conn, sucursal_id=None):
    return conn.execute(
        "SELECT COUNT(*) as num_ventas, COALESCE(SUM(total),0) as total, "
        "COALESCE(AVG(total),0) as promedio "
        "FROM ventas "
        "WHERE DATE(creado_en)=DATE('now') AND estado='completada' "
        "AND (sucursal_id=? OR ? IS NULL)",
        (sucursal_id, sucursal_id)
    ).fetchone()


def ventas_ayer(conn, sucursal_id=None):
    return conn.execute(
        "SELECT COUNT(*) as num_ventas, COALESCE(SUM(total),0) as total, "
        "COALESCE(AVG(total),0) as promedio "
        "FROM ventas "
        "WHERE DATE(creado_en)=DATE('now','-1 day') AND estado='completada' "
        "AND (sucursal_id=? OR ? IS NULL)",
        (sucursal_id, sucursal_id)
    ).fetchone()


def ventas_semana(conn, sucursal_id=None):
    rows = conn.execute(
        "SELECT DATE(creado_en) as fecha, COUNT(*) as num_ventas, "
        "COALESCE(SUM(total),0) as total "
        "FROM ventas "
        "WHERE creado_en>=DATE('now','-7 days') AND estado='completada' "
        "AND (sucursal_id=? OR ? IS NULL) "
        "GROUP BY fecha ORDER BY fecha",
        (sucursal_id, sucursal_id)
    ).fetchall()
    return [dict(r) for r in rows]


def ventas_mes(conn, sucursal_id=None):
    rows = conn.execute(
        "SELECT DATE(creado_en) as fecha, COUNT(*) as num_ventas, "
        "COALESCE(SUM(total),0) as total "
        "FROM ventas "
        "WHERE strftime('%Y-%m',creado_en)=strftime('%Y-%m','now') "
        "AND estado='completada' "
        "AND (sucursal_id=? OR ? IS NULL) "
        "GROUP BY fecha ORDER BY fecha",
        (sucursal_id, sucursal_id)
    ).fetchall()
    return [dict(r) for r in rows]


def producto_mas_vendido(conn, dias=1):
    fecha = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT p.id, p.nombre, SUM(vi.cantidad) as unidades, SUM(vi.subtotal) as total "
        "FROM venta_items vi "
        "JOIN productos p ON vi.producto_id=p.id "
        "JOIN ventas v ON vi.venta_id=v.id "
        "WHERE v.estado='completada' AND DATE(v.creado_en)>=? "
        "GROUP BY vi.producto_id ORDER BY unidades DESC LIMIT 1",
        (fecha,)
    ).fetchone()
    return dict(row) if row else None


def stock_bajo(conn, sucursal_id=None):
    prods = conn.execute(
        "SELECT nombre, stock, stock_minimo FROM productos "
        "WHERE activo=1 AND tiene_variantes=0 AND stock<=stock_minimo LIMIT 10"
    ).fetchall()
    variantes = conn.execute(
        "SELECT p.nombre||' '||pv.nombre as nombre, pv.stock, pv.stock_minimo "
        "FROM producto_variantes pv JOIN productos p ON pv.producto_id=p.id "
        "WHERE pv.activo=1 AND pv.stock<=pv.stock_minimo LIMIT 10"
    ).fetchall()
    return [dict(r) for r in prods] + [dict(r) for r in variantes]


def vencimientos_proximos(conn, dias=7):
    fecha_limite = (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")
    try:
        rows = conn.execute(
            "SELECT l.numero_lote, p.nombre as producto, l.cantidad_actual, "
            "l.fecha_vencimiento "
            "FROM lotes l JOIN productos p ON l.producto_id=p.id "
            "WHERE l.estado='activo' AND l.fecha_vencimiento<=? "
            "AND l.cantidad_actual>0 ORDER BY l.fecha_vencimiento ASC LIMIT 10",
            (fecha_limite,)
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def mejor_cajero_hoy(conn):
    row = conn.execute(
        "SELECT u.nombre, COUNT(*) as ventas, COALESCE(SUM(v.total),0) as total "
        "FROM ventas v JOIN usuarios u ON v.usuario_id=u.id "
        "WHERE DATE(v.creado_en)=DATE('now') AND v.estado='completada' "
        "GROUP BY v.usuario_id ORDER BY total DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def hora_pico_hoy(conn):
    row = conn.execute(
        "SELECT strftime('%H',creado_en) as hora, COUNT(*) as ventas, "
        "COALESCE(SUM(total),0) as total "
        "FROM ventas "
        "WHERE DATE(creado_en)=DATE('now') AND estado='completada' "
        "GROUP BY hora ORDER BY ventas DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def prediccion_agotamiento(conn, producto_id):
    hace30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    prod = conn.execute(
        "SELECT nombre, stock FROM productos WHERE id=? AND activo=1",
        (producto_id,)
    ).fetchone()
    if not prod:
        return None
    vel = conn.execute(
        "SELECT COALESCE(AVG(d.c),0) as prom_diario FROM ("
        "  SELECT SUM(vi.cantidad) as c "
        "  FROM venta_items vi JOIN ventas v ON vi.venta_id=v.id "
        "  WHERE vi.producto_id=? AND v.estado='completada' "
        "  AND DATE(v.creado_en)>=? GROUP BY DATE(v.creado_en)"
        ") d",
        (producto_id, hace30)
    ).fetchone()
    prom = float(vel["prom_diario"] or 0)
    dias_restantes = int(prod["stock"] / prom) if prom > 0 else None
    return {
        "producto": prod["nombre"],
        "stock": prod["stock"],
        "prom_diario": round(prom, 1),
        "dias_restantes": dias_restantes,
    }
