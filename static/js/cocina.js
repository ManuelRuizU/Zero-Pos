/* ═════════════════════════════════════════════════════════════
   ZERO POS — cocina.js
   Lógica de cocina.html
   ═════════════════════════════════════════════════════════════ */

function reloj() {
  document.getElementById('reloj').textContent = new Date().toLocaleTimeString('es-CL');
}
setInterval(reloj, 1000);
reloj();

async function cargarPedidos() {
  try {
    const ventas = await fetch('/api/ventas?limite=20', {credentials:'include'}).then(r=>r.json());
    const hoy = ventas.filter(v => v.estado==='completada' && v.creado_en?.startsWith(new Date().toISOString().substring(0,10)));
    const cola = document.getElementById('cola');
    if (!hoy.length) {
      cola.innerHTML='<div class="empty"><div style="font-size:48px;margin-bottom:12px">🍳</div><div>Sin pedidos pendientes</div></div>';
      return;
    }
    cola.innerHTML = hoy.slice(0,12).map(v=>`
      <div class="pedido" id="p${v.id}">
        <div class="pedido-header">
          <span class="pedido-num">Pedido #${v.id}</span>
          <span class="pedido-hora">${v.creado_en?.substring(11,16)||''}</span>
        </div>
        <div class="pedido-items">
          <div class="item-linea"><span class="item-qty">⏳</span> ${v.total?.toLocaleString('es-CL')} — ${v.metodo_pago}</div>
        </div>
        <div class="pedido-footer">
          <button class="btn-accion btn-listo" onclick="marcarListo(${v.id})">✓ Listo</button>
        </div>
      </div>`).join('');
  } catch(e) {}
}

function marcarListo(id) {
  const el = document.getElementById('p'+id);
  if (el) { el.classList.add('listo'); setTimeout(()=>el.remove(), 2000); }
}

async function init() {
  const me = await fetch('/api/auth/me',{credentials:'include'}).then(r=>r.json()).catch(()=>null);
  if (!me||me.error) { location.href='login.html'; return; }
  cargarPedidos();
  setInterval(cargarPedidos, 15000);
}

init();


if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', {scope: '/'})
      .catch(err => console.log('SW error:', err));
  });
}
