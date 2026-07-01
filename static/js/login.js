/* ═════════════════════════════════════════════════════════════
   ZERO POS — login.js
   Lógica de login.html
   ═════════════════════════════════════════════════════════════ */

const _COLORES = [
  '#22c55e','#22c55e','#06b6d4','#10b981','#f59e0b','#ef4444','#ec4899','#0ea5e9'
];
let pin = '';
let usuarioSeleccionado = null;
let _modoAcceso = 'entrada';

let _estadoTurno = { estado: 'cerrado', cajero_reemplazo: false, cajero_nombre: '' };

const _MODO_BTN = {
  entrada:           'btnModoEntrada',
  salida:            'btnModoSalida',
  salida_colacion:   'btnModoSalidaColacion',
  entrada_colacion:  'btnModoEntradaColacion',
};

function seleccionarModo(modo) {
  _modoAcceso = modo;
  Object.entries(_MODO_BTN).forEach(([m, id]) => {
    const btn = document.getElementById(id);
    if (btn) btn.classList.toggle('activo', m === modo);
  });
}

function _horaActual() {
  const d = new Date();
  return d.toLocaleTimeString('es-CL', {hour:'2-digit', minute:'2-digit', hour12:false});
}

function _avatarColor(nombre) {
  let h = 0;
  for (let i = 0; i < (nombre||'').length; i++) h = (h * 31 + nombre.charCodeAt(i)) & 0xFFFFFF;
  return _COLORES[Math.abs(h) % _COLORES.length];
}

function crearRipple(btn, event) {
  const rect = btn.getBoundingClientRect();
  const ripple = document.createElement('span');
  ripple.classList.add('ripple');
  const size = Math.max(rect.width, rect.height);
  ripple.style.width = ripple.style.height = size + 'px';
  ripple.style.left = (event.clientX - rect.left - size / 2) + 'px';
  ripple.style.top  = (event.clientY - rect.top  - size / 2) + 'px';
  btn.appendChild(ripple);
  setTimeout(() => ripple.remove(), 400);
}

async function cargarUsuarios() {
  try {
    const usuarios = await fetch('/api/auth/usuarios/publico', {credentials:'include'})
      .then(r => r.json());
    const grid = document.getElementById('usuariosGrid');
    grid.innerHTML = '';
    if (!usuarios || !usuarios.length) {
      mostrarPin(null);
      return;
    }
    usuarios.forEach(u => {
      const inicial = (u.nombre || '?')[0].toUpperCase();
      const color   = _avatarColor(u.nombre);
      const card = document.createElement('div');
      card.className = 'usuario-card';
      card.innerHTML = `
        <div class="usuario-avatar" style="background:${color}">${inicial}</div>
        <div class="usuario-nombre">${u.nombre}</div>
        <div class="usuario-rol">${u.rol || ''}</div>`;
      card.onclick = () => mostrarPin(u);
      grid.appendChild(card);
    });
    if (usuarios.length === 1) mostrarPin(usuarios[0]);
  } catch(e) {
    mostrarPin(null);
  }
}

function mostrarPin(u) {
  usuarioSeleccionado = u;
  pin = '';
  actualizarCirculos();
  setError('');

  const avatar = document.getElementById('pinAvatar');
  if (u) {
    const inicial = (u.nombre || '?')[0].toUpperCase();
    const color   = _avatarColor(u.nombre);
    avatar.textContent = inicial;
    avatar.style.background = `linear-gradient(135deg, ${color}, #22c55e)`;
    document.getElementById('pinNombreUsuario').textContent = u.nombre;
    document.getElementById('pinSubtitulo').textContent = u.rol || 'Introduce tu PIN';
  } else {
    avatar.textContent = '🔑';
    avatar.style.background = 'rgba(255,255,255,0.08)';
    document.getElementById('pinNombreUsuario').textContent = 'Introduce tu PIN';
    document.getElementById('pinSubtitulo').textContent = '4 dígitos';
  }

  document.getElementById('pantallaUsuarios').style.opacity = '0';
  document.getElementById('pantallaUsuarios').style.pointerEvents = 'none';
  document.getElementById('pantallaPin').classList.add('activa');
  // Refinar botones de modo con el estado de turno de este usuario específico
  if (u?.id) adaptarModosPorEstado(u.id);
}

function volverUsuarios() {
  pin = '';
  actualizarCirculos();
  setError('');
  document.getElementById('pantallaPin').classList.remove('activa');
  document.getElementById('pantallaUsuarios').style.opacity = '1';
  document.getElementById('pantallaUsuarios').style.pointerEvents = '';
}

function actualizarCirculos(estado) {
  for (let i = 0; i < 4; i++) {
    const dot = document.getElementById('pc' + i);
    dot.classList.remove('activo', 'correcto', 'error');
    if (estado === 'correcto') {
      dot.classList.add('correcto');
    } else if (estado === 'error') {
      dot.classList.add('error');
    } else if (i < pin.length) {
      dot.classList.add('activo');
    }
  }
}

function presionarPin(digito) {
  if (pin.length >= 4) return;
  pin += digito;
  actualizarCirculos();
  if (navigator.vibrate) navigator.vibrate(30);
  if (pin.length === 4) setTimeout(intentarLogin, 200);
}

function borrarPin() {
  if (!pin.length) return;
  pin = pin.slice(0, -1);
  actualizarCirculos();
  setError('');
}

function setError(msg) {
  document.getElementById('pinError').textContent = msg;
}

function triggerError() {
  actualizarCirculos('error');
  const wrapper = document.getElementById('loginWrapper');
  wrapper.classList.remove('error');
  void wrapper.offsetHeight;
  wrapper.classList.add('error');
  setTimeout(() => {
    wrapper.classList.remove('error');
    pin = '';
    actualizarCirculos();
  }, 500);
}

async function intentarLogin() {
  if (pin.length !== 4) return;
  try {
    const body = {pin, modo: _modoAcceso};
    if (usuarioSeleccionado) body.usuario_id = usuarioSeleccionado.id;
    else if (_cambiarPinUsuarioId) body.usuario_id = _cambiarPinUsuarioId;
    const r = await fetch('/api/auth/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
      credentials: 'include',
    });
    const data = await r.json();
    if (data.cambiar_pin) {
      _mostrarModalCambioPin(data.usuario_id);
      return;
    }
    if (r.ok) {
      actualizarCirculos('correcto');
      setTimeout(() => _mostrarPantallaPost(data), 300);
    } else if (data.upgrade) {
      setError('Límite de sesiones alcanzado. Pide al admin que cierre una.');
      triggerError();
      if (navigator.vibrate) navigator.vibrate([60, 30, 60]);
    } else {
      setError(data.error || 'PIN incorrecto');
      triggerError();
      if (navigator.vibrate) navigator.vibrate([60, 30, 60]);
    }
  } catch(e) {
    setError('Error de conexión');
    triggerError();
  }
}

async function _mostrarPantallaPost(data) {
  const nombre  = data.usuario?.nombre || '';
  const modo    = data.modo || _modoAcceso;
  const hora    = _horaActual();
  const rol     = data.usuario?.rol || '';

  // Calcular resumen asistencia para pantalla entrada
  let horasSemana = '';
  if (modo === 'entrada') {
    try {
      const res = await fetch('/api/auth/asistencia/resumen', {credentials:'include'}).then(r=>r.json());
      const hrs  = res.horas_semana ?? 0;
      const pact = res.jornada_pactada ?? 45;
      horasSemana = `Esta semana: ${hrs} hrs trabajadas de ${pact} hrs pactadas`;
    } catch(e) {}

    // Verificar si hay turno propio abierto
    if (rol !== 'cocina') {
      let turnoAbierto = false;
      try {
        const tRes = await fetch('/api/auth/turno/actual', {credentials:'include'}).then(r => r.json());
        turnoAbierto = !!tRes.turno;
      } catch(e) {}
      if (!turnoAbierto) {
        // Detectar si es cajero de reemplazo (entra mientras otro está en colación)
        const esReemplazo = _estadoTurno.estado === 'colacion_activa';
        const sub = document.getElementById('entradaSubtitulo');
        document.getElementById('entradaNombre').textContent = nombre;
        document.getElementById('entradaHora').textContent   = hora;
        if (esReemplazo) {
          if (sub) sub.textContent = '👥 Cajero de reemplazo';
          const cajero = _estadoTurno.cajero_nombre || 'cajero principal';
          document.getElementById('entradaHorasSemana').textContent = `Cubriendo a: ${cajero}`;
        } else {
          if (sub) sub.textContent = saludoPorHora('entrada');
          document.getElementById('entradaHorasSemana').textContent = 'Abriendo caja...';
        }
        document.getElementById('pantallaEntrada').classList.add('activa');
        setTimeout(() => { window.location.href = 'pos.html'; }, esReemplazo ? 3000 : 1500);
        return;
      }
    }
  }

  const idPantalla = {
    entrada:          'pantallaEntrada',
    salida:           'pantallaSalida',
    salida_colacion:  'pantallaSalidaColacion',
    entrada_colacion: 'pantallaEntradaColacion',
  }[modo];

  if (!idPantalla) {
    // Fallback por rol
    window.location.href = rol === 'cocina' ? 'cocina.html' : 'pos.html';
    return;
  }

  if (modo === 'entrada') {
    const sub = document.getElementById('entradaSubtitulo');
    if (sub) sub.textContent = saludoPorHora('entrada');
    document.getElementById('entradaNombre').textContent      = nombre;
    document.getElementById('entradaHora').textContent        = hora;
    document.getElementById('entradaHorasSemana').textContent = horasSemana;
    setTimeout(() => location.href = rol === 'cocina' ? 'cocina.html' : 'pos.html', 3000);
  } else if (modo === 'salida') {
    const saludo = saludoPorHora('salida');
    const subtEl = document.getElementById('salidaSubtitulo');
    const buenEl = document.getElementById('salidaBuenas');
    if (subtEl) subtEl.textContent = saludo;
    if (buenEl) buenEl.textContent = saludo;
    document.getElementById('salidaNombre').textContent  = nombre;
    document.getElementById('salidaHora').textContent    = hora;
    try {
      const res = await fetch('/api/auth/asistencia/resumen', {credentials:'include'}).then(r=>r.json());
      if (res.ultima_entrada) {
        const ini = new Date(res.ultima_entrada.replace(' ','T'));
        const fin = new Date();
        const diffMin = Math.round((fin - ini) / 60000);
        const h = Math.floor(diffMin / 60);
        const m = diffMin % 60;
        document.getElementById('salidaResumen').textContent = `Hoy trabajaste ${h} hrs ${m} min`;
      }
    } catch(e) {}
  } else if (modo === 'salida_colacion') {
    document.getElementById('salidaColNombre').textContent = nombre;
    document.getElementById('salidaColHora').textContent   = `Colación iniciada a las ${hora}`;
  } else if (modo === 'entrada_colacion') {
    document.getElementById('entradaColNombre').textContent = nombre;
    document.getElementById('entradaColHora').textContent   = `Son las ${hora}`;
    try {
      const rCol = await fetch('/api/auth/turno/reactivar', {
        method: 'POST', credentials: 'include',
      }).then(r => r.json());
      if (rCol.minutos != null) {
        document.getElementById('entradaColMinutos').textContent =
          `Colación: ${rCol.minutos} minutos`;
      }
    } catch(e) {}
    setTimeout(() => location.href = 'pos.html', 3000);
  }

  document.getElementById(idPantalla).classList.add('activa');
}

document.addEventListener('keydown', e => {
  if (!document.getElementById('pantallaPin').classList.contains('activa')) return;
  if (e.key >= '0' && e.key <= '9') presionarPin(e.key);
  else if (e.key === 'Backspace') borrarPin();
  else if (e.key === 'Escape') volverUsuarios();
});

// ?modo= en URL se respeta dentro de _mostrarSolo() en adaptarModosPorEstado()
// — no se aplica aquí para evitar race condition con el fetch async

async function adaptarModosPorEstado(userId) {
  const BTNS = {
    entrada:          document.getElementById('btnModoEntrada'),
    salida:           document.getElementById('btnModoSalida'),
    salida_colacion:  document.getElementById('btnModoSalidaColacion'),
    entrada_colacion: document.getElementById('btnModoEntradaColacion'),
  };

  function _mostrarSolo(...modos) {
    const urlModo = new URLSearchParams(window.location.search).get('modo');
    const MODOS_SALIDA = ['salida', 'salida_colacion'];
    if (urlModo && MODOS_SALIDA.includes(urlModo) && !modos.includes(urlModo)) {
      modos = [urlModo];
    }
    Object.entries(BTNS).forEach(([m, btn]) => {
      if (btn) btn.style.display = modos.includes(m) ? '' : 'none';
    });
    seleccionarModo((urlModo && modos.includes(urlModo)) ? urlModo : modos[0]);
    document.querySelector('.modo-grid')?.classList.add('visible');
  }

  try {
    const url = userId
      ? `/api/auth/turno/estado?usuario_id=${userId}`
      : '/api/auth/turno/estado';
    const r = await fetch(url, {credentials: 'include'});
    const data = await r.json();
    _estadoTurno = data;

    // Banner: mostrar quién está en colación para guiar al siguiente en identificarse
    const banner = document.getElementById('colacionBanner');
    const bannerNombre = document.getElementById('colacionBannerNombre');
    if (banner && bannerNombre) {
      if (data.estado === 'colacion_activa' && data.cajero_nombre) {
        bannerNombre.textContent = data.cajero_nombre;
        banner.style.display = 'flex';
      } else {
        banner.style.display = 'none';
      }
    }

    const miTurno = data.mi_turno; // 'abierto' | 'colacion' | 'ninguno' | undefined

    if (miTurno === 'colacion') {
      _mostrarSolo('entrada_colacion');
    } else if (miTurno === 'abierto') {
      data.puede_colacion
        ? _mostrarSolo('salida_colacion', 'salida')
        : _mostrarSolo('salida');
    } else {
      _mostrarSolo('entrada');
    }
  } catch(e) {
    _mostrarSolo('entrada');
  }
}

cargarUsuarios();
adaptarModosPorEstado();


let _cambiarPinUsuarioId = null;

function _mostrarModalCambioPin(usuarioId) {
  _cambiarPinUsuarioId = usuarioId;
  document.getElementById('inputPinNuevo').value = '';
  document.getElementById('inputPinConfirmar').value = '';
  document.getElementById('modalCambioPinError').textContent = '';
  document.getElementById('modalCambioPin').style.display = 'flex';
  document.getElementById('inputPinNuevo').focus();
}

async function _guardarPinNuevo() {
  const pinNuevo     = document.getElementById('inputPinNuevo').value.trim();
  const pinConfirmar = document.getElementById('inputPinConfirmar').value.trim();
  const errEl        = document.getElementById('modalCambioPinError');

  if (pinNuevo.length !== 4 || !/^\d{4}$/.test(pinNuevo)) {
    errEl.textContent = 'El PIN debe tener exactamente 4 dígitos';
    return;
  }
  if (pinNuevo !== pinConfirmar) {
    errEl.textContent = 'Los PINs no coinciden';
    return;
  }
  if (pinNuevo === '1234') {
    errEl.textContent = 'No puedes usar 1234 como PIN';
    return;
  }

  errEl.textContent = '';
  try {
    const r = await fetch('/api/auth/cambiar-pin', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      credentials: 'include',
      body: JSON.stringify({usuario_id: _cambiarPinUsuarioId, pin_nuevo: pinNuevo}),
    });
    const d = await r.json();
    if (!r.ok || !d.ok) {
      errEl.textContent = d.error || 'Error al guardar PIN';
      return;
    }
    document.getElementById('modalCambioPin').style.display = 'none';
    // Continuar con el login usando el PIN nuevo
    pin = pinNuevo;
    await intentarLogin();
  } catch(e) {
    errEl.textContent = 'Error de conexión';
  }
}


if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', {scope: '/'})
      .catch(err => console.log('SW error:', err));
  });
}
