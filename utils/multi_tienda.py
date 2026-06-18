#utils/multi_tienda.py

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("zero_pos.multi")
BASE_DIR = Path(__file__).parent.parent


def sincronizar_sucursales() -> dict:
    """
    Sincronización local entre nodos vía archivos JSON en carpeta compartida.
    En una red local, montar la carpeta sync/ como unidad compartida.
    """
    sync_dir = BASE_DIR / "sync"
    sync_dir.mkdir(exist_ok=True)

    from database import db_session
    try:
        with db_session() as conn:
            productos = conn.execute(
                "SELECT id, nombre, precio, stock, codigo_barras FROM productos WHERE activo=1"
            ).fetchall()
            ventas_hoy = conn.execute(
                """SELECT id, total, metodo_pago, creado_en
                   FROM ventas WHERE DATE(creado_en)=DATE('now') AND estado='completada'"""
            ).fetchall()

        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "productos": [dict(p) for p in productos],
            "ventas_hoy_count": len(ventas_hoy),
            "ventas_hoy_total": sum(v["total"] for v in ventas_hoy),
        }

        snap_file = sync_dir / "snapshot.json"
        snap_file.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
        logger.info(f"Snapshot exportado: {len(productos)} productos, {len(ventas_hoy)} ventas")

        otros = list(sync_dir.glob("snapshot_*.json"))
        importados = []
        for f in otros:
            try:
                datos = json.loads(f.read_text())
                importados.append({
                    "archivo": f.name,
                    "timestamp": datos.get("timestamp"),
                    "ventas": datos.get("ventas_hoy_count", 0),
                    "total": datos.get("ventas_hoy_total", 0),
                })
            except Exception:
                pass

        return {
            "ok": True,
            "exportado": snap_file.name,
            "otras_sucursales": importados,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
