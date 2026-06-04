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

function aplicarTema(tema, persistir = true) {
  document.documentElement.setAttribute('data-tema', tema);
  localStorage.setItem('zero-tema', tema);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = tema === 'claro' ? '#f1f5f9' : '#6366f1';
  _actualizarBotonesTema(tema);
  if (persistir) {
    fetch('/api/config', {
      method: 'PUT', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tema_modo: tema }),
    }).catch(() => {});
  }
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

async function cargarTemaGuardado() {
  // 1. Aplicar localStorage inmediatamente para evitar flash
  const temaLocal  = localStorage.getItem('zero-tema')  || 'oscuro';
  const colorLocal = localStorage.getItem('zero-color') || 'zero';
  const customLocal = localStorage.getItem('zero-color-custom');

  aplicarTema(temaLocal, false);
  if (colorLocal === 'custom' && customLocal) {
    aplicarColor(customLocal);
  } else {
    aplicarColor(colorLocal);
  }

  // 2. Sincronizar con el servidor (para multi-dispositivo)
  try {
    const resp = await fetch('/api/config', { credentials: 'include' });
    if (!resp.ok) return;
    const config = await resp.json();
    if (config.tema_color) {
      aplicarColor(config.tema_color);
      localStorage.setItem('zero-color', 'custom');
      localStorage.setItem('zero-color-custom', config.tema_color);
    }
    if (config.tema_modo) {
      aplicarTema(config.tema_modo, false);
    }
  } catch (_) {
    // Sin servidor → valores de localStorage ya aplicados
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

/* ── Selector de color personalizado ────────────────────────────────── */

let _colorTemporal = localStorage.getItem('zero-color-custom') || '#6366f1';
let _colorOriginalState = null;

function abrirSelectorColor() {
  document.getElementById('panelColor')?.remove();

  _colorTemporal = localStorage.getItem('zero-color-custom') || '#6366f1';
  _colorOriginalState = {
    dataColor: document.documentElement.getAttribute('data-tema-color') || 'zero',
    inlineAccent: document.documentElement.style.getPropertyValue('--accent'),
    inlineAccent2: document.documentElement.style.getPropertyValue('--accent2'),
  };

  const panel = document.createElement('div');
  panel.id = 'panelColor';
  panel.style.cssText = `
    position:fixed;inset:0;
    background:rgba(0,0,0,0.85);
    display:flex;align-items:center;
    justify-content:center;z-index:99999;
  `;
  panel.innerHTML = `
    <div style="
      background:var(--bg);border:1px solid var(--border);
      border-radius:20px;padding:24px;
      width:90%;max-width:340px;
    ">
      <h3 style="color:var(--text);margin:0 0 20px;font-size:18px">
        🎨 Color personalizado
      </h3>

      <div id="previewColor" style="
        background:${_colorTemporal};border-radius:12px;height:80px;
        display:flex;align-items:center;justify-content:center;
        margin-bottom:20px;transition:background 0.2s;
      ">
        <span style="color:white;font-weight:700;font-size:16px;
          text-shadow:0 1px 3px rgba(0,0,0,0.5)">ZERO POS</span>
      </div>

      <p style="color:var(--text-dim);font-size:12px;margin:0 0 10px">
        Colores rápidos
      </p>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px">
        ${[
          ['#6366f1','ZERO'],['#22c55e','Verde'],['#3b82f6','Azul'],
          ['#ef4444','Rojo'],['#f97316','Naranja'],['#ec4899','Rosa'],
          ['#8b5cf6','Violeta'],['#14b8a6','Teal'],['#f59e0b','Ámbar'],
          ['#64748b','Gris'],
        ].map(([hex, nombre]) => `
          <button onclick="previsualizarColor('${hex}')" title="${nombre}" style="
            width:32px;height:32px;border-radius:50%;background:${hex};
            border:2px solid transparent;cursor:pointer;
            transition:transform 0.1s,border-color 0.1s;
          " onmouseover="this.style.transform='scale(1.2)'"
            onmouseout="this.style.transform='scale(1)'">
          </button>
        `).join('')}
      </div>

      <p style="color:var(--text-dim);font-size:12px;margin:0 0 8px">Código HEX</p>
      <div style="display:flex;gap:8px;margin-bottom:16px">
        <input id="inputHex" type="text" value="${_colorTemporal}" placeholder="#6366f1"
          maxlength="7" style="
            flex:1;padding:10px 12px;
            background:var(--surface2);border:1px solid var(--border);
            border-radius:8px;color:var(--text);
            font-size:15px;font-family:monospace;
          "
          oninput="if(this.value.match(/^#[0-9A-Fa-f]{6}$/)) previsualizarColor(this.value)">
        <input id="inputColorNativo" type="color" value="${_colorTemporal}" style="
            width:44px;height:44px;border:none;border-radius:8px;
            cursor:pointer;padding:2px;background:var(--surface2);
          "
          oninput="previsualizarColor(this.value);document.getElementById('inputHex').value=this.value;">
      </div>

      <p style="color:var(--text-dim);font-size:12px;margin:0 0 8px">Brillo / Oscuridad</p>
      <input id="sliderBrillo" type="range" min="-50" max="50" value="0"
        style="width:100%;margin-bottom:4px;accent-color:var(--accent)"
        oninput="ajustarBrillo(this.value)">
      <div style="display:flex;justify-content:space-between;margin-bottom:20px">
        <span style="color:var(--text-dim);font-size:11px">Más oscuro</span>
        <span style="color:var(--text-dim);font-size:11px">Más claro</span>
      </div>

      <div style="display:flex;gap:8px">
        <button onclick="_cancelarSelectorColor()" style="
          flex:1;padding:12px;background:var(--surface2);
          color:var(--text);border:1px solid var(--border);
          border-radius:10px;cursor:pointer;font-size:15px;
        ">Cancelar</button>
        <button onclick="confirmarColor()" id="btnConfirmarColor" style="
          flex:2;padding:12px;background:${_colorTemporal};
          color:white;border:none;border-radius:10px;
          cursor:pointer;font-weight:700;font-size:15px;
          transition:background 0.2s;
        ">✅ Aplicar</button>
      </div>
    </div>
  `;
  document.body.appendChild(panel);
}

function _cancelarSelectorColor() {
  if (_colorOriginalState) {
    document.documentElement.setAttribute('data-tema-color', _colorOriginalState.dataColor);
    if (_colorOriginalState.inlineAccent) {
      document.documentElement.style.setProperty('--accent', _colorOriginalState.inlineAccent);
      document.documentElement.style.setProperty('--accent2', _colorOriginalState.inlineAccent2);
    } else {
      document.documentElement.style.removeProperty('--accent');
      document.documentElement.style.removeProperty('--accent2');
    }
    _colorOriginalState = null;
  }
  document.getElementById('panelColor')?.remove();
}

function previsualizarColor(hex) {
  if (!hex.match(/^#[0-9A-Fa-f]{6}$/)) return;
  _colorTemporal = hex;

  const preview = document.getElementById('previewColor');
  if (preview) preview.style.background = hex;
  const inputHex = document.getElementById('inputHex');
  if (inputHex) inputHex.value = hex;
  const inputNativo = document.getElementById('inputColorNativo');
  if (inputNativo) inputNativo.value = hex;
  const btnConfirmar = document.getElementById('btnConfirmarColor');
  if (btnConfirmar) btnConfirmar.style.background = hex;

  // Preview en tiempo real en la página
  document.documentElement.style.setProperty('--accent', hex);
  document.documentElement.style.setProperty('--accent2', hex + 'cc');
}

function _hexToHSL(hex) {
  let r = parseInt(hex.slice(1, 3), 16) / 255;
  let g = parseInt(hex.slice(3, 5), 16) / 255;
  let b = parseInt(hex.slice(5, 7), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h, s, l = (max + min) / 2;
  if (max === min) {
    h = s = 0;
  } else {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = (g - b) / d + (g < b ? 6 : 0); break;
      case g: h = (b - r) / d + 2; break;
      case b: h = (r - g) / d + 4; break;
    }
    h /= 6;
  }
  return [h * 360, s * 100, l * 100];
}

function _HSLToHex(h, s, l) {
  s /= 100; l /= 100;
  const a = s * Math.min(l, 1 - l);
  const f = n => {
    const k = (n + h / 30) % 12;
    const c = l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return Math.round(255 * c).toString(16).padStart(2, '0');
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

function ajustarBrillo(valor) {
  const [h, s, l] = _hexToHSL(_colorTemporal);
  const nuevaL = Math.max(10, Math.min(90, l + parseInt(valor)));
  previsualizarColor(_HSLToHex(h, s, nuevaL));
}

function confirmarColor() {
  aplicarColor(_colorTemporal);
  _colorOriginalState = null;
  document.getElementById('panelColor')?.remove();

  // Persistir en servidor (multi-dispositivo)
  fetch('/api/config', {
    method: 'PUT',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tema_color: _colorTemporal }),
  }).catch(() => {});

  // Toast si existe función en la página
  if (typeof showToast === 'function') showToast('🎨 Color aplicado', 'ok');
}

// Inicializar al cargar la página
cargarTemaGuardado();
