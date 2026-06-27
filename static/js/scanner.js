/* ═════════════════════════════════════════════════════════════
   ZERO POS — scanner.js
   Lógica de scanner.html
   ═════════════════════════════════════════════════════════════ */

let productoEncontrado = null;
window._carrito = {};

async function iniciarCamara() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'}});
    document.getElementById('video').srcObject = stream;
  } catch(e) {
    document.getElementById('video').style.display='none';
    document.getElementById('msg').textContent='Cámara no disponible — usa el campo manual';
  }
}

async function buscarCodigo() {
  const codigo = document.getElementById('codigoInput').value.trim();
  if (!codigo) return;
  try {
    const r = await fetch(`/api/productos/barras/${encodeURIComponent(codigo)}`,{credentials:'include'});
    if (r.ok) {
      const p = await r.json();
      mostrarProducto(p);
    } else {
      document.getElementById('resultado').style.display='none';
      document.getElementById('msg').textContent='Código no encontrado: ' + codigo;
    }
  } catch(e) {
    document.getElementById('msg').textContent='Error de conexión';
  }
}

function mostrarProducto(p) {
  productoEncontrado = p;
  document.getElementById('resNombre').textContent = p.nombre;
  document.getElementById('resPrecio').textContent = '$' + Math.round(p.precio).toLocaleString('es-CL');
  document.getElementById('resStock').textContent = `Stock: ${p.stock}`;
  document.getElementById('resultado').style.display='block';
  document.getElementById('msg').textContent='';
  const yaEnCarrito = window._carrito[p.id];
  mostrarToastScanner(p.nombre, yaEnCarrito ? yaEnCarrito.cantidad + 1 : 1);
}

function agregarYContinuar() {
  if (!productoEncontrado) return;
  const id = productoEncontrado.id;
  if (window._carrito[id]) {
    window._carrito[id].cantidad++;
  } else {
    window._carrito[id] = { ...productoEncontrado, cantidad: 1 };
  }
  actualizarBadgeScanner();
  document.getElementById('resultado').style.display = 'none';
  document.getElementById('codigoInput').value = '';
  document.getElementById('codigoInput').focus();
  productoEncontrado = null;
}

function irAPos() {
  const items = Object.values(window._carrito || {});
  if (items.length > 0) {
    sessionStorage.setItem('scan_products', JSON.stringify(items));
  } else if (productoEncontrado) {
    sessionStorage.setItem('scan_product', JSON.stringify(productoEncontrado));
  }
  location.href = 'pos.html';
}

function mostrarToastScanner(nombre, cantidad) {
  const toast = document.getElementById('scannerToast');
  if (!toast) return;
  toast.textContent = `✅ ${nombre} ×${cantidad}`;
  toast.classList.add('show');
  clearTimeout(window._scanToastTimer);
  window._scanToastTimer = setTimeout(() => {
    toast.classList.remove('show');
  }, 2000);
}

function actualizarBadgeScanner() {
  const badge = document.getElementById('scannerBadge');
  if (!badge) return;
  const items = Object.values(window._carrito || {});
  const total = items.reduce((s, i) => s + i.precio * i.cantidad, 0);
  const count = items.reduce((s, i) => s + i.cantidad, 0);
  if (count > 0) {
    badge.textContent = `🛒 ${count} · $${fmt(total)}`;
    badge.style.display = 'flex';
  } else {
    badge.style.display = 'none';
  }
}

iniciarCamara();


if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', {scope: '/'})
      .catch(err => console.log('SW error:', err));
  });
}
