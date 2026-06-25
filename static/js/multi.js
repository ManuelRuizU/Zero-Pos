/* ═════════════════════════════════════════════════════════════
   ZERO POS — multi.js
   Lógica de multi.html
   Nota: fmt() viene de zero-utils.js (window.fmt)
   ═════════════════════════════════════════════════════════════ */

async function init() {
  const me = await fetch('/api/auth/me',{credentials:'include'}).then(r=>r.json()).catch(()=>null);
  if (!me||me.error||me.rol!=='admin') { location.href='login.html'; return; }
  cargar();
}

async function cargar() {
  const sucursales = await fetch('/api/sucursales',{credentials:'include'}).then(r=>r.json()).catch(()=>[]);
  const grid = document.getElementById('gridSucursales');
  if (!sucursales.length) {
    grid.innerHTML='<p style="color:var(--text-dim);font-size:13px">No hay sucursales registradas.</p>';
    return;
  }
  grid.innerHTML='';
  for (const s of sucursales) {
    const res = await fetch(`/api/sucursales/${s.id}/resumen`,{credentials:'include'}).then(r=>r.json()).catch(()=>({ventas_hoy:{num:0,total:0},productos_activos:0}));
    const div = document.createElement('div');
    div.className='suc-card';
    div.innerHTML=`
      <div class="suc-nombre">🏪 ${s.nombre}</div>
      <div class="suc-dir">${s.direccion||'Sin dirección'}</div>
      <div class="kpi-row">
        <div class="kpi-mini"><div class="val">${res.ventas_hoy.num}</div><div class="lbl">Ventas hoy</div></div>
        <div class="kpi-mini"><div class="val">${fmt(res.ventas_hoy.total)}</div><div class="lbl">Recaudado</div></div>
        <div class="kpi-mini"><div class="val">${res.productos_activos}</div><div class="lbl">Productos</div></div>
      </div>
    `;
    grid.appendChild(div);
  }
}

async function sincronizar() {
  const r = await fetch('/api/sucursales/sincronizar',{method:'POST',credentials:'include'}).then(r=>r.json());
  alert(r.ok ? '✓ Sincronización completada' : 'Error: ' + r.error);
}

function abrirModal() { document.getElementById('modal').classList.add('active'); }
function cerrarModal() { document.getElementById('modal').classList.remove('active'); }

async function guardar() {
  const nombre = document.getElementById('sNombre').value.trim();
  if (!nombre) { alert('Nombre requerido'); return; }
  const r = await fetch('/api/sucursales',{
    method:'POST',credentials:'include',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({nombre, direccion:document.getElementById('sDireccion').value, telefono:document.getElementById('sTelefono').value})
  });
  if (r.ok) { cerrarModal(); cargar(); }
}

document.addEventListener('keydown',e=>{ if(e.key==='Escape') cerrarModal(); });
init();


if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', {scope: '/'})
      .catch(err => console.log('SW error:', err));
  });
}
