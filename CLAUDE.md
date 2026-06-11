# CLAUDE.md — Contrato de Desarrollo ZERO POS
# Lee este archivo COMPLETO antes de tocar cualquier código.
# Última actualización: 2026-06-11

---

## ¿Qué es ZERO POS?

Sistema POS (punto de venta) local-first para pequeño comercio chileno.
- Backend: Python 3 + Flask + SQLite (WAL mode)
- Frontend: HTML/CSS/JS puro — SIN frameworks (React, Vue, etc.)
- Sin dependencias de internet para operar
- Corre desde PC local, accesible por red LAN
- Puerto HTTPS: 5001 | Puerto HTTP (clientes): 5000

**Filosofía irrenunciable: el sistema debe funcionar SIN internet.**
Cualquier llamada a servicios externos (Open Food Facts, etc.)
debe tener timeout corto y fallback local obligatorio.

---

## Stack — NO cambiar sin autorización explícita

| Capa | Tecnología | Notas |
|------|-----------|-------|
| Backend | Python 3 + Flask | Waitress en producción |
| DB | SQLite WAL | db_session() como context manager |
| Frontend | HTML/CSS/JS puro | Sin frameworks. Sin excepciones. |
| CSS | Variables en zero-tokens.css | Todos los colores/tamaños desde variables |
| Servidor | systemd (zeropos.service) | Auto-restart, arranca con el sistema |
| Impresora | Xprinter LAN 192.168.50.122:9100 | ESC/POS raw, puerto 9100 |

---

## Archivos JS globales — NUNCA duplicar funciones

| Archivo | Contenido | Regla |
|---------|-----------|-------|
| `static/js/zero-utils.js` | `fmt()`, helpers globales | Única declaración. Nunca redeclarar en HTML. |
| `static/js/zero-config.js` | Configuración del sistema | Solo lectura desde HTML |
| `static/js/zero-temas.js` | Sistema de temas claro/oscuro | No mezclar con zero-tokens.css |

**REGLA CRÍTICA:** Si una función ya existe en zero-utils.js,
NO declararla de nuevo en pos.html, inventario.html ni ningún otro HTML.
Causa SyntaxError que rompe toda la ejecución del JS.

---

## CSS — Sistema de variables

Todos los colores, tamaños y espaciados están en `static/css/zero-tokens.css`.
- NUNCA usar colores hardcodeados (#fff, rgb(...)) en componentes nuevos
- SIEMPRE usar var(--zero-...) 
- Los 5 archivos CSS tienen responsabilidades separadas:
  - `zero-tokens.css` → variables
  - `zero-base.css` → reset y tipografía
  - `zero-components.css` → botones, cards, modales
  - `zero-layout.css` → grids y estructura
  - `zero-themes.css` → temas claro/oscuro

---

## Funcionalidades ESTABLES — NO tocar sin razón explícita

Estas funciones fueron depuradas y funcionan correctamente.
Modificarlas sin necesidad directa está PROHIBIDO.

### Carrito (pos.html)
- `guardarCarritoLocal()` → guarda en localStorage key `zero_carrito_v1`
- `recuperarCarritoLocal()` → lee y pinta en UI al cargar
- El carrito persiste entre recargas (F5) ✅
- Se limpia SOLO en logout o venta exitosa
- **NO cambiar la key `zero_carrito_v1`**
- **NO mover estas funciones a scope local** (deben ser globales)

### Escáner de cámara (pos.html e inventario.html)
- Objeto `Escaner` con `getUserMedia` + BarcodeDetector nativo + ZXing fallback
- `facingMode: 'environment'` para cámara trasera en móvil
- Atributo `playsinline` en `<video>` es CRÍTICO para iOS — nunca remover
- El botón `btnCamara` llama `Escaner.abrir()` — NO conectar a input[type=file]
- Input[type=file] existe como botón SEPARADO para "escanear desde foto"
- **LECCIÓN APRENDIDA:** commit 48c7ed4 rompió esto al reemplazar getUserMedia
  por input file "para más confiabilidad" — fue un error. No repetir.

### Impresión de tickets (routes/ventas.py)
- `import threading` está al top del archivo ✅
- `_imprimir_ticket_async()` está envuelta en try/except propio ✅
- Si falla la impresión → se loguea pero la venta retorna 200 igual
- La venta NUNCA debe fallar por un error de impresión
- **NO mover la llamada a _imprimir_ticket_async fuera del try/except**

### Pantalla cliente (cliente.html)
- Polling cada 3 segundos a `/api/ventas/pantalla-cliente`
- SSE/BroadcastChannel fue evaluado y RECHAZADO (consumía workers Waitress)
- **NO reimplementar SSE ni BroadcastChannel**

### Servidor y puertos
- Puerto 5001: HTTPS principal (POS, admin, inventario)
- Puerto 5000: HTTP sin certificado (portal clientes ZERO CREDIT, QR)
- El mux en app.py separa HTTP→:5000 y TLS→:5099 internamente
- **NO cambiar puertos sin actualizar TODA la configuración**
- systemd service: `/etc/systemd/system/zeropos.service` ✅
- Para reiniciar: `sudo systemctl restart zeropos`
- Para ver logs: `journalctl -u zeropos -f`

### Base de datos
- Siempre usar `db_session()` como context manager
- Convertir sqlite3.Row a dict() inmediatamente después de fetchone()/fetchall()
- **NO usar .get() directamente sobre sqlite3.Row** (causa AttributeError)

### ZERO CREDIT (fiado.py + credit.html)
- Portal cliente en HTTP :5000/credit/[token] (sin certificado, para Android)
- QR de cliente apunta a IP de red real, NO a 127.0.0.1
- Tarjeta impresa incluye QR funcional

---

## Funcionalidades EN DESARROLLO (pueden modificarse)

- Retry automático impresora por papel agotado → routes/impresora.py
- Reimpresión manual de tickets → routes/impresora.py + ventas del día
- Open Food Facts en leer-producto → routes/inventario.py
- Foto de producto guardada desde escáner → routes/inventario.py
- Pantalla cliente no limpia al vaciar carrito → pendiente

---

## Decisiones de arquitectura tomadas — NO reabrir

| Decisión | Resolución | Razón |
|----------|-----------|-------|
| SSE vs Polling | **Polling** | SSE consumía workers Waitress |
| Tailscale | **Rechazado** | Innecesario en red local |
| Swipe-to-delete en carrito | **Rechazado** | Riesgoso en entorno cajero |
| PWA install en HTTP local | **Manual** | Chrome no permite prompt en HTTP |
| Certificado SSL | **Auto-firmado** | Costo cero, usuario acepta una vez |
| Framework frontend | **Ninguno** | Debe correr offline desde USB |

---

## Reglas de trabajo obligatorias

### Antes de modificar cualquier archivo:
1. Leer este archivo completo
2. Identificar si el archivo está en la lista "ESTABLES"
3. Si está estable → modificar SOLO lo necesario, nada más
4. Si hay duda → hacer la modificación mínima posible

### Al agregar features nuevas:
1. NO reimplementar lo que ya existe
2. Agregar código nuevo SIN tocar el código estable que lo rodea
3. Si necesitas refactorizar algo estable → pregunta primero

### Commits:
- Mensajes descriptivos en español o inglés
- Un commit por fix/feature
- NO agrupar fixes no relacionados en un solo commit

### Lo que NUNCA está permitido:
- Reemplazar getUserMedia por input[type=file] en el escáner
- Declarar fmt() fuera de zero-utils.js
- Usar SSE o BroadcastChannel
- Hardcodear colores fuera de zero-tokens.css
- Llamadas externas sin timeout y fallback local
- Romper el try/except que protege _imprimir_ticket_async

---

## Contacto y jerarquía de decisiones

- Product Owner y aprobador final: Manuel Ruiz (Manu)
- Revisor técnico: Claude (claude.ai) — todas las sugerencias
  de otras IAs deben pasar por revisión aquí antes de implementarse
- Implementación: Claude Code

**Ante cualquier duda sobre si algo se puede cambiar: NO cambiar.**
Consultar primero.
