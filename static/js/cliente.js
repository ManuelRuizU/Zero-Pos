/* ═════════════════════════════════════════════════════════════
   ZERO POS — cliente.js
   Lógica de cliente.html
   Depende de: qrcode.min.js
   ═════════════════════════════════════════════════════════════ */

/* ═══════════════════════════════════════════════════════════
   HELPERS
══════════════════════════════════════════════════════════ */
window.fmt = window.fmt || (n => '$' + (Math.round(Number(n)) || 0).toLocaleString('es-CL'));

/* ═══════════════════════════════════════════════════════════
   CARRUSEL PUBLICIDAD
══════════════════════════════════════════════════════════ */
class CarruselPublicidad {
  constructor(contenedor, slides, opciones = {}) {
    this.contenedor = contenedor;
    this.slides = slides;
    this.indice = 0;
    this.duracion = (opciones.duracion || 5) * 1000;
    this.transicion = opciones.transicion || 'kenburns';
    this.intervalo = null;
    this.slideActual = null;
    this._iniciado = false;
  }

  iniciar() {
    if (this._iniciado) return;
    this._iniciado = true;
    if (!this.slides.length) return;
    this.contenedor.innerHTML = '';
    this._renderSlide(0);
    this.intervalo = setInterval(() => this._siguiente(), this.duracion);
    this._actualizarIndicadores();
  }

  detener() {
    clearInterval(this.intervalo);
    this.intervalo = null;
    this._iniciado = false;
  }

  reiniciar(slides, opciones = {}) {
    this.detener();
    this.slides = slides;
    this.indice = 0;
    this.duracion = (opciones.duracion || this.duracion / 1000) * 1000;
    this.contenedor.innerHTML = '';
    this.slideActual = null;
    this.iniciar();
  }

  _renderSlide(idx) {
    const s = this.slides[idx];

    if (s.plantilla_id) {
      // Renderizado con plantilla HTML en iframe
      const iframe = document.createElement('iframe');
      iframe.className = 'slide-iframe';
      iframe.src = `/static/plantillas_publicidad/${s.plantilla_id}.html`;
      iframe.setAttribute('sandbox', 'allow-scripts allow-same-origin');
      iframe.setAttribute('loading', 'eager');
      this.contenedor.appendChild(iframe);

      let _enviado = false;
      const _enviarDatos = () => {
        if (_enviado) return;
        _enviado = true;
        let datos = {};
        try { datos = JSON.parse(s.datos_plantilla || '{}'); } catch(e) {}
        iframe.contentWindow.postMessage({
          tipo: 'slide-data',
          titulo:    s.titulo    || '',
          subtitulo: s.subtitulo || '',
          imagen_url: s.imagen_url || null,
          color:  s.color  || '#22c55e',
          color2: s.color2 || '#22c55e',
          datos,
        }, '*');
      };

      iframe.addEventListener('load', () => {
        setTimeout(_enviarDatos, 100);
        requestAnimationFrame(() => iframe.classList.add('visible'));
      });
      requestAnimationFrame(() => { if (!iframe.classList.contains('visible')) iframe.classList.add('visible'); });
      this.slideActual = iframe;
      return;
    }

    // Modo simple (sin plantilla)
    const el = document.createElement('div');
    el.className = 'slide-pub';

    if (s.imagen_url) {
      el.style.backgroundImage = `url(${s.imagen_url})`;
      if (this.transicion === 'kenburns') {
        el.style.animation = `kenBurns${idx % 2 === 0 ? '' : '2'} ${this.duracion}ms ease-out forwards`;
      }
    } else {
      el.style.background = `linear-gradient(135deg, ${s.color || '#22c55e'}, ${s.color2 || '#22c55e'})`;
    }

    const overlay = document.createElement('div');
    overlay.className = 'slide-overlay';
    el.appendChild(overlay);

    if (s.titulo || s.subtitulo) {
      const texto = document.createElement('div');
      texto.className = 'slide-texto';
      if (s.titulo)    texto.innerHTML += `<div class="slide-titulo">${_esc(s.titulo)}</div>`;
      if (s.subtitulo) texto.innerHTML += `<div class="slide-subtitulo">${_esc(s.subtitulo)}</div>`;
      el.appendChild(texto);
    }

    this.contenedor.appendChild(el);
    requestAnimationFrame(() => el.classList.add('visible'));
    this.slideActual = el;
  }

  _siguiente() {
    const anterior = this.slideActual;
    this.indice = (this.indice + 1) % this.slides.length;
    this._renderSlide(this.indice);
    this._actualizarIndicadores();
    if (anterior) {
      setTimeout(() => {
        anterior.classList.remove('visible');
        setTimeout(() => anterior.remove(), 900);
      }, 100);
    }
  }

  _actualizarIndicadores() {
    const cont = document.getElementById('indicadoresCarrusel');
    if (!cont) return;
    cont.innerHTML = this.slides.map((_, i) => {
      const cls = i === this.indice ? ' activo' : '';
      const w = i === this.indice ? '24px' : '8px';
      return `<div class="ind-dot${cls}" style="width:${w}"></div>`;
    }).join('');
  }
}

function _esc(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/* ═══════════════════════════════════════════════════════════
   ESTADO DE PANTALLA
══════════════════════════════════════════════════════════ */
let carruselIdle = null;
let carruselVenta = null;
let estadoActual = 'idle';
let _pagadoTimer = null;
let _negocioNombre = 'ZERO POS';
let _slidesActuales = [];
let _qrInstance    = null;
let _linkPagoActual = null;

function _setEstado(nombre) {
  document.querySelectorAll('.estado').forEach(el => el.classList.remove('activo'));
  const el = document.getElementById('estado' + nombre.charAt(0).toUpperCase() + nombre.slice(1));
  if (el) el.classList.add('activo');
  estadoActual = nombre;
}

function mostrarEstadoIdle() {
  _setEstado('idle');
  if (carruselIdle && !carruselIdle._iniciado) carruselIdle.iniciar();
  if (carruselVenta) carruselVenta.detener();
}

function mostrarEstadoVenta() {
  _setEstado('venta');
  if (carruselIdle) carruselIdle.detener();
  if (carruselVenta && !carruselVenta._iniciado) carruselVenta.iniciar();
}

function mostrarEstadoGracias(total, vuelto) {
  _setEstado('gracias');
  document.getElementById('montoGracias').textContent = `Total: ${fmt(total)}`;
  const vueltoEl = document.getElementById('vueltoGracias');
  if (vuelto > 0) {
    vueltoEl.style.display = 'block';
    vueltoEl.textContent = `Vuelto: ${fmt(vuelto)}`;
  } else {
    vueltoEl.style.display = 'none';
  }
  setTimeout(() => {
    mostrarEstadoIdle();
  }, 3000);
}

function mostrarQRPago(linkPago, total) {
  document.getElementById('clienteTotalTarjeta').textContent =
    '$' + (Math.round(Number(total)) || 0).toLocaleString('es-CL');

  const canvas = document.getElementById('clienteQRCanvas');

  if (linkPago !== _linkPagoActual) {
    _linkPagoActual = linkPago;
    canvas.innerHTML = '';
    if (linkPago && typeof QRCode !== 'undefined') {
      _qrInstance = new QRCode(canvas, {
        text:         linkPago,
        width:        240,
        height:       240,
        colorDark:    '#000000',
        colorLight:   '#ffffff',
        correctLevel: QRCode.CorrectLevel.M,
      });
    } else if (linkPago) {
      canvas.innerHTML = `<div style="font-size:11px;color:#000;padding:8px;word-break:break-all;max-width:240px">${linkPago}</div>`;
    }
  }

  _setEstado('cobrarTarjeta');
  if (carruselIdle)  carruselIdle.detener();
  if (carruselVenta) carruselVenta.detener();
}

/* ═══════════════════════════════════════════════════════════
   ACTUALIZAR DATOS DE VENTA
══════════════════════════════════════════════════════════ */
function actualizarDatosVenta(data) {
  // Nombre negocio
  document.getElementById('nombreNegocioVenta').textContent = _negocioNombre;

  // Total
  const totalEl = document.getElementById('totalVenta');
  if (totalEl) {
    const nuevoTotal = fmt(data.total || 0);
    if (totalEl.textContent !== nuevoTotal) {
      totalEl.style.transform = 'scale(1.05)';
      totalEl.textContent = nuevoTotal;
      setTimeout(() => { totalEl.style.transform = ''; }, 200);
    }
  }

  // Último producto
  const items = data.items || [];
  if (items.length > 0) {
    const ultimo = items[items.length - 1];
    document.getElementById('nombreUltimoProducto').textContent = ultimo.nombre || '—';
    document.getElementById('precioUltimoProducto').textContent = fmt(ultimo.subtotal || 0);
    document.getElementById('cantidadUltimoProducto').textContent =
      `${ultimo.cantidad} × ${fmt(ultimo.precio_unit || 0)}`;
    const imgEl = document.getElementById('imagenUltimoProducto');
    if (ultimo.imagen_url) {
      imgEl.innerHTML = `<img src="${_esc(ultimo.imagen_url)}" alt="">`;
    } else {
      imgEl.textContent = '🛍️';
    }
  }

  // Lista items
  const listaEl = document.getElementById('listaItems');
  if (listaEl) {
    const maxItems = window.innerHeight < 700 ? 3 : 5;
    listaEl.innerHTML = items.slice(-maxItems).map(item => `
      <div class="item-fila">
        <span class="item-fila-nombre">${item.cantidad}× ${_esc(item.nombre)}</span>
        <span class="item-fila-precio">${fmt(item.subtotal || 0)}</span>
      </div>`).join('');
  }
}

/* ═══════════════════════════════════════════════════════════
   SINCRONIZACIÓN CON EL POS
══════════════════════════════════════════════════════════ */
let _estadoAnterior = null;

async function sincronizar() {
  try {
    const data = await fetch('/api/ventas/pantalla-cliente', { cache: 'no-store' })
      .then(r => r.json());

    if (data.activa && data.items && data.items.length) {
      if (_pagadoTimer) { clearTimeout(_pagadoTimer); _pagadoTimer = null; }
      if (estadoActual !== 'venta') mostrarEstadoVenta();
      actualizarDatosVenta(data);
      _estadoAnterior = 'venta';

    } else if (data.estado === 'pagado') {
      if (_estadoAnterior === 'venta' && !_pagadoTimer) {
        _pagadoTimer = setTimeout(() => {
          _pagadoTimer = null;
          _estadoAnterior = 'idle';
        }, 3500);
        mostrarEstadoGracias(data.total || 0, data.vuelto || 0);
      } else if (!_pagadoTimer && estadoActual !== 'gracias') {
        if (estadoActual !== 'idle') mostrarEstadoIdle();
      }

    } else {
      if (_pagadoTimer) { clearTimeout(_pagadoTimer); _pagadoTimer = null; }
      if (estadoActual !== 'idle' && estadoActual !== 'gracias') mostrarEstadoIdle();
      _estadoAnterior = 'idle';
    }
  } catch(e) {
    // Sin conexión → no cambiar estado
  }
}

/* ═══════════════════════════════════════════════════════════
   CARGA PUBLICIDAD
══════════════════════════════════════════════════════════ */
async function cargarPublicidad() {
  try {
    const slides = await fetch('/api/publicidad', { cache: 'no-store' }).then(r => r.json());
    const cfg = await fetch('/api/publicidad/config', { cache: 'no-store' }).then(r => r.json())
      .catch(() => ({ duracion: 5, transicion: 'kenburns' }));

    // Si son los mismos slides, no reiniciar
    const nuevosIds = JSON.stringify(slides.map(s => s.id + s.activo));
    const actualesIds = JSON.stringify(_slidesActuales.map(s => s.id + s.activo));
    if (nuevosIds === actualesIds && carruselIdle && carruselVenta) return;

    _slidesActuales = slides;
    const opciones = { duracion: cfg.duracion || 5, transicion: cfg.transicion || 'kenburns' };

    if (slides.length === 0) {
      // Mostrar placeholder
      document.getElementById('carruselPublicidad').style.visibility = 'hidden';
      document.getElementById('placeholderIdle').style.display = 'flex';
      carruselIdle = null;
      carruselVenta = null;
    } else {
      document.getElementById('carruselPublicidad').style.visibility = 'visible';
      document.getElementById('placeholderIdle').style.display = 'none';

      if (carruselIdle) {
        carruselIdle.reiniciar(slides, opciones);
      } else {
        carruselIdle = new CarruselPublicidad(
          document.getElementById('carruselPublicidad'), slides, opciones
        );
        if (estadoActual === 'idle') carruselIdle.iniciar();
      }

      if (carruselVenta) {
        carruselVenta.reiniciar(slides, opciones);
      } else {
        carruselVenta = new CarruselPublicidad(
          document.getElementById('carruselPublicidadVenta'), slides, opciones
        );
        if (estadoActual === 'venta') carruselVenta.iniciar();
      }
    }
  } catch(e) {
    // Sin slides → placeholder
    document.getElementById('placeholderIdle').style.display = 'flex';
    document.getElementById('carruselPublicidad').style.visibility = 'hidden';
  }
}

/* ═══════════════════════════════════════════════════════════
   CARGA CONFIG NEGOCIO
══════════════════════════════════════════════════════════ */
async function cargarConfigNegocio() {
  try {
    const cfg = await fetch('/api/config').then(r => r.json());
    if (cfg.nombre_negocio) {
      _negocioNombre = cfg.nombre_negocio;
      document.getElementById('nombreNegocioIdle').textContent = cfg.nombre_negocio;
      document.getElementById('nombreNegocioVenta').textContent = cfg.nombre_negocio;
    }
    if (cfg.tema_color) {
      document.documentElement.style.setProperty('--negocio-color', cfg.tema_color);
    }
    // Logo
    const logo = document.getElementById('logoNegocioIdle');
    const logoUrl = '/static/negocio/logo_ticket.png';
    const img = new Image();
    img.onload = () => { logo.src = logoUrl; logo.style.display = 'block'; };
    img.src = logoUrl;
  } catch(e) {}
}

/* ═══════════════════════════════════════════════════════════
   INICIALIZACIÓN
══════════════════════════════════════════════════════════ */
async function sincronizarPantalla() {
  try {
    const resp = await fetch('/api/ventas/pantalla-cliente', { cache: 'no-store' });
    if (!resp.ok) return;
    const data = await resp.json();
    if (data.estado === 'cobrar_tarjeta') {
      mostrarQRPago(data.link_pago || '', data.total || 0);
    } else if (data && data.activa) {
      _linkPagoActual = null;
      mostrarEstadoVenta();
      actualizarDatosVenta(data);
    } else if (data.estado === 'pagado') {
      _linkPagoActual = null;
      mostrarEstadoGracias(data.total || 0, data.vuelto || 0);
    } else {
      _linkPagoActual = null;
      mostrarEstadoIdle();
    }
  } catch(e) {
    console.log('Sin conexión al POS');
  }
}

cargarConfigNegocio();
cargarPublicidad();
sincronizarPantalla();
setInterval(sincronizarPantalla, 2000);
setInterval(cargarPublicidad,  9000);


if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', {scope: '/'})
      .catch(err => console.log('SW error:', err));
  });
}
