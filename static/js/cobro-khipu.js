/* ═════════════════════════════════════════════════════════════
   ZERO POS — cobro-khipu.js
   Lógica de cobro-khipu.html
   ═════════════════════════════════════════════════════════════ */

const params = new URLSearchParams(location.search);
const monto = parseFloat(params.get('monto')||0);
const paymentUrl = params.get('url')||'';
const paymentId = params.get('pid')||'';

document.getElementById('montoDisplay').textContent = '$' + Math.round(monto).toLocaleString('es-CL');
if (paymentUrl) document.getElementById('btnPagar').href = paymentUrl;

async function verificar() {
  if (!paymentId) return;
  try {
    const r = await fetch(`/api/khipu/verificar/${paymentId}`,{credentials:'include'}).then(r=>r.json());
    const div = document.getElementById('estadoDiv');
    const txt = document.getElementById('estadoTexto');
    if (r.estado==='done'||r.estado==='pagado') {
      div.className='estado pagado';
      txt.textContent='✓ Pago confirmado';
      setTimeout(()=>cerrar(), 3000);
    } else {
      txt.textContent='Estado: ' + (r.estado||'pendiente');
    }
  } catch(e) {}
}

function cerrar() {
  if (window.opener) window.close();
  else history.back();
}

if (paymentId) setInterval(verificar, 5000);


if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', {scope: '/'})
      .catch(err => console.log('SW error:', err));
  });
}
