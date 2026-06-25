/* ═════════════════════════════════════════════════════════════
   ZERO POS — meson.js
   Lógica de meson.html
   ═════════════════════════════════════════════════════════════ */

'use strict';
const fmt = n => '$' + Math.round(n).toLocaleString('es-CL');

// ── ESTADO ────────────────────────────────────────────────────────────────────
let usuarioActual = null, pinVal = '', usuarioSeleccionado = null;
let productos = [], indiceCodigo = new Map(), categorias = [], catActual = null;
let carrito = [];
let _prodNuevoCodigo = '', _merchProd = null, _cantVal = '', _merchCodigo = '';
let _pedidosTimer = null, _pedidosVistos = new Set();
let _modoActual = null, _toastTimer = null, _enviadoTimer = null, _listoTimer = null;
let _merchItems = [];
let _llamarActivo = false;

// ── TOAST ─────────────────────────────────────────────────────────────────────
function showToast(msg, tipo = 'info') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'show ' + tipo;
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove('show'), 3200);
}

// ── LOGIN ─────────────────────────────────────────────────────────────────────
async function cargarUsuarios() {
  const lista = await fetch('/api/auth/usuarios/publico').then(r => r.json()).catch(() => []);
  const grid = document.getElementById('userGrid');
  grid.innerHTML = lista.map(u =>
    `<button class="user-btn" onclick="selUser(this,${u.id},${JSON.stringify(u.nombre)})">${u.nombre}</button>`
  ).join('');
  if (lista.length === 1) selUser(grid.firstElementChild, lista[0].id, lista[0].nombre);
}
function selUser(el, id, nombre) {
  document.querySelectorAll('.user-btn').forEach(b => b.classList.remove('selected'));
  el.classList.add('selected');
  usuarioSeleccionado = { id, nombre };
  pinVal = ''; updatePinDots();
}
function pinDigit(d) {
  if (pinVal.length >= 4) return;
  pinVal += d; updatePinDots();
  if (pinVal.length === 4) setTimeout(pinSubmit, 150);
}
function pinBorrar() { pinVal = pinVal.slice(0, -1); updatePinDots(); }
function updatePinDots() {
  for (let i = 0; i < 4; i++)
    document.getElementById('d' + i).classList.toggle('filled', i < pinVal.length);
}
async function pinSubmit() {
  if (!usuarioSeleccionado) { document.getElementById('loginErr').textContent = 'Selecciona un vendedor'; return; }
  if (pinVal.length !== 4) { document.getElementById('loginErr').textContent = 'Ingresa tu PIN'; return; }
  try {
    const r = await fetch('/api/auth/login', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin: pinVal, usuario_id: usuarioSeleccionado.id }),
    });
    const data = await r.json();
    if (r.ok) { usuarioActual = data.usuario; entrarAlMain(); }
    else { document.getElementById('loginErr').textContent = data.error || 'PIN incorrecto'; pinVal = ''; updatePinDots(); }
  } catch (e) { document.getElementById('loginErr').textContent = 'Error de conexión'; pinVal = ''; updatePinDots(); }
}
async function logout() {
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
  location.reload();
}

// ── ENTRADA AL MAIN ───────────────────────────────────────────────────────────
function entrarAlMain() {
  document.getElementById('pantallaLogin').style.display = 'none';
  document.getElementById('pantallaMain').style.display = 'flex';
  document.getElementById('topUser').textContent = usuarioActual.nombre;
  document.getElementById('inicioSaludo').textContent = 'Bienvenido/a, ' + usuarioActual.nombre;
  if (!['bodega','delivery','cocina'].includes(usuarioActual.rol)) {
    const btn = document.getElementById('btnMesonCredit');
    if (btn) btn.style.display = '';
  }
  cargarProductos();
  actualizarBadgePedidos();
  iniciarPollLlamada();
}

// ── NAVEGACIÓN ─────────────────────────────────────────────────────────────────
function irModo(modo) {
  _modoActual = modo;
  document.getElementById('modoInicio').style.display = 'none';
  document.getElementById('btnBack').style.display = '';

  if (modo === 'venta') {
    document.getElementById('topbarModo').textContent = 'Nueva venta';
    document.getElementById('clienteLabel').style.display = 'flex';
    document.getElementById('inputCliente').value = '';
    document.getElementById('modoVenta').style.display = 'flex';
    carrito = [];
    actualizarFAB();
    renderGrid();
  } else if (modo === 'mercaderia') {
    document.getElementById('topbarModo').textContent = 'Recibir mercadería';
    document.getElementById('modoMercaderia').style.display = 'flex';
  } else if (modo === 'pedidos') {
    document.getElementById('topbarModo').textContent = 'Mis pedidos';
    document.getElementById('modoPedidos').style.display = 'flex';
    cargarMisPedidos();
    _pedidosTimer = setInterval(cargarMisPedidos, 10000);
  }
}

function volverInicio() {
  if (_pedidosTimer) { clearInterval(_pedidosTimer); _pedidosTimer = null; }
  cerrarDrawer();
  ['modoVenta', 'modoMercaderia', 'modoPedidos'].forEach(id =>
    document.getElementById(id).style.display = 'none'
  );
  document.getElementById('modoInicio').style.display = '';
  document.getElementById('btnBack').style.display = 'none';
  document.getElementById('topbarModo').textContent = 'Mesón';
  document.getElementById('clienteLabel').style.display = 'none';
  _modoActual = null;
  actualizarBadgePedidos();
}

// ── PRODUCTOS ──────────────────────────────────────────────────────────────────
async function cargarProductos() {
  productos = await fetch('/api/productos/completos', { credentials: 'include' })
    .then(r => r.json()).catch(() => []);
  indiceCodigo = new Map();
  const catSet = new Map();
  productos.forEach(p => {
    if (p.codigo_barras) indiceCodigo.set(String(p.codigo_barras), p);
    if (p._variantes) p._variantes.forEach(v => {
      if (v.codigo_barras) indiceCodigo.set(String(v.codigo_barras), { ...p, _v: v });
    });
    if (p.categoria_nombre) catSet.set(p.categoria_id, p.categoria_nombre);
  });
  categorias = [{ id: null, nombre: 'Todos' },
    ...Array.from(catSet.entries()).map(([id, nombre]) => ({ id, nombre }))];
  renderCats();
  if (!('BarcodeDetector' in window)) setTimeout(() => Escaner._cargarZXing().catch(() => {}), 0);
}

function renderCats() {
  document.getElementById('catsBar').innerHTML = categorias.map(c =>
    `<button class="cat-chip ${c.id === catActual ? 'active' : ''}" onclick="filtrarCat(${JSON.stringify(c.id)})">${c.nombre}</button>`
  ).join('');
}
function filtrarCat(cid) {
  catActual = cid === null ? null : Number(cid);
  renderCats(); renderGrid();
}
function filtrarProds() { renderGrid(); }

// Emoji por categoría para las cards
const _emojiCat = { bebidas:'🥤', pan:'🥖', panaderia:'🥐', cafe:'☕', sushi:'🍣',
  carnes:'🥩', lacteos:'🥛', verduras:'🥬', frutas:'🍎', snacks:'🍪',
  aseo:'🧼', congelados:'🧊', alcohol:'🍺', vinos:'🍷' };
function _emoji(prod) {
  const cn = (prod.categoria_nombre || '').toLowerCase();
  for (const [k, v] of Object.entries(_emojiCat))
    if (cn.includes(k)) return v;
  return '📦';
}

function renderGrid() {
  const q = (document.getElementById('searchProd')?.value || '').toLowerCase().trim();
  let lista = productos.filter(p => p.activo !== 0);
  if (catActual !== null) lista = lista.filter(p => p.categoria_id === catActual);
  if (q) lista = lista.filter(p =>
    p.nombre.toLowerCase().includes(q) || (p.codigo_barras || '').includes(q)
  );
  const grid = document.getElementById('mesonGrid');
  if (!grid) return;
  if (!lista.length) {
    grid.innerHTML = '<div class="grid-vacio">Sin resultados</div>';
    return;
  }
  grid.innerHTML = lista.slice(0, 100).map(p => `
    <div class="meson-card" onclick="agregarAlCarrito(${p.id})">
      <div class="mc-emoji">${_emoji(p)}</div>
      <div class="mc-nombre">${p.nombre}</div>
      <div class="mc-precio">${p.es_granel ? fmt(p.precio) + '/' + (p.precio_por || 'kg') : fmt(p.precio)}</div>
    </div>`).join('');
}

function agregarAlCarrito(pid) {
  const p = productos.find(x => x.id === pid);
  if (!p) return;
  const existe = carrito.find(i => i.producto_id === pid);
  if (existe) { existe.cantidad++; existe.subtotal = existe.precio_unit * existe.cantidad; }
  else carrito.push({ producto_id: pid, nombre: p.nombre, cantidad: 1, precio_unit: p.precio, subtotal: p.precio });
  actualizarFAB();
  renderDrawerItems();
  if (navigator.vibrate) navigator.vibrate(30);
}

// ── FAB Y DRAWER ──────────────────────────────────────────────────────────────
function actualizarFAB() {
  const fab = document.getElementById('mesonCartFAB');
  const count = carrito.reduce((s, i) => s + i.cantidad, 0);
  const total = carrito.reduce((s, i) => s + i.subtotal, 0);
  if (count > 0) {
    fab.style.display = '';
    document.getElementById('mesonCartCount').textContent = count;
    document.getElementById('mesonCartTotal').textContent = fmt(total);
  } else {
    fab.style.display = 'none';
  }
}

function abrirDrawer() {
  document.getElementById('mesonDrawer').classList.add('abierto');
  document.getElementById('mesonOverlay').classList.add('visible');
  renderDrawerItems();
}
function cerrarDrawer() {
  document.getElementById('mesonDrawer').classList.remove('abierto');
  document.getElementById('mesonOverlay').classList.remove('visible');
  if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
  document.body.focus();
}

function renderDrawerItems() {
  const el = document.getElementById('drawerItems');
  // Actualizar nombre cliente
  const nombre = _getNombreCliente();
  document.getElementById('drawerCliente').textContent = nombre || '—';
  if (!carrito.length) {
    el.innerHTML = '<div class="drawer-empty">El carrito está vacío</div>';
    document.getElementById('drawerTotal').textContent = '$0';
    return;
  }
  el.innerHTML = carrito.map((item, idx) => `
    <div class="ditem-row">
      <div class="ditem-cant-ctrl">
        <button class="ditem-cant-btn" onclick="cambiarCant(${idx},-1)">−</button>
        <span class="ditem-cant-num">${item.cantidad}</span>
        <button class="ditem-cant-btn" onclick="cambiarCant(${idx},1)">+</button>
      </div>
      <div class="ditem-info">
        <div class="ditem-nombre">${item.nombre}</div>
        <div class="ditem-sub">${fmt(item.subtotal)}</div>
      </div>
      <button class="ditem-del" onclick="quitarItem(${idx})">✕</button>
    </div>`).join('');
  document.getElementById('drawerTotal').textContent = fmt(carrito.reduce((s, i) => s + i.subtotal, 0));
}

function _getNombreCliente() {
  return (document.getElementById('inputCliente')?.value || '').trim();
}

function cambiarCant(idx, delta) {
  carrito[idx].cantidad = Math.max(1, carrito[idx].cantidad + delta);
  carrito[idx].subtotal = carrito[idx].precio_unit * carrito[idx].cantidad;
  actualizarFAB(); renderDrawerItems();
}
function quitarItem(idx) { carrito.splice(idx, 1); actualizarFAB(); renderDrawerItems(); }
function limpiarCarrito() {
  if (carrito.length && !confirm('¿Limpiar el carrito?')) return;
  carrito = []; actualizarFAB(); renderDrawerItems();
}

// ── ESCÁNER ────────────────────────────────────────────────────────────────────
function _escanerOverlay(msg) {
  const el = document.getElementById('escanerOverlay');
  if (msg) { document.getElementById('escanerOverlayMsg').textContent = msg; el.style.display = 'flex'; }
  else el.style.display = 'none';
}
const Escaner = {
  _zxingPromise: null,
  _cargarZXing() {
    if (typeof ZXing !== 'undefined') return Promise.resolve();
    if (this._zxingPromise) return this._zxingPromise;
    this._zxingPromise = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/@zxing/library@0.20.0/umd/index.min.js';
      s.onload = () => { console.log('[ZERO] ZXing cargado OK'); setTimeout(resolve, 100); };
      s.onerror = e => { console.error('[ZERO] ZXing falló al cargar:', e); reject(e); };
      document.head.appendChild(s);
    });
    return this._zxingPromise;
  },
};
async function detectarConZXing(file) {
  try {
    await Escaner._cargarZXing();
    if (typeof ZXing === 'undefined') return null;
    return new Promise(resolve => {
      const img = new Image();
      const url = URL.createObjectURL(file);
      img.onload = () => {
        const MAX = 1200;
        let w = img.width, h = img.height;
        if (w > MAX || h > MAX) {
          const ratio = Math.min(MAX / w, MAX / h);
          w = Math.floor(w * ratio); h = Math.floor(h * ratio);
        }
        const canvas = document.createElement('canvas');
        canvas.width = w; canvas.height = h;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, w, h);
        console.log('[ZERO] Canvas ZXing:', w, 'x', h);
        try {
          const d = ctx.getImageData(0, 0, w, h);
          const lum = new ZXing.RGBLuminanceSource(d.data, w, h);
          const bin = new ZXing.BinaryBitmap(new ZXing.HybridBinarizer(lum));
          const r = new ZXing.MultiFormatReader().decode(bin);
          URL.revokeObjectURL(url);
          console.log('[ZERO] ZXing encontró:', r.getText());
          resolve(r.getText());
        } catch (e) {
          try {
            const cx = Math.floor(w * 0.1), cy = Math.floor(h * 0.1);
            const cw = Math.floor(w * 0.8), ch = Math.floor(h * 0.8);
            const d2 = ctx.getImageData(cx, cy, cw, ch);
            const lum2 = new ZXing.RGBLuminanceSource(d2.data, cw, ch);
            const bin2 = new ZXing.BinaryBitmap(new ZXing.HybridBinarizer(lum2));
            const r2 = new ZXing.MultiFormatReader().decode(bin2);
            URL.revokeObjectURL(url);
            console.log('[ZERO] ZXing centro:', r2.getText());
            resolve(r2.getText());
          } catch (e2) {
            URL.revokeObjectURL(url);
            console.warn('[ZERO] ZXing no detectó código');
            resolve(null);
          }
        }
      };
      img.onerror = () => { URL.revokeObjectURL(url); resolve(null); };
      img.src = url;
    });
  } catch (e) {
    console.error('[ZERO] Error ZXing:', e);
    return null;
  }
}
async function detectarCodigoEnImagen(file) {
  try {
    showToast('🔍 Analizando código...', 'info');
    const fd = new FormData();
    fd.append('imagen', file);
    const resp = await fetch('/api/productos/detectar-codigo', {
      method: 'POST',
      credentials: 'include',
      body: fd,
    });
    const data = await resp.json();
    if (data.ok && data.codigo) {
      console.log('[ZERO] Código detectado en servidor:', data.codigo, '(' + data.tipo + ')');
      return data.codigo;
    }
    console.warn('[ZERO] No se detectó código:', data.mensaje || data.error);
    return null;
  } catch (e) {
    console.error('[ZERO] Error enviando imagen al servidor:', e);
    return null;
  }
}
function abrirEscaner(onDetectado) {
  const input = document.createElement('input');
  input.type = 'file'; input.accept = 'image/*';
  if (/Android|iPhone|iPad|iPod/i.test(navigator.userAgent)) input.capture = 'environment';
  input.onchange = async e => {
    const file = e.target.files?.[0];
    if (!file) return;
    _escanerOverlay('📷 Analizando imagen...');
    try {
      const codigo = await detectarCodigoEnImagen(file);
      _escanerOverlay(null);
      if (codigo) {
        if (navigator.vibrate) navigator.vibrate(50);
        onDetectado(codigo);
      } else {
        showToast('No se detectó código — ingresa manualmente', 'error');
        const campo = document.getElementById('searchProd');
        if (campo) { campo.focus(); campo.select(); }
      }
    } catch (err) { _escanerOverlay(null); showToast('Error al procesar imagen', 'error'); }
  };
  input.click();
}
function escanearVenta() {
  abrirEscaner(codigo => {
    const prod = indiceCodigo.get(String(codigo));
    if (prod) { agregarAlCarrito(prod.id); showToast('✓ ' + prod.nombre, 'success'); }
    else {
      _prodNuevoCodigo = codigo;
      document.getElementById('prodNuevoCodigo').textContent = 'Código: ' + codigo;
      document.getElementById('prodNuevoNombre').value = '';
      document.getElementById('prodNuevoPrecio').value = '';
      document.getElementById('overlayProdNuevo').classList.add('active');
      setTimeout(() => document.getElementById('prodNuevoNombre').focus(), 100);
    }
  });
}
function cerrarProdNuevo() { document.getElementById('overlayProdNuevo').classList.remove('active'); }
async function agregarProdNuevo() {
  const nombre = document.getElementById('prodNuevoNombre').value.trim();
  const precio = parseInt(document.getElementById('prodNuevoPrecio').value) || 0;
  if (!nombre) { showToast('Ingresa un nombre', 'error'); return; }
  if (precio <= 0) { showToast('Ingresa un precio válido', 'error'); return; }
  let productoId = null;
  try {
    const r = await fetch('/api/productos', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nombre, precio, codigo_barras: _prodNuevoCodigo || null, activo: 0, pendiente_verificar: 1, stock: 0 }),
    });
    if (r.ok) { const d = await r.json(); productoId = d.id; }
  } catch (e) {}
  carrito.push({ producto_id: productoId, nombre: nombre + ' ⚠️', cantidad: 1, precio_unit: precio, subtotal: precio, _pendiente: true });
  actualizarFAB(); renderDrawerItems();
  showToast('Agregado (pendiente de verificar)', 'info');
  cerrarProdNuevo();
}

// ── ENVIAR A CAJA ─────────────────────────────────────────────────────────────
async function enviarACaja() {
  if (!carrito.length) { showToast('El carrito está vacío', 'error'); return; }
  const total = carrito.reduce((s, i) => s + i.subtotal, 0);
  const nombre = _getNombreCliente();
  try {
    const r = await fetch('/api/pedidos', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tipo: 'local', estado: 'en_espera', origen: 'meson',
        cliente_nombre: nombre || '',
        metodo_pago: 'efectivo',
        items: carrito.map(i => ({
          producto_id: i.producto_id || null,
          nombre: i.nombre.replace(' ⚠️', ''),
          cantidad: i.cantidad, precio: i.precio_unit, subtotal: i.subtotal,
        })),
      }),
    });
    const data = await r.json();
    if (!r.ok) { showToast(data.error || 'Error al enviar', 'error'); return; }
    const displayNombre = data.cliente_nombre || '#' + data.numero;
    document.getElementById('enviadoNum').textContent = 'Pedido #' + data.numero + ' — ' + displayNombre;
    document.getElementById('enviadoTotal').textContent = fmt(total);
    document.getElementById('enviadoSub').textContent = nombre
      ? 'El cajero llamará a ' + displayNombre + ' cuando esté listo'
      : 'El cajero procesará el pedido';
    document.getElementById('overlayEnviado').classList.add('active');
    carrito = []; cerrarDrawer(); actualizarFAB();
    if (_enviadoTimer) clearTimeout(_enviadoTimer);
    _enviadoTimer = setTimeout(() => {
      document.getElementById('overlayEnviado').classList.remove('active');
      volverInicio();
    }, 5000);
  } catch (e) { showToast('Error de conexión', 'error'); }
}

// ── MODO 2: MERCADERÍA ─────────────────────────────────────────────────────────
function escanearMerch() {
  abrirEscaner(codigo => {
    const prod = indiceCodigo.get(String(codigo));
    if (prod) abrirMerchCant(prod);
    else {
      _merchCodigo = codigo;
      document.getElementById('merchNuevoCodigo').textContent = 'Código: ' + codigo;
      ['merchNuevoNombre','merchNuevoCosto','merchNuevoCant'].forEach(id => document.getElementById(id).value = '');
      document.getElementById('overlayMerchNuevo').classList.add('active');
      setTimeout(() => document.getElementById('merchNuevoNombre').focus(), 100);
    }
  });
}
function buscarMerch() {
  document.getElementById('merchBuscarInput').value = '';
  document.getElementById('merchBuscarResultados').innerHTML = '';
  document.getElementById('overlayMerchBuscar').classList.add('active');
  setTimeout(() => document.getElementById('merchBuscarInput').focus(), 100);
}
function filtrarMerchBuscar() {
  const q = document.getElementById('merchBuscarInput').value.toLowerCase().trim();
  const el = document.getElementById('merchBuscarResultados');
  if (!q) { el.innerHTML = ''; return; }
  const found = productos.filter(p => p.nombre.toLowerCase().includes(q) || (p.codigo_barras || '').includes(q)).slice(0, 15);
  if (!found.length) { el.innerHTML = '<p style="padding:10px;color:var(--text-dim);font-size:13px">Sin resultados</p>'; return; }
  el.innerHTML = found.map(p =>
    `<div class="merch-buscar-item" onclick="seleccionarMerchProd(${p.id})">
      <div class="merch-buscar-nombre">${p.nombre}</div>
      <div class="merch-buscar-sub">Stock: ${p.stock} | ${fmt(p.precio)}</div>
    </div>`).join('');
}
function seleccionarMerchProd(pid) {
  cerrarMerchBuscar();
  const p = productos.find(x => x.id === pid);
  if (p) abrirMerchCant(p);
}
function cerrarMerchBuscar() { document.getElementById('overlayMerchBuscar').classList.remove('active'); }
function abrirMerchCant(prod) {
  _merchProd = prod; _cantVal = '';
  document.getElementById('merchCantTitulo').textContent = prod.nombre;
  document.getElementById('merchCantSub').textContent = 'Stock actual: ' + prod.stock + ' unidades';
  document.getElementById('cantDisplay').textContent = '0';
  document.getElementById('overlayMerchCant').classList.add('active');
}
function cerrarMerchCant() { document.getElementById('overlayMerchCant').classList.remove('active'); _merchProd = null; }
function cantNum(d) { _cantVal = _cantVal === '0' ? d : _cantVal + d; document.getElementById('cantDisplay').textContent = _cantVal || '0'; }
function cantBorrar() { _cantVal = _cantVal.slice(0,-1); document.getElementById('cantDisplay').textContent = _cantVal || '0'; }
async function confirmarMerchCant() {
  const cant = parseInt(_cantVal) || 0;
  if (!cant) { showToast('Ingresa una cantidad', 'error'); return; }
  if (!_merchProd) return;
  try {
    const r = await fetch(`/api/productos/${_merchProd.id}/stock`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tipo: 'entrada', cantidad: cant, motivo: 'recepcion_meson' }),
    });
    const data = await r.json();
    if (r.ok) {
      const p = productos.find(x => x.id === _merchProd.id);
      if (p) p.stock = data.stock_nuevo;
      _merchItems.push({ nombre: _merchProd.nombre, cantidad: cant, ok: true });
      renderMerchLista(); showToast('+' + cant + ' ' + _merchProd.nombre, 'success');
    } else showToast(data.error || 'Error', 'error');
  } catch (e) { showToast('Error de conexión', 'error'); }
  cerrarMerchCant();
}
function cerrarMerchNuevo() { document.getElementById('overlayMerchNuevo').classList.remove('active'); }
async function confirmarMerchNuevo() {
  const nombre = document.getElementById('merchNuevoNombre').value.trim();
  const costo  = parseInt(document.getElementById('merchNuevoCosto').value) || 0;
  const cant   = parseInt(document.getElementById('merchNuevoCant').value) || 0;
  if (!nombre) { showToast('Ingresa un nombre', 'error'); return; }
  try {
    const r = await fetch('/api/productos', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nombre, precio_costo: costo, precio: costo, stock: cant, activo: 0, pendiente_verificar: 1, codigo_barras: _merchCodigo || null }),
    });
    if (r.ok) {
      _merchItems.push({ nombre, cantidad: cant, ok: false });
      renderMerchLista(); showToast(nombre + ' guardado como pendiente', 'info'); cerrarMerchNuevo();
    } else { const d = await r.json(); showToast(d.error || 'Error', 'error'); }
  } catch (e) { showToast('Error de conexión', 'error'); }
}
function renderMerchLista() {
  const el = document.getElementById('merchLista');
  if (!_merchItems.length) { el.innerHTML = '<div class="merch-empty">Nada recibido aún</div>'; return; }
  el.innerHTML = _merchItems.map(item => `
    <div class="merch-item">
      <span class="merch-item-icon">${item.ok ? '✅' : '⚠️'}</span>
      <div class="merch-item-info">
        <div class="merch-item-nombre">${item.nombre}</div>
        <div class="${item.ok ? 'merch-item-cant' : 'merch-item-warn'}">
          +${item.cantidad} ${item.ok ? 'recibidas' : '— pendiente verificar'}
        </div>
      </div>
    </div>`).join('');
}

// ── MODO 3: MIS PEDIDOS ───────────────────────────────────────────────────────
async function cargarMisPedidos() {
  try {
    const d = await fetch('/api/pedidos?activos=1', { credentials: 'include' }).then(r => r.json()).catch(() => []);
    const todos = Array.isArray(d) ? d : (d.pedidos || []);
    const misMios = todos.filter(p => p.origen === 'meson' && ['en_espera','en_proceso','listo'].includes(p.estado));
    renderMisPedidos(misMios);
    misMios.forEach(p => {
      if (p.estado === 'listo' && !_pedidosVistos.has(p.id)) {
        _pedidosVistos.add(p.id);
        mostrarAvisoListo(p.cliente_nombre || '#' + p.numero);
      }
    });
    const badge = document.getElementById('badgePedidos');
    badge.textContent = misMios.length;
    badge.style.display = misMios.length ? '' : 'none';
  } catch (e) {}
}
function mostrarAvisoListo(nombre) {
  document.getElementById('listoNombre').textContent = nombre;
  document.getElementById('overlayListo').classList.add('active');
  if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
  if (_listoTimer) clearTimeout(_listoTimer);
  _listoTimer = setTimeout(() => document.getElementById('overlayListo').classList.remove('active'), 5000);
}
function renderMisPedidos(pedidos) {
  const el = document.getElementById('pedidosLista');
  if (!pedidos.length) { el.innerHTML = '<div class="pedidos-empty">Sin pedidos activos</div>'; return; }
  const labels = { en_espera:'🔵 En espera', en_proceso:'🟡 Preparando', listo:'🟢 Listo' };
  el.innerHTML = pedidos.map(p => `
    <div class="pedido-row ${p.estado === 'listo' ? 'listo' : ''}"
         onclick="${p.estado === 'listo' ? `mostrarAvisoListo(${JSON.stringify(p.cliente_nombre || '#' + p.numero)})` : ''}">
      <div class="pedido-num">#${p.numero}</div>
      <div class="pedido-info">
        <div class="pedido-nombre">${p.cliente_nombre || '#' + p.numero}</div>
        <div class="pedido-total">${fmt(p.total)}</div>
      </div>
      <span class="pedido-estado estado-${p.estado}">${labels[p.estado] || p.estado}</span>
    </div>`).join('');
  document.getElementById('pedidosRefreshLabel').textContent =
    'Actualizado — ' + pedidos.length + ' pedido' + (pedidos.length !== 1 ? 's' : '') + ' activo' + (pedidos.length !== 1 ? 's' : '');
}
async function actualizarBadgePedidos() {
  try {
    const d = await fetch('/api/pedidos?activos=1', { credentials: 'include' }).then(r => r.json()).catch(() => []);
    const todos = Array.isArray(d) ? d : (d.pedidos || []);
    const n = todos.filter(p => p.origen === 'meson' && ['en_espera','en_proceso','listo'].includes(p.estado)).length;
    const badge = document.getElementById('badgePedidos');
    badge.textContent = n; badge.style.display = n ? '' : 'none';
  } catch (e) {}
}

// ── POLL CAJERO ────────────────────────────────────────────────────────────────
function iniciarPollLlamada() {
  setInterval(async () => {
    try {
      const d = await fetch('/api/pedidos/llamar/activo', { credentials: 'include' }).then(r => r.json());
      if (d.activo && !_llamarActivo) {
        _llamarActivo = true;
        showToast('¡Llamando ticket #' + d.numero + '!', 'success');
        setTimeout(() => { _llamarActivo = false; }, 5000);
      } else if (!d.activo) { _llamarActivo = false; }
    } catch (e) {}
  }, 3000);
}

// ── EVENTS ─────────────────────────────────────────────────────────────────────
document.getElementById('btnScanVenta').addEventListener('click', escanearVenta);

document.addEventListener('keydown', e => {
  if (document.getElementById('pantallaLogin').style.display !== 'none') {
    if (e.key >= '0' && e.key <= '9') pinDigit(e.key);
    else if (e.key === 'Backspace') pinBorrar();
    else if (e.key === 'Enter') pinSubmit();
  }
  if (e.key === 'Escape') {
    document.querySelectorAll('.overlay.active').forEach(o => o.classList.remove('active'));
    cerrarDrawer();
  }
});

// Swipe para cerrar drawer
(function() {
  let startY = 0;
  const dr = document.getElementById('mesonDrawer');
  dr.addEventListener('touchstart', e => { startY = e.touches[0].clientY; }, { passive: true });
  dr.addEventListener('touchend', e => {
    if (e.changedTouches[0].clientY - startY > 60) cerrarDrawer();
  }, { passive: true });
})();

// ── INIT ───────────────────────────────────────────────────────────────────────
cargarUsuarios();
fetch('/api/auth/me', { credentials: 'include' }).then(r => r.json()).then(data => {
  if (data && data.id) { usuarioActual = data; entrarAlMain(); }
}).catch(() => {});


if ('serviceWorker' in navigator)
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {}));
