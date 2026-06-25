/* ═════════════════════════════════════════════════════════════
   ZERO POS — credit.js
   Lógica del portal ZERO CREDIT (credit.html)
   Depende de: zero-utils.js, zero-temas.js
   ═════════════════════════════════════════════════════════════ */

function escH(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

  function showToast(msg, tipo='ok') {
    const t = document.getElementById('toast');
    t.textContent = msg; t.className = `toast show ${tipo}`;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => { t.className = 'toast'; }, 3200);
  }

  let _clienteActual = null;
  let _todosClientes = [];

  function showTab(tab) {
    ['resumen','clientes','vencidos'].forEach(t => {
      document.getElementById('tab-' + t).style.display = t === tab ? '' : 'none';
      document.getElementById('tab-' + t + '-btn').classList.toggle('active', t === tab);
    });
    if (tab === 'resumen') cargarResumen();
    if (tab === 'clientes') cargarClientes();
    if (tab === 'vencidos') cargarVencidos();
  }

  async function cargarResumen() {
    const r = await fetch('/api/fiado/resumen',{credentials:'include'}).then(r=>r.json()).catch(()=>({}));
    document.getElementById('kpiDeuda').textContent = fmt(r.total_deuda||0);
    document.getElementById('kpiClientes').textContent = r.total_clientes||0;
    document.getElementById('kpiVencidos').textContent = r.vencidos||0;
    document.getElementById('kpiCobrado').textContent = fmt(r.cobrado_hoy||0);
    if ((r.vencidos||0) > 0) {
      const venc = await fetch('/api/fiado/clientes?estado=vencido',{credentials:'include'}).then(r=>r.json()).catch(()=>[]);
      document.getElementById('listaVencidosResumen').innerHTML = `
        <div style="margin-top:16px">
          <h3 style="color:var(--danger,#ef4444);font-size:14px;margin-bottom:10px">⚠️ Clientes con deuda vencida</h3>
          ${renderClientesList(venc.slice(0,5))}
        </div>`;
    } else {
      document.getElementById('listaVencidosResumen').innerHTML = '';
    }
  }

  async function cargarClientes() {
    _todosClientes = await fetch('/api/fiado/clientes',{credentials:'include'}).then(r=>r.json()).catch(()=>[]);
    document.getElementById('listaClientes').innerHTML = renderClientesList(_todosClientes);
  }

  async function cargarVencidos() {
    const venc = await fetch('/api/fiado/clientes?estado=vencido',{credentials:'include'}).then(r=>r.json()).catch(()=>[]);
    document.getElementById('listaVencidos').innerHTML = venc.length
      ? renderClientesList(venc, true)
      : '<p style="color:var(--text-dim);text-align:center;padding:40px">✅ Sin fiados vencidos</p>';
  }

  function renderClientesList(clientes, showWA=false) {
    if (!clientes.length) return '<p style="color:var(--text-dim);padding:20px">Sin clientes</p>';
    return clientes.map(c => {
      const estadoColor = c.estado==='vencido'?'var(--danger,#ef4444)':c.estado==='por_vencer'?'var(--warning,#f59e0b)':'var(--success,#22c55e)';
      const estadoLabel = c.estado==='vencido'?'⚠️ Vencido':c.estado==='por_vencer'?'⏰ Por vencer':'✅ Al día';
      const diasLabel = c.dias_restantes != null ? (c.dias_restantes < 0 ? `Hace ${-c.dias_restantes}d` : `${c.dias_restantes}d`) : '';
      const avatar = c.nombre[0].toUpperCase();
      const bgColor = typeof colorAvatar === 'function' ? colorAvatar(c.nombre) : '#6366f1';
      const waMsg = encodeURIComponent(`Hola ${c.nombre}, te recordamos que tienes una deuda de $${(c.deuda_actual||0).toLocaleString('es-CL')} pendiente. Por favor pasa a regularizar. ¡Gracias!`);
      return `
        <div class="cliente-item" onclick="abrirCliente(${c.id})">
          <div class="avatar" style="background:${bgColor}">${avatar}</div>
          <div style="flex:1;min-width:0">
            <div style="font-weight:600">${escH(c.nombre)} ${escH(c.apellido||'')}</div>
            <div style="font-size:12px;color:var(--text-dim)">Deuda: <strong>$${(c.deuda_actual||0).toLocaleString('es-CL')}</strong>${diasLabel ? ` · ${diasLabel}` : ''}</div>
          </div>
          <div style="display:flex;align-items:center;gap:6px">
            <span class="badge-estado" style="background:${estadoColor}22;color:${estadoColor}">${estadoLabel}</span>
            ${showWA && c.telefono ? `<button onclick="event.stopPropagation();window.open('https://wa.me/56${c.telefono.replace(/[^0-9]/g,'')}?text=${waMsg}')" style="background:none;border:none;cursor:pointer;font-size:18px;padding:4px" title="WhatsApp">📱</button>` : ''}
          </div>
        </div>`;
    }).join('');
  }

  function filtrarClientes(q) {
    const lower = q.toLowerCase();
    const filtered = _todosClientes.filter(c =>
      (c.nombre||'').toLowerCase().includes(lower) ||
      (c.apellido||'').toLowerCase().includes(lower) ||
      (c.telefono||'').includes(q)
    );
    document.getElementById('listaClientes').innerHTML = renderClientesList(filtered);
  }

  async function abrirCliente(id) {
    const c = await fetch(`/api/fiado/clientes/${id}`,{credentials:'include'}).then(r=>r.json()).catch(()=>null);
    if (!c) { showToast('Error al cargar cliente', 'error'); return; }
    _clienteActual = c;

    document.getElementById('modalCliente')?.remove();

    const barColor   = c.estado==='vencido'?'#ef4444':c.pct_usado>=80?'#f97316':c.pct_usado>=50?'#f59e0b':'#22c55e';
    const estadoColor = c.estado==='vencido'?'#ef4444':c.estado==='por_vencer'?'#f59e0b':'#22c55e';
    const estadoLabel = c.estado==='vencido'?'⚠️ Vencido':c.estado==='por_vencer'?'⏰ Por vencer':'✅ Al día';
    const avatarBg   = typeof colorAvatar==='function' ? colorAvatar(c.nombre) : '#6366f1';
    const initial    = c.nombre.charAt(0).toUpperCase();

    const movs = (c.movimientos||[]).map(m => {
      const monto = m.tipo==='cargo'
        ? `<span style="color:#ef4444;font-weight:700;">+${fmt(m.monto)}</span>`
        : `<span style="color:#22c55e;font-weight:700;">-${fmt(m.monto)}</span>`;
      const fecha = m.creado_en
        ? new Date(m.creado_en).toLocaleDateString('es-CL',{day:'2-digit',month:'2-digit'})
        : '';
      return `<div style="display:flex;justify-content:space-between;align-items:center;
                          padding:9px 0;border-bottom:1px solid var(--border,#2a2a3a);">
        <div style="font-size:13px;line-height:1.4;">
          <span>${m.tipo==='cargo'?'🔴':'🟢'} ${m.tipo.charAt(0).toUpperCase()+m.tipo.slice(1)}</span>
          ${m.descripcion?`<span style="color:var(--text-dim,#888);"> — ${escH(m.descripcion)}</span>`:''}
          ${fecha?`<div style="font-size:11px;color:var(--text-dim,#888);">${fecha}</div>`:''}
        </div>
        ${monto}
      </div>`;
    }).join('');

    const modal = document.createElement('div');
    modal.id = 'modalCliente';
    modal.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;flex-direction:column;justify-content:flex-end;';

    modal.innerHTML = `
      <div onclick="cerrarModalCliente()"
           style="position:absolute;inset:0;background:rgba(0,0,0,0.65);backdrop-filter:blur(4px);"></div>

      <div id="panelClienteSheet" onclick="event.stopPropagation()"
           style="position:relative;background:var(--surface,#1e1e2e);
                  border-radius:20px 20px 0 0;max-height:90vh;
                  display:flex;flex-direction:column;z-index:1;
                  transform:translateY(100%);transition:transform .3s cubic-bezier(.05,.7,.1,1);">

        <!-- Drag handle -->
        <div style="width:40px;height:4px;background:var(--border,#333);border-radius:2px;
                    margin:12px auto 0;flex-shrink:0;"></div>

        <!-- Header fijo -->
        <div style="display:flex;align-items:center;justify-content:space-between;
                    padding:12px 16px 14px;border-bottom:1px solid var(--border,#2a2a3a);flex-shrink:0;">
          <div style="display:flex;align-items:center;gap:10px;min-width:0;">
            <div style="width:44px;height:44px;border-radius:50%;background:${avatarBg};
                        display:flex;align-items:center;justify-content:center;
                        font-size:20px;font-weight:700;color:#fff;flex-shrink:0;">
              ${initial}
            </div>
            <div style="min-width:0;">
              <div style="font-weight:700;font-size:16px;line-height:1.2;
                          white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                ${escH(c.nombre)} ${escH(c.apellido||'')}
              </div>
              <span style="font-size:11px;background:${estadoColor}22;color:${estadoColor};
                           padding:2px 9px;border-radius:20px;font-weight:600;
                           display:inline-block;margin-top:4px;">
                ${estadoLabel}
              </span>
            </div>
          </div>
          <button onclick="cerrarModalCliente()"
                  style="width:34px;height:34px;border-radius:50%;flex-shrink:0;
                         background:var(--surface2,#252540);border:1px solid var(--border,#333);
                         color:var(--text,#fff);font-size:20px;cursor:pointer;
                         display:flex;align-items:center;justify-content:center;
                         line-height:1;margin-left:8px;">×</button>
        </div>

        <!-- Contenido scrolleable -->
        <div style="overflow-y:auto;flex:1;padding:16px;-webkit-overflow-scrolling:touch;">

          <!-- KPIs -->
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;">
            <div style="background:var(--surface2,#252540);border-radius:12px;padding:14px;">
              <div style="font-size:11px;color:var(--text-dim,#888);text-transform:uppercase;
                          letter-spacing:.4px;margin-bottom:4px;">Deuda</div>
              <div style="font-size:22px;font-weight:800;color:${barColor};">${fmt(c.deuda_actual||0)}</div>
            </div>
            <div style="background:var(--surface2,#252540);border-radius:12px;padding:14px;">
              <div style="font-size:11px;color:var(--text-dim,#888);text-transform:uppercase;
                          letter-spacing:.4px;margin-bottom:4px;">Disponible</div>
              <div style="font-size:22px;font-weight:800;color:#22c55e;">${fmt(c.disponible||0)}</div>
            </div>
          </div>

          <!-- Barra uso -->
          <div style="background:var(--surface2,#252540);border-radius:6px;height:8px;
                      overflow:hidden;margin-bottom:6px;">
            <div style="height:100%;width:${c.pct_usado||0}%;background:${barColor};
                        border-radius:6px;transition:width .6s;"></div>
          </div>
          <div style="font-size:12px;color:var(--text-dim,#888);margin-bottom:16px;">
            ${c.pct_usado||0}% usado · Límite ${fmt(c.limite_credito||0)}
            ${c.dias_restantes!=null ? ` · ${c.dias_restantes<0?`Venció hace ${-c.dias_restantes}d`:`Vence en ${c.dias_restantes}d`}` : ''}
          </div>

          <!-- Info de contacto -->
          ${(c.telefono||c.proximo_vencimiento||c.notas) ? `
          <div style="background:var(--surface2,#252540);border-radius:10px;padding:12px;
                      margin-bottom:16px;font-size:13px;color:var(--text-dim,#aaa);
                      display:flex;flex-direction:column;gap:5px;">
            ${c.telefono?`<span>📞 ${escH(c.telefono)}</span>`:''}
            ${c.proximo_vencimiento?`<span>📅 Vence: ${c.proximo_vencimiento}</span>`:''}
            ${c.notas?`<span>📝 ${escH(c.notas)}</span>`:''}
          </div>` : ''}

          <!-- Movimientos -->
          <div style="font-size:11px;font-weight:700;color:var(--text-dim,#888);
                      text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;">
            Últimos movimientos
          </div>
          ${movs || '<div style="color:var(--text-dim,#888);font-size:13px;padding:8px 0;">Sin movimientos</div>'}
        </div>

        <!-- Footer fijo -->
        <div style="display:flex;gap:8px;padding:12px 16px;
                    border-top:1px solid var(--border,#2a2a3a);flex-shrink:0;
                    background:var(--surface,#1e1e2e);">
          <button id="btnReimprimirTarjeta" onclick="reimprimirTarjeta()"
                  style="flex:1;padding:13px 8px;background:var(--surface2,#252540);
                         color:var(--text,#fff);border:1px solid var(--border,#333);
                         border-radius:10px;cursor:pointer;font-size:13px;font-weight:600;">
            🖨️ Reimprimir
          </button>
          <button onclick="abrirModalAbono()"
                  style="flex:2;padding:13px;background:var(--accent,#6366f1);
                         color:#fff;border:none;border-radius:10px;
                         cursor:pointer;font-size:14px;font-weight:700;">
            💳 Registrar abono
          </button>
        </div>
      </div>
    `;

    document.body.appendChild(modal);
    document.body.style.overflow = 'hidden';

    // Slide-up animation
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const panel = document.getElementById('panelClienteSheet');
      if (panel) panel.style.transform = 'translateY(0)';
    }));
  }

  window.cerrarModalCliente = function() {
    const modal = document.getElementById('modalCliente');
    if (!modal) return;
    const panel = document.getElementById('panelClienteSheet');
    document.body.style.overflow = '';
    _clienteActual = null;
    if (document.activeElement) document.activeElement.blur();
    if (panel) {
      panel.style.transition = 'transform .25s cubic-bezier(.32,0,.67,0)';
      panel.style.transform = 'translateY(100%)';
      setTimeout(() => modal.remove(), 260);
    } else {
      modal.remove();
    }
  }

  window.abrirModalAbono = function() {
    if (!_clienteActual) return;
    document.getElementById('abonoMonto').value = '';
    document.getElementById('abonoDesc').value = '';
    document.getElementById('modalAbono').classList.add('active');
  }

  async function confirmarAbono() {
    if (!_clienteActual) return;
    const monto = parseInt(document.getElementById('abonoMonto').value) || 0;
    const desc = document.getElementById('abonoDesc').value.trim() || 'Abono en tienda';
    if (monto <= 0) { showToast('Ingresa un monto válido', 'error'); return; }
    const r = await fetch('/api/fiado/abono', {
      method:'POST', credentials:'include',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({cliente_id: _clienteActual.id, monto, descripcion: desc})
    }).then(r=>r.json()).catch(()=>({error:'Error de conexión'}));
    if (r.ok) {
      showToast(`✓ Abono registrado — deuda nueva: ${fmt(r.deuda_nueva)}`);
      document.getElementById('modalAbono').classList.remove('active');
      cerrarModalCliente();
      const tabClientes = document.getElementById('tab-clientes');
      if (tabClientes && tabClientes.style.display !== 'none') cargarClientes();
      cargarResumen();
    } else {
      showToast(r.error || 'Error', 'error');
    }
  }

  function setLimite(n) { document.getElementById('ncLimite').value = n; }

  async function crearCliente() {
    const nombre = document.getElementById('ncNombre').value.trim();
    const tel = document.getElementById('ncTelefono').value.trim();
    if (!nombre || !tel) { showToast('Nombre y teléfono requeridos', 'error'); return; }
    const payload = {
      nombre,
      apellido: document.getElementById('ncApellido').value.trim(),
      telefono: tel,
      limite_credito: parseInt(document.getElementById('ncLimite').value)||10000,
      frecuencia_pago: document.getElementById('ncFrecuencia').value,
      notas: document.getElementById('ncNotas').value.trim()
    };
    const r = await fetch('/api/fiado/clientes', {
      method:'POST', credentials:'include',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)
    }).then(res=>res.json()).catch(()=>({error:'Error de conexión'}));
    if (r.id) {
      document.getElementById('modalNuevoCliente').classList.remove('active');
      document.getElementById('ncNombre').value = '';
      document.getElementById('ncApellido').value = '';
      document.getElementById('ncTelefono').value = '';
      document.getElementById('ncNotas').value = '';
      showToast(`✓ ${escH(nombre)} creado — QR listo`);
      if (r.qr_imagen) {
        const w = window.open('','_blank','width=420,height=520');
        if (w) {
          w.document.write(`<html><head><title>ZERO CREDIT — ${escH(r.nombre)}</title></head><body style="text-align:center;font-family:sans-serif;padding:20px;background:#fff">
            <h2 style="margin-bottom:4px">ZERO CREDIT</h2>
            <h3 style="margin-top:0">${escH(r.nombre)} ${escH(r.apellido||'')}</h3>
            <img src="data:image/png;base64,${r.qr_imagen}" style="width:200px;height:200px">
            <p>Límite: ${fmt(r.limite_credito)}</p>
            <p style="font-size:12px"><a href="${r.url_portal}">${r.url_portal}</a></p>
            <button onclick="window.print()" style="padding:10px 20px;background:#6366f1;color:white;border:none;border-radius:8px;cursor:pointer;font-size:14px">Imprimir tarjeta</button>
          <script src="/static/js/credit.js"></script>
</body></html>`);
          w.document.close();
        }
      }
      cargarClientes();
      cargarResumen();
    } else {
      showToast(r.error || 'Error al crear', 'error');
    }
  }

  async function reimprimirTarjeta() {
    if (!_clienteActual) return;
    const btn = document.getElementById('btnReimprimirTarjeta');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Generando…'; btn.style.background = ''; }

    try {
      const r = await fetch(`/api/fiado/clientes/${_clienteActual.id}/tarjeta`, {
        method: 'POST', credentials: 'include'
      }).then(res => res.json());

      if (!r.qr_imagen) throw new Error('Sin QR');

      // Popup para imprimir manualmente
      const w = window.open('', '_blank', 'width=420,height=560');
      if (w) {
        w.document.write(`<!DOCTYPE html><html><head><title>ZERO CREDIT — ${escH(_clienteActual.nombre)}</title></head>
          <body style="text-align:center;font-family:sans-serif;padding:20px;background:#fff">
            <h2 style="margin-bottom:4px">ZERO CREDIT</h2>
            <h3 style="margin-top:0">${escH(_clienteActual.nombre)} ${escH(_clienteActual.apellido||'')}</h3>
            <img src="data:image/png;base64,${r.qr_imagen}" style="width:200px;height:200px;display:block;margin:0 auto">
            <p style="font-size:14px">Límite: ${fmt(_clienteActual.limite_credito||0)}</p>
            <p style="font-size:11px;word-break:break-all"><a href="${r.url_portal}">${r.url_portal}</a></p>
            <button onclick="window.print()" style="padding:10px 20px;background:#6366f1;color:white;border:none;border-radius:8px;cursor:pointer;font-size:14px;margin-top:8px">🖨️ Imprimir</button>
          <script src="/static/js/credit.js"></script>
</body></html>`);
        w.document.close();
      }

      // Impresora térmica (silenciosa)
      fetch(`/api/fiado/clientes/${_clienteActual.id}/imprimir_tarjeta`, {
        method: 'POST', credentials: 'include'
      }).then(res => res.json()).then(res => {
        if (res.ok) showToast('✓ Tarjeta enviada a impresora térmica');
      }).catch(() => {});

      if (btn) { btn.textContent = '✅ Impreso'; btn.style.background = '#22c55e'; }

    } catch(e) {
      showToast('Error al obtener tarjeta', 'error');
      if (btn) { btn.textContent = '❌ Error'; btn.style.background = '#ef4444'; }

    } finally {
      setTimeout(() => {
        if (btn) {
          btn.disabled = false;
          btn.textContent = '🖨️ Reimprimir tarjeta';
          btn.style.background = '';
        }
      }, 2000);
    }
  }

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      cerrarModalCliente();
      document.getElementById('modalAbono').classList.remove('active');
      document.getElementById('modalNuevoCliente').classList.remove('active');
    }
  });

  // Init
  (async () => {
    const me = await fetch('/api/auth/me',{credentials:'include'}).then(r=>r.json()).catch(()=>null);
    if (!me || me.error) { location.href='login.html'; return; }
    showTab('resumen');
  })();
