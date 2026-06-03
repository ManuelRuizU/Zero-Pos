/* ─────────────────────────────────────────────────────────────────────────
   ZERO POS — Sistema de temas
   Claro/oscuro + paleta de colores de acento personalizables
   ──────────────────────────────────────────────────────────────────────── */

const TEMAS = {
  oscuro: { nombre: 'Oscuro', icono: '🌙' },
  claro:  { nombre: 'Claro',  icono: '☀️' },
};

const COLORES_ZERO = {
  zero:    { nombre: 'ZERO',    hex: '#6366f1' },
  verde:   { nombre: 'Verde',   hex: '#22c55e' },
  azul:    { nombre: 'Azul',    hex: '#3b82f6' },
  rojo:    { nombre: 'Rojo',    hex: '#ef4444' },
  naranja: { nombre: 'Naranja', hex: '#f97316' },
  rosa:    { nombre: 'Rosa',    hex: '#ec4899' },
};

function aplicarTema(tema) {
  document.documentElement.setAttribute('data-tema', tema);
  localStorage.setItem('zero-tema', tema);
  // Actualizar meta theme-color según tema
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = tema === 'claro' ? '#f1f5f9' : '#6366f1';
  _actualizarBotonesTema(tema);
}

function aplicarColor(color) {
  if (COLORES_ZERO[color]) {
    document.documentElement.setAttribute('data-tema-color', color);
    document.documentElement.style.removeProperty('--accent');
    document.documentElement.style.removeProperty('--accent2');
    localStorage.setItem('zero-color', color);
    localStorage.removeItem('zero-color-custom');
  } else {
    // Color hex personalizado
    document.documentElement.setAttribute('data-tema-color', 'custom');
    document.documentElement.style.setProperty('--accent', color);
    document.documentElement.style.setProperty('--accent2', color + 'cc');
    localStorage.setItem('zero-color', 'custom');
    localStorage.setItem('zero-color-custom', color);
  }
  _actualizarCirculos(color);
}

function cargarTemaGuardado() {
  const tema  = localStorage.getItem('zero-tema')  || 'oscuro';
  const color = localStorage.getItem('zero-color') || 'zero';
  const custom = localStorage.getItem('zero-color-custom');

  aplicarTema(tema);
  if (color === 'custom' && custom) {
    aplicarColor(custom);
  } else {
    aplicarColor(color);
  }
}

function _actualizarBotonesTema(tema) {
  document.querySelectorAll('.btn-tema').forEach(b => {
    b.classList.toggle('activo', b.dataset.tema === tema);
  });
}

function _actualizarCirculos(colorActivo) {
  document.querySelectorAll('.circulo-color[data-color]').forEach(b => {
    b.classList.toggle('activo', b.dataset.color === colorActivo);
  });
}

// Inicializar al cargar la página
cargarTemaGuardado();
