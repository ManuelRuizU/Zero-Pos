/* ─────────────────────────────────────────────────────────────────────────
   ZERO POS — Utilidades compartidas
   Funciones globales disponibles en todas las páginas.
   Las páginas que definen sus propias versiones (fmt, showToast) las
   sobreescriben al cargarse, por lo que este archivo funciona como fallback
   y fuente de verdad para páginas que no las tienen definidas.
   ──────────────────────────────────────────────────────────────────────── */

/**
 * Formatea un número como precio en pesos chilenos.
 * $1.890  →  fmt(1890)
 */
window.fmt = function(n) {
  return '$' + Math.round(Number(n) || 0).toLocaleString('es-CL');
};

window.formatearPrecio = window.fmt;

/**
 * Normaliza texto para búsquedas: elimina tildes, convierte a minúsculas.
 */
function normalizarTexto(t) {
  return String(t || '').toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9 ]/g, ' ')
    .replace(/\s+/g, ' ').trim();
}

/**
 * Formatea una fecha ISO/Date a cadena legible en español.
 * @param {string|Date} fecha
 * @param {boolean} [conHora=false]
 */
function formatearFecha(fecha, conHora = false) {
  if (!fecha) return '';
  const d = new Date(fecha);
  if (isNaN(d)) return String(fecha);
  const opciones = { day: '2-digit', month: '2-digit', year: 'numeric' };
  if (conHora) { opciones.hour = '2-digit'; opciones.minute = '2-digit'; }
  return d.toLocaleDateString('es-CL', opciones);
}

/**
 * Detecta si el agente de usuario es móvil o tablet.
 */
function isMobile() {
  return /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
}

/**
 * Wrapper fetch con credenciales, manejo de errores y Content-Type JSON.
 * @returns {Promise<any>}  JSON parseado o lanza Error con mensaje del servidor.
 */
async function fetchZero(url, options = {}) {
  const defaults = {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  };
  const res = await fetch(url, { ...defaults, ...options, headers: { ...defaults.headers, ...(options.headers || {}) } });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

/**
 * Genera un color determinista a partir de un string (para avatares).
 */
const _PALETA_AVATARES = ['#6366f1','#8b5cf6','#06b6d4','#10b981','#f59e0b','#ef4444','#ec4899','#0ea5e9'];
function colorAvatar(nombre) {
  let h = 0;
  for (let i = 0; i < (nombre || '').length; i++) h = (h * 31 + nombre.charCodeAt(i)) & 0xFFFFFF;
  return _PALETA_AVATARES[Math.abs(h) % _PALETA_AVATARES.length];
}
