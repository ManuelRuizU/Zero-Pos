/* ═════════════════════════════════════════════════════════════
   ZERO POS — pedidos.js
   Lógica de pedidos.html
   ═════════════════════════════════════════════════════════════ */

// ─── State ───────────────────────────────────────────────
let pedidoTipo  = 'delivery';
let carrito     = [];
let cfgComuna   = '';       // [{producto_id, variante_id, nombre, cantidad, precio, subtotal, notas}]
let clienteActual = null;
let todosProd   = [];
let colaFiltro  = 'activos';
let allPedidos  = [];
let prodPendiente = null;   // producto esperando selección de variante
let _telTimer   = null;
let _prodTimer  = null;

// ─── Helpers ─────────────────────────────────────────────
const fmt = n => '$' + Math.round(n).toLocaleString('es-CL');

async function apiFetch(url, opts = {}) {
  try {
    const r = await fetch(url, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      ...opts,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    return r.ok ? r.json() : null;
  } catch { return null; }
}

// ─── Init ────────────────────────────────────────────────
async function init() {
  todosProd = await apiFetch('/api/productos/completos') || [];
  const cfg = await apiFetch('/api/config') || {};
  cfgComuna = cfg.comuna_negocio || '';
  await cargarCola();
  setInterval(cargarCola, 15000);
}

// ─── Tipo selector ───────────────────────────────────────
function setTipo(t) {
  pedidoTipo = t;
  document.querySelectorAll('.tipo-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tipo === t);
  });
  const showCliente  = t !== 'local';
  const showDir      = t === 'delivery';
  document.getElementById('secCliente').style.display   = showCliente ? '' : 'none';
  document.getElementById('secDireccion').style.display = showDir ? '' : 'none';
  validarForm();
}

// ─── Phone search ────────────────────────────────────────
function onTelInput(val) {
  clearTimeout(_telTimer);
  if (val.length < 7) { limpiarClienteBadge(); return; }
  _telTimer = setTimeout(() => buscarCliente(val), 400);
}

async function buscarCliente(tel) {
  const cl = await apiFetch(`/api/clientes/buscar?tel=${encodeURIComponent(tel)}`);
  if (cl && cl.id) {
    clienteActual = cl;
    document.getElementById('fNombre').value  = cl.nombre || '';
    document.getElementById('fTel2').value    = cl.telefono2 || '';
    document.getElementById('fEmail').value   = cl.email || '';
    document.getElementById('fDir').value     = cl.direccion || '';
    document.getElementById('fDepto').value   = cl.depto || '';
    document.getElementById('fComuna').value  = cl.comuna || '';
    const badge = document.getElementById('clienteBadge');
    badge.style.display = '';
    badge.className = '';
    badge.textContent = `✓ Cliente conocido — ${cl.total_pedidos} pedidos anteriores`;
    if (cl.receptores_frecuentes && cl.receptores_frecuentes.length > 0) {
      mostrarSugerenciaReceptor(cl.receptores_frecuentes[0]);
    } else {
      document.getElementById('receptorSugerencia').style.display = 'none';
    }
  } else {
    clienteActual = null;
    limpiarClienteBadge(true);
    document.getElementById('receptorSugerencia').style.display = 'none';
  }
  validarForm();
}

let _receptorSugerido = null;

function toggleReceptorFields() {
  const chk = document.getElementById('chkReceptor');
  const campos = document.getElementById('camposReceptor');
  campos.style.display = chk.checked ? 'flex' : 'none';
  if (chk.checked) document.getElementById('receptorNombre').focus();
}

function mostrarSugerenciaReceptor(rf) {
  _receptorSugerido = rf;
  const veces = rf.veces === 1 ? 'la última vez' : `las últimas ${rf.veces} veces`;
  document.getElementById('receptorSugerenciaTexto').textContent =
    `¿Entregamos a ${rf.nombre} como ${veces}?`;
  document.getElementById('receptorSugerencia').style.display = '';
}

function aceptarReceptorSugerido() {
  if (!_receptorSugerido) return;
  document.getElementById('chkReceptor').checked = true;
  toggleReceptorFields();
  document.getElementById('receptorNombre').value = _receptorSugerido.nombre;
  document.getElementById('receptorTel').value    = _receptorSugerido.tel || '';
  document.getElementById('receptorSugerencia').style.display = 'none';
  _receptorSugerido = null;
}

function rechazarReceptorSugerido() {
  document.getElementById('receptorSugerencia').style.display = 'none';
  _receptorSugerido = null;
  document.getElementById('chkReceptor').checked = true;
  toggleReceptorFields();
}

// ─── Autocomplete + validación de dirección ──────────────────────────────────
let _dirTimer = null;

function onDirInput(val) {
  clearTimeout(_dirTimer);
  document.getElementById('alertaDireccion').style.display = 'none';
  document.getElementById('fDir').style.borderColor = '';
  if (!val || val.length < 3) {
    document.getElementById('dirAutocomplete').style.display = 'none';
    return;
  }
  _dirTimer = setTimeout(() => _buscarDirecciones(val), 320);
}

async function _buscarDirecciones(q) {
  const comuna = document.getElementById('fComuna').value.trim() || cfgComuna;
  const params = new URLSearchParams({q});
  if (comuna) params.set('comuna', comuna);
  const results = await apiFetch(`/api/direcciones/buscar?${params}`) || [];
  const ac = document.getElementById('dirAutocomplete');
  if (!results.length) { ac.style.display = 'none'; return; }
  ac.innerHTML = results.map(r => {
    const c = r.calle.replace(/'/g, "\\'");
    const com = (r.comuna || '').replace(/'/g, "\\'");
    return `<div class="prod-result-item" onclick="seleccionarDir('${c}','${com}')">
      <span class="pname">${r.calle}</span>
      <span class="pprice">${r.comuna || ''}${r.fuente==='nominatim' ? ' 🌐' : ''}</span>
    </div>`;
  }).join('');
  ac.style.display = '';
}

function seleccionarDir(calle, comuna) {
  document.getElementById('fDir').value = calle;
  document.getElementById('dirAutocomplete').style.display = 'none';
  document.getElementById('alertaDireccion').style.display = 'none';
  document.getElementById('fDir').style.borderColor = 'var(--green)';
  if (comuna && !document.getElementById('fComuna').value.trim()) {
    document.getElementById('fComuna').value = comuna;
  }
  validarForm();
}

function usarSugerenciaDir(calle) {
  document.getElementById('fDir').value = calle;
  document.getElementById('alertaDireccion').style.display = 'none';
  document.getElementById('fDir').style.borderColor = 'var(--green)';
  validarForm();
}

function limpiarClienteBadge(nuevo = false) {
  const badge = document.getElementById('clienteBadge');
  if (nuevo) {
    badge.style.display = '';
    badge.className = 'nuevo';
    badge.textContent = '+ Nuevo cliente';
  } else {
    badge.style.display = 'none';
  }
}

// ─── Product search ──────────────────────────────────────
function onProdInput(val) {
  clearTimeout(_prodTimer);
  cerrarVariantes();
  if (!val.trim()) { document.getElementById('prodResultados').style.display = 'none'; return; }
  _prodTimer = setTimeout(() => mostrarResultados(val), 180);
}

function mostrarResultados(q) {
  const lower = q.toLowerCase();
  const matches = todosProd.filter(p =>
    p.nombre.toLowerCase().includes(lower) && p.stock > 0 || p.tiene_variantes
  ).slice(0, 10);

  const box = document.getElementById('prodResultados');
  if (!matches.length) { box.style.display = 'none'; return; }

  box.innerHTML = matches.map(p => {
    const varHint = p.tiene_variantes && p._variantes && p._variantes.length
      ? `<span class="variantes-hint">${p._variantes.length} variantes</span>` : '';
    return `<div class="prod-result-item" onclick="seleccionarProd(${p.id})">
      <div>
        <div class="pname">${p.nombre}</div>
        ${varHint}
      </div>
      <span class="pprice">${fmt(p.precio)}</span>
    </div>`;
  }).join('');
  box.style.display = '';
}

function seleccionarProd(id) {
  const prod = todosProd.find(p => p.id === id);
  if (!prod) return;
  document.getElementById('prodResultados').style.display = 'none';
  document.getElementById('prodInput').value = '';

  if (prod.tiene_variantes && prod._variantes && prod._variantes.length > 1) {
    prodPendiente = prod;
    mostrarVariantesPicker(prod);
  } else {
    agregarAlCarrito(prod, prod._variantes && prod._variantes.length ? prod._variantes[0] : null);
  }
}

function mostrarVariantesPicker(prod) {
  const picker = document.getElementById('variantesPicker');
  document.getElementById('vpTitulo').textContent = `Elige variante de ${prod.nombre}:`;
  const grid = document.getElementById('variantesGrid2');
  grid.innerHTML = prod._variantes.map(v => `
    <button class="vp-btn" onclick="seleccionarVariante(${v.id})"
            ${v.stock <= 0 ? 'disabled style="opacity:.4"' : ''}>
      ${v.nombre}<br><small style="color:var(--text-dim)">${fmt(v.precio)}</small>
    </button>`).join('');
  picker.style.display = 'flex';
}

function seleccionarVariante(vid) {
  if (!prodPendiente) return;
  const v = prodPendiente._variantes.find(x => x.id === vid);
  if (!v) return;
  agregarAlCarrito(prodPendiente, v);
  cerrarVariantes();
}

function cerrarVariantes() {
  prodPendiente = null;
  document.getElementById('variantesPicker').style.display = 'none';
}

function agregarAlCarrito(prod, variante) {
  const nombre = variante ? `${prod.nombre} — ${variante.nombre}` : prod.nombre;
  const precio = variante ? variante.precio : prod.precio;
  const existing = carrito.find(i =>
    i.producto_id === prod.id && i.variante_id === (variante ? variante.id : null)
  );
  if (existing) {
    existing.cantidad++;
    existing.subtotal = existing.cantidad * existing.precio;
  } else {
    carrito.push({
      producto_id: prod.id,
      variante_id: variante ? variante.id : null,
      nombre, cantidad: 1, precio, subtotal: precio, notas: '',
    });
  }
  renderCarrito();
}

function renderCarrito() {
  const lista = document.getElementById('carritoLista');
  if (!carrito.length) {
    lista.innerHTML = '<div style="color:var(--text-dim);font-size:12px;padding:4px 0">Sin productos aún</div>';
    actualizarTotal();
    validarForm();
    return;
  }
  lista.innerHTML = carrito.map((item, i) => `
    <div class="carrito-item">
      <div style="flex:1">
        <div style="display:flex;align-items:center;gap:8px">
          <div class="ci-nombre">${item.nombre}</div>
          <div class="ci-precio">${fmt(item.subtotal)}</div>
          <div class="ci-qty">
            <button onclick="cambiarQty(${i},-1)">−</button>
            <span>${item.cantidad}</span>
            <button onclick="cambiarQty(${i},1)">+</button>
          </div>
          <button class="ci-del" onclick="quitarItem(${i})">×</button>
        </div>
        <input class="ci-notas-input" type="text"
               placeholder="Nota (ej: sin wasabi)"
               value="${item.notas || ''}"
               oninput="setNotaItem(${i}, this.value)">
      </div>
    </div>`).join('');
  actualizarTotal();
  validarForm();
}

function cambiarQty(i, delta) {
  carrito[i].cantidad = Math.max(1, carrito[i].cantidad + delta);
  carrito[i].subtotal = carrito[i].cantidad * carrito[i].precio;
  renderCarrito();
}

function quitarItem(i) {
  carrito.splice(i, 1);
  renderCarrito();
}

function setNotaItem(i, val) {
  carrito[i].notas = val;
}

function actualizarTotal() {
  const total = carrito.reduce((s, i) => s + i.subtotal, 0);
  document.getElementById('totalVal').textContent = fmt(total);
}

// ─── Validation ──────────────────────────────────────────
function validarForm() {
  let ok = carrito.length > 0;
  if (pedidoTipo !== 'local') {
    ok = ok && document.getElementById('fNombre').value.trim() !== '';
  }
  if (pedidoTipo === 'delivery') {
    ok = ok && document.getElementById('fDir').value.trim() !== '';
  }
  document.getElementById('btnConfirmar').disabled = !ok;
}

// ─── Confirm order ───────────────────────────────────────
async function confirmarPedido() {
  const nombre = document.getElementById('fNombre').value.trim();
  const payload = {
    tipo:           pedidoTipo,
    cliente_nombre: nombre || 'Local',
    cliente_tel:    document.getElementById('fTel').value.trim(),
    cliente_tel2:   document.getElementById('fTel2').value.trim(),
    cliente_email:  document.getElementById('fEmail').value.trim(),
    direccion:      document.getElementById('fDir').value.trim(),
    depto:          document.getElementById('fDepto').value.trim(),
    referencia:     document.getElementById('fRef').value.trim(),
    comuna:         document.getElementById('fComuna').value.trim() || cfgComuna,
    notas:          document.getElementById('fNotas').value.trim(),
    metodo_pago:    document.getElementById('fPago').value,
    receptor_nombre: document.getElementById('chkReceptor')?.checked
                       ? document.getElementById('receptorNombre').value.trim() || null
                       : null,
    receptor_tel:   document.getElementById('chkReceptor')?.checked
                       ? document.getElementById('receptorTel').value.trim() || null
                       : null,
    items: carrito.map(i => ({
      producto_id: i.producto_id,
      variante_id: i.variante_id,
      nombre:      i.nombre,
      cantidad:    i.cantidad,
      precio:      i.precio,
      subtotal:    i.subtotal,
      notas:       i.notas || null,
    })),
  };

  const btn = document.getElementById('btnConfirmar');
  btn.disabled = true;
  btn.textContent = 'Enviando…';

  const res = await apiFetch('/api/pedidos', { method: 'POST', body: payload });

  btn.disabled = false;
  btn.textContent = '✅ Confirmar Pedido';

  if (!res || !res.id) {
    alert('Error al crear el pedido. Intenta de nuevo.');
    return;
  }

  printComanda(res);
  limpiarForm();
  await cargarCola();
  if (window.innerWidth <= 720) showTab('cola');
}

function limpiarForm() {
  carrito = [];
  clienteActual = null;
  _receptorSugerido = null;
  ['fTel','fNombre','fTel2','fEmail','fDir','fDepto','fRef','fComuna','fNotas',
   'receptorNombre','receptorTel'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  const chk = document.getElementById('chkReceptor');
  if (chk) { chk.checked = false; }
  document.getElementById('camposReceptor').style.display = 'none';
  document.getElementById('receptorSugerencia').style.display = 'none';
  document.getElementById('clienteBadge').style.display = 'none';
  document.getElementById('alertaDireccion').style.display = 'none';
  document.getElementById('fDir').style.borderColor = '';
  renderCarrito();
}

// ─── Cola ────────────────────────────────────────────────
function setFiltro(f, btn) {
  colaFiltro = f;
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  renderCola();
}

async function cargarCola() {
  const data = await apiFetch('/api/pedidos?activos=1') || [];
  // Also fetch despachados for "todos" filter
  const todos = await apiFetch('/api/pedidos') || [];
  allPedidos = todos;
  const activos = data.length;
  document.getElementById('badgeActivos').textContent = activos;
  const tabBadge = document.getElementById('tabColaBadge');
  tabBadge.textContent = activos > 0 ? `(${activos})` : '';
  renderCola();
}

const TIPO_EMOJI = { delivery: '🛵', retiro: '🏠', local: '🪑' };
const ESTADO_LABEL = {
  nuevo: 'Nuevo', preparando: 'Preparando',
  listo: 'Listo', despachado: 'Despachado', cancelado: 'Cancelado',
};

function tiempoDesde(iso) {
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60)  return `${diff}s`;
  if (diff < 3600) return `${Math.floor(diff/60)}m`;
  return `${Math.floor(diff/3600)}h`;
}

function renderCola() {
  let lista = allPedidos;
  if (colaFiltro === 'activos') {
    lista = allPedidos.filter(p => !['despachado','cancelado'].includes(p.estado));
  } else if (colaFiltro !== 'todos') {
    lista = allPedidos.filter(p => p.estado === colaFiltro);
  }

  const box = document.getElementById('colaCards');
  if (!lista.length) {
    box.innerHTML = `<div style="color:var(--text-dim);font-size:13px;padding:20px;text-align:center">
      ${colaFiltro === 'activos' ? 'Sin pedidos activos' : 'Sin pedidos'}</div>`;
    return;
  }

  box.innerHTML = lista.map(p => {
    const items = p.items || [];
    const resumen = items.slice(0,2).map(i => `${i.cantidad}× ${i.nombre}`).join(', ')
      + (items.length > 2 ? ` y ${items.length - 2} más` : '');

    const notasItems = items.filter(i => i.notas).map(i => `⚠️ ${i.nombre}: ${i.notas}`).join(' | ');

    const acciones = buildAcciones(p);
    return `
    <div class="pedido-card estado-${p.estado}">
      <div class="pc-top">
        <span class="pc-num">#${String(p.numero).padStart(3,'0')}</span>
        <span class="pc-tipo">${TIPO_EMOJI[p.tipo] || ''}</span>
        <span class="estado-badge estado-${p.estado}">${ESTADO_LABEL[p.estado]}</span>
        <span class="pc-time">hace ${tiempoDesde(p.creado_en)}</span>
      </div>
      <div class="pc-cliente">${p.cliente_nombre}</div>
      ${p.tipo === 'delivery' && p.direccion ? `<div style="font-size:11px;color:var(--text-dim)">📍 ${p.direccion}${p.depto ? ', '+p.depto : ''}</div>` : ''}
      <div class="pc-items">${resumen}</div>
      ${notasItems ? `<div class="pc-notas">${notasItems}</div>` : ''}
      ${p.notas ? `<div class="pc-notas">📝 ${p.notas}</div>` : ''}
      <div style="font-size:12px;color:var(--text-dim)">${fmt(p.total)} · ${p.metodo_pago}</div>
      <div class="pc-actions">${acciones}</div>
    </div>`;
  }).join('');
}

function buildAcciones(p) {
  let html = '';
  if (p.estado === 'nuevo') {
    html += `<button class="btn-primary" onclick="cambiarEstado(${p.id},'preparando')">🍳 Preparar</button>`;
  }
  if (p.estado === 'preparando') {
    html += `<button class="btn-primary" onclick="cambiarEstado(${p.id},'listo')">✅ Listo</button>`;
  }
  if (p.estado === 'listo') {
    const label = p.tipo === 'retiro' ? '📦 Entregar' : '🛵 Despachar';
    html += `<button class="btn-primary" onclick="cambiarEstado(${p.id},'despachado')">${label}</button>`;
  }
  html += `<button onclick="printComandaById(${p.id})">🖨 Comanda</button>`;
  if (p.tipo === 'delivery' && p.direccion) {
    html += `<button onclick="verRuta(${p.id})">🗺 Ruta</button>`;
  }
  if (!['despachado','cancelado'].includes(p.estado)) {
    html += `<button class="btn-danger" onclick="cancelarPedido(${p.id})">❌</button>`;
  }
  return html;
}

async function cambiarEstado(id, estado) {
  await apiFetch(`/api/pedidos/${id}/estado`, { method: 'PUT', body: { estado } });
  if (estado === 'listo') {
    const p = allPedidos.find(x => x.id === id);
    if (p) printTicket(p);
  }
  await cargarCola();
}

async function cancelarPedido(id) {
  if (!confirm('¿Cancelar este pedido?')) return;
  await apiFetch(`/api/pedidos/${id}`, { method: 'DELETE' });
  await cargarCola();
}

// ─── QR Ruta ─────────────────────────────────────────────
async function verRuta(id) {
  const data = await apiFetch(`/api/pedidos/${id}/qr-ruta`);
  if (!data) { alert('Sin dirección registrada'); return; }
  const modal = document.getElementById('modalQR');
  document.getElementById('qrDirText').textContent = data.direccion || '';
  document.getElementById('qrMapsLink').href = data.maps_url || '#';
  if (data.qr_base64) {
    document.getElementById('qrImg').src = `data:image/png;base64,${data.qr_base64}`;
    document.getElementById('qrImg').style.display = '';
  } else {
    document.getElementById('qrImg').style.display = 'none';
  }
  modal.classList.add('active');
}

function cerrarQR() {
  document.getElementById('modalQR').classList.remove('active');
}

// ─── Print ───────────────────────────────────────────────
function buildComandaHTML(p) {
  const hora = new Date(p.creado_en || Date.now()).toLocaleTimeString('es-CL',{hour:'2-digit',minute:'2-digit'});
  const tipoLabel = p.tipo === 'delivery' ? 'DELIVERY' : p.tipo === 'retiro' ? 'RETIRO' : 'LOCAL';
  const emoji = TIPO_EMOJI[p.tipo] || '';
  let html = `
    <div class="print-center print-big">🍳 COCINA — ${tipoLabel} #${String(p.numero).padStart(3,'0')}</div>
    <div class="print-center print-line">${hora}</div>
    <div class="print-sep"></div>`;
  (p.items || []).forEach(i => {
    html += `<div class="print-line print-bold">${i.cantidad}× ${i.nombre}</div>`;
    if (i.notas) html += `<div class="print-line print-nota">&nbsp;&nbsp;⚠️ ${i.notas}</div>`;
  });
  html += `<div class="print-sep"></div>`;
  if (p.tipo !== 'local') {
    html += `<div class="print-line print-bold">${tipoLabel} → ${p.cliente_nombre}</div>`;
    if (p.cliente_tel) html += `<div class="print-line">📱 ${p.cliente_tel}</div>`;
    if (p.direccion) {
      html += `<div class="print-line">📍 ${p.direccion}</div>`;
      if (p.depto)     html += `<div class="print-line">&nbsp;&nbsp;${p.depto}</div>`;
      if (p.referencia) html += `<div class="print-line">Ref: ${p.referencia}</div>`;
    }
  }
  if (p.notas) html += `<div class="print-line print-nota">📝 ${p.notas}</div>`;
  html += `<div class="print-sep"></div>`;
  return html;
}

function printComanda(p) {
  document.getElementById('printZone').innerHTML = buildComandaHTML(p);
  window.print();
}

async function printComandaById(id) {
  const p = allPedidos.find(x => x.id === id);
  if (p) printComanda(p);
}

function printTicket(p) {
  const hora = new Date(p.creado_en || Date.now()).toLocaleTimeString('es-CL',{hour:'2-digit',minute:'2-digit'});
  const tipoLabel = p.tipo === 'delivery' ? '🛵 DELIVERY' : p.tipo === 'retiro' ? '🏠 RETIRO' : '🪑 LOCAL';
  let html = `
    <div class="print-center print-big">Pedido #${String(p.numero).padStart(3,'0')}</div>
    <div class="print-center print-line">${tipoLabel} — ${hora}</div>
    <div class="print-sep"></div>`;
  (p.items || []).forEach(i => {
    html += `<div class="print-line">${i.cantidad}× ${i.nombre} — ${fmt(i.subtotal)}</div>`;
    if (i.notas) html += `<div class="print-line print-nota">&nbsp;&nbsp;⚠️ ${i.notas}</div>`;
  });
  html += `<div class="print-sep"></div>
    <div class="print-line print-bold">TOTAL: ${fmt(p.total)}</div>
    <div class="print-line">Pago: ${p.metodo_pago}</div>`;
  if (p.tipo !== 'local' && p.cliente_nombre) {
    html += `<div class="print-sep"></div>
      <div class="print-line print-bold">${p.cliente_nombre}</div>`;
    if (p.cliente_tel) html += `<div class="print-line">📱 ${p.cliente_tel}</div>`;
    if (p.tipo === 'delivery' && p.direccion) {
      html += `<div class="print-line">📍 ${p.direccion}</div>`;
      if (p.depto) html += `<div class="print-line">&nbsp;&nbsp;${p.depto}</div>`;
      if (p.referencia) html += `<div class="print-line">Ref: ${p.referencia}</div>`;
    }
  }
  if (p.notas) html += `<div class="print-sep"></div><div class="print-line print-nota">📝 ${p.notas}</div>`;
  html += `<div class="print-sep"></div>
    <div class="print-center print-line" style="font-size:11px">ZERO POS — Sin internet. Sin comisiones.</div>`;
  document.getElementById('printZone').innerHTML = html;
  window.print();
}

// ─── Mobile tabs ─────────────────────────────────────────
function showTab(tab) {
  const form = document.getElementById('panelForm');
  const cola = document.getElementById('panelCola');
  const tabs = document.querySelectorAll('#tabs button');
  if (tab === 'form') {
    form.classList.remove('tab-hidden');
    cola.classList.add('tab-hidden');
    tabs[0].classList.add('active');
    tabs[1].classList.remove('active');
  } else {
    form.classList.add('tab-hidden');
    cola.classList.remove('tab-hidden');
    tabs[0].classList.remove('active');
    tabs[1].classList.add('active');
  }
}

// ─── Keyboard ────────────────────────────────────────────
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.getElementById('prodResultados').style.display = 'none';
    cerrarVariantes();
    cerrarQR();
  }
});

document.addEventListener('click', e => {
  if (!e.target.closest('#prodSearch')) {
    document.getElementById('prodResultados').style.display = 'none';
  }
});

['fNombre','fDir'].forEach(id => {
  document.getElementById(id).addEventListener('input', validarForm);
});

document.getElementById('fDir').addEventListener('blur', async () => {
  setTimeout(() => {
    document.getElementById('dirAutocomplete').style.display = 'none';
  }, 200);
  const calle = document.getElementById('fDir').value.trim();
  const comuna = document.getElementById('fComuna').value.trim() || cfgComuna;
  if (!calle || calle.length < 4) return;
  const res = await apiFetch('/api/direcciones/validar', {
    method: 'POST', body: {calle, comuna}
  });
  if (!res) return;
  const alertaEl = document.getElementById('alertaDireccion');
  if (res.valida) {
    alertaEl.style.display = 'none';
    document.getElementById('fDir').style.borderColor = 'var(--green)';
    if (res.nombre_oficial && res.nombre_oficial !== calle) {
      document.getElementById('fDir').value = res.nombre_oficial;
    }
    if (res.alerta) {
      alertaEl.innerHTML = `ℹ️ ${res.alerta}`;
      alertaEl.style.background = 'rgba(99,102,241,.1)';
      alertaEl.style.borderColor = 'rgba(99,102,241,.3)';
      alertaEl.style.color = 'var(--accent2)';
      alertaEl.style.display = '';
    }
  } else {
    document.getElementById('fDir').style.borderColor = 'var(--red)';
    if (res.sugerencias?.length) {
      const btns = res.sugerencias.map(s => {
        const esc = s.replace(/'/g, "\\'");
        return `<button onclick="usarSugerenciaDir('${esc}')"
                  style="margin:2px 4px 2px 0;background:rgba(239,68,68,.15);
                         border:1px solid rgba(239,68,68,.4);border-radius:5px;
                         padding:2px 8px;font-size:11px;cursor:pointer;
                         color:var(--red);font-family:inherit;">${s}</button>`;
      }).join('');
      alertaEl.innerHTML = `⚠️ ${res.alerta}<br>${btns}`;
    } else {
      alertaEl.innerHTML = `⚠️ ${res.alerta || ''}`;
    }
    alertaEl.style.background = 'rgba(239,68,68,.1)';
    alertaEl.style.borderColor = 'rgba(239,68,68,.4)';
    alertaEl.style.color = 'var(--red)';
    if (res.alerta) alertaEl.style.display = '';
  }
});

document.addEventListener('click', e => {
  if (!e.target.closest('#fDir') && !e.target.closest('#dirAutocomplete')) {
    document.getElementById('dirAutocomplete').style.display = 'none';
  }
});

// ─── Start ───────────────────────────────────────────────
init();


if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', {scope: '/'})
      .catch(err => console.log('SW error:', err));
  });
}
