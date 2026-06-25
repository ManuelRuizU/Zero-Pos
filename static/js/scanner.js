/* ═════════════════════════════════════════════════════════════
   ZERO POS — scanner.js
   Lógica de scanner.html
   ═════════════════════════════════════════════════════════════ */

let productoEncontrado = null;

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
}

function irAPos() {
  if (productoEncontrado) {
    sessionStorage.setItem('scan_product', JSON.stringify(productoEncontrado));
  }
  location.href='pos.html';
}

iniciarCamara();


if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', {scope: '/'})
      .catch(err => console.log('SW error:', err));
  });
}
