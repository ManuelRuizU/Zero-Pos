# CLAUDE.md — Contrato de Desarrollo ZERO POS
# Lee este archivo COMPLETO antes de tocar cualquier código.
# Última actualización: 2026-06-29

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

## Estructura de archivos frontend — UN archivo por página

Cada página HTML tiene su propio CSS y JS externos. NUNCA escribir CSS o JS inline en HTML.

### JS globales (compartidos, cargan antes que el JS de la página)

| Archivo | Contenido | Regla |
|---------|-----------|-------|
| `static/js/zero-utils.js` | `fmt()`, helpers globales | Única declaración. Nunca redeclarar. |
| `static/js/zero-config.js` | Configuración del sistema | Solo lectura |
| `static/js/zero-temas.js` | Sistema de temas claro/oscuro | No mezclar con zero-tokens.css |

### JS por página

| Página | JS | CSS |
|--------|-----|-----|
| pos.html | `static/js/pos.js` | `static/css/pos.css` |
| admin.html | `static/js/admin.js` | `static/css/admin.css` |
| inventario.html | `static/js/inventario.js` | `static/css/inventario.css` |
| login.html | `static/js/login.js` | `static/css/login.css` |
| cliente.html | `static/js/cliente.js` | `static/css/cliente.css` |
| meson.html | `static/js/meson.js` | `static/css/meson.css` |
| pedidos.html | `static/js/pedidos.js` | `static/css/pedidos.css` |
| onboarding.html | `static/js/onboarding.js` | `static/css/onboarding.css` |
| credit.html | `static/js/credit.js` | `static/css/credit.css` |
| cocina.html | `static/js/cocina.js` | `static/css/cocina.css` |
| cobro-khipu.html | `static/js/cobro-khipu.js` | `static/css/cobro-khipu.css` |
| multi.html | `static/js/multi.js` | `static/css/multi.css` |
| scanner.html | `static/js/scanner.js` | `static/css/scanner.css` |

**Orden de carga en cada página:**
```html
<script src="/static/js/zero-utils.js"></script>
<script src="/static/js/zero-config.js"></script>   <!-- si aplica -->
<script src="/static/js/zero-temas.js"></script>
<script src="/static/js/[pagina].js"></script>
```

**REGLA CRÍTICA:** Si una función ya existe en zero-utils.js,
NO declararla de nuevo en ningún .js ni .html de página.
`fmt()` se declara SOLO en zero-utils.js como `window.fmt`.
Causa SyntaxError silencioso que rompe toda la ejecución JS.

---

## CSS — Sistema de variables

Todos los colores, tamaños y espaciados están en `static/css/zero-tokens.css`.
- NUNCA usar colores hardcodeados (#fff, rgb(...)) en componentes nuevos
- SIEMPRE usar var(--zero-...) 
- NUNCA escribir CSS inline en archivos HTML — usar el .css de la página
- Los archivos CSS globales tienen responsabilidades separadas:
  - `zero-tokens.css` → variables
  - `zero-base.css` → reset y tipografía
  - `zero-components.css` → botones, cards, modales
  - `zero-layout.css` → grids y estructura
  - `zero-themes.css` → temas claro/oscuro
- Los CSS de página (`pos.css`, `admin.css`, etc.) contienen estilos específicos
  de cada pantalla y se cargan después de los globales

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
- **El objeto `Escaner` tiene `_cargarZXing()` como método INTERNO.**
  Nunca moverlo a función externa. La carga de ZXing es responsabilidad
  exclusiva del objeto Escaner, no del scope global de pos.html.

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

### Permisos de sesión y turno (pos.html)
- Cierre de sesión solo para admin — cajeros solo pueden cerrar turno
- Botones #btnCerrarSesionMenu y #btnCerrarSesionDropdown: display:none por defecto, se muestran en _aplicarPermisosPOS() si rol === 'admin'
- cerrarSesion() verifica turno activo antes de hacer logout — si hay turno abierto muestra toast de error
- _meRol: variable global seteada en init() con me.rol

### Historial de ventas (pos.html)
- Función abrirHistorial() carga /api/ventas?limit=100
- Deduplica por id antes de renderizar (Map por v.id)
- _renderFiltrosHistorial() + _aplicarFiltrosHistorial() manejan filtros client-side
- Modal #modalDetalleVenta tiene z-index:1300 para quedar sobre el drawer (z-index:1200)
- Al cerrar modal → vuelve al historial (NO a la caja)
- _detalleVentaActual tiene estructura {venta: {...}, items: [...]}
- _reimprimirVentaDetalle() y _anularVentaDetalle() usan _detalleVentaActual.venta?.id
- **NO cambiar la estructura del objeto retornado por /api/ventas/{id}**

### Mux (app.py)
- Timeout del mux: conn.settimeout(30) y create_connection(timeout=30)
- NO reducir estos timeouts — endpoints como OCR + OFF tardan ~6-8 segundos
- El mux está en _run_mux() líneas ~144-230

### Service Worker (static/sw.js)
- CACHE_NAME actual: `'zeropos-v19'`
- **Ubicación:** `static/sw.js` — físicamente en /static/ pero Flask lo sirve
  en la ruta `/sw.js` (raíz) via `@app.route("/sw.js")` en app.py.
  **NO mover a static/js/** — el SW necesita scope `/` y se registra como `/sw.js`.
  Header `Service-Worker-Allowed: /` permite controlar todas las rutas.
- Las rutas /api/ NO se interceptan — el handler hace return sin respondWith
- Las rutas externas (url.origin !== self.location.origin) tampoco se interceptan
- Solo se cachean archivos /static/ con estrategia cache-first
- Para forzar reinstalación del SW: bump CACHE_NAME (v19 → v20, etc.)
- **LECCIÓN APRENDIDA:** cache-first significa que cambios en HTML/JS/CSS NO se ven
  hasta que el SW renueve su caché. Ante bugs "el código viejo sigue corriendo"
  → hacer bump del CACHE_NAME es el primer paso de diagnóstico.
  self.skipWaiting() + clients.claim() activan el nuevo SW inmediatamente.
- Al agregar nuevos archivos CSS o JS de página → agregarlos a URLS_TO_CACHE
  y hacer bump del CACHE_NAME.

### Open Food Facts (routes/inventario.py)
- _buscar_open_food_facts() funciona correctamente
- El endpoint POST /api/inventario/leer-producto consulta OFF antes de OCR
- OFF solo se consulta desde el BACKEND, nunca desde el frontend
- Timeout configurado en la función para no bloquear si no hay internet

### mkcert SSL
- Certificado en: ~/Proyectos/zero_pos/ssl/cert.pem
- Clave en: ~/Proyectos/zero_pos/ssl/key.pem
- CA root en: ~/.local/share/mkcert/rootCA.pem
- Válido hasta: 12 Septiembre 2028
- Para instalar en nuevos dispositivos: servir rootCA.pem por HTTP :5000

### event_log (database.py)
- Tabla para auditoría y futura sincronización cloud
- Helper log_event(conn, entidad, accion, entidad_id, payload, usuario_id, usuario_nombre)
- Registrar en: crear venta, anular venta, cambio precio, entrada stock
- NO eliminar ni modificar la estructura de la tabla
- pending_sync=1 significa pendiente de sincronizar con ZERO CLOUD

### ensure_column() y ensure_index() (database.py)
- Reemplazaron todos los ALTER TABLE repetidos
- Usar SIEMPRE estas funciones para nuevas columnas
- NUNCA usar try/except con ALTER TABLE directamente
- ensure_column(conn, tabla, columna, tipo, default=None)
- ensure_index(conn, nombre, tabla, columnas)

### Stock insuficiente (pos.html)
- 3 niveles: color en cantidad, botón cobrar, modal confirmación
- Modal NO bloquea — permite confirmar igual
- El dueño siempre tiene la última palabra
- NO eliminar el modal ni convertirlo en bloqueo total

### Iconos Tabler
- CDN: https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@2.47.0/tabler-icons.min.css
- Está en: pos.html, admin.html, inventario.html
- Todos los iconos usan clase: <i class="ti ti-NOMBRE">
- Colores con fondo por ítem en drawer pos.html
- NO reemplazar por emojis ni otras librerías de iconos

### Categorías inventario
- Sidebar con grupos desplegables por departamento
- Bebidas unifica alcohólicas y sin alcohol con sub-filtro
- Departamentos activables desde admin (columna activo en categorias)
- Stock por voz DESACTIVADO temporalmente (botón oculto)
  Reactivar cuando mejore el reconocimiento

### Overlay turno cerrado (pos.html)
- `#overlayTurnoCerrado` cubre toda la caja cuando no hay turno abierto
- **`display:none` por defecto** en el HTML (evita flash al recargar con turno abierto)
- `<body class="cargando">` inicia la página; CSS en pos.css aplica:
  - `.layout` y `.topbar` → `visibility:hidden` (oculta el contenido de la caja)
  - `#overlayTurnoCerrado` → `display:flex` (overlay opaco cubre todo)
  - `#overlayTurnoCerrado > *` → `visibility:hidden` (no muestra "turno cerrado"
    hasta que verificarTurno() confirme que realmente está cerrado)
- `verificarTurno(me)` al terminar llama `document.body.classList.remove('cargando')`
  → si hay turno: `overlay.style.display='none'`, layout visible → caja aparece limpia
  → si no hay: overlay visible con contenido "turno cerrado"
- **LECCIÓN APRENDIDA:** `visibility:hidden` en el overlay (versión anterior) NO ocultaba
  el contenido de la caja porque también volvía transparente el fondo del overlay.
  La corrección fue ocultar `.layout` y `.topbar` directamente.
- z-index: 9999 (mayor que cualquier modal)
- `_confirmarTurno()` al abrir turno: oculta el overlay (todos los roles)
- Al cerrar turno exitosamente → redirige a `login.html?modo=salida`
- El botón "ABRIR EL TURNO" llama `_abrirModalTurno('abrir')` (con guión bajo)
- **NO** agregar redirect a admin.html al abrir turno — todos los roles quedan en pos.html

### Tickets de turno (utils/impresora.py + routes/auth.py)
- `imprimir_apertura_turno(turno, config, config_imp)` — ticket al abrir turno
- `imprimir_cierre_turno(turno, ventas_resumen, config, config_imp)` — ticket al cerrar
- Ambos se llaman en threads daemon desde routes/auth.py después de cerrar el with db_session()
- Estructura ticket cierre: Header → CIERRE DE TURNO → Fechas → VENTAS DEL TURNO
  (brutas/reembolsos/$0/descuentos/$0/netas + desglose por método) →
  CAJÓN DE EFECTIVO (fondo + cobros + teórico + real + descuadre) →
  BILLETES Y MONEDAS → Footer
- El ticket apertura incluye denominaciones_apertura si las hay
- Fondo inicial del turno viene de turno.fondo_inicial (no de ventas_resumen)

### Sistema de asistencia (migración _m017)
- Tabla `asistencia`: tipos entrada/salida/salida_colacion/entrada_colacion
- Columna `usuarios.jornada_horas_semanales INTEGER DEFAULT 45`
- Se registra automáticamente en routes/auth.py `login()` leyendo campo `modo` del body
- El campo `modo` se envía desde login.html junto con el PIN — no es un endpoint separado
- Endpoints: GET /api/auth/asistencia (semana actual, tabla para admin)
             GET /api/auth/asistencia/resumen (horas semana, jornada pactada)
- login.html muestra 4 botones de modo antes del teclado PIN
- URL ?modo=salida preselecciona el modo automáticamente (usado por cerrar turno)
- Pantallas post-login: pantallaEntrada (auto-redirect 3s, solo si turno abierto) / pantallaSalida /
  pantallaSalidaColacion / pantallaEntradaColacion
- Auto-redirect de pantallaEntrada → SIEMPRE a pos.html (no a admin.html)
  Excepción: rol cocina → cocina.html
- Admin accede a admin.html desde el botón dashboard en pos.html, no en el login
- Vista asistencia en admin.html (tab Equipo): tabla + barras de progreso por usuario
  Verde ≤90% jornada | Amarillo >90% | Rojo ≥100%
- `crear_usuario()` en routes/auth.py: el INSERT **debe incluir jornada_horas_semanales**
  (se lee de `data.get("jornada_horas_semanales", 45)` — sin esto el valor siempre queda en 45)

### Cajero de reemplazo en colación (login.js + routes/auth.py)
- Config key `cajero_reemplazo_colacion` = '1' habilita botón "ABRIR TURNO" durante colación
- `/api/auth/turno/estado` devuelve `estado='colacion_activa'`, `cajero_reemplazo=True/False`,
  `cajero_nombre` (nombre del cajero principal en colación)
- `_estadoTurno` en login.js almacena esta respuesta para usarla en `_mostrarPantallaPost()`
- Si `_estadoTurno.estado === 'colacion_activa'` en el flujo entrada sin turno propio:
  - `entradaSubtitulo` → "👥 Cajero de reemplazo"
  - `entradaHorasSemana` → "Cubriendo a: [cajero_nombre]"
  - redirect a pos.html después de 3 segundos (en vez de 1.5s)
- Cada cajero (principal y reemplazo) tiene su propio registro de turno en BD
- La pantalla "¿Quién eres?" muestra TODOS los usuarios activos — cada uno selecciona
  su nombre y PIN por separado al abrir/cerrar su turno

### Flujo de navegación login → caja (LECCIÓN APRENDIDA)
- Login con modo=entrada (cualquier rol excepto cocina):
  - Si turno CERRADO → redirect directo a pos.html (sin pantalla bienvenida)
  - Si turno ABIERTO → pantalla bienvenida 3s → pos.html
- Cocina siempre va a cocina.html independiente del turno
- Admin NO va a admin.html al hacer login — siempre pasa por pos.html primero
- RAZÓN: el turno se abre desde pos.html, y admin también necesita abrir turno
- La verificación del turno se hace en `_mostrarPantallaPost()` en login.js
  consultando `/api/auth/turno/actual` después del login exitoso
- **NO** mostrar pantalla bienvenida si el turno está cerrado — genera confusión
- **LECCIÓN APRENDIDA:** pos.js redirige a `login.html?modo=salida` DESPUÉS de cerrar el
  turno — cuando login.html carga, el turno ya está cerrado. `adaptarModosPorEstado()`
  detectaba `estado='cerrado'` y sobreescribía el modo a 'entrada', mandando al cajero
  al flujo de "Abriendo caja" en vez de "Buenas noches".
  **FIX:** en `_mostrarSolo()` (login.js), si `urlModo` es 'salida' o 'salida_colacion'
  y no está en los modos calculados por estado, forzar `modos = [urlModo]`.
  `const MODOS_SALIDA = ['salida', 'salida_colacion']` — estos siempre ganan sobre el estado.

### Límite de sesiones cajero (routes/auth.py)
- Config key `max_cajeros` (default 2): máximo de sesiones cajero simultáneas
- **LECCIÓN APRENDIDA:** la función original `_contar_sesiones_activas()` contaba TODOS
  los archivos en `flask_sessions/` incluyendo sesiones admin y de prueba, bloqueando
  login de cajeros con error 403 "Límite alcanzado" aunque no hubiera nadie logueado.
- **FIX:** `_contar_sesiones_cajero()` abre cada archivo pickle y solo cuenta los que
  tienen `usuario_rol == 'cajero'`. NUNCA volver al conteo ciego por mtime.
- `flask_sessions/` acumula archivos con el tiempo — si hay 403 inexplicable en cajero,
  verificar cantidad de archivos: `ls flask_sessions/ | wc -l`
- Los archivos expiran por mtime > 12h (ajustado desde 8h para dar más margen)
- **NO** usar `confirm()` ni `alert()` nativos en admin.js — usar `_confirmar()`

### Modales de confirmación en admin.html
- `_confirmar(msg, onOk, {btnLabel, danger})` en admin.js — reemplaza todos los `confirm()`
- `#modalConfirm` en admin.html con `#modalConfirmMsg` y `#btnConfirmOk`
- `danger: true` → botón rojo (`var(--danger)`)
- Ejemplo: `_confirmar('¿Eliminar?', () => hacerAlgo(), { btnLabel: 'Eliminar', danger: true })`
- `_confirmCancel()` cierra el modal
- `eliminarUsuario(id, nombre)` hace DELETE a `/api/auth/usuarios/<id>` (soft delete activo=0)
- **NUNCA** usar `confirm()` o `alert()` en admin.js — rompe UX en dispositivos táctiles

### Integración SumUp (routes/sumup.py)
- Hosted Checkout API con `hosted_checkout.enabled=True`
- Genera `hosted_checkout_url` real de SumUp (fallback a URL manual si no viene)
- QR embebido en cliente.html via qrcode.js local (`/static/js/vendor/qrcode.min.js`)
- Cliente escanea QR → paga con wallet/tarjeta desde su teléfono
- Polling automático cada 3s en pos.html confirma estado via `/api/sumup/estado/<id>`
- Venta se marca `completada` + `metodo_pago='tarjeta'` automáticamente al confirmar
- Soporta Apple Pay, Google Pay, tarjeta — sin hardware físico requerido
- Comisión 2.49% + IVA por transacción
- qrcode.min.js en `/static/js/vendor/` — funciona sin internet (offline-first)
- `sumup_api_key`, `sumup_merchant_code`, `sumup_email` configurables desde admin.html
- `CLAVES_PERMITIDAS` en config.py incluye todas las claves SumUp
- `confirmar_webhook`: endpoint sin auth para que cliente.html notifique pago exitoso
- `estado_cliente`: endpoint sin auth para consultar estado de un checkout
- Tabla `pagos_sumup`: `checkout_id`, `link_pago`, `estado`, `venta_id`

### Seguridad git
- `certs/` excluido de git (.gitignore) — certificados SSL del equipo
- `*.db`, `*.db-wal`, `*.db-shm`, `*.db-bak` excluidos de git
- `static/negocio/`, `static/productos_img/` excluidos — datos del cliente
- Nunca subir archivos sensibles al repositorio

---

## Funcionalidades EN DESARROLLO (pueden modificarse)

- Retry automático impresora por papel agotado → routes/impresora.py
- Reimpresión manual de tickets → routes/impresora.py + ventas del día
- Open Food Facts en leer-producto → routes/inventario.py
- Foto de producto guardada desde escáner → routes/inventario.py
- Pantalla cliente no limpia al vaciar carrito → pendiente
- OAuth2 SumUp (flujo "Conectar con SumUp") → routes/sumup.py
- Verificar polling pagos_sumup pendientes al reiniciar servidor → routes/sumup.py
- Webhook SumUp para confirmación instantánea (actualmente usa polling) → routes/sumup.py

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
| event_log estructura | **Fija** | Base de ZERO CLOUD sync — no modificar |
| Migraciones DB | **ensure_column/ensure_index** | Estándar para nuevas columnas |
| uuid + updated_at + deleted_at | **Completado _m015** | Base de ZERO CLOUD sync |
| Services/domain layer | **Pendiente** | Cuando haya 5+ clientes activos |
| Login admin → pos.html | **pos.html siempre** | Admin necesita abrir turno desde pos.html |
| Redirect post-abrir-turno | **Queda en pos.html** | Evita ciclo pos→admin→pos con turno cerrado |

### Fase 1 Sync — COMPLETADA (migración _m015)
- uuid agregado en: productos, ventas, clientes, usuarios, categorias, turnos, pedidos
- updated_at, deleted_at, origin_device agregados
- 539 registros existentes poblados con uuid
- Triggers: trg_productos_updated_at, trg_ventas_updated_at
- Índices: idx_productos_uuid, idx_ventas_uuid, idx_clientes_uuid, idx_usuarios_uuid
- NO modificar estos campos — son base de ZERO CLOUD

### Migración _m016 — stock_movimientos sync (COMPLETADA)
- referencia_tipo, referencia_id, uuid, origin_device en stock_movimientos
- Índices: idx_stock_mov_producto, idx_stock_mov_referencia

### Migración _m017 — asistencia (COMPLETADA)
- Tabla asistencia con tipos entrada/salida/salida_colacion/entrada_colacion
- Índices: idx_asistencia_usuario, idx_asistencia_fecha
- Columna usuarios.jornada_horas_semanales INTEGER DEFAULT 45

### Migraciones _m018 y _m019 — Fase 2 Sync (COMPLETADAS)
- Ver sección "Fase 2 Sync" arriba
- Próxima migración disponible: _m020

### Fase 2 Sync — COMPLETADA (migraciones _m018 y _m019)

**_m018_device_y_devices:**
- Tabla `devices`: id, device_id (UUID único), nombre, ip_local, tipo, ultima_vez, activo
- `device_id` en config: UUID generado automáticamente al aplicar la migración
- Identifica cada instalación ZERO POS de forma única para sincronización

**_m019_event_log_sync:**
- Columnas añadidas a event_log: sync_at, sync_error, retry_count
- Índices: idx_event_log_sync_queue (pending_sync, retry_count, created_at)
           idx_event_log_sync_at
- event_log ya funciona como cola de sync — worker pendiente de implementar

### Fase 3 Sync — PENDIENTE
- Worker de sincronización cloud (leer pending_sync=1, enviar a API, marcar sync_at)
- UI de estado sync en admin.html
- Resolución de conflictos por updated_at + origin_device

### Reglas de migración
- SIEMPRE usar ensure_column() para nuevas columnas
- SIEMPRE usar ensure_index() para nuevos índices
- NUNCA usar ALTER TABLE con try/except directamente
- Cada migración va en función _mXXX() en database.py
- Poblar uuid en registros existentes al agregar columna

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

## Reglas de código

### .gitignore — archivos excluidos del repositorio
Estos paths NO deben commitarse nunca (datos de usuario o secretos):
- `certs/` — certificados SSL del equipo
- `static/negocio/` — imágenes y datos de negocio del cliente
- `static/productos_img/` — fotos de productos (binarios pesados)
- `static/rootCA.pem` — CA root de mkcert
- `*.pem` — cualquier certificado o clave privada
- `*.db` / `*.db-wal` / `*.db-shm` — base de datos SQLite local

### Auditoría pendiente (revisar antes de cada release)
1. **cargarZXing** — verificar que `_cargarZXing()` sigue siendo método INTERNO
   del objeto `Escaner` en pos.js e inventario.js (nunca debe ser función global)
2. **fmt() redeclaraciones** — buscar `function fmt(` o `const fmt =` en archivos .js y .html;
   la única declaración válida es `window.fmt` en `static/js/zero-utils.js`
3. **CSS/JS inline** — ningún HTML debe tener bloques `<style>` o `<script>` con contenido;
   todo va en sus respectivos .css y .js de página
4. **zero-utils.js globals** — ninguna función de zero-utils.js debe redeclararse en
   ningún .js de página — causa SyntaxError silencioso
5. **Threads daemon** — toda llamada a impresora debe estar en `threading.Thread(daemon=True)`,
   envuelta en try/except propio; nunca en el hilo principal de Flask
6. **Colores hardcodeados** — grep `#[0-9a-fA-F]{3,6}` y `rgb(` en CSS nuevos;
   todos los colores deben usar `var(--zero-...)` de zero-tokens.css
7. **SW cache** — al agregar nuevo CSS/JS de página, agregarlo a URLS_TO_CACHE en sw.js
   y hacer bump del CACHE_NAME

---

## Contacto y jerarquía de decisiones

- Product Owner y aprobador final: Manuel Ruiz (Manu)
- Revisor técnico: Claude (claude.ai) — todas las sugerencias
  de otras IAs deben pasar por revisión aquí antes de implementarse
- Implementación: Claude Code

**Ante cualquier duda sobre si algo se puede cambiar: NO cambiar.**
Consultar primero.
