/* ═══════════════════════════════════════════════════════════════
   ZERO POS — inventario.js
   Lógica de la pantalla de inventario (inventario.html)
   Depende de: zero-utils.js, zero-temas.js
   Nota: fmt() viene de zero-utils.js (window.fmt)
═══════════════════════════════════════════════════════════════ */

/* ── Variables y funciones principales ──────────────────────── */
let categorias = [];
let soloStockBajo = false;
let catFiltroId = null;
let _cachedProds = [];
let _deptoAbiertos = new Set(['Alimentación']);

async function init() {
  const me = await fetch('/api/auth/me',{credentials:'include'}).then(r=>r.json()).catch(()=>null);
  if (!me||me.error) { location.href='login.html'; return; }
  categorias = await fetch('/api/productos/categorias',{credentials:'include'}).then(r=>r.json()).catch(()=>[]);
  filtrarCategoriasPorDepto();
  cargarCatFiltros();
  renderCatTab();
  // Auto-filtrar por categoría si viene ?filtrar_cat= desde admin
  const paramCat = new URLSearchParams(window.location.search).get('filtrar_cat');
  if (paramCat) {
    const cat = categorias.find(c => c.nombre === paramCat);
    if (cat) { catFiltroId = cat.id; }
  }
  cargarProductos();
}

function renderCatTab() {
  const div = document.getElementById('tablaCats');
  if (!div) return;
  const DEPTOS = ['Alimentación','Bebidas con Alcohol','Belleza y Cuidado Personal','Limpieza del Hogar','Mundo Bebé','Mascotas','Manualidades y Hogar','Juguetes y Entretencion','Ferretería Básica','Tabaco','Otros'];
  const grupos = {};
  DEPTOS.forEach(d => grupos[d] = []);
  categorias.forEach(c => {
    const d = c.departamento || 'Alimentación';
    (grupos[d] = grupos[d] || []).push(c);
  });
  div.innerHTML = DEPTOS.filter(d => grupos[d]?.length).map(d => `
    <div style="margin-bottom:20px">
      <h3 style="font-size:12px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px;font-weight:600">${d}</h3>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        ${grupos[d].map(c => `<span style="background:var(--surface2);border:1px solid var(--border);border-radius:20px;padding:6px 14px;font-size:13px">${c.icono||'📦'} ${escH(c.nombre)}</span>`).join('')}
      </div>
    </div>`).join('');
}

async function crearCategoria() {
  const nombre = document.getElementById('catNombreInput')?.value.trim();
  if (!nombre) { showToast('El nombre es requerido', 'error'); return; }
  const depto = document.getElementById('catDeptoInput')?.value || 'Alimentación';
  const icono = document.getElementById('catIconoInput')?.value.trim() || '📦';
  try {
    const r = await fetch('/api/productos/categorias', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ nombre, departamento: depto, icono }),
    });
    const d = await r.json();
    if (r.ok) {
      categorias = await fetch('/api/productos/categorias',{credentials:'include'}).then(r=>r.json()).catch(()=>[]);
      filtrarCategoriasPorDepto();
      document.getElementById('catFiltros').innerHTML = '<button class="cat-filtro-btn active" onclick="filtrarPorCat(null,this)">Todos</button>';
      cargarCatFiltros();
      renderCatTab();
      if (document.getElementById('catNombreInput')) document.getElementById('catNombreInput').value = '';
      showToast('✅ Categoría creada: ' + nombre, 'ok');
      document.getElementById('formNuevaCat').style.display = 'none';
    } else { showToast('Error: ' + (d.error || 'No se pudo crear'), 'error'); }
  } catch(e) { showToast('Error al crear categoría', 'error'); }
}

function showTab(name, btn) {
  document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  btn.classList.add('active');
  if (name==='proveedores') cargarProveedores();
  if (name==='alertas') cargarAlertas();
  if (name==='productos') cargarProductos();
  if (name==='categorias') renderCatTab();
}

// ── Filtro por categoría ───────────────────────────────────────────────
function cargarCatFiltros() {
  // La sidebar de categorías se puebla en _poblarSidebarCats() (llamado desde cargarProductos)
  // Esta función se mantiene como stub para compatibilidad con código legacy
  const filtros = document.getElementById('catFiltros');
  if (!filtros) return;
  // fallback: populate if the old element still exists
  categorias.forEach(c => {
    const btn = document.createElement('button');
    btn.className = 'cat-filtro-btn';
    btn.dataset.catId = c.id;
    btn.textContent = (c.icono ? c.icono + ' ' : '') + c.nombre;
    btn.onclick = () => filtrarPorCat(c.id, btn);
    filtros.appendChild(btn);
  });
}

// ── Sidebar de categorías ─────────────────────────────────────────────
function abrirSidebarCat() {
  document.getElementById('sidebarCat').classList.add('open');
  document.getElementById('sidebarOverlay').classList.add('active');
}
function cerrarSidebarCat() {
  document.getElementById('sidebarCat').classList.remove('open');
  document.getElementById('sidebarOverlay').classList.remove('active');
  if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
  document.body.focus();
}
function seleccionarCategoriaSidebar(id, btn) {
  catFiltroId = id;
  document.querySelectorAll('#sidebarCatBody .inv-cat-item').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  else {
    const primer = document.querySelector('#sidebarCatBody .inv-cat-item[data-cat-id=""]');
    if (primer) primer.classList.add('active');
  }
  // Chip de filtro activo
  const chipDiv = document.getElementById('chipFiltroActivo');
  const chipLabel = document.getElementById('chipFiltroLabel');
  if (id) {
    const cat = categorias.find(c=>c.id==id);
    chipLabel.textContent = (cat?.icono||'') + ' ' + (cat?.nombre||'');
    chipDiv.style.display = '';
  } else {
    chipDiv.style.display = 'none';
  }
  cerrarSidebarCat();
  cargarProductos();
}
function filtrarPorCat(id, btn) {
  seleccionarCategoriaSidebar(id, null);
}
function _toggleDeptoSidebar(depto) {
  if (_deptoAbiertos.has(depto)) _deptoAbiertos.delete(depto);
  else _deptoAbiertos.add(depto);
  _poblarSidebarCats();
}

function _poblarSidebarCats() {
  const body = document.getElementById('sidebarCatBody');
  const contadores = {};
  (_cachedProds||[]).forEach(p => { if (p.categoria_id) contadores[p.categoria_id] = (contadores[p.categoria_id]||0)+1; });
  const total = (_cachedProds||[]).length;

  const deptos = {};
  categorias.forEach(c => {
    const d = c.departamento || 'Otros';
    if (!deptos[d]) deptos[d] = [];
    deptos[d].push(c);
  });

  let html = `<div class="inv-cat-item ${!catFiltroId?'active':''}" data-cat-id="" onclick="seleccionarCategoriaSidebar(null,this)">
    <span>Todos</span><span class="inv-cat-count">${total}</span></div>`;

  Object.entries(deptos).forEach(([depto, cats]) => {
    const abierto = _deptoAbiertos.has(depto);
    const chevron = abierto ? 'ti-chevron-down' : 'ti-chevron-right';
    const deptoEsc = depto.replace(/'/g, "\\'");
    html += `<div class="sidebar-depto-btn" onclick="_toggleDeptoSidebar('${deptoEsc}')">
      <i class="ti ${chevron}"></i>${depto}</div>`;
    if (abierto) {
      cats.forEach(c => {
        const cnt = contadores[c.id]||0;
        const activo = catFiltroId == c.id ? 'active' : '';
        html += `<div class="inv-cat-item ${activo}" data-cat-id="${c.id}" onclick="seleccionarCategoriaSidebar(${c.id},this)">
          <span>${c.nombre}</span><span class="inv-cat-count">${cnt}</span></div>`;
      });
    }
  });
  body.innerHTML = html;
}

// ── Lista mobile-first de productos ───────────────────────────────────
const _COLORES_PROD = ['#6366f1','#8b5cf6','#06b6d4','#10b981','#f59e0b','#ef4444','#ec4899'];

async function cargarProductos() {
  const q = document.getElementById('searchProd').value.trim();
  let url = `/api/productos?activos=1`;
  if (q) url += '&q=' + encodeURIComponent(q);
  if (soloStockBajo) url += '&alerta_stock=1';
  if (catFiltroId) url += '&categoria_id=' + catFiltroId;
  const prods = await fetch(url,{credentials:'include'}).then(r=>r.json()).catch(()=>[]);
  _cachedProds = prods;
  _poblarSidebarCats();
  const cont = document.getElementById('tablaProds');
  if (!prods.length) {
    cont.innerHTML='<div style="text-align:center;color:var(--text-dim);padding:32px 16px;font-size:14px">Sin productos</div>';
    return;
  }
  cont.innerHTML = prods.map((p, idx) => {
    const bajoCls = p.stock <= p.stock_minimo ? 'prod-row-stock-bajo' : '';
    const color = _COLORES_PROD[idx % _COLORES_PROD.length];
    const imgHtml = p.imagen_url
      ? `<img src="${p.imagen_url}" alt="" onerror="this.parentElement.textContent='${(p.nombre||'')[0]?.toUpperCase()||'?'}';">`
      : (p.nombre||'?')[0].toUpperCase();
    const stockText = p.modo_stock === 'sin_stock' ? '∞' : p.stock;
    const stockInfo = `${p.categoria_nombre||'—'} · Stock: ${stockText}${p.stock <= p.stock_minimo && p.modo_stock !== 'sin_stock' ? ' ⚠️' : ''}`;
    const nombreSafe = (p.nombre||'').replace(/'/g,"\\'").replace(/"/g,'&quot;');
    return `<div class="prod-row ${bajoCls}" onclick="abrirDetalleProd(${p.id})">
      <div class="prod-row-img" style="background:${color}20;color:${color}">${imgHtml}</div>
      <div class="prod-row-info">
        <div class="prod-row-nombre">${p.nombre}${p.marca_nombre?` <span style="font-size:11px;color:#818cf8">${p.marca_nombre}</span>`:''}</div>
        <div class="prod-row-meta">${stockInfo}</div>
      </div>
      <div class="prod-row-precio">${fmt(p.precio)}</div>
      <div class="prod-row-chevron">›</div>
    </div>`;
  }).join('');
}

// ── Modal detalle rápido de producto ──────────────────────────────────
function _cerrarDetalle() {
  const m = document.getElementById('_modalDetalleProd');
  if (m) m.style.display = 'none';
  document.getElementById('fabComandoStock')?.style.setProperty('display','flex');
}

function abrirDetalleProd(id) {
  const p = (_cachedProds||[]).find(x=>x.id===id);
  if (!p) { editarProd(id); return; }
  const costo = p.precio_costo || 0;
  const margen = p.precio > 0 ? Math.round((p.precio - costo) / p.precio * 100) : 0;
  const mColor = margen >= 30 ? 'var(--success)' : margen >= 15 ? 'var(--warning)' : 'var(--danger)';
  const stockLabel = p.modo_stock === 'sin_stock' ? '∞' : p.stock;
  const stockColor = p.stock <= p.stock_minimo && p.modo_stock !== 'sin_stock' ? 'var(--warning)' : 'var(--success)';

  let modal = document.getElementById('_modalDetalleProd');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = '_modalDetalleProd';
    modal.className = 'modal-overlay';
    modal.style.cssText = 'display:none;align-items:flex-end;padding:0';
    document.body.appendChild(modal);
  }
  modal.innerHTML = `
    <div style="background:#13131a;border:1px solid var(--border);border-radius:20px 20px 0 0;width:100%;max-width:520px;padding:24px 22px 32px;max-height:80vh;overflow-y:auto;animation:slideUp .2s ease">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
        <div style="font-size:17px;font-weight:700;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${p.nombre}</div>
        <button onclick="_cerrarDetalle()" style="background:none;border:none;color:var(--text-dim);font-size:22px;cursor:pointer;margin-left:12px;flex-shrink:0">✕</button>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px">
        <div style="background:var(--surface2);border-radius:12px;padding:14px">
          <div style="font-size:11px;color:var(--text-dim);margin-bottom:4px">PRECIO VENTA</div>
          <div style="font-size:22px;font-weight:800;color:var(--success)">${fmt(p.precio)}</div>
        </div>
        <div style="background:var(--surface2);border-radius:12px;padding:14px">
          <div style="font-size:11px;color:var(--text-dim);margin-bottom:4px">STOCK</div>
          <div style="font-size:22px;font-weight:800;color:${stockColor}">${stockLabel}</div>
        </div>
        <div style="background:var(--surface2);border-radius:12px;padding:14px">
          <div style="font-size:11px;color:var(--text-dim);margin-bottom:4px">COSTO</div>
          <div style="font-size:16px;font-weight:700">${fmt(costo)}</div>
        </div>
        <div style="background:var(--surface2);border-radius:12px;padding:14px">
          <div style="font-size:11px;color:var(--text-dim);margin-bottom:4px">MARGEN</div>
          <div style="font-size:16px;font-weight:700;color:${mColor}">${margen}%</div>
        </div>
      </div>
      ${p.sku?`<div style="font-size:12px;color:var(--text-dim);margin-bottom:6px">SKU: <span style="font-family:monospace;color:var(--text)">${p.sku}</span></div>`:''}
      ${p.categoria_nombre?`<div style="font-size:12px;color:var(--text-dim);margin-bottom:6px">Categoría: <span style="color:var(--text)">${p.categoria_nombre}</span></div>`:''}
      ${p.marca_nombre?`<div style="font-size:12px;color:var(--text-dim);margin-bottom:16px">Marca: <span style="color:#818cf8;font-weight:600">${p.marca_nombre}</span></div>`:''}
      <div style="margin-top:20px">
        <div style="display:flex;gap:10px;margin-bottom:8px">
          <button class="btn" style="flex:1;min-height:44px;font-size:13px" onclick="_cerrarDetalle();ajustarStock(${p.id},'${(p.nombre||'').replace(/'/g,"\\'")}',${p.stock})">📊 Stock</button>
          <button class="btn primary" style="flex:1;min-height:44px;font-size:13px" onclick="_cerrarDetalle();editarProd(${p.id})">✏️ Editar</button>
        </div>
        <button class="btn" style="width:100%;min-height:44px;font-size:13px;font-weight:700;background:#16a34a;border-color:#16a34a;color:#fff" onclick="_cerrarDetalle();abrirComandoStock()">🎤 Agregar stock</button>
      </div>
    </div>`;
  modal.style.display = 'flex';
  document.getElementById('fabComandoStock')?.style.setProperty('display','none');
  modal.onclick = e => { if (e.target === modal) _cerrarDetalle(); };
}

function filtrarProds(toggleBajo) {
  if (toggleBajo) soloStockBajo = !soloStockBajo;
  clearTimeout(filtrarProds._t);
  filtrarProds._t = setTimeout(cargarProductos, 250);
}

// ── Buscador con Enter → escaneo de código ────────────────────────────
function esCodigoBarras(val) {
  return /^\d{8,14}$/.test(val);
}

function manejarEnterBusqueda(e) {
  if (e.key !== 'Enter') return;
  const val = document.getElementById('searchProd').value.trim();
  if (!val) return;
  if (esCodigoBarras(val)) {
    e.preventDefault();
    document.getElementById('searchProd').value = '';
    buscarPorCodigoBarras(val);
  }
}

async function buscarPorCodigoBarras(codigo) {
  let prod = _cachedProds.find(p => p.codigo_barras === codigo);
  if (!prod) {
    const res = await fetch(`/api/productos?activos=1&q=${encodeURIComponent(codigo)}`,{credentials:'include'}).then(r=>r.json()).catch(()=>[]);
    prod = res.find(p => p.codigo_barras === codigo);
  }
  if (prod) {
    editarProd(prod.id);
  } else {
    alert(`Código ${codigo} no encontrado en inventario`);
  }
}

// ── Escáner de cámara ─────────────────────────────────────────────────
function abrirEscanerVideo(onCodigo) {
  const modal = document.createElement('div');
  modal.id = 'modalEscanerVideo';
  modal.style.cssText = 'position:fixed;inset:0;background:#000;display:flex;flex-direction:column;align-items:center;justify-content:center;z-index:9999;';
  modal.innerHTML = `
    <div style="position:relative;width:100%;max-width:400px;padding:0 16px">
      <video id="videoScan" autoplay playsinline muted style="width:100%;border-radius:12px;display:block"></video>
      <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:70%;aspect-ratio:2/1;border:3px solid #6366f1;border-radius:8px;box-shadow:0 0 0 9999px rgba(0,0,0,0.5);pointer-events:none">
        <div style="position:absolute;left:0;right:0;height:2px;background:#6366f1;animation:scanLine 1.5s ease-in-out infinite"></div>
      </div>
      <p style="color:white;text-align:center;margin-top:16px;font-size:15px;opacity:.8">Apunta al código de barras</p>
      <button onclick="cerrarEscanerVideo()" style="position:absolute;top:4px;right:20px;background:rgba(0,0,0,0.6);color:white;border:none;border-radius:50%;width:36px;height:36px;font-size:18px;cursor:pointer;line-height:36px;text-align:center">✕</button>
    </div>
    <style>@keyframes scanLine{0%,100%{top:0}50%{top:calc(100% - 2px)}}</style>
  `;
  document.body.appendChild(modal);

  let stream = null, intervalId = null, detectando = false;

  window.cerrarEscanerVideo = () => {
    if (intervalId) clearInterval(intervalId);
    if (stream) stream.getTracks().forEach(t => t.stop());
    modal.remove();
    delete window.cerrarEscanerVideo;
  };

  navigator.mediaDevices.getUserMedia({
    video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } }
  }).then(async s => {
    stream = s;
    const video = document.getElementById('videoScan');
    video.srcObject = s;
    try { await video.play(); } catch(e) {}
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d', { willReadFrequently: true });

    intervalId = setInterval(async () => {
      if (detectando || video.readyState < 2) return;
      detectando = true;
      const vw = video.videoWidth, vh = video.videoHeight;
      const x = vw * 0.2, y = vh * 0.3, w = vw * 0.6, h = vh * 0.4;
      canvas.width = w; canvas.height = h;
      ctx.drawImage(video, x, y, w, h, 0, 0, w, h);
      canvas.toBlob(async blob => {
        if (!blob) { detectando = false; return; }
        try {
          const fd = new FormData();
          fd.append('imagen', blob, 'frame.jpg');
          const resp = await fetch('/api/productos/detectar-codigo', { method: 'POST', credentials: 'include', body: fd });
          const data = await resp.json();
          if (data.ok && data.codigo) {
            if (navigator.vibrate) navigator.vibrate(100);
            cerrarEscanerVideo();
            onCodigo(data.codigo);
            return;
          }
        } catch(e) { console.error('[ZERO] Error frame:', e); }
        detectando = false;
      }, 'image/jpeg', 0.8);
    }, 800);

  }).catch(err => {
    console.error('[ZERO] Sin cámara:', err);
    modal.remove();
    delete window.cerrarEscanerVideo;
    abrirEscanerArchivo(onCodigo);
  });
}

function abrirEscanerArchivo(onCodigo) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  if (/iPhone|iPad|Android/i.test(navigator.userAgent)) input.capture = 'environment';
  input.style.display = 'none';
  document.body.appendChild(input);
  input.addEventListener('change', async e => {
    const file = e.target.files?.[0];
    document.body.removeChild(input);
    if (!file) return;
    showToast('🔍 Analizando...', 'ok');
    try {
      const fd = new FormData();
      fd.append('imagen', file);
      const resp = await fetch('/api/productos/detectar-codigo', { method: 'POST', credentials: 'include', body: fd });
      const data = await resp.json();
      if (data.ok && data.codigo) {
        onCodigo(data.codigo);
      } else {
        showToast('No detectado — ingresa el código', 'error');
        document.getElementById('searchProd')?.focus();
      }
    } catch(e) {
      showToast('Error al procesar imagen', 'error');
    }
  });
  input.click();
}

function abrirEscanerInv() {
  const esMobil = /iPhone|iPad|Android/i.test(navigator.userAgent);
  if (esMobil) {
    abrirEscanerVideo(codigo => buscarPorCodigoBarras(codigo));
  } else {
    abrirEscanerArchivo(codigo => buscarPorCodigoBarras(codigo));
  }
}

// ── Cálculos financieros ──────────────────────────────────────────────
function calcularFinanciero() {
  const precio = parseInt(document.getElementById('prodPrecio').value) || 0;
  const costo  = parseInt(document.getElementById('prodCosto').value)  || 0;
  const valorNeto = Math.round(precio / 1.19);
  const iva       = precio - valorNeto;
  const margen    = precio > 0 ? ((precio - costo) / precio * 100).toFixed(1) : 0;

  document.getElementById('valorNeto').textContent = '$' + valorNeto.toLocaleString('es-CL');
  document.getElementById('montoIva').textContent  = '$' + iva.toLocaleString('es-CL');
  document.getElementById('margenPct').textContent = margen + '%';

  const el = document.getElementById('margenPct');
  el.style.color = margen >= 30 ? '#22c55e' : margen >= 15 ? '#eab308' : '#ef4444';

  const tasa = parseFloat(document.getElementById('prodTasaImp').value) || 0;
  const montoImpAdic = Math.round(valorNeto * tasa / 100);
  document.getElementById('montoImpAdic').textContent = '$' + montoImpAdic.toLocaleString('es-CL');
}

function toggleImpAdic() {
  const activo = document.getElementById('prodImpAdic').checked;
  document.getElementById('impAdicOpts').style.display = activo ? '' : 'none';
  calcularFinanciero();
}

// ── Marcas autocomplete ───────────────────────────────────────────────
let _marcaTimer = null;
async function buscarMarcas(inputId, hiddenId, dropId) {
  const input = document.getElementById(inputId);
  const drop  = document.getElementById(dropId);
  if (!input || !drop) return;
  const q = input.value.trim();
  document.getElementById(hiddenId).value = '';
  clearTimeout(_marcaTimer);
  _marcaTimer = setTimeout(async () => {
    const rows = await fetch(`/api/productos/marcas?q=${encodeURIComponent(q)}`, {credentials:'include'})
      .then(r => r.json()).catch(() => []);
    const exact = rows.find(m => m.nombre.toLowerCase() === q.toLowerCase());
    let html = rows.map(m =>
      `<div class="marca-opt" onclick="seleccionarMarca('${escH(m.nombre)}',${m.id},'${inputId}','${hiddenId}','${dropId}')">${escH(m.nombre)}</div>`
    ).join('');
    if (q && !exact) {
      html += `<div class="marca-opt create" onclick="crearYSeleccionarMarca('${escH(q)}','${inputId}','${hiddenId}','${dropId}')">+ Crear "${escH(q)}"</div>`;
    }
    drop.innerHTML = html || (q ? `<div class="marca-opt" style="color:var(--text-dim)">Sin resultados</div>` : '');
    drop.style.display = html ? '' : 'none';
  }, 200);
}

function seleccionarMarca(nombre, id, inputId, hiddenId, dropId) {
  document.getElementById(inputId).value  = nombre;
  document.getElementById(hiddenId).value = id;
  document.getElementById(dropId).style.display = 'none';
}

async function crearYSeleccionarMarca(nombre, inputId, hiddenId, dropId) {
  const r = await fetch('/api/productos/marcas', {
    method:'POST', credentials:'include',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({nombre}),
  });
  const d = await r.json();
  if (d.ok) {
    seleccionarMarca(nombre, d.id, inputId, hiddenId, dropId);
    showToast(`Marca "${nombre}" guardada`, 'ok');
  } else {
    showToast('Error al crear marca', 'error');
  }
}

document.addEventListener('click', e => {
  if (!e.target.closest('.marca-dropdown') && !e.target.matches('[id^="prodMarcaInput"],[id^="iaMarcaInput"]')) {
    document.querySelectorAll('.marca-dropdown').forEach(d => d.style.display = 'none');
  }
});

// ── Departamento / categoría ──────────────────────────────────────────
function filtrarCategoriasPorDepto() {
  const depto = document.getElementById('prodDepartamento').value;
  const sel = document.getElementById('prodCategoria');
  const prev = sel.value;
  sel.innerHTML = '<option value="">Sin categoría</option>';
  categorias
    .filter(c => !depto || (c.departamento || 'Alimentación') === depto)
    .forEach(c => sel.insertAdjacentHTML('beforeend', `<option value="${c.id}">${c.nombre}</option>`));
  if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
}

// ── Modal producto ────────────────────────────────────────────────────
function abrirModalProd() {
  document.getElementById('prodId').value = '';
  document.getElementById('modalProdTitle').textContent = 'Nuevo producto';
  ['prodNombre','prodBarras','prodSKU','prodMarcaInput'].forEach(id => document.getElementById(id).value = '');
  ['prodPrecio','prodCosto'].forEach(id => document.getElementById(id).value = '0');
  document.getElementById('prodMarcaId').value = '';
  document.getElementById('prodStock').value = '0';
  document.getElementById('prodStockMin').value = '5';
  document.getElementById('prodDepartamento').value = '';
  filtrarCategoriasPorDepto();
  document.getElementById('prodCategoria').value = '';
  document.getElementById('prodGranel').checked = false;
  document.getElementById('granelOpts').style.display = 'none';
  document.getElementById('prodPrecioPor').value = 'unidad';
  document.getElementById('prodUnidadMedida').value = 'unidad';
  document.getElementById('prodHoraReset').value = '06:00';
  document.getElementById('prodImpAdic').checked = false;
  document.getElementById('impAdicOpts').style.display = 'none';
  document.getElementById('prodTasaImp').value = '20.5';
  selModoStock('normal');
  _bindNormBlur('prodNombre');
  calcularFinanciero();
  document.getElementById('seccionLotes').style.display = 'none';
  document.getElementById('panelLotes').style.display = 'none';
  document.getElementById('chkTieneLotes').checked = false;
  document.getElementById('seccionModificadores').style.display = 'none';
  document.getElementById('modalProd').classList.add('active');
}

async function editarProd(id) {
  const p = await fetch(`/api/productos/${id}`,{credentials:'include'}).then(r=>r.json());
  if (p.error) { alert('Producto no encontrado'); return; }
  document.getElementById('prodId').value = p.id;
  document.getElementById('modalProdTitle').textContent = 'Editar producto';
  document.getElementById('prodNombre').value = p.nombre;
  document.getElementById('prodSKU').value = p.sku || '';
  document.getElementById('prodPrecio').value = p.precio;
  document.getElementById('prodCosto').value = p.precio_costo || 0;
  document.getElementById('prodStockMin').value = p.stock_minimo;
  document.getElementById('prodBarras').value = p.codigo_barras || '';
  const catDeProd = categorias.find(c => c.id == p.categoria_id);
  document.getElementById('prodDepartamento').value = catDeProd?.departamento || '';
  filtrarCategoriasPorDepto();
  document.getElementById('prodCategoria').value = p.categoria_id || '';
  document.getElementById('prodStock').value = p.stock;
  const granel = p.es_granel === 1 || p.es_granel === true;
  document.getElementById('prodGranel').checked = granel;
  document.getElementById('granelOpts').style.display = granel ? '' : 'none';
  document.getElementById('prodPrecioPor').value = p.precio_por || 'unidad';
  document.getElementById('prodUnidadMedida').value = p.unidad_medida || 'unidad';
  document.getElementById('prodHoraReset').value = p.hora_reset_stock || '06:00';
  const impAdic = p.tiene_impuesto_adicional === 1 || p.tiene_impuesto_adicional === true;
  document.getElementById('prodImpAdic').checked = impAdic;
  document.getElementById('impAdicOpts').style.display = impAdic ? '' : 'none';
  document.getElementById('prodTasaImp').value = p.tasa_impuesto_adicional || 20.5;
  document.getElementById('prodMarcaInput').value = p.marca_nombre || '';
  document.getElementById('prodMarcaId').value    = p.marca_id    || '';
  _bindNormBlur('prodNombre');
  selModoStock(p.modo_stock || 'normal');
  calcularFinanciero();
  // Lotes
  const tieneLotes = p.tiene_lotes === 1 || p.tiene_lotes === true;
  document.getElementById('seccionLotes').style.display = '';
  document.getElementById('chkTieneLotes').checked = tieneLotes;
  _sincToggleLotes(tieneLotes);
  document.getElementById('panelLotes').style.display = tieneLotes ? '' : 'none';
  if (tieneLotes) cargarLotesProducto(p.id);
  // Modificadores
  document.getElementById('seccionModificadores').style.display = '';
  cargarModificadoresDeProducto(p.id);
  document.getElementById('modalProd').classList.add('active');
}

async function guardarProd() {
  const id = document.getElementById('prodId').value;
  const skuVal = document.getElementById('prodSKU').value.trim();
  const nombre = document.getElementById('prodNombre').value.trim();
  if (!nombre) { alert('El nombre es requerido'); return; }
  const data = {
    nombre,
    precio:       parseInt(document.getElementById('prodPrecio').value) || 0,
    precio_costo: parseInt(document.getElementById('prodCosto').value)  || 0,
    stock:        parseInt(document.getElementById('prodStock').value)  || 0,
    stock_minimo: parseInt(document.getElementById('prodStockMin').value) || 5,
    codigo_barras: document.getElementById('prodBarras').value.trim() || null,
    categoria_id:  document.getElementById('prodCategoria').value || null,
    es_granel:     document.getElementById('prodGranel').checked ? 1 : 0,
    precio_por:    document.getElementById('prodPrecioPor').value,
    unidad_medida: document.getElementById('prodUnidadMedida').value,
    modo_stock:    document.querySelector('.modo-stock-btn.active')?.dataset.modo || 'normal',
    hora_reset_stock: document.getElementById('prodHoraReset').value || '06:00',
    tiene_impuesto_adicional: document.getElementById('prodImpAdic').checked ? 1 : 0,
    tasa_impuesto_adicional:  parseFloat(document.getElementById('prodTasaImp').value) || 0,
    tiene_lotes: document.getElementById('chkTieneLotes').checked ? 1 : 0,
    ...(skuVal ? {sku: skuVal} : {}),
    ...(document.getElementById('prodMarcaId').value ? {marca_id: parseInt(document.getElementById('prodMarcaId').value)} : {}),
  };
  const url = id ? `/api/productos/${id}` : '/api/productos';
  const r = await fetch(url, {
    method: id ? 'PUT' : 'POST', credentials: 'include',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data),
  });
  if (r.ok) { cerrarModalProd(); cargarProductos(); }
  else { const e = await r.json(); alert(e.error || 'Error al guardar'); }
}

function toggleGranel() {
  document.getElementById('granelOpts').style.display = document.getElementById('prodGranel').checked ? '' : 'none';
}

function selModoStock(modo) {
  document.querySelectorAll('.modo-stock-btn').forEach(b => b.classList.toggle('active', b.dataset.modo === modo));
  document.getElementById('modoProduccionOpts').style.display = modo === 'produccion' ? '' : 'none';
  document.getElementById('modoSinStockMsg').style.display    = modo === 'sin_stock'  ? '' : 'none';
  const stockRow = document.getElementById('prodStock')?.closest('.form-group');
  const minRow   = document.getElementById('prodStockMin')?.closest('.form-group');
  if (stockRow) stockRow.style.display = modo === 'sin_stock' ? 'none' : '';
  if (minRow)   minRow.style.display   = modo === 'sin_stock' ? 'none' : '';
}

function abrirModalProduccion() {
  const id = document.getElementById('prodId').value;
  const nombre = document.getElementById('prodNombre').value;
  if (!id) { alert('Guarda el producto primero'); return; }
  document.getElementById('prodProduccionId').value = id;
  document.getElementById('prodProduccionNombre').textContent = nombre;
  document.getElementById('prodProduccionQty').value = '';
  document.getElementById('modalProduccion').classList.add('active');
}

async function guardarProduccion() {
  const id  = document.getElementById('prodProduccionId').value;
  const qty = parseInt(document.getElementById('prodProduccionQty').value) || 0;
  if (qty <= 0) { alert('Ingresa una cantidad mayor a 0'); return; }
  const r = await fetch(`/api/productos/${id}/stock`, {
    method: 'POST', credentials: 'include',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({tipo: 'ajuste', cantidad: qty, motivo: 'produccion_diaria'}),
  });
  if (r.ok) { cerrarModalProduccion(); cargarProductos(); }
  else { const e = await r.json(); alert(e.error || 'Error'); }
}

function _blurInv() { if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur(); document.body.focus(); }
function cerrarModalProduccion() { document.getElementById('modalProduccion').classList.remove('active'); _blurInv(); }
function cerrarModalProd() { document.getElementById('modalProd').classList.remove('active'); _blurInv(); }

// ── Lotes ────────────────────────────────────────────────────────
let _loteUltimoId = null;

async function cargarLotesProducto(productoId) {
  const r = await fetch(`/api/inventario/lotes?producto_id=${productoId}`, {credentials:'include'});
  if (!r.ok) return;
  const lotes = await r.json();
  const lista = document.getElementById('listaLotes');
  if (!lotes.length) { lista.innerHTML = '<div style="font-size:12px;color:var(--text-dim)">Sin lotes registrados</div>'; return; }
  const estadoEmoji = {activo:'🟢', agotado:'⚫', vencido:'🔴', retirado:'⚪'};
  lista.innerHTML = lotes.map(l => `
    <div style="display:flex;align-items:center;justify-content:space-between;background:var(--surface2);border-radius:8px;padding:10px 12px;font-size:13px">
      <div>
        <span style="font-weight:600">${l.numero_lote || `L-${l.id}`}</span>
        <span style="color:var(--text-dim);margin-left:8px">${l.cantidad_actual} uds</span>
        ${l.fecha_vencimiento ? `<span style="color:var(--text-dim);margin-left:8px">· vence ${l.fecha_vencimiento}</span>` : ''}
      </div>
      <span title="${l.estado}">${estadoEmoji[l.estado] || '●'}</span>
    </div>
  `).join('');
}

function toggleLotes(activo) {
  document.getElementById('panelLotes').style.display = activo ? '' : 'none';
  const prodId = document.getElementById('prodId').value;
  if (activo && prodId) cargarLotesProducto(parseInt(prodId));
}

function toggleLotesVencimientos() {
  const chk = document.getElementById('chkTieneLotes');
  chk.checked = !chk.checked;
  _sincToggleLotes(chk.checked);
  toggleLotes(chk.checked);
}

function _sincToggleLotes(activo) {
  const ind = document.getElementById('toggleLotesIndicador');
  const dot = document.getElementById('toggleLotesDot');
  if (ind) ind.style.background = activo ? '#22c55e' : 'var(--border)';
  if (dot) dot.style.left = activo ? '20px' : '2px';
}

// ── Modificadores ─────────────────────────────────────────────────────────────
let _modifAsignados = [];   // [{id, nombre, tipo, seleccion, opciones}]
let _todosModificadores = [];

async function _cargarTodosModificadores() {
  try {
    _todosModificadores = await fetch('/api/modificadores',{credentials:'include'}).then(r=>r.json());
  } catch(e) { _todosModificadores = []; }
}

async function cargarModificadoresDeProducto(prodId) {
  await _cargarTodosModificadores();
  try {
    _modifAsignados = await fetch(`/api/modificadores/por-producto/${prodId}`,{credentials:'include'}).then(r=>r.json());
  } catch(e) { _modifAsignados = []; }
  _renderModifAsignados();
  _poblarSelectModif();
}

function _renderModifAsignados() {
  const cont = document.getElementById('listaModificadoresAsignados');
  if (!_modifAsignados.length) {
    cont.innerHTML = '<div style="font-size:12px;color:var(--text-dim)">Sin modificadores asignados</div>';
    return;
  }
  cont.innerHTML = _modifAsignados.map(m => `
    <div style="display:flex;align-items:center;justify-content:space-between;background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:10px 12px">
      <div>
        <div style="font-size:13px;font-weight:600">${m.nombre} <span style="font-size:11px;color:var(--text-dim)">${m.tipo === 'obligatorio' ? '★ oblig.' : 'opcional'} · ${m.seleccion === 'unico' ? 'solo 1' : 'múltiple'}</span></div>
        <div style="font-size:11px;color:var(--text-dim);margin-top:3px">${(m.opciones||[]).map(o=>o.nombre+(o.precio_extra?` +$${o.precio_extra.toLocaleString('es-CL')}`:'`')).join(', ')}</div>
      </div>
      <button onclick="quitarModificador(${m.id})" style="background:none;border:none;color:#ef4444;font-size:18px;cursor:pointer;padding:4px">✕</button>
    </div>`).join('');
}

function _poblarSelectModif() {
  const sel = document.getElementById('selectModifDisponibles');
  const asignadosIds = new Set(_modifAsignados.map(m=>m.id));
  sel.innerHTML = '<option value="">— Seleccionar grupo —</option>';
  _todosModificadores.filter(m=>!asignadosIds.has(m.id)).forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = m.nombre + (m.tipo==='obligatorio' ? ' ★' : '');
    sel.appendChild(opt);
  });
}

async function asignarModificador() {
  const prodId = document.getElementById('prodId').value;
  if (!prodId) { alert('Guarda el producto primero'); return; }
  const mid = parseInt(document.getElementById('selectModifDisponibles').value);
  if (!mid) return;
  const ya = _modifAsignados.find(m=>m.id===mid);
  if (ya) return;
  const nuevo = _todosModificadores.find(m=>m.id===mid);
  if (!nuevo) return;
  _modifAsignados.push(nuevo);
  await _guardarModifAsignados(parseInt(prodId));
}

async function quitarModificador(mid) {
  const prodId = document.getElementById('prodId').value;
  if (!prodId) return;
  _modifAsignados = _modifAsignados.filter(m=>m.id!==mid);
  await _guardarModifAsignados(parseInt(prodId));
}

async function _guardarModifAsignados(prodId) {
  await fetch(`/api/modificadores/por-producto/${prodId}`, {
    method: 'PUT', credentials: 'include',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({modificador_ids: _modifAsignados.map(m=>m.id)}),
  });
  _renderModifAsignados();
  _poblarSelectModif();
}

function abrirModalNuevoModificador() {
  document.getElementById('modifNombre').value = '';
  document.getElementById('modifTipo').value = 'opcional';
  document.getElementById('modifSeleccion').value = 'unico';
  document.getElementById('modifOpciones').value = '';
  document.getElementById('modalNuevoModificador').classList.add('active');
}

function cerrarModalNuevoModificador() {
  document.getElementById('modalNuevoModificador').classList.remove('active');
  _blurInv();
}

async function guardarNuevoModificador() {
  const nombre = document.getElementById('modifNombre').value.trim();
  if (!nombre) { alert('El nombre es requerido'); return; }
  const tipo      = document.getElementById('modifTipo').value;
  const seleccion = document.getElementById('modifSeleccion').value;
  const lineas    = document.getElementById('modifOpciones').value.split('\n').map(l=>l.trim()).filter(Boolean);
  const opciones  = lineas.map(l => {
    const [nom, precio] = l.split(':');
    return {nombre: nom.trim(), precio_extra: parseInt(precio?.trim()) || 0};
  });
  const r = await fetch('/api/modificadores', {
    method: 'POST', credentials: 'include',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({nombre, tipo, seleccion, opciones}),
  });
  if (!r.ok) { alert('Error al crear modificador'); return; }
  const d = await r.json();
  cerrarModalNuevoModificador();
  await _cargarTodosModificadores();
  // Auto-asignar al producto actual
  const prodId = parseInt(document.getElementById('prodId').value);
  if (prodId) {
    const nuevo = _todosModificadores.find(m=>m.id===d.id);
    if (nuevo) { _modifAsignados.push(nuevo); await _guardarModifAsignados(prodId); }
  } else {
    _poblarSelectModif();
  }
}

function abrirModalNuevoLote() {
  const prodId = document.getElementById('prodId').value;
  if (!prodId) { alert('Guarda el producto primero'); return; }
  document.getElementById('loteProductoId').value = prodId;
  document.getElementById('loteNumero').value = '';
  document.getElementById('loteCantidad').value = '1';
  document.getElementById('loteFechaVenc').value = '';
  document.getElementById('loteNotas').value = '';
  document.getElementById('loteBtnsImprimir').style.display = 'none';
  document.getElementById('loteModalBtns').style.display = 'flex';
  _loteUltimoId = null;
  document.getElementById('modalNuevoLote').classList.add('active');
}

function cerrarModalNuevoLote() {
  document.getElementById('modalNuevoLote').classList.remove('active');
  _blurInv();
  const prodId = document.getElementById('prodId').value;
  if (prodId) cargarLotesProducto(parseInt(prodId));
}

async function guardarNuevoLote() {
  const prodId = parseInt(document.getElementById('loteProductoId').value);
  const cantidad = parseInt(document.getElementById('loteCantidad').value) || 0;
  if (!cantidad) { alert('Ingresa una cantidad'); return; }
  const body = {
    producto_id:       prodId,
    cantidad:          cantidad,
    fecha_vencimiento: document.getElementById('loteFechaVenc').value || null,
    numero_lote:       document.getElementById('loteNumero').value.trim() || null,
    notas:             document.getElementById('loteNotas').value.trim() || null,
  };
  const r = await fetch('/api/inventario/lotes', {
    method: 'POST', credentials: 'include',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (!r.ok) { const e = await r.json(); alert(e.error || 'Error al crear lote'); return; }
  const d = await r.json();
  _loteUltimoId = d.id;
  document.getElementById('btnImprimirEtiquetas').dataset.loteId = d.id;
  document.getElementById('btnImprimirEtiquetas').dataset.cantidad = cantidad;
  document.getElementById('btnImprimirEtiquetas').textContent = `🖨️ Imprimir ${cantidad} etiqueta(s)`;
  document.getElementById('loteBtnsImprimir').style.display = '';
  document.getElementById('loteModalBtns').style.display = 'none';
  cargarProductos();
}

function imprimirEtiquetasLote() {
  const btn = document.getElementById('btnImprimirEtiquetas');
  const loteId = btn.dataset.loteId;
  const cant = btn.dataset.cantidad || 1;
  if (!loteId) return;
  window.open(`/api/inventario/lotes/${loteId}/etiquetas/pdf?cantidad=${cant}`, '_blank');
}

async function eliminarProd(id, nombre) {
  if (!confirm(`¿Eliminar "${nombre}"? El producto quedará inactivo.`)) return;
  const r = await fetch(`/api/productos/${id}`, {method:'DELETE', credentials:'include'});
  if (r.ok) cargarProductos();
  else { const e = await r.json(); alert(e.error || 'Error al eliminar'); }
}

async function ajustarStock(id, nombre, stockActual) {
  const val = prompt(`Stock actual de "${nombre}": ${stockActual}\nNuevo stock:`);
  if (val === null) return;
  const r = await fetch(`/api/productos/${id}/stock`, {
    method:'POST', credentials:'include',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({tipo:'ajuste', cantidad: parseInt(val)||0, motivo:'ajuste_manual'}),
  });
  if (r.ok) cargarProductos();
}

// ── Proveedores ───────────────────────────────────────────────────────
async function cargarProveedores() {
  const provs = await fetch('/api/inventario/proveedores',{credentials:'include'}).then(r=>r.json()).catch(()=>[]);
  const tbody = document.getElementById('tablaProvs');
  if (!provs.length) { tbody.innerHTML='<tr><td colspan="6" style="text-align:center;color:var(--text-dim);padding:20px">Sin proveedores</td></tr>'; return; }
  tbody.innerHTML = provs.map(p=>`<tr>
    <td><strong>${p.nombre}</strong></td>
    <td>${p.rut||'—'}</td><td>${p.contacto||'—'}</td>
    <td>${p.telefono||'—'}</td><td>${p.email||'—'}</td>
    <td><button class="btn" style="padding:4px 10px;font-size:12px" onclick="editarProv(${p.id})">Editar</button></td>
  </tr>`).join('');
}

function abrirModalProv() {
  document.getElementById('provId').value = '';
  document.getElementById('modalProvTitle').textContent = 'Nuevo proveedor';
  ['provNombre','provRut','provContacto','provTelefono','provEmail','provDireccion'].forEach(id => document.getElementById(id).value = '');
  document.getElementById('modalProv').classList.add('active');
}

async function editarProv(id) {
  const provs = await fetch('/api/inventario/proveedores',{credentials:'include'}).then(r=>r.json());
  const p = provs.find(x => x.id === id);
  if (!p) return;
  document.getElementById('provId').value = p.id;
  document.getElementById('modalProvTitle').textContent = 'Editar proveedor';
  document.getElementById('provNombre').value = p.nombre;
  document.getElementById('provRut').value = p.rut || '';
  document.getElementById('provContacto').value = p.contacto || '';
  document.getElementById('provTelefono').value = p.telefono || '';
  document.getElementById('provEmail').value = p.email || '';
  document.getElementById('provDireccion').value = p.direccion || '';
  document.getElementById('modalProv').classList.add('active');
}

async function guardarProv() {
  const id = document.getElementById('provId').value;
  const data = {
    nombre:    document.getElementById('provNombre').value.trim(),
    rut:       document.getElementById('provRut').value.trim(),
    contacto:  document.getElementById('provContacto').value.trim(),
    telefono:  document.getElementById('provTelefono').value.trim(),
    email:     document.getElementById('provEmail').value.trim(),
    direccion: document.getElementById('provDireccion').value.trim(),
  };
  if (!data.nombre) { alert('Nombre requerido'); return; }
  const url = id ? `/api/inventario/proveedores/${id}` : '/api/inventario/proveedores';
  const r = await fetch(url, {method:id?'PUT':'POST', credentials:'include',
    headers:{'Content-Type':'application/json'}, body: JSON.stringify(data)});
  if (r.ok) { cerrarModalProv(); cargarProveedores(); }
  else { const e = await r.json(); alert(e.error || 'Error'); }
}

function cerrarModalProv() { document.getElementById('modalProv').classList.remove('active'); _blurInv(); }

// ── Alertas ───────────────────────────────────────────────────────────
async function cargarAlertas() {
  const alertas = await fetch('/api/productos/alertas',{credentials:'include'}).then(r=>r.json()).catch(()=>[]);
  const tbody = document.getElementById('tablaAlertas');
  if (!alertas.length) { tbody.innerHTML='<tr><td colspan="5" style="text-align:center;color:var(--text-dim);padding:20px">✓ Sin alertas de stock</td></tr>'; return; }
  tbody.innerHTML = alertas.map(a=>`<tr>
    <td><strong>${a.producto_nombre}</strong></td>
    <td class="stock-bajo">${a.stock}</td>
    <td>${a.stock_minimo}</td>
    <td><span class="badge badge-bajo">Stock bajo</span></td>
    <td><button class="btn" style="padding:4px 10px;font-size:12px" onclick="marcarLeida(${a.id})">✓ Atendida</button></td>
  </tr>`).join('');
}

async function marcarLeida(id) {
  await fetch(`/api/productos/alertas/${id}/leer`,{method:'POST',credentials:'include'});
  cargarAlertas();
}

// ── Escáner código de barras ──────────────────────────────────────────
const mostrarToast = (msg, tipo) => showToast(msg, tipo || 'ok');

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

// ── Normalización de nombres (Title Case español) ────────────────────────────
const _MINUSC = new Set(['de','del','la','las','los','el','y','e','o','a','en','con','por','para','sin','al','un','una']);
function normalizarNombreJS(texto) {
  return texto.trim().toLowerCase().split(' ')
    .map((p, i) => (i === 0 || !_MINUSC.has(p)) ? p.charAt(0).toUpperCase() + p.slice(1) : p)
    .join(' ');
}
function _bindNormBlur(id) {
  const el = document.getElementById(id);
  if (!el || el._normBound) return;
  el._normBound = true;
  el.addEventListener('blur', e => {
    const v = e.target.value.trim();
    if (v) e.target.value = normalizarNombreJS(v);
  });
}

// ─── Flujo 4 pasos: Nuevo producto con IA ─────────────────────────────────────

// ── FLUJO: Código → OFF → Foto → Formulario → Guardar ────────────────────────
let estadoNuevoProd = {
  paso: 1,             // 1=código, 'buscando', 2=foto, 3=formulario, 4=guardar
  codigo: null,        // barcode confirmado desde paso 1
  fotos: [],
  datosIA: {},
  imagenUrl: null,
  fuenteDatos: null,   // 'open_food_facts' | 'ocr_local' | null
  _form: {},
  _usarFoto: true,     // true | 'off' | false
  _imagenUrlOff: null,
  _codigoDetectado: null,
  _sugerencias: null,
};

function iniciarFlujoIA() {
  estadoNuevoProd = { paso:1, codigo:null, fotos:[], datosIA:{}, imagenUrl:null,
    fuenteDatos:null, _form:{}, _usarFoto:true, _imagenUrlOff:null,
    _codigoDetectado:null, _sugerencias:null };
  document.getElementById('flujoNuevoProd').style.display = 'block';
  renderPasoActual();
}
function cerrarFlujoIA() { document.getElementById('flujoNuevoProd').style.display = 'none'; }

function avanzarPaso(n) {
  if (estadoNuevoProd.paso === 3 && n !== 3) {
    const nombre = document.getElementById('iaNombre')?.value.trim() || '';
    const precio = parseInt(document.getElementById('iaPrecio')?.value) || 0;
    function _markField(id, msg) {
      showToast(msg, 'error');
      const el = document.getElementById(id);
      if (el) {
        el.style.border = '2px solid #ef4444';
        el.style.boxShadow = '0 0 0 3px rgba(239,68,68,0.2)';
        el.focus();
        setTimeout(() => { el.style.border = ''; el.style.boxShadow = ''; }, 3000);
      }
    }
    const costo3  = parseInt(document.getElementById('iaCosto')?.value) || 0;
    const stock3  = document.getElementById('iaStock')?.value;
    if (!nombre) { _markField('iaNombre', '⚠️ Ingresa el nombre del producto'); return; }
    if (!precio) { _markField('iaPrecio', '⚠️ Ingresa el precio de venta'); return; }
    if (!costo3) { _markField('iaCosto',  '⚠️ Ingresa el precio de costo'); return; }
    if (stock3 === '' || stock3 === null || stock3 === undefined) { _markField('iaStock', '⚠️ Ingresa la cantidad en bodega'); return; }
    estadoNuevoProd._form = {
      nombre, precio,
      costo:      costo3,
      stock:      parseInt(stock3) || 0,
      catId:      document.getElementById('iaCatId')?.value || '',
      marcaId:    document.getElementById('iaMarcaId')?.value || '',
      marcaNombre: document.getElementById('iaMarcaInput')?.value.trim() || '',
      depto:      document.getElementById('iaDepto')?.value || '',
    };
  }
  estadoNuevoProd.paso = n;
  renderPasoActual();
}

function _renderProgreso() {
  const PASOS = [{n:1,l:'Código'},{n:2,l:'Foto'},{n:3,l:'Datos'},{n:4,l:'Listo'}];
  const p = estadoNuevoProd.paso;
  const pNum = p === 'buscando' ? 1.5 : (typeof p === 'number' ? p : 1);
  return `<div class="flujo-progress">
    ${PASOS.map((s,i) => {
      const done   = s.n < pNum;
      const active = !done && s.n <= Math.ceil(pNum);
      return `<div class="flujo-step ${active?'active':done?'done':''}">
        <div class="flujo-dot">${done?'✓':s.n}</div><span>${s.l}</span>
      </div>${i<3?`<div class="flujo-line ${done?'done':''}"></div>`:''}`;
    }).join('')}
  </div>`;
}

function renderPasoActual() {
  document.getElementById('flujoProgreso').innerHTML = _renderProgreso();
  const c = document.getElementById('flujoPaso');
  c.innerHTML = '';
  const p = estadoNuevoProd.paso;
  if      (p === 1)          _rpPaso1Codigo(c);
  else if (p === 'buscando') _rpBuscando(c);
  else if (p === 2)          _rpPaso2Foto(c);
  else if (p === 3)          _rpPaso3Form(c);
  else if (p === 4)          _rpPaso4Guardar(c);
}

// ── PASO 1: Código de barras ──────────────────────────────────────────────────

function _rpPaso1Codigo(c) {
  c.innerHTML = `
    <h2 style="font-size:20px;margin-bottom:8px">🔢 Escanea el código de barras</h2>
    <p style="color:var(--text-dim);font-size:14px;margin-bottom:20px">
      Escanea o escribe el código para buscar el producto automáticamente.
    </p>
    <button class="btn primary" style="width:100%;padding:14px;font-size:15px;margin-bottom:16px" onclick="_escanearCodigoPaso1()">
      📷 Abrir escáner de video
    </button>
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;color:var(--text-dim);font-size:12px">
      <div style="flex:1;height:1px;background:var(--border)"></div>o escribe el código<div style="flex:1;height:1px;background:var(--border)"></div>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:20px">
      <input id="codigoPaso1Input" type="text" inputmode="numeric" placeholder="7802200263031"
        class="flujo-input" style="flex:1;margin:0"
        onkeydown="if(event.key==='Enter')_confirmarCodigoPaso1()">
      <button class="btn" style="padding:12px 16px;flex-shrink:0" onclick="_confirmarCodigoPaso1()">Buscar</button>
    </div>
    <button style="width:100%;padding:12px;background:none;border:none;color:var(--text-dim);font-size:13px;cursor:pointer" onclick="estadoNuevoProd.paso=2;renderPasoActual()">
      Saltar — sin código de barras
    </button>`;
  setTimeout(() => document.getElementById('codigoPaso1Input')?.focus(), 80);
}

async function _escanearCodigoPaso1() {
  const esMobil = /iPhone|iPad|Android/i.test(navigator.userAgent);
  const codigo = await new Promise(resolve => {
    if (esMobil) abrirEscanerVideo(c => resolve(c));
    else abrirEscanerArchivo(c => resolve(c));
  });
  if (codigo) buscarEnOFF(codigo);
}

function _confirmarCodigoPaso1() {
  const val = document.getElementById('codigoPaso1Input')?.value.trim();
  if (val) buscarEnOFF(val);
}

// ── Buscar en OFF (transición automática) ────────────────────────────────────

function _rpBuscando(c) {
  c.innerHTML = `
    <div style="text-align:center;padding:40px 16px">
      <h2 style="font-size:20px;margin-bottom:12px">🔍 Buscando en Open Food Facts...</h2>
      <p style="color:var(--text-dim);font-size:14px;margin-bottom:24px">
        Código: <strong>${escH(estadoNuevoProd.codigo||'')}</strong>
      </p>
      <div style="display:flex;gap:8px;justify-content:center">
        ${[0,1,2].map(i=>`<div style="width:10px;height:10px;border-radius:50%;background:var(--accent);animation:pulse-dot 1s ${i*.33}s infinite alternate"></div>`).join('')}
      </div>
    </div>`;
}

async function buscarEnOFF(codigo) {
  estadoNuevoProd.codigo = codigo;
  estadoNuevoProd.paso = 'buscando';
  renderPasoActual();

  showToast('🌐 Buscando producto en línea...');
  try {
    const fd = new FormData();
    fd.append('codigo_barras', codigo);
    fd.append('solo_off', '1');
    const resp = await fetch('/api/inventario/leer-producto', { method:'POST', credentials:'include', body: fd });
    const data = await resp.json();

    if (data.ok && data.producto) {
      estadoNuevoProd.datosIA       = data.producto;
      estadoNuevoProd.imagenUrl     = data.imagen_url || null;
      estadoNuevoProd._imagenUrlOff = data.producto.imagen_url_off || null;
      estadoNuevoProd.fuenteDatos   = 'open_food_facts';
      if (estadoNuevoProd._imagenUrlOff) estadoNuevoProd._usarFoto = 'off';
      showToast('✅ Producto encontrado en línea');
      estadoNuevoProd.paso = 3;
    } else {
      showToast('⚠️ No encontrado en línea. Toma una foto o ingresa manualmente.', 'error');
      estadoNuevoProd.paso = 2;
    }
  } catch(e) {
    showToast('📵 Sin conexión. Ingresa el nombre manualmente.', 'error');
    estadoNuevoProd.paso = 2;
  }
  renderPasoActual();
}

// ── PASO 2: Foto (opcional) ───────────────────────────────────────────────────

function _rpPaso2Foto(c) {
  const n = estadoNuevoProd.fotos.length;
  const previewsHtml = n ? estadoNuevoProd.fotos.map((f,i) => {
    const url = URL.createObjectURL(f);
    return `<div style="position:relative">
      <img src="${url}" class="foto-thumb ${i===0?'principal':''}">
      ${i===0?'<span style="position:absolute;bottom:3px;left:3px;background:#22c55e;color:#000;font-size:9px;padding:1px 5px;border-radius:4px">portada</span>':''}
      <button onclick="_eliminarFoto(${i})" style="position:absolute;top:2px;right:2px;background:rgba(0,0,0,.6);border:none;color:white;border-radius:50%;width:20px;height:20px;cursor:pointer;font-size:11px;padding:0">✕</button>
    </div>`;
  }).join('') : '';

  c.innerHTML = `
    <h2 style="font-size:20px;margin-bottom:8px">📷 Fotografía el producto</h2>
    <p style="color:var(--text-dim);font-size:14px;margin-bottom:16px">
      Toma una foto para guardar en el catálogo y leer la etiqueta.
    </p>
    ${n ? `<div class="foto-preview-grid" style="margin-bottom:16px">${previewsHtml}</div>` : `
      <div class="drop-zone" style="margin-bottom:16px">
        <div style="font-size:48px;margin-bottom:10px">📷</div>
        <p style="font-size:13px;color:var(--text-dim)">Foto frontal con buena iluminación</p>
      </div>`}
    ${n < 3 ? `<button class="btn ${n===0?'primary':''}" style="width:100%;padding:14px;font-size:15px;margin-bottom:10px" onclick="_tomarFoto()">
      📷 ${n===0?'Tomar foto':'+ Agregar otra foto'}
    </button>` : ''}
    ${n > 0 ? `<button class="btn" style="width:100%;padding:14px;font-size:15px;font-weight:700;margin-bottom:10px;background:#22c55e;border-color:#22c55e;color:#000" onclick="_analizarFotoPaso2()">
      ✓ Listo — analizar con IA
    </button>` : ''}
    <button style="width:100%;padding:12px;background:none;border:none;color:var(--text-dim);font-size:13px;cursor:pointer" onclick="avanzarPaso(3)">
      Saltar → ingresar datos manualmente
    </button>
    <button style="width:100%;padding:8px;background:none;border:none;color:var(--text-dim);font-size:12px;cursor:pointer;margin-top:2px" onclick="estadoNuevoProd.paso=1;renderPasoActual()">
      ← Volver al código
    </button>`;
}

function _eliminarFoto(i) { estadoNuevoProd.fotos.splice(i,1); renderPasoActual(); }

function _tomarFoto() {
  const input = document.createElement('input');
  input.type='file'; input.accept='image/*'; input.style.display='none';
  if (/iPhone|iPad|Android/i.test(navigator.userAgent)) input.capture='environment';
  document.body.appendChild(input);
  input.addEventListener('change', e => {
    document.body.removeChild(input);
    const f = e.target.files?.[0];
    if (f) { estadoNuevoProd.fotos.push(f); renderPasoActual(); }
  });
  input.click();
}

async function _analizarFotoPaso2() {
  const c = document.getElementById('flujoPaso');
  c.innerHTML = `
    <div style="text-align:center;padding:40px 16px">
      <h2 style="font-size:20px;margin-bottom:20px">🤖 Analizando la foto...</h2>
      <div style="display:flex;gap:8px;justify-content:center">
        ${[0,1,2].map(i=>`<div style="width:10px;height:10px;border-radius:50%;background:var(--accent);animation:pulse-dot 1s ${i*.33}s infinite alternate"></div>`).join('')}
      </div>
    </div>`;
  try {
    const fd = new FormData();
    estadoNuevoProd.fotos.forEach(f => fd.append('imagenes', f));
    if (estadoNuevoProd.codigo) fd.append('codigo_barras', estadoNuevoProd.codigo);
    fd.append('categorias', categorias.map(cat=>cat.nombre).join(', '));
    const resp = await fetch('/api/inventario/leer-producto', { method:'POST', credentials:'include', body: fd });
    const data = await resp.json();

    if (data.ok && data.producto) {
      estadoNuevoProd.datosIA       = data.producto;
      estadoNuevoProd.imagenUrl     = data.imagen_url || null;
      estadoNuevoProd._imagenUrlOff = data.producto.imagen_url_off || null;
      estadoNuevoProd.fuenteDatos   = data.fuente || data.producto.fuente || 'ocr_local';
      if (data.codigo_detectado && !estadoNuevoProd.codigo) {
        estadoNuevoProd.codigo = data.codigo_detectado;
        estadoNuevoProd._codigoDetectado = data.codigo_detectado;
      }
      estadoNuevoProd._sugerencias = (data.sugerencias && data.sugerencias.length) ? data.sugerencias : null;
      if (estadoNuevoProd._sugerencias) {
        estadoNuevoProd.paso = 3;
        document.getElementById('flujoProgreso').innerHTML = _renderProgreso();
        _rpSugerencias(document.getElementById('flujoPaso'));
        return;
      }
    } else {
      if (data.imagen_url) estadoNuevoProd.imagenUrl = data.imagen_url;
      showToast('No se pudo leer la etiqueta — rellena manualmente', 'error');
    }
  } catch(e) {
    showToast('Error al analizar la foto', 'error');
  }
  avanzarPaso(3);
}

function _rpSugerencias(c) {
  const sugs = estadoNuevoProd._sugerencias || [];
  c.innerHTML = `
    <div style="padding:4px 0">
      <h2 style="font-size:18px;margin-bottom:4px">🔍 ¿Es uno de estos?</h2>
      <p style="color:var(--text-dim);font-size:13px;margin-bottom:16px">Open Food Facts encontró productos similares</p>
      ${sugs.map((s, i) => `
        <button onclick="_elegirSugerencia(${i})" style="width:100%;text-align:left;background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin-bottom:8px;cursor:pointer;display:flex;align-items:center;gap:12px">
          <span style="font-size:22px;flex-shrink:0">🏷️</span>
          <span style="flex:1;min-width:0">
            <div style="font-size:14px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escH(s.nombre)}</div>
            <div style="font-size:12px;color:var(--text-dim);margin-top:2px">${[s.marca,s.contenido].filter(Boolean).map(escH).join(' · ') || '—'}</div>
          </span>
          <span style="font-size:18px;color:var(--accent2);flex-shrink:0">›</span>
        </button>`).join('')}
      <button onclick="_elegirSugerencia(null)" style="width:100%;padding:12px;background:none;border:1px dashed var(--border);border-radius:10px;color:var(--text-dim);font-size:13px;cursor:pointer;margin-top:4px">
        Ninguno de estos → ingresar manual
      </button>
    </div>`;
}

function _elegirSugerencia(idx) {
  if (idx !== null) {
    const s = estadoNuevoProd._sugerencias[idx];
    estadoNuevoProd.datosIA = { ...estadoNuevoProd.datosIA, ...s };
    estadoNuevoProd.fuenteDatos = 'open_food_facts';
    if (s.codigo_barras) estadoNuevoProd.codigo = s.codigo_barras;
  }
  estadoNuevoProd._sugerencias = null;
  avanzarPaso(3);
}

window.volverAPaso1 = function() {
  iniciarFlujoIA();
};

// ── PASO 3: Formulario ────────────────────────────────────────────────────────

function _rpPaso3Form(c) {
  const d = estadoNuevoProd.datosIA;
  const f = estadoNuevoProd._form;
  const ia = v => !!(d[v]);
  const val = (key, fallback='') => f[key] !== undefined ? f[key] : (d[key]||fallback);

  let catSugeridaId = '';
  if (d.categoria_sugerida) {
    const match = categorias.find(cat => cat.nombre === d.categoria_sugerida);
    if (match) catSugeridaId = match.id;
  }
  const depAct = f.depto || d.departamento || '';
  const DEPTOS = ['Alimentación','Bebidas con Alcohol','Belleza y Cuidado Personal','Limpieza del Hogar','Mundo Bebé','Mascotas','Manualidades y Hogar','Juguetes y Entretencion','Ferretería Básica','Tabaco','Otros'];
  const catsFilt = depAct ? categorias.filter(cat=>cat.departamento===depAct) : categorias;
  const fuente = estadoNuevoProd.fuenteDatos;

  c.innerHTML = `
    <h2 style="font-size:20px;margin-bottom:4px">✨ Revisar y completar</h2>
    <p style="color:var(--text-dim);font-size:13px;margin-bottom:10px">${d.nombre?'Revisa los datos y completa lo que falta.':'Ingresa los datos del producto.'}</p>

    ${fuente === 'open_food_facts'
      ? `<div style="display:inline-flex;align-items:center;gap:6px;background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.4);border-radius:20px;padding:4px 12px;font-size:12px;color:#86efac;margin-bottom:12px">🌐 Datos obtenidos en línea</div>`
      : fuente === 'ocr_local'
      ? `<div style="display:inline-flex;align-items:center;gap:6px;background:rgba(234,179,8,.10);border:1px solid rgba(234,179,8,.4);border-radius:20px;padding:4px 12px;font-size:12px;color:#fde047;margin-bottom:12px">📷 Datos leídos de la foto</div>`
      : `<div style="display:inline-flex;align-items:center;gap:6px;background:rgba(148,163,184,.08);border:1px solid rgba(148,163,184,.3);border-radius:20px;padding:4px 12px;font-size:12px;color:var(--text-dim);margin-bottom:12px">✏️ Ingreso manual</div>`
    }

    ${estadoNuevoProd._codigoDetectado ? `
    <div style="background:#0f2d1a;border:1px solid #22c55e;border-radius:8px;padding:10px 14px;margin-bottom:14px;font-size:13px;color:#86efac">
      ✅ Código detectado en la foto: <strong>${escH(estadoNuevoProd._codigoDetectado)}</strong>
    </div>` : ''}

    ${(estadoNuevoProd.imagenUrl || estadoNuevoProd._imagenUrlOff) ? (() => {
      const sel = estadoNuevoProd._usarFoto;
      const catEmoji = (() => { try { return categorias.find(cat=>cat.id==catSugeridaId)?.icono || '📦'; } catch(e){ return '📦'; } })();
      const tieneFoto = !!estadoNuevoProd.imagenUrl;
      const tieneOff  = !!estadoNuevoProd._imagenUrlOff;
      const btnFoto = tieneFoto ? `
        <button onclick="estadoNuevoProd._usarFoto=true;renderPasoActual()"
          style="flex:1;padding:10px;background:${sel===true?'rgba(34,197,94,.15)':'var(--surface)'};border:2px solid ${sel===true?'#22c55e':'var(--border)'};border-radius:10px;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:6px">
          <img src="${escH(estadoNuevoProd.imagenUrl)}" style="width:56px;height:56px;object-fit:cover;border-radius:8px" onerror="this.style.display='none'">
          <span style="font-size:11px;color:${sel===true?'#86efac':'var(--text-dim)'}">📷 Mi foto</span>
        </button>` : '';
      const btnOff = tieneOff ? `
        <button onclick="estadoNuevoProd._usarFoto='off';renderPasoActual()"
          style="flex:1;padding:10px;background:${sel==='off'?'rgba(59,130,246,.15)':'var(--surface)'};border:2px solid ${sel==='off'?'#3b82f6':'var(--border)'};border-radius:10px;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:6px">
          <img src="${escH(estadoNuevoProd._imagenUrlOff)}" style="width:56px;height:56px;object-fit:cover;border-radius:8px" onerror="this.style.display='none'">
          <span style="font-size:11px;color:${sel==='off'?'#93c5fd':'var(--text-dim)'}">🌐 Imagen de OFF</span>
        </button>` : '';
      const btnIcon = `
        <button onclick="estadoNuevoProd._usarFoto=false;renderPasoActual()"
          style="flex:1;padding:10px;background:${sel===false?'rgba(99,102,241,.15)':'var(--surface)'};border:2px solid ${sel===false?'#6366f1':'var(--border)'};border-radius:10px;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:6px">
          <span style="font-size:42px;line-height:1">${catEmoji}</span>
          <span style="font-size:11px;color:${sel===false?'#a5b4fc':'var(--text-dim)'}">🎨 Ícono auto</span>
        </button>`;
      return `
      <div style="margin-bottom:16px">
        <label class="flujo-label">Imagen del producto</label>
        <div style="display:flex;gap:8px;margin-top:6px">${btnFoto}${btnOff}${btnIcon}</div>
      </div>`;
    })() : ''}

    <div class="flujo-field">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <label class="flujo-label" style="margin:0">Nombre *</label>
        ${ia('nombre')?'<span class="ia-badge">✅ IA</span>':''}
      </div>
      <input id="iaNombre" class="flujo-input ${ia('nombre')?'ia-filled':''}" value="${escH(val('nombre'))}" placeholder="Nombre del producto" style="font-size:15px">
    </div>

    <div class="flujo-field">
      <label class="flujo-label">Precio de venta *</label>
      <input id="iaPrecio" type="number" class="flujo-input" value="${f.precio||''}" placeholder="Ej: 1890" inputmode="numeric" style="font-size:18px;font-weight:700">
    </div>

    <div class="flujo-field">
      <label class="flujo-label">Precio de costo *</label>
      <input id="iaCosto" type="number" class="flujo-input" value="${f.costo||''}" placeholder="Precio pagado al proveedor" inputmode="numeric">
    </div>

    <div class="flujo-field">
      <label class="flujo-label">Cantidad en bodega *</label>
      <input id="iaStock" type="number" class="flujo-input" value="${f.stock!==undefined?f.stock:''}" placeholder="Ej: 10" inputmode="numeric">
    </div>

    <div class="flujo-field" style="position:relative">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <label class="flujo-label" style="margin:0">Marca</label>
        ${ia('marca')?'<span class="ia-badge">✅ IA</span>':''}
      </div>
      <input id="iaMarcaInput" class="flujo-input ${ia('marca')?'ia-filled':''}"
        value="${escH(f.marcaNombre||d.marca||'')}" placeholder="Buscar o crear marca..."
        autocomplete="off"
        oninput="buscarMarcas('iaMarcaInput','iaMarcaId','marcaDropdownIA')"
        onfocus="buscarMarcas('iaMarcaInput','iaMarcaId','marcaDropdownIA')">
      <input type="hidden" id="iaMarcaId" value="${escH(f.marcaId||'')}">
      <div id="marcaDropdownIA" class="marca-dropdown" style="display:none"></div>
    </div>

    <div class="flujo-field">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <label class="flujo-label" style="margin:0">Departamento</label>
        ${ia('departamento')?'<span class="ia-badge">✅ IA</span>':''}
      </div>
      <select id="iaDepto" class="flujo-input ${ia('departamento')?'ia-filled':''}" onchange="_actualizarCatsFormIA()">
        <option value="">Seleccionar...</option>
        ${DEPTOS.map(dep=>`<option value="${escH(dep)}" ${dep===depAct?'selected':''}>${escH(dep)}</option>`).join('')}
      </select>
    </div>

    <div class="flujo-field">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <label class="flujo-label" style="margin:0">Categoría</label>
        ${catSugeridaId?'<span class="ia-badge">✅ IA</span>':''}
      </div>
      <select id="iaCatId" class="flujo-input ${catSugeridaId?'ia-filled':''}">
        <option value="">Sin categoría</option>
        ${catsFilt.map(cat=>`<option value="${cat.id}" ${cat.id==catSugeridaId?'selected':''}>${escH(cat.nombre)}</option>`).join('')}
      </select>
    </div>


    <div style="display:flex;flex-direction:column;gap:10px">
      <button class="btn" style="padding:11px" onclick="estadoNuevoProd.paso=2;renderPasoActual()">← Volver a la foto</button>
      <button class="btn primary" style="padding:14px;font-size:15px;font-weight:700" onclick="avanzarPaso(4)">Continuar → Confirmar</button>
    </div>`;

  setTimeout(() => {
    _bindNormBlur('iaNombre');
    (!d.nombre ? document.getElementById('iaNombre') : document.getElementById('iaPrecio'))?.focus();
  }, 80);
}

function _actualizarCatsFormIA() {
  const depto = document.getElementById('iaDepto')?.value;
  estadoNuevoProd._form.depto = depto;
  const sel = document.getElementById('iaCatId');
  if (!sel) return;
  const cf = depto ? categorias.filter(c=>c.departamento===depto) : categorias;
  sel.innerHTML = '<option value="">Sin categoría</option>' + cf.map(c=>`<option value="${c.id}">${escH(c.nombre)}</option>`).join('');
}

function _rpPaso4Guardar(c) {
  const fd = estadoNuevoProd._form;
  const nombre  = fd.nombre  || estadoNuevoProd.datosIA.nombre  || '';
  const precio  = fd.precio  || estadoNuevoProd.datosIA.precio  || '';
  const costo   = fd.costo   || estadoNuevoProd.datosIA.costo   || '';
  const stock   = fd.stock   != null ? fd.stock : (estadoNuevoProd.datosIA.stock ?? '');
  const codigo  = estadoNuevoProd.codigo || '';
  const fuente  = estadoNuevoProd.fuenteDatos;

  const fuenteBadge = fuente === 'open_food_facts'
    ? `<span style="display:inline-block;background:#0f2d1a;border:1px solid #22c55e;color:#86efac;border-radius:6px;padding:3px 10px;font-size:12px">🌐 Datos en línea</span>`
    : fuente === 'ocr_local'
    ? `<span style="display:inline-block;background:#2d1f0f;border:1px solid #f59e0b;color:#fcd34d;border-radius:6px;padding:3px 10px;font-size:12px">📷 Leído de foto</span>`
    : `<span style="display:inline-block;background:#1a1a2e;border:1px solid #6366f1;color:#a5b4fc;border-radius:6px;padding:3px 10px;font-size:12px">✏️ Ingreso manual</span>`;

  const imgSrc = (() => {
    const sel = estadoNuevoProd._usarFoto;
    if (sel === true  && estadoNuevoProd.imagenUrl)     return estadoNuevoProd.imagenUrl;
    if (sel === 'off' && estadoNuevoProd._imagenUrlOff) return estadoNuevoProd._imagenUrlOff;
    return null;
  })();

  c.innerHTML = `
    <h2 style="font-size:20px;margin-bottom:4px">✅ Confirmar producto</h2>
    <p style="color:var(--text-dim);font-size:13px;margin-bottom:16px">Revisa los datos antes de guardar.</p>

    <div style="background:var(--surface2);border-radius:10px;padding:16px;margin-bottom:16px;display:flex;gap:14px;align-items:flex-start">
      ${imgSrc ? `<img src="${escH(imgSrc)}" style="width:72px;height:72px;object-fit:cover;border-radius:8px;flex-shrink:0">` : `<div style="width:72px;height:72px;border-radius:8px;background:var(--surface3);display:flex;align-items:center;justify-content:center;font-size:28px;flex-shrink:0">📦</div>`}
      <div style="flex:1;min-width:0">
        <div style="font-size:17px;font-weight:700;margin-bottom:4px;word-break:break-word">${escH(nombre || '(sin nombre)')}</div>
        <div style="font-size:22px;font-weight:800;color:var(--accent);margin-bottom:6px">${precio ? '$' + parseInt(precio).toLocaleString('es-CL') : '—'}</div>
        <div style="display:flex;flex-wrap:wrap;gap:6px;font-size:12px;color:var(--text-dim)">
          ${costo  ? `<span>Costo: $${parseInt(costo).toLocaleString('es-CL')}</span>` : ''}
          ${stock  !== '' ? `<span>Stock: ${stock}</span>` : ''}
          ${codigo ? `<span>Código: ${escH(codigo)}</span>` : ''}
        </div>
        <div style="margin-top:8px">${fuenteBadge}</div>
      </div>
    </div>

    <div style="display:flex;flex-direction:column;gap:10px">
      <button class="btn primary" style="padding:15px;font-size:16px;font-weight:700" onclick="_guardarProductoFlujoIA()">💾 Guardar en el catálogo</button>
      <button class="btn" style="padding:11px;font-size:14px" onclick="estadoNuevoProd.paso=3;renderPasoActual()">← Volver a editar</button>
    </div>`;
}

async function _guardarProductoFlujoIA() {
  const fd = estadoNuevoProd._form;
  const nombre = fd.nombre || estadoNuevoProd.datosIA.nombre || '';
  const precio = fd.precio || 0;
  function _highlightError(inputId, msg) {
    estadoNuevoProd.paso = 3;
    renderPasoActual();
    showToast(msg, 'error');
    const el = document.getElementById(inputId);
    if (el) {
      el.style.border = '2px solid #ef4444';
      el.style.boxShadow = '0 0 0 3px rgba(239,68,68,0.2)';
      el.focus();
      setTimeout(() => { el.style.border = ''; el.style.boxShadow = ''; }, 3000);
    }
  }

  if (!nombre) { _highlightError('iaNombre', '⚠️ Ingresa el nombre del producto'); return; }
  if (!precio) { _highlightError('iaPrecio', '⚠️ Ingresa el precio de venta'); return; }
  const costo = fd.costo;
  if (!costo) { _highlightError('iaCosto', '⚠️ Ingresa el precio de costo'); return; }
  const cantidad = fd.stock;
  if (cantidad === '' || cantidad === null || cantidad === undefined) { _highlightError('iaStock', '⚠️ Ingresa la cantidad en bodega'); return; }

  const imagenUrlFinal = (() => {
    const sel = estadoNuevoProd._usarFoto;
    if (sel === true  && estadoNuevoProd.imagenUrl)     return estadoNuevoProd.imagenUrl;
    if (sel === 'off' && estadoNuevoProd._imagenUrlOff) return estadoNuevoProd._imagenUrlOff;
    return null;
  })();

  const data = {
    nombre, precio,
    precio_costo: fd.costo || 0,
    stock: fd.stock || 0,
    codigo_barras: estadoNuevoProd.codigo || null,
    ...(fd.catId   ? { categoria_id: parseInt(fd.catId) } : {}),
    ...(fd.marcaId ? { marca_id: parseInt(fd.marcaId) }  : {}),
    ...(imagenUrlFinal ? { imagen_url: imagenUrlFinal } : {}),
  };

  try {
    const r = await fetch('/api/productos', {
      method:'POST', credentials:'include',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(data),
    });
    if (r.ok) {
      cerrarFlujoIA();
      showToast(`✅ ${nombre} guardado en el catálogo`, 'ok');
      cargarProductos();
    } else if (r.status === 409) {
      const e = await r.json();
      if (confirm(`Ya existe: "${e.existente.nombre}"\n¿Actualizar sus datos?`)) {
        const rPut = await fetch(`/api/productos/${e.existente.id}`, {
          method:'PUT', credentials:'include',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify(data),
        });
        if (rPut.ok) { cerrarFlujoIA(); showToast('✅ Producto actualizado', 'ok'); cargarProductos(); }
        else { const e2 = await rPut.json(); showToast('Error: ' + (e2.error || 'No se pudo actualizar'), 'error'); }
      }
    } else {
      const e = await r.json();
      showToast('Error: ' + (e.error || 'No se pudo guardar'), 'error');
    }
  } catch(e) { showToast('Error al guardar', 'error'); }
}

// Escanear barcode en el modal manual (sin IA)
function _escanearBarraModal() {
  const esMobil = /iPhone|iPad|Android/i.test(navigator.userAgent);
  const cb = c => { if (c) document.getElementById('prodBarras').value = c; };
  if (esMobil) abrirEscanerVideo(cb);
  else abrirEscanerArchivo(cb);
}

async function guardarProductoNuevo() {
  const modal = document.getElementById('modalNuevoProd');
  const codigo = modal?.dataset.codigo || null;
  const nombre = document.getElementById('npNombre')?.value.trim();
  const precio = parseInt(document.getElementById('npPrecio')?.value) || 0;
  if (!nombre) { showToast('El nombre es requerido', 'error'); document.getElementById('npNombre')?.focus(); return; }
  const imagenUrl = modal?.dataset.imagenUrl || estadoNuevoProd.imagenUrl || null;
  const data = {
    nombre,
    precio,
    precio_costo: parseInt(document.getElementById('npCosto')?.value) || 0,
    stock:        parseInt(document.getElementById('npStock')?.value) || 0,
    codigo_barras: codigo || null,
    ...(imagenUrl ? { imagen_url: imagenUrl } : {}),
  };
  try {
    const r = await fetch('/api/productos', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (r.ok) {
      modal?.remove();
      showToast('✅ Producto guardado', 'ok');
      cargarProductos();
    } else if (r.status === 409) {
      const e = await r.json();
      const existente = e.existente;
      if (confirm(`Ya existe: "${existente.nombre}"\n¿Actualizar sus datos?`)) {
        const rPut = await fetch(`/api/productos/${existente.id}`, {
          method: 'PUT', credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
        });
        if (rPut.ok) {
          modal?.remove();
          showToast('✅ Producto actualizado', 'ok');
          cargarProductos();
        } else {
          const ep = await rPut.json();
          showToast('Error al actualizar: ' + (ep.error || ''), 'error');
        }
      }
    } else {
      const e = await r.json();
      showToast('Error: ' + (e.error || 'No se pudo guardar'), 'error');
    }
  } catch(e) {
    showToast('Error al guardar', 'error');
  }
}

async function crearCatNueva(nombre, depto) {
  try {
    const r = await fetch('/api/productos/categorias', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ nombre, departamento: depto, icono: '📦' }),
    });
    const d = await r.json();
    if (r.ok) {
      categorias = await fetch('/api/productos/categorias',{credentials:'include'}).then(r=>r.json()).catch(()=>[]);
      filtrarCategoriasPorDepto();
      document.getElementById('catFiltros').innerHTML = '<button class="cat-filtro-btn active" onclick="filtrarPorCat(null,this)">Todos</button>';
      cargarCatFiltros();
      renderCatTab();
      const banner = document.getElementById('npCatNuevaBanner');
      if (banner) banner.innerHTML = `<span style="color:#86efac">✅ Categoría "${nombre}" creada</span>`;
      showToast('✅ Categoría creada: ' + nombre, 'ok');
    } else { showToast('Error: ' + (d.error || 'No se pudo crear'), 'error'); }
  } catch(e) { showToast('Error al crear categoría', 'error'); }
}

// ── Lector de facturas ────────────────────────────────────────────────
const escH = s => (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
let _facturaData = null;

function showToast(msg, tipo='ok') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `show ${tipo}`;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => { t.className = ''; }, 3200);
}

function leerFactura() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*,application/pdf';
  input.onchange = async () => {
    const file = input.files[0];
    if (!file) return;
    document.getElementById('spinnerOverlay').classList.add('active');
    try {
      const fd = new FormData();
      fd.append('factura', file);
      const r = await fetch('/api/inventario/leer-factura', {
        method: 'POST', credentials: 'include', body: fd,
      });
      const d = await r.json();
      if (!d.ok) throw new Error(d.error || 'Error al analizar la factura');
      mostrarModalFactura(d.datos, d.fuente);
    } catch (e) {
      showToast('Error: ' + e.message, 'error');
    } finally {
      document.getElementById('spinnerOverlay').classList.remove('active');
    }
  };
  input.click();
}

function mostrarModalFactura(datos, fuente) {
  _facturaData = datos;
  const fuentes = {tinyllama:'🦙 TinyLlama', heuristico:'📐 Regex', '':''};
  const el = document.getElementById('facFuente');
  if (el) el.textContent = fuentes[fuente] || fuente || '';
  const p = datos.proveedor || {};
  document.getElementById('facNombre').value   = p.nombre || '';
  document.getElementById('facRut').value      = p.rut || '';
  document.getElementById('facVendedor').value = p.vendedor_nombre || '';
  document.getElementById('facTelefono').value = p.vendedor_telefono || '';
  document.getElementById('facFolio').value    = datos.folio || '';
  document.getElementById('facFecha').value    = datos.fecha || '';
  document.getElementById('facTotal').textContent = fmt(datos.total || 0);

  const prods = datos.productos || [];
  const nuevos = prods.filter(x => !x.existe).length;
  const exist  = prods.filter(x => x.existe).length;
  document.getElementById('facResumen').textContent =
    prods.length ? `${nuevos} nuevo${nuevos !== 1 ? 's' : ''} · ${exist} existente${exist !== 1 ? 's' : ''}` : '';

  const facProds = document.getElementById('facProductos');
  if (!prods.length) {
    facProds.innerHTML = `
      <div style="text-align:center;padding:20px 0;color:var(--text-dim)">
        <div style="font-size:28px;margin-bottom:8px">📋</div>
        <div style="font-size:13px;margin-bottom:12px">No se detectaron productos automáticamente</div>
        <button class="btn primary sm" onclick="_agregarFilaFactura()">+ Agregar manualmente</button>
      </div>`;
  } else {
    facProds.innerHTML = prods.map((prod, i) => `
      <div class="factura-prod-row" id="fprow${i}">
        <input type="checkbox" id="fchk${i}" checked style="cursor:pointer;accent-color:var(--accent)">
        <input class="finput" id="fnombre${i}" value="${escH(prod.nombre)}" style="min-width:0">
        <input class="finput" id="fbarras${i}" value="${escH(prod.codigo_barras || '')}" placeholder="—">
        <input class="finput" id="fcant${i}"   type="number" value="${prod.cantidad||1}" min="1">
        <input class="finput" id="fpunit${i}"  type="number" value="${prod.precio_unitario||0}" min="0">
        <span class="${prod.existe ? 'badge-existe' : 'badge-nuevo'}">${prod.existe ? '✅ Existe' : '✨ Nuevo'}</span>
      </div>
    `).join('');
    // Botón para añadir más filas
    facProds.insertAdjacentHTML('beforeend',
      `<div style="text-align:right;margin-top:6px"><button class="btn sm" onclick="_agregarFilaFactura()">+ Agregar producto</button></div>`
    );
  }

  document.getElementById('modalFactura').classList.add('active');
}

function _agregarFilaFactura() {
  const facProds = document.getElementById('facProductos');
  // Limpiar el mensaje de "no detectados" si existe
  const placeholder = facProds.querySelector('[style*="text-align:center"]');
  if (placeholder) placeholder.remove();
  // Quitar botón de agregar al final si existe, para reinsertarlo después
  const btnAgregar = facProds.querySelector('[style*="text-align:right"]');
  if (btnAgregar) btnAgregar.remove();

  const i = facProds.querySelectorAll('.factura-prod-row').length;
  const fila = document.createElement('div');
  fila.className = 'factura-prod-row';
  fila.id = `fprow${i}`;
  fila.innerHTML = `
    <input type="checkbox" id="fchk${i}" checked style="cursor:pointer;accent-color:var(--accent)">
    <input class="finput" id="fnombre${i}" placeholder="Nombre producto" style="min-width:0">
    <input class="finput" id="fbarras${i}" placeholder="Código barras">
    <input class="finput" id="fcant${i}"   type="number" value="1" min="1">
    <input class="finput" id="fpunit${i}"  type="number" value="0" min="0">
    <span class="badge-nuevo">✨ Nuevo</span>
  `;
  facProds.appendChild(fila);
  facProds.insertAdjacentHTML('beforeend',
    `<div style="text-align:right;margin-top:6px"><button class="btn sm" onclick="_agregarFilaFactura()">+ Agregar producto</button></div>`
  );
  fila.querySelector(`#fnombre${i}`).focus();
}

function cerrarModalFactura() {
  document.getElementById('modalFactura').classList.remove('active');
  _facturaData = null;
  _blurInv();
}

async function importarFactura() {
  if (!_facturaData) return;
  const selectedProds = [];
  // Recorre todas las filas del DOM (incluye filas manuales)
  document.querySelectorAll('#facProductos .factura-prod-row').forEach((row, i) => {
    if (!row.querySelector(`#fchk${i}`)?.checked) return;
    const nombre = (row.querySelector(`#fnombre${i}`)?.value || '').trim();
    if (!nombre) return;
    const barras = (row.querySelector(`#fbarras${i}`)?.value || '').trim();
    selectedProds.push({
      nombre,
      codigo_barras:   barras || null,
      cantidad:        parseInt(row.querySelector(`#fcant${i}`)?.value)  || 1,
      precio_unitario: parseInt(row.querySelector(`#fpunit${i}`)?.value) || 0,
    });
  });

  if (!selectedProds.length) { showToast('Selecciona al menos un producto', 'error'); return; }

  const payload = {
    proveedor: {
      nombre:             document.getElementById('facNombre').value.trim(),
      rut:                document.getElementById('facRut').value.trim(),
      vendedor_nombre:    document.getElementById('facVendedor').value.trim(),
      vendedor_telefono:  document.getElementById('facTelefono').value.trim(),
    },
    folio:    document.getElementById('facFolio').value.trim(),
    fecha:    document.getElementById('facFecha').value,
    total:    _facturaData.total || 0,
    productos: selectedProds,
  };

  try {
    const r = await fetch('/api/inventario/importar-factura', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || 'Error al importar');
    cerrarModalFactura();
    cargarProductos();
    showToast(`✓ ${d.creados} nuevo${d.creados!==1?'s':''} · ${d.actualizados} actualizado${d.actualizados!==1?'s':''}`, 'ok');
    if (d.sin_precio?.length) {
      setTimeout(() =>
        showToast(`⚠️ ${d.sin_precio.length} producto${d.sin_precio.length!==1?'s':''} sin precio de venta`, 'error'),
        3500
      );
    }
  } catch (e) {
    showToast('Error: ' + e.message, 'error');
  }
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    cerrarModalProd();
    cerrarModalProv();
    cerrarModalProduccion();
    cerrarModalFactura();
    document.getElementById('modalNuevoLote').classList.remove('active');
  }
});

init();


/* ── Service Worker registration ──────────────────────────────── */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', {scope: '/'})
      .catch(err => console.log('SW error:', err));
  });
}


/* ── Comando de stock por voz ──────────────────────────────────── */
function abrirComandoStock() {
  document.getElementById('panelComandoStock').style.transform = 'translateY(0)';
  document.getElementById('overlayComandoStock').style.display = 'block';
  document.getElementById('resultadoComandoStock').style.display = 'none';
  document.getElementById('inputComandoStock').value = '';
  setTimeout(() => document.getElementById('inputComandoStock')?.focus(), 300);
}

function cerrarComandoStock() {
  document.getElementById('panelComandoStock').style.transform = 'translateY(100%)';
  document.getElementById('overlayComandoStock').style.display = 'none';
  document.getElementById('resultadoComandoStock').style.display = 'none';
  document.getElementById('inputComandoStock').value = '';
  if (document.activeElement) document.activeElement.blur();
}

async function procesarComandoStock() {
  const input = document.getElementById('inputComandoStock');
  const texto = input?.value.trim();
  const resultado = document.getElementById('resultadoComandoStock');
  if (!texto) return;

  resultado.style.display = 'block';
  resultado.style.background = '#1e1e2e';
  resultado.style.border = '1px solid #444';
  resultado.style.color = '#ccc';
  resultado.innerHTML = '⏳ Procesando...';

  try {
    const resp = await fetch('/api/voz/comando-stock', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texto }),
    });
    const data = await resp.json();

    if (data.status === 'success') {
      resultado.style.background = '#0f2d1a';
      resultado.style.border = '1px solid #22c55e';
      resultado.style.color = '#86efac';
      resultado.innerHTML = data.mensaje;
      input.value = '';
      setTimeout(() => {
        cerrarComandoStock();
        if (typeof cargarProductos === 'function') cargarProductos();
      }, 2000);
    } else {
      resultado.style.background = '#2d1111';
      resultado.style.border = '1px solid #ef4444';
      resultado.style.color = '#fca5a5';
      resultado.innerHTML = data.mensaje || 'Error desconocido';
    }
  } catch(e) {
    resultado.style.background = '#2d1111';
    resultado.style.color = '#fca5a5';
    resultado.innerHTML = '❌ Error de conexión';
  }
}

function activarVozStock() {
  const btn = document.getElementById('btnVozStock');
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    showToast('⚠️ Tu navegador no soporta voz. Escribe el comando.');
    return;
  }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recognition = new SR();
  recognition.lang = 'es-CL';
  recognition.continuous = false;
  recognition.interimResults = true;

  btn.innerHTML = '🔴 Escuchando...';
  btn.style.background = '#ef4444';
  btn.style.border = '1px solid #ef4444';

  const input = document.getElementById('inputComandoStock');

  recognition.onresult = (e) => {
    const interino = Array.from(e.results).map(r => r[0].transcript).join('');
    input.value = interino;
    // Auto-procesar cuando el resultado es final
    if (e.results[e.results.length - 1].isFinal) {
      btn.innerHTML = '🎤 Hablar';
      btn.style.background = '';
      btn.style.border = '';
      procesarComandoStock();
    }
  };
  recognition.onerror = () => {
    btn.innerHTML = '🎤 Hablar';
    btn.style.background = '';
    btn.style.border = '';
    showToast('No se escuchó nada. Intenta de nuevo.');
  };
  recognition.onend = () => {
    btn.innerHTML = '🎤 Hablar';
    btn.style.background = '';
    btn.style.border = '';
  };
  recognition.start();
}

// Hover effect FAB
const _fab = document.getElementById('fabComandoStock');
if (_fab) {
  _fab.addEventListener('mouseenter', () => {
    _fab.style.transform = 'scale(1.05)';
    _fab.style.boxShadow = '0 6px 24px rgba(0,0,0,0.5)';
  });
  _fab.addEventListener('mouseleave', () => {
    _fab.style.transform = '';
    _fab.style.boxShadow = '0 4px 16px rgba(0,0,0,0.4)';
  });
}
