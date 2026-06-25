/* ═════════════════════════════════════════════════════════════
   ZERO POS — onboarding.js
   Lógica de onboarding.html
   ═════════════════════════════════════════════════════════════ */

let zeroTipoSeleccionado = null;
let siiSeleccionado      = 'no';

const SUBTIPOS = {
  store: [
    {value:'almacen',    label:'Almacén / Minimarket'},
    {value:'botilleria', label:'Botillería'},
    {value:'panaderia',  label:'Panadería / Pastelería'},
    {value:'ropa',       label:'Tienda de ropa'},
    {value:'farmacia',   label:'Farmacia'},
    {value:'ferreteria', label:'Ferretería'},
    {value:'kiosco',     label:'Kiosco'},
    {value:'otro_store', label:'Otro'},
  ],
  food: [
    {value:'food_truck',   label:'Food Truck'},
    {value:'sushi',        label:'Sushi / Delivery'},
    {value:'pizzeria',     label:'Pizzería'},
    {value:'dark_kitchen', label:'Dark Kitchen'},
    {value:'hamburguesas', label:'Hamburguesas'},
    {value:'otro_food',    label:'Otro'},
  ],
  resto: [
    {value:'restaurante', label:'Restaurante'},
    {value:'cafe_salon',  label:'Café con salón'},
    {value:'bar',         label:'Bar / Pub'},
    {value:'otro_resto',  label:'Otro'},
  ],
  service: [
    {value:'peluqueria',   label:'Peluquería'},
    {value:'barberia',     label:'Barbería'},
    {value:'nail',         label:'Nail Art / Spa'},
    {value:'veterinaria',  label:'Veterinaria'},
    {value:'otro_service', label:'Otro'},
  ],
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function $(id)      { return document.getElementById(id); }
function _show(id)  { $(id).style.display = 'block'; }
function _hide(id)  { $(id).style.display = 'none'; }
function _prog(pct) { $('progressFill').style.width = pct; }

function mostrarError(msg) {
  $('errorMsg').textContent = msg;
  $('modalError').style.display = 'flex';
}
function cerrarError() { $('modalError').style.display = 'none'; }

function limpiarError(input) {
  input.classList.remove('campo-error');
  const err = document.getElementById(input.id + 'Error');
  if (err) err.textContent = '';
}

function _setErr(id, msg) {
  const el = $(id);
  el.classList.add('campo-error');
  const err = $(id + 'Error');
  if (err) err.textContent = msg;
}

function _validar(campos) {
  let ok = true;
  let primero = null;
  campos.forEach(({id, msg}) => {
    const val = $(id).value.trim();
    if (!val) {
      _setErr(id, msg);
      ok = false;
      if (!primero) primero = $(id);
    }
  });
  if (primero) primero.focus();
  return ok;
}

// ── Init ─────────────────────────────────────────────────────────────────────

async function init() {
  const me = await fetch('/api/auth/me', {credentials:'include'})
    .then(r => r.json()).catch(() => null);
  if (!me || me.error) { location.href = 'login.html'; return; }

  const forzar = new URLSearchParams(window.location.search).get('forzar');
  if (!forzar) {
    const estado = await fetch('/api/onboarding/estado', {credentials:'include'})
      .then(r => r.json()).catch(() => ({}));
    if (estado.completado) { location.href = 'pos.html'; return; }
  }
}

// ── Paso 1 ───────────────────────────────────────────────────────────────────

function seleccionarZero(card, tipo) {
  document.querySelectorAll('[data-zero]').forEach(c => c.classList.remove('selected'));
  card.classList.add('selected');
  zeroTipoSeleccionado = tipo;
  $('btnContinuar1').disabled = false;
  _poblarSubtipos(tipo);
  console.log('[ZERO] Tipo seleccionado:', tipo);
}

function _poblarSubtipos(tipo) {
  const sel = $('subtipoNegocio');
  sel.innerHTML = '<option value="">Selecciona (opcional)</option>';
  (SUBTIPOS[tipo] || []).forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.value;
    opt.textContent = s.label;
    sel.appendChild(opt);
  });
}

function irPaso2() {
  if (!zeroTipoSeleccionado) return;
  _hide('paso1'); _show('paso2'); _prog('50%');
}

function volverPaso1() {
  _hide('paso2'); _show('paso1'); _prog('25%');
}

// ── Paso 2 ───────────────────────────────────────────────────────────────────

function irPaso3() {
  const ok = _validar([
    {id: 'nombreNegocio', msg: 'El nombre del negocio es obligatorio'},
    {id: 'dirNegocio',    msg: 'La dirección es obligatoria'},
    {id: 'telNegocio',    msg: 'El teléfono es obligatorio'},
  ]);
  if (!ok) return;
  console.log('[ZERO] Negocio:', $('nombreNegocio').value.trim(),
              '| Subtipo:', $('subtipoNegocio').value || '(ninguno)');
  _hide('paso2'); _show('paso3'); _prog('75%');
}

function volverPaso2() {
  _hide('paso3'); _show('paso2'); _prog('50%');
}

// ── Paso 3 ───────────────────────────────────────────────────────────────────

function irPaso4() {
  const ok = _validar([
    {id: 'responsableNombre', msg: 'El nombre es obligatorio'},
    {id: 'responsableTel',    msg: 'El teléfono es obligatorio'},
    {id: 'responsableEmail',  msg: 'El email es obligatorio'},
  ]);
  if (!ok) return;
  _hide('paso3'); _show('paso4'); _prog('100%');
}

function volverPaso3() {
  _hide('paso4'); _show('paso3'); _prog('75%');
}

// ── Paso 4 ───────────────────────────────────────────────────────────────────

function selSII(val) {
  siiSeleccionado = val;
  $('opNoSII').classList.toggle('selected', val === 'no');
  $('opSiSII').classList.toggle('selected', val === 'si');
  $('siiCampos').style.display = val === 'si' ? 'block' : 'none';
}

async function confirmar() {
  $('btnEmpezar').disabled = true;

  const nombre    = $('nombreNegocio').value.trim();
  const dir       = $('dirNegocio').value.trim();
  const tel       = $('telNegocio').value.trim();
  const subtipo   = $('subtipoNegocio').value;
  const respNom   = $('responsableNombre').value.trim();
  const respTel   = $('responsableTel').value.trim();
  const respEmail = $('responsableEmail').value.trim();

  const configPayload = {
    nombre_negocio:      nombre,
    direccion_negocio:   dir,
    telefono_negocio:    tel,
    responsable_nombre:  respNom,
    responsable_telefono: respTel,
    responsable_email:   respEmail,
    sii_activo:          siiSeleccionado === 'si' ? '1' : '0',
    tipo_negocio:        zeroTipoSeleccionado,
  };
  if (subtipo) configPayload.subtipo_negocio = subtipo;

  if (siiSeleccionado === 'si') {
    const rut   = $('rutNegocio').value.trim();
    const razon = $('razonSocial').value.trim();
    const giro  = $('giroNegocio').value.trim();
    if (rut)   configPayload.rut_negocio  = rut;
    if (razon) configPayload.razon_social = razon;
    if (giro)  configPayload.giro         = giro;
  }

  console.log('[ZERO] Guardando config…', {tipo: zeroTipoSeleccionado, subtipo});

  _hide('paso4'); _show('loading');
  $('loadingMsg').textContent = 'Cargando tus productos...';

  try {
    // 1. Guardar configuración
    const rCfg = await fetch('/api/config', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(configPayload),
    });
    if (!rCfg.ok) {
      const err = await rCfg.json().catch(() => ({}));
      throw new Error(err.error || 'Error al guardar configuración');
    }

    // 2. Cargar productos
    const rComp = await fetch('/api/onboarding/completar', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({tipo: zeroTipoSeleccionado, subtipo}),
    });
    const data = await rComp.json();

    _hide('loading');

    if (data.ok) {
      _show('exito');
      $('exitoMsg').textContent =
        `Se cargaron ${data.productos_cargados} productos. ¡A vender!`;
    } else {
      mostrarError('Error: ' + (data.error || 'Error desconocido'));
      _show('paso4');
      $('btnEmpezar').disabled = false;
    }
  } catch(e) {
    _hide('loading');
    mostrarError(e.message || 'Error de conexión. Verifica que el servidor esté activo.');
    _show('paso4');
    $('btnEmpezar').disabled = false;
  }
}

init();


if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', {scope: '/'})
      .catch(err => console.log('SW error:', err));
  });
}
