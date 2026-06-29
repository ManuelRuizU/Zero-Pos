/* ═══════════════════════════════════════════════════════════════
   ZERO POS — admin.js
   Lógica del panel de administración (admin.html)
   Depende de: zero-utils.js, zero-temas.js
   Nota: fmt() viene de zero-utils.js (window.fmt)
═══════════════════════════════════════════════════════════════ */

/* ── Variables y funciones principales ──────────────────────── */
function _esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

async function init() {
  const me = await fetch('/api/auth/me',{credentials:'include'}).then(r=>r.json()).catch(()=>null);
  if (!me||me.error||me.rol!=='admin') { location.href='login.html'; return; }
  cargarDashboard();
  const urlEl = document.getElementById('urlCliente');
  if (urlEl) urlEl.textContent = `${location.protocol}//${location.host}/static/cliente.html`;
  const cfg = await fetch('/api/config',{credentials:'include'}).then(r=>r.json()).catch(()=>({}));
  const deliveryActivo = cfg.modulo_delivery === '1' || cfg.modulo_delivery === true || cfg.modulo_delivery === 1;
  const btnPedidos = document.getElementById('btnNavPedidosAdmin');
  if (btnPedidos) btnPedidos.style.display = deliveryActivo ? '' : 'none';
}

function copiarUrlCliente() {
  const url = document.getElementById('urlCliente').textContent;
  navigator.clipboard.writeText(url).then(() => {
    const btn = event.target;
    const orig = btn.textContent;
    btn.textContent = '✓';
    setTimeout(() => btn.textContent = orig, 1500);
  }).catch(() => {});
}

function showTab(name, btn) {
  document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  btn.classList.add('active');
  if (name==='ventas') cargarVentas();
  if (name==='config') cargarConfig();
  if (name==='voz') { cargarVozConfig(); cargarHistorialVoz(); cargarAprendizaje(); }
  if (name==='categorias') cargarCatArbol();
  if (name==='equipo') cargarEquipo();
  if (name==='publicidad') pubCargar();
}

async function cargarDashboard() {
  const [dia, alertas, pendientes] = await Promise.all([
    fetch('/api/reportes/ventas/dia',{credentials:'include'}).then(r=>r.json()).catch(()=>({por_metodo:[],por_hora:[],top_productos:[]})),
    fetch('/api/productos/alertas',{credentials:'include'}).then(r=>r.json()).catch(()=>[]),
    fetch('/api/productos/pendientes-verificar',{credentials:'include'}).then(r=>r.json()).catch(()=>[]),
  ]);

  const totales = dia.por_metodo.reduce((a,r)=>({n:a.n+r.num_ventas,t:a.t+r.total}),{n:0,t:0});
  document.getElementById('kpiNum').textContent = totales.n;
  document.getElementById('kpiTotal').textContent = fmt(totales.t);
  document.getElementById('kpiTicket').textContent = totales.n ? fmt(totales.t/totales.n) : '$0';
  document.getElementById('kpiAlertas').textContent = alertas.length;

  if (pendientes.length) {
    document.getElementById('kpiPendientes').textContent = pendientes.length;
    document.getElementById('kpiPendientesCard').style.display = '';
    document.getElementById('kpiSinCat').textContent = pendientes.length;
    document.getElementById('kpiSinCatCard').style.display = '';
  }

  renderBars('chartHoras', dia.por_hora, r=>r.hora+':00', r=>r.total);
  renderBars('chartTop', dia.top_productos.slice(0,6), r=>r.nombre, r=>r.unidades);
}

function irAProductosPendientes() {
  window.location.href = '/static/inventario.html?filtrar=pendientes';
}

function irAInventarioSinCat() {
  window.location.href = '/static/inventario.html?filtrar_cat=Sin+categor%C3%ADa';
}

function renderBars(elId, data, labelFn, valFn) {
  const el = document.getElementById(elId);
  if (!data.length) { el.innerHTML = '<p style="color:var(--text-dim);font-size:12px">Sin datos</p>'; return; }
  const max = Math.max(...data.map(valFn)) || 1;
  el.innerHTML = data.map(r => {
    const pct = (valFn(r)/max*100).toFixed(0);
    const label = String(labelFn(r)).substring(0,10);
    return `<div class="bar-row">
      <span class="bar-label">${label}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
      <span class="bar-val">${typeof valFn(r)==='number'?valFn(r).toLocaleString('es-CL'):valFn(r)}</span>
    </div>`;
  }).join('');
}

async function cargarVentas() {
  const ventas = await fetch('/api/ventas?limite=50',{credentials:'include'}).then(r=>r.json()).catch(()=>[]);
  const tbody = document.getElementById('tablaVentas');
  if (!ventas.length) { tbody.innerHTML='<tr><td colspan="6" style="text-align:center;color:var(--text-dim)">Sin ventas</td></tr>'; return; }
  tbody.innerHTML = ventas.map(v=>`
    <tr>
      <td>#${v.id}</td>
      <td>${v.creado_en?.substring(0,16)||'—'}</td>
      <td>${v.cajero||'—'}</td>
      <td>${v.metodo_pago}</td>
      <td style="font-weight:700">${fmt(v.total)}</td>
      <td><span style="color:${v.estado==='completada'?'var(--success)':v.estado==='anulada'?'var(--danger)':'var(--warning)'}">${v.estado}</span></td>
    </tr>`).join('');
}

async function preguntarIA() {
  const input = document.getElementById('iaPregunta');
  const pregunta = input.value.trim();
  const el = document.getElementById('iaRespuesta');
  el.textContent = 'Consultando...';
  try {
    const r = await fetch('/api/reportes/ia/analisis', {
      method:'POST', credentials:'include',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({pregunta}),
    }).then(r=>r.json());
    el.textContent = r.respuesta || 'Sin respuesta';
    input.value = '';
  } catch(e) {
    el.textContent = 'Error al consultar IA';
  }
}

async function crearBackup() {
  const btn = event.currentTarget;
  btn.disabled = true; btn.textContent = 'Creando...';
  const r = await fetch('/api/backup/crear',{method:'POST',credentials:'include'}).then(r=>r.json());
  btn.disabled = false; btn.textContent = '💾 Solo local';
  if (r.ok) { showFeedback('fb_backup', `✓ ${r.nombre} (${r.tamaño_kb} KB)`); cargarListaBackups(); }
  else alert('Error: ' + r.error);
}

async function backupAhora() {
  const btn = event.currentTarget;
  btn.disabled = true; btn.textContent = 'Ejecutando...';
  try {
    const r = await fetch('/api/backup/ahora',{method:'POST',credentials:'include'}).then(r=>r.json());
    if (r.ok) {
      const res = r.resultados || {};
      const msgs = Object.entries(res).map(([k,v]) => `${k}: ${v ? '✓' : '✗'}`).join(' · ');
      showFeedback('fb_backup', msgs || '✓ OK');
      cargarListaBackups(); cargarEstadoBackup();
    } else { alert('Error: ' + (r.error || 'Desconocido')); }
  } catch(e) { alert('Error: ' + e.message); }
  finally { btn.disabled = false; btn.textContent = '▶ Backup completo ahora'; }
}

async function guardarBackupConfig() {
  const destinos = ['local','pendrive','email','rclone'].filter(d => {
    const el = document.getElementById('dest_' + d); return el && el.checked;
  });
  const payload = {
    hora:           document.getElementById('cfg_backup_hora')?.value || '03:00',
    retener_dias:   parseInt(document.getElementById('cfg_backup_retener_dias')?.value) || 7,
    destinos,
    email_destino:  document.getElementById('cfg_backup_email_destino')?.value.trim() || '',
    smtp_provider:  document.getElementById('cfg_smtp_provider')?.value || 'gmail',
    smtp_host:      document.getElementById('cfg_smtp_host')?.value.trim() || '',
    smtp_port:      document.getElementById('cfg_smtp_port')?.value || '587',
    smtp_user:      document.getElementById('cfg_smtp_user')?.value.trim() || '',
    smtp_password:  document.getElementById('cfg_smtp_password')?.value || '',
    rclone_remote:  document.getElementById('cfg_backup_rclone_remote')?.value.trim() || 'gdrive',
  };
  const r = await fetch('/api/backup/config',{method:'PUT',credentials:'include',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)}).then(r=>r.json());
  if (r.ok) showFeedback('fb_backup', '✓ Guardado');
}

async function probarEmail() {
  const btn = event.currentTarget;
  const fb = document.getElementById('fb_email_test');
  btn.disabled = true; btn.textContent = 'Enviando...';
  fb.textContent = '';
  try {
    const email = document.getElementById('cfg_backup_email_destino')?.value.trim();
    const r = await fetch('/api/backup/probar-email',{method:'POST',credentials:'include',
      headers:{'Content-Type':'application/json'}, body:JSON.stringify({email_destino: email})}).then(r=>r.json());
    if (r.ok) {
      fb.style.color = 'var(--success)'; fb.textContent = '✓ Email enviado correctamente';
    } else if (r.mensaje === 'muy_grande') {
      fb.style.color = 'var(--warning)';
      fb.textContent = '⚠️ Base de datos muy grande para email. Recomendamos configurar Google Drive con rclone.';
      document.getElementById('rcloneConfig').style.display = '';
    } else if (r.mensaje === 'smtp_no_configurado') {
      fb.style.color = 'var(--danger)'; fb.textContent = '✗ SMTP no configurado. Completa host, usuario y contraseña.';
    } else {
      fb.style.color = 'var(--danger)'; fb.textContent = '✗ Error: ' + (r.mensaje || r.error || 'Desconocido');
    }
  } catch(e) { fb.style.color = 'var(--danger)'; fb.textContent = '✗ ' + e.message; }
  finally { btn.disabled = false; btn.textContent = '📤 Probar envío ahora'; }
}

const SMTP_DATA = {
  gmail:   { host:'smtp.gmail.com', port:587, instrucciones:'Necesitas una "Contraseña de aplicación".\nGmail → Cuenta → Seguridad → Verificación en dos pasos → Contraseñas de aplicaciones' },
  outlook: { host:'smtp.office365.com', port:587, instrucciones:'Usa tu contraseña normal de Outlook.' },
  yahoo:   { host:'smtp.mail.yahoo.com', port:587, instrucciones:'Genera una contraseña de aplicación en Yahoo → Seguridad.' },
  custom:  { host:'', port:587, instrucciones:'Ingresa los datos de tu servidor SMTP.' },
};

function onSMTPProviderChange() {
  const p = document.getElementById('cfg_smtp_provider')?.value;
  const d = SMTP_DATA[p];
  if (!d) return;
  if (d.host) document.getElementById('cfg_smtp_host').value = d.host;
  document.getElementById('cfg_smtp_port').value = d.port;
  const instr = document.getElementById('smtpInstrucciones');
  if (instr) instr.textContent = d.instrucciones;
}

function toggleEmailConfig() {
  const show = document.getElementById('dest_email')?.checked;
  const el = document.getElementById('emailConfig');
  if (el) el.style.display = show ? '' : 'none';
}

function toggleRcloneConfig() {
  const show = document.getElementById('dest_rclone')?.checked;
  const el = document.getElementById('rcloneConfig');
  if (el) el.style.display = show ? '' : 'none';
}

async function cargarEstadoBackup() {
  const div = document.getElementById('backupEstado');
  if (!div) return;
  try {
    const est = await fetch('/api/backup/estado',{credentials:'include'}).then(r=>r.json());
    const chip = (ok, label, sub) => `
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 12px">
        <div style="font-size:12px;font-weight:600">${ok ? '✅' : '⬜'} ${label}</div>
        <div style="font-size:11px;color:var(--text-dim);margin-top:2px">${sub}</div>
      </div>`;
    div.innerHTML =
      chip(est.local?.activo,   '💾 Local',   est.local?.ultimo   || 'Sin backups aún') +
      chip(est.pendrive?.detectado, '🔌 Pendrive', est.pendrive?.detectado ? est.pendrive.ruta : 'No detectado') +
      chip(est.email?.configurado,  '📧 Email',    est.email?.email    || 'No configurado') +
      chip(est.rclone?.instalado,   '☁️ rclone',   est.rclone?.instalado ? `Remote: ${est.rclone.remote}` : 'rclone no instalado');
  } catch(_) { div.innerHTML = ''; }
}

// ── Config ────────────────────────────────────────────────────────────
let cfgActual = {};

async function cargarConfig() {
  cfgActual = await fetch('/api/config',{credentials:'include'}).then(r=>r.json()).catch(()=>({}));
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val ?? ''; };
  const setChk = (id, val) => { const el = document.getElementById(id); if (el) el.checked = val==='1'||val===true; };

  set('cfg_tipo_negocio',        cfgActual.tipo_negocio || 'tienda');
  set('cfg_nombre_negocio',      cfgActual.nombre_negocio);
  set('cfg_nombre_terminal',     cfgActual.nombre_terminal || 'Caja 1');
  set('cfg_rut_negocio',         cfgActual.rut_negocio);
  set('cfg_comuna_negocio',      cfgActual.comuna_negocio);
  set('cfg_mensaje_ticket',      cfgActual.mensaje_ticket);
  set('cfg_whatsapp_plantilla',  cfgActual.whatsapp_plantilla);
  set('cfg_moneda',              cfgActual.moneda || 'CLP');
  set('cfg_iva_porcentaje',      cfgActual.iva_porcentaje ?? '19');
  set('cfg_impresora_tipo',         cfgActual.impresora_tipo || 'red');
  set('cfg_impresora_ip',           cfgActual.impresora_ip);
  set('cfg_impresora_puerto',       cfgActual.impresora_puerto || '9100');
  set('cfg_impresora_autocorte',    cfgActual.impresora_autocorte || '1');
  set('cfg_impresora_corte_tipo',   cfgActual.impresora_corte_tipo || 'FULL');
  set('cfg_khipu_receiver_id',   cfgActual.khipu_receiver_id);
  set('cfg_khipu_secret',        cfgActual.khipu_secret ? '••••••••••••' : '');
  set('cfg_sumup_api_key',       cfgActual.sumup_api_key ? '••••••••••••' : '');
  set('cfg_sumup_merchant_code', cfgActual.sumup_merchant_code || '');
  set('cfg_sumup_email',         cfgActual.sumup_email || '');
  set('cfg_sumup_currency',      cfgActual.sumup_currency || 'CLP');
  set('cfg_banco_titular',       cfgActual.banco_titular);
  set('cfg_rut_negocio_banco',   cfgActual.rut_negocio);
  set('cfg_banco_nombre',        cfgActual.banco_nombre);
  set('cfg_banco_tipo_cuenta',   cfgActual.banco_tipo_cuenta || 'Cuenta Corriente');
  set('cfg_banco_cuenta',        cfgActual.banco_cuenta);
  set('cfg_backup_hora',              cfgActual.backup_hora || '03:00');
  set('cfg_backup_retener_dias',      cfgActual.backup_retener_dias || '7');
  set('cfg_backup_email_destino',     cfgActual.backup_email_destino || '');
  set('cfg_smtp_provider',            cfgActual.smtp_provider || 'gmail');
  set('cfg_smtp_host',                cfgActual.smtp_host || '');
  set('cfg_smtp_port',                cfgActual.smtp_port || '587');
  set('cfg_smtp_user',                cfgActual.smtp_user || '');
  set('cfg_smtp_password',            cfgActual.smtp_password ? '••••••••••••' : '');
  set('cfg_backup_rclone_remote',     cfgActual.backup_rclone_remote || 'gdrive');
  // Destinos checkboxes
  const destinos = (cfgActual.backup_destinos || 'local').split(',').map(d => d.trim());
  ['local','pendrive','email','rclone'].forEach(d => {
    const el = document.getElementById('dest_' + d);
    if (el) el.checked = destinos.includes(d);
  });
  onSMTPProviderChange();
  toggleEmailConfig();
  toggleRcloneConfig();
  cargarEstadoBackup();
  setChk('cfg_pantalla_cliente_activa', cfgActual.pantalla_cliente_activa);
  setChk('cfg_pantalla_cocina_activa',  cfgActual.pantalla_cocina_activa);
  setChk('cfg_modulo_delivery',         cfgActual.modulo_delivery);
  setChk('cfg_modo_mesas',                       cfgActual.modo_mesas);
  setChk('cfg_turno_contar_denominaciones',      cfgActual.turno_contar_denominaciones);
  setChk('cfg_cajero_reemplazo_colacion',        cfgActual.cajero_reemplazo_colacion);

  set('cfg_google_maps_api_key', cfgActual.google_maps_api_key ? '••••••••' : '');
  set('cfg_delivery_tarifa_tipo',   cfgActual.delivery_tarifa_tipo || 'gratis');
  set('cfg_delivery_precio_fijo',   cfgActual.delivery_precio_fijo);
  set('cfg_delivery_precio_km1',    cfgActual.delivery_precio_km1);
  set('cfg_delivery_precio_km3',    cfgActual.delivery_precio_km3);
  set('cfg_delivery_precio_km5',    cfgActual.delivery_precio_km5);
  set('cfg_delivery_precio_mas5',   cfgActual.delivery_precio_mas5);
  set('cfg_delivery_texto',         cfgActual.delivery_texto || 'Reparto');
  toggleDeliveryTarifa();
  toggleImpresora();
  cargarListaBackups();
  cargarMapaInfo();
  // WiFi
  set('cfg_wifi_ssid', cfgActual.wifi_ssid || '');
  set('cfg_wifi_password', cfgActual.wifi_password || '');
  if (cfgActual.wifi_ssid) _mostrarQrWifi(cfgActual.wifi_ssid, cfgActual.wifi_password || '');
  _actualizarModulosVisibles();
}

function _actualizarModulosVisibles() {
  const tipo = document.getElementById('cfg_tipo_negocio')?.value || 'tienda';
  const esRestaurante = ['restaurante','bar','cafe','pasteleria','sushi','pizzeria'].includes(tipo);
  const esMesas = ['restaurante','bar'].includes(tipo);
  const rowCocina = document.getElementById('row_pantalla_cocina');
  const rowMesas  = document.getElementById('row_modo_mesas');
  if (rowCocina) rowCocina.style.display = esRestaurante ? '' : 'none';
  if (rowMesas)  rowMesas.style.display  = esMesas ? '' : 'none';
}

function toggleCfgSeccion(header) {
  const body  = header.nextElementSibling;
  const arrow = header.querySelector('.cfg-seccion-arrow');
  const isOpen = body.classList.contains('abierto');
  body.classList.toggle('abierto', !isOpen);
  arrow.classList.toggle('abierto', !isOpen);
}

function toggleImpresora() {
  const tipo = document.getElementById('cfg_impresora_tipo')?.value;
  const showRed = tipo === 'red';
  document.getElementById('grp_imp_ip').style.display     = showRed ? '' : 'none';
  document.getElementById('grp_imp_puerto').style.display = showRed ? '' : 'none';
}

const SECCIONES = {
  negocio:   ['tipo_negocio','nombre_negocio','rut_negocio','moneda','iva_porcentaje','comuna_negocio','mensaje_ticket','nombre_terminal','whatsapp_plantilla'],
  impresora: ['impresora_tipo','impresora_ip','impresora_puerto','impresora_autocorte','impresora_corte_tipo'],
  khipu:     ['khipu_receiver_id','khipu_secret'],
  sumup:     ['sumup_api_key','sumup_merchant_code','sumup_email','sumup_currency'],
  banco:     ['banco_titular','banco_nombre','banco_tipo_cuenta','banco_cuenta'],
  pantallas: ['pantalla_cliente_activa','pantalla_cocina_activa','modulo_delivery','modo_mesas','turno_contar_denominaciones','cajero_reemplazo_colacion'],
  delivery:  ['delivery_tarifa_tipo','delivery_precio_fijo','delivery_precio_km1','delivery_precio_km3','delivery_precio_km5','delivery_precio_mas5','delivery_texto'],
  backup:    ['backup_hora','backup_retener_dias','backup_email_destino','smtp_provider','smtp_host','smtp_port','smtp_user','backup_rclone_remote'],
};

async function guardarSeccion(seccion) {
  const claves = SECCIONES[seccion];
  const data = {};

  for (const clave of claves) {
    const el = document.getElementById('cfg_' + clave);
    if (!el) continue;

    if (el.type === 'checkbox') {
      data[clave] = el.checked ? '1' : '0';
    } else if (el.type === 'password' && el.value === '••••••••••••') {
      // no sobreescribir si no cambió
    } else {
      data[clave] = el.value.trim();
    }
  }

  // El RUT en datos bancarios es el mismo que rut_negocio (campo compartido)
  if (seccion === 'banco') {
    const rutBanco = document.getElementById('cfg_rut_negocio_banco')?.value.trim();
    if (rutBanco) data['rut_negocio'] = rutBanco;
  }

  const r = await fetch('/api/config', {
    method:'POST', credentials:'include',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(data),
  }).then(r=>r.json());

  if (r.ok) showFeedback('fb_'+seccion);
  else alert('Error: ' + (r.error || 'desconocido'));
}

function showFeedback(id, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg || '✓ Guardado';
  el.classList.add('show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 2500);
}

async function testImpresora() {
  const res = document.getElementById('imp_test_result');
  res.style.display = 'block';
  res.textContent = 'Probando...';
  res.style.color = 'var(--text-dim)';
  const r = await fetch('/api/impresora/test',{method:'POST',credentials:'include'}).then(r=>r.json());
  res.textContent = r.ok ? 'OK - Impresora conectada correctamente' : 'X ' + (r.error || 'Sin respuesta');
  res.style.color = r.ok ? 'var(--success)' : 'var(--danger)';
}

async function subirLogoTicket(input) {
  if (!input.files.length) return;
  const fd = new FormData();
  fd.append('logo', input.files[0]);
  try {
    const r = await fetch('/api/config/logo-ticket', {method:'POST', credentials:'include', body:fd}).then(r=>r.json());
    if (r.ok) {
      const preview = document.getElementById('logoPreview');
      if (preview) {
        preview.src = '/static/negocio/logo_ticket.png?t=' + Date.now();
        preview.style.display = '';
      }
      showToast && showToast('Logo guardado', 'success');
    } else {
      alert('Error: ' + (r.error || 'No se pudo subir el logo'));
    }
  } catch(e) { alert('Error de conexión'); }
}

async function guardarWifi() {
  const ssid = (document.getElementById('cfg_wifi_ssid')?.value || '').trim();
  const pass = (document.getElementById('cfg_wifi_password')?.value || '').trim();
  const r = await fetch('/api/config', {
    method: 'POST', credentials: 'include',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({wifi_ssid: ssid, wifi_password: pass}),
  }).then(r => r.json()).catch(() => ({}));
  if (r.ok) {
    showFeedback('fb_wifi');
    if (ssid) _mostrarQrWifi(ssid, pass);
  } else {
    alert('Error: ' + (r.error || 'desconocido'));
  }
}

function _mostrarQrWifi(ssid, pass) {
  const wifiStr = `WIFI:T:WPA;S:${ssid};P:${pass};;`;
  const url = `https://api.qrserver.com/v1/create-qr-code/?size=160x160&data=${encodeURIComponent(wifiStr)}`;
  const img = document.getElementById('wifiQrImg');
  const prev = document.getElementById('wifiQrPreview');
  if (img && prev) {
    img.src = url;
    prev.style.display = '';
  }
}

function toggleDeliveryTarifa() {
  const tipo = document.getElementById('cfg_delivery_tarifa_tipo')?.value || 'gratis';
  const rowFijo = document.getElementById('rowDeliveryFijo');
  const rowDist = document.getElementById('rowDeliveryDistancia');
  if (rowFijo) rowFijo.style.display = tipo === 'fijo' ? '' : 'none';
  if (rowDist) rowDist.style.display = tipo === 'distancia' ? '' : 'none';
}

async function cargarMapaInfo() {
  const rows = await fetch('/api/mapa/comunas',{credentials:'include'})
    .then(r=>r.json()).catch(()=>[]);
  const listEl   = document.getElementById('mapaComunasList');
  const estadoEl = document.getElementById('mapaEstadoCapaLocal');
  const gmEl     = document.getElementById('mapaEstadoGoogle');
  const costoEl  = document.getElementById('mapaGoogleCosto');

  if (cfgActual.google_maps_api_key && cfgActual.google_maps_api_key !== '••••••••') {
    gmEl.style.color = 'var(--success)';
    gmEl.textContent = 'Activo';
    costoEl.style.display = '';
    costoEl.textContent = 'Google Maps: primeras 40.000 consultas/mes gratis · ~$5 USD por cada 1.000 adicionales.';
  }

  if (!rows || !rows.length) {
    estadoEl.textContent = 'Sin datos cargados';
    estadoEl.style.color = 'var(--text-dim)';
    listEl.innerHTML = '<div style="font-size:12px;color:var(--text-dim);">Ninguna comuna cargada aún.</div>';
    return;
  }
  const total = rows.reduce((s,r)=>s+r.calles,0);
  estadoEl.textContent = `${rows.length} comunas · ${total.toLocaleString()} calles`;
  estadoEl.style.color = 'var(--success)';
  listEl.innerHTML = rows.map(r=>
    `<div style="display:flex;justify-content:space-between;font-size:12px;
                 padding:4px 0;border-bottom:1px solid var(--border);">
       <span>${r.comuna}</span>
       <span style="color:var(--text-dim)">${r.calles.toLocaleString()} calles</span>
     </div>`
  ).join('');
}

async function cargarMapaComuna() {
  const comuna = document.getElementById('mapaInputComuna').value.trim();
  if (!comuna) return;
  const progEl = document.getElementById('mapaProgreso');
  const btn    = document.getElementById('btnCargarMapa');
  progEl.style.display = '';
  progEl.style.color   = 'var(--accent2)';
  progEl.textContent   = `Descargando calles de ${comuna}… (puede tomar hasta 60 s)`;
  btn.disabled = true;
  try {
    const r = await fetch('/api/mapa/cargar-comuna',{
      method:'POST', credentials:'include',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({comuna}),
    }).then(r=>r.json());
    if (r.ok) {
      progEl.style.color = 'var(--success)';
      progEl.textContent = `✅ ${r.calles.toLocaleString()} calles cargadas para ${r.comuna}`;
      document.getElementById('mapaInputComuna').value = '';
      cargarMapaInfo();
    } else {
      progEl.style.color = 'var(--danger)';
      progEl.textContent = `✗ ${r.error || 'Sin datos o sin internet'}`;
    }
  } catch(e) {
    progEl.style.color = 'var(--danger)';
    progEl.textContent = 'Error de conexión';
  }
  btn.disabled = false;
}

async function guardarMapaConfig() {
  const key = document.getElementById('cfg_google_maps_api_key').value.trim();
  if (!key || key === '••••••••') { showFeedback('fb_mapa'); return; }
  const r = await fetch('/api/config',{
    method:'POST', credentials:'include',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({google_maps_api_key: key}),
  }).then(r=>r.json());
  if (r.ok) showFeedback('fb_mapa');
}

async function cargarListaBackups() {
  const list = document.getElementById('backupList');
  if (!list) return;
  const backups = await fetch('/api/backup/listar',{credentials:'include'}).then(r=>r.json()).catch(()=>[]);
  if (!backups.length) {
    list.innerHTML = '<p style="color:var(--text-dim);font-size:12px;padding:8px 0">Sin backups todavía</p>';
    return;
  }
  list.innerHTML = backups.map(b => `
    <div class="backup-item">
      <span class="backup-item-name">${b.nombre}</span>
      <div style="display:flex;align-items:center;gap:10px;">
        <span class="backup-item-size">${b.tamaño_kb} KB</span>
        <a href="/api/backup/descargar/${encodeURIComponent(b.nombre)}"
           style="color:var(--accent2);font-size:11px;text-decoration:none;">↓ Descargar</a>
      </div>
    </div>`).join('');
}

// ── Voz ──────────────────────────────────────────────────────────────
let _vozNombreSel = '';

function rellenarSelectorVoces(nombreSel) {
  if (nombreSel !== undefined) _vozNombreSel = nombreSel;
  const cont = document.getElementById('vozSelectorContainer');
  if (!cont) return;
  if (!window.speechSynthesis) {
    cont.innerHTML = '<p style="color:var(--text-dim);font-size:13px;">Tu navegador no soporta síntesis de voz.</p>';
    return;
  }
  const todas = window.speechSynthesis.getVoices();
  const esVoces = todas.filter(v => v.lang && v.lang.toLowerCase().startsWith('es'));
  if (!esVoces.length) {
    cont.innerHTML = '<p style="color:var(--text-dim);font-size:13px;">No hay voces en español disponibles en este navegador.</p>';
    return;
  }
  // Default preference if nothing saved
  if (!_vozNombreSel) {
    _vozNombreSel = (
      todas.find(v => v.name === 'Google español de Estados Unidos') ||
      todas.find(v => v.name === 'Google español') ||
      esVoces[0]
    )?.name || '';
  }
  const rows = esVoces.map(v => {
    const safe = v.name.replace(/'/g, "\\'");
    const checked = v.name === _vozNombreSel ? 'checked' : '';
    return `<div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--border);">
      <label style="display:flex;align-items:center;gap:8px;cursor:pointer;flex:1;min-width:0;">
        <input type="radio" name="voz_nombre" value="${v.name}" ${checked} onchange="_vozNombreSel=this.value">
        <span style="font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${v.name}</span>
        <span style="font-size:11px;color:var(--text-dim);flex-shrink:0;">(${v.lang})</span>
      </label>
      <button class="btn sm" style="flex-shrink:0;" onclick="probarVozNombre('${safe}')">▶ Probar</button>
    </div>`;
  }).join('');
  cont.innerHTML = rows;
}

function probarVozNombre(nombre) {
  if (!window.speechSynthesis) return;
  const vel = parseFloat(document.getElementById('voz_velocidad')?.value) || 0.8;
  const ton = parseFloat(document.getElementById('voz_tono')?.value) || 1.0;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance('Hola, soy ZERO. Tu asistente de ventas.');
  u.lang = 'es-CL'; u.rate = vel; u.pitch = ton; u.volume = 1.0;
  const v = window.speechSynthesis.getVoices().find(v => v.name === nombre);
  if (v) u.voice = v;
  window.speechSynthesis.speak(u);
}

async function cargarVozConfig() {
  const cfg = await fetch('/api/voz/config', {credentials:'include'}).then(r=>r.json()).catch(()=>({}));
  const kw = cfg.voz_palabra_clave || 'ZERO';
  const presets = ['ZERO','HAL','JARVIS','NOVA'];
  const sel = document.getElementById('voz_palabra_preset');
  if (presets.includes(kw)) {
    sel.value = kw;
    document.getElementById('voz_kw_custom_grp').style.display = 'none';
  } else {
    sel.value = 'custom';
    document.getElementById('voz_kw_custom_grp').style.display = '';
    document.getElementById('voz_palabra_clave').value = kw;
  }
  document.getElementById('voz_activa').checked = cfg.voz_activa !== '0';
  const vel = parseFloat(cfg.voz_velocidad || '0.8');
  const ton = parseFloat(cfg.voz_tono || '1.0');
  document.getElementById('voz_velocidad').value = vel;
  document.getElementById('voz_tono').value = ton;
  document.getElementById('voz_vel_label').textContent = vel.toFixed(1) + '×';
  document.getElementById('voz_tono_label').textContent = ton.toFixed(1);
  actualizarPreviews(kw);
  // Voice selector
  _vozNombreSel = cfg.voz_nombre || '';
  if (window.speechSynthesis) {
    window.speechSynthesis.onvoiceschanged = () => rellenarSelectorVoces();
    rellenarSelectorVoces();
  }
}

function vozPresetChange() {
  const v = document.getElementById('voz_palabra_preset').value;
  document.getElementById('voz_kw_custom_grp').style.display = v === 'custom' ? '' : 'none';
  if (v !== 'custom') actualizarPreviews(v);
}

function actualizarPreviews(kw) {
  for (let i = 1; i <= 6; i++) {
    const el = document.getElementById('voz_kw_preview' + (i === 1 ? '' : i));
    if (el) el.textContent = kw;
  }
}

async function guardarVoz() {
  let kw = document.getElementById('voz_palabra_preset').value;
  if (kw === 'custom') kw = document.getElementById('voz_palabra_clave').value.trim() || 'ZERO';
  const data = {
    voz_activa:       document.getElementById('voz_activa').checked ? '1' : '0',
    voz_palabra_clave: kw.toUpperCase(),
    voz_velocidad:    document.getElementById('voz_velocidad').value,
    voz_tono:         document.getElementById('voz_tono').value,
    voz_nombre:       _vozNombreSel,
    voz_volumen:      '1.0',
  };
  const r = await fetch('/api/voz/config', {
    method:'POST', credentials:'include',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(data),
  }).then(r=>r.json());
  if (r.ok) { showFeedback('fb_voz'); actualizarPreviews(kw.toUpperCase()); }
  else alert('Error: ' + (r.error || 'desconocido'));
}

function probarVoz() {
  const kw = document.getElementById('voz_palabra_preset').value === 'custom'
    ? document.getElementById('voz_palabra_clave').value || 'ZERO'
    : document.getElementById('voz_palabra_preset').value;
  const vel = parseFloat(document.getElementById('voz_velocidad').value);
  const ton = parseFloat(document.getElementById('voz_tono').value);
  if (!window.speechSynthesis) { alert('Tu navegador no soporta síntesis de voz'); return; }
  probarVozNombre(_vozNombreSel || '');
}

async function cargarAprendizaje() {
  const container = document.getElementById('aprendizajeContainer');
  const data = await fetch('/api/voz/aprendizaje', {credentials:'include'}).then(r=>r.json()).catch(()=>({acciones:[],productos:[],variantes:[]}));

  const todas = [
    ...(data.acciones  || []).map(r => ({...r, tipo:'Acción',  tipo_key:'accion',   color:'#22c55e'})),
    ...(data.productos || []).map(r => ({...r, tipo:'Producto', tipo_key:'producto', color:'#22c55e'})),
    ...(data.variantes || []).map(r => ({...r, tipo:'Variante', tipo_key:'variante', color:'#f59e0b'})),
  ];

  if (!todas.length) {
    container.innerHTML = `<p style="color:var(--text-dim);font-size:13px;padding:8px 0">
      ZERO aún no ha aprendido palabras nuevas.<br>
      Cuando digas algo que no entienda y confirmes la sugerencia, aparecerá aquí automáticamente.
    </p>`;
    return;
  }

  container.innerHTML = `<div style="overflow-x:auto">
    <table>
      <thead><tr>
        <th>Dijiste</th><th>Significa</th><th>Tipo</th><th>Usos</th><th>Aprendido</th><th></th>
      </tr></thead>
      <tbody>
      ${todas.map(r => `<tr>
        <td><strong style="color:var(--text)">"${r.palabra}"</strong></td>
        <td style="color:var(--accent2)">${r.significa}</td>
        <td><span style="color:${r.color};font-size:11px;font-weight:600">${r.tipo}</span></td>
        <td style="color:var(--text-dim)">${r.veces_usado || 0}×</td>
        <td style="color:var(--text-dim);font-size:12px">${r.aprendido || '—'}</td>
        <td><button class="btn sm danger" onclick="olvidarPalabra(${r.id},'${r.tipo_key}')">🗑 Olvidar</button></td>
      </tr>`).join('')}
      </tbody>
    </table>
  </div>`;
}

async function olvidarPalabra(id, tipo) {
  if (!confirm('¿Quieres que ZERO olvide esta palabra aprendida?')) return;
  const r = await fetch(`/api/voz/aprendizaje/${id}?tipo=${tipo}`, {
    method:'DELETE', credentials:'include'
  }).then(r=>r.json()).catch(()=>({ok:false}));
  if (r.ok) cargarAprendizaje();
  else alert('Error al eliminar');
}

async function cargarHistorialVoz() {
  const list = document.getElementById('vozHistorialList');
  const rows = await fetch('/api/voz/historial', {credentials:'include'}).then(r=>r.json()).catch(()=>[]);
  if (!rows.length) {
    list.innerHTML = '<p style="color:var(--text-dim);font-size:13px;padding:8px 0">Sin comandos hoy</p>';
    return;
  }
  list.innerHTML = `<table style="width:100%">
    <thead><tr><th>Hora</th><th>Texto</th><th>Acción detectada</th><th>Usuario</th></tr></thead>
    <tbody>
    ${rows.map(r => {
      let accionDisplay = '';
      try {
        const a = typeof r.accion === 'string' ? JSON.parse(r.accion) : r.accion;
        accionDisplay = a.accion || a.consulta || a.tipo || JSON.stringify(a).slice(0,40);
      } catch(e) { accionDisplay = String(r.accion || '').slice(0, 60); }
      return `<tr>
        <td>${(r.creado_en||'').slice(11,16)}</td>
        <td>${r.texto||''}</td>
        <td style="color:var(--accent2)">${accionDisplay}</td>
        <td>${r.usuario||'—'}</td>
      </tr>`;
    }).join('')}
    </tbody></table>`;
}

// ── Categorías ────────────────────────────────────────────────────────────────
let _catModalFn = null;
let _catArbol       = {};
let _catDeptoActivo = {};

async function cargarCatArbol() {
  const el = document.getElementById('catArbol');
  el.innerHTML = '<p style="color:var(--text-dim);font-size:13px;">Cargando...</p>';
  const resp = await fetch('/api/productos/categorias/arbol',{credentials:'include'})
    .then(r=>r.json()).catch(()=>({}));
  _catArbol = resp.departamentos || resp;
  _catDeptoActivo = resp.depto_activo || {};
  renderCatArbol(_catArbol, _catDeptoActivo);
}

async function catToggleDepto(departamento, activar) {
  await fetch('/api/productos/categorias/departamento/toggle', {
    method:'PUT', credentials:'include',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({departamento, activo: activar ? 1 : 0})
  });
  cargarCatArbol();
}

function renderCatArbol(arbol, deptoActivo) {
  const el = document.getElementById('catArbol');
  const deptos = Object.keys(arbol || {});
  if (!deptos.length) {
    el.innerHTML = '<p style="color:var(--text-dim);font-size:13px;">Sin categorías</p>';
    return;
  }
  el.innerHTML = deptos.map(depto => {
    const cats   = arbol[depto];
    const activo = deptoActivo[depto] !== false;
    const dq     = depto.replace(/'/g, "\\'").replace(/"/g, '&quot;');
    const toggleStyle = activo
      ? 'background:rgba(34,197,94,0.15);border:1px solid #22c55e;color:#22c55e'
      : 'background:rgba(239,68,68,0.15);border:1px solid #ef4444;color:#ef4444';
    return `<div class="cat-depto-section" style="${activo?'':'opacity:.55'}">
      <div class="cat-depto-header">
        <span class="cat-depto-title">${depto}</span>
        <div style="display:flex;gap:6px;align-items:center">
          <button class="btn sm" style="${toggleStyle};font-size:11px;padding:3px 10px;border-radius:20px"
            onclick="catToggleDepto('${dq}',${!activo})">${activo?'ON':'OFF'}</button>
          <button class="btn sm" onclick="catNuevaCat('${dq}')">+ Categoría</button>
        </div>
      </div>
      <div class="cat-list">
        ${cats.map(c => {
          const nq = c.nombre.replace(/'/g, "\\'").replace(/"/g, '&quot;');
          const iq = (c.icono||'📦').replace(/'/g, "\\'").replace(/"/g, '&quot;');
          return `<div class="cat-row">
            <span class="cat-icono">${c.icono||'📦'}</span>
            <span class="cat-nombre">${c.nombre}</span>
            <span class="cat-count">${c.total_productos} prod.</span>
            <div class="cat-actions">
              <button class="btn sm" title="Editar"
                onclick="catEditarCat(${c.id},'${nq}','${dq}','${iq}')">✏️</button>
              <button class="btn sm danger" title="Eliminar"
                onclick="catEliminarCat(${c.id},'${nq}',${c.total_productos})">🗑️</button>
            </div>
          </div>`;
        }).join('')}
      </div>
    </div>`;
  }).join('');
}

function _catDeptoOptions(selected) {
  return Object.keys(_catArbol).map(d =>
    `<option value="${d.replace(/"/g,'&quot;')}" ${d===selected?'selected':''}>${d}</option>`
  ).join('');
}

function catNuevaCat(depto) {
  document.getElementById('catModalTitle').textContent = '+ Nueva categoría';
  document.getElementById('catModalOkBtn').textContent = 'Crear';
  document.getElementById('catModalBody').innerHTML = `
    <div class="form-group" style="margin-bottom:12px;">
      <label>Nombre</label>
      <input id="catInNombre" class="cat-input" placeholder="Ej: Frutas Exóticas">
    </div>
    <div class="form-group" style="margin-bottom:12px;">
      <label>Ícono (emoji)</label>
      <input id="catInIcono" class="cat-input" placeholder="📦" value="📦">
    </div>
    <div class="form-group">
      <label>Departamento</label>
      <input id="catInDepto" class="cat-input" list="catDeptoList" value="${depto.replace(/"/g,'&quot;')}">
      <datalist id="catDeptoList">${Object.keys(_catArbol).map(d=>`<option value="${d}">`).join('')}</datalist>
    </div>`;
  _catModalFn = async () => {
    const nombre = document.getElementById('catInNombre').value.trim();
    const icono  = document.getElementById('catInIcono').value.trim() || '📦';
    const dept   = document.getElementById('catInDepto').value.trim() || depto;
    if (!nombre) { document.getElementById('catInNombre').focus(); return; }
    const r = await fetch('/api/productos/categorias',{
      method:'POST', credentials:'include',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({nombre, icono, departamento: dept}),
    }).then(r=>r.json());
    if (r.ok) { catCerrarModal(); cargarCatArbol(); }
    else alert(r.error || 'Error al crear categoría');
  };
  _catAbrirModal();
}

function catEditarCat(id, nombre, depto, icono) {
  document.getElementById('catModalTitle').textContent = '✏️ Editar categoría';
  document.getElementById('catModalOkBtn').textContent = 'Guardar';
  document.getElementById('catModalBody').innerHTML = `
    <div class="form-group" style="margin-bottom:12px;">
      <label>Nombre</label>
      <input id="catInNombre" class="cat-input" value="${nombre.replace(/"/g,'&quot;')}">
    </div>
    <div class="form-group" style="margin-bottom:12px;">
      <label>Ícono (emoji)</label>
      <input id="catInIcono" class="cat-input" value="${(icono||'📦').replace(/"/g,'&quot;')}">
    </div>
    <div class="form-group">
      <label>Departamento</label>
      <input id="catInDepto" class="cat-input" list="catDeptoListE" value="${depto.replace(/"/g,'&quot;')}">
      <datalist id="catDeptoListE">${Object.keys(_catArbol).map(d=>`<option value="${d}">`).join('')}</datalist>
    </div>`;
  _catModalFn = async () => {
    const n   = document.getElementById('catInNombre').value.trim();
    const ico = document.getElementById('catInIcono').value.trim() || '📦';
    const d   = document.getElementById('catInDepto').value.trim();
    if (!n) { document.getElementById('catInNombre').focus(); return; }
    const r = await fetch(`/api/productos/categorias/${id}`,{
      method:'PUT', credentials:'include',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({nombre:n, icono:ico, departamento:d}),
    }).then(r=>r.json());
    if (r.ok) { catCerrarModal(); cargarCatArbol(); }
    else alert(r.error || 'Error al guardar');
  };
  _catAbrirModal();
}

async function catEliminarCat(id, nombre, total) {
  if (total > 0) {
    const cats = await fetch('/api/productos/categorias?todas=1',{credentials:'include'}).then(r=>r.json()).catch(()=>[]);
    const opts = cats.filter(c=>c.id!==id)
      .map(c=>`<option value="${c.id}">${c.nombre}</option>`).join('');
    document.getElementById('catModalTitle').textContent = '🗑️ Eliminar categoría';
    document.getElementById('catModalOkBtn').textContent = 'Mover y eliminar';
    document.getElementById('catModalBody').innerHTML = `
      <p style="font-size:13px;color:var(--text-dim);margin-bottom:14px;">
        <strong style="color:var(--text)">"${nombre}"</strong> tiene
        <strong style="color:var(--warning)">${total} productos</strong>.<br>
        Elige a qué categoría moverlos:
      </p>
      <div class="form-group">
        <label>Mover productos a</label>
        <select id="catInMoverA" class="cat-select">${opts}</select>
      </div>`;
    _catModalFn = async () => {
      const moverId = document.getElementById('catInMoverA').value;
      const r = await fetch(`/api/productos/categorias/${id}?mover_a=${moverId}`,{
        method:'DELETE', credentials:'include',
      }).then(r=>r.json());
      if (r.ok) { catCerrarModal(); cargarCatArbol(); }
      else alert(r.error || 'Error al eliminar');
    };
    _catAbrirModal();
  } else {
    if (!confirm(`¿Eliminar la categoría "${nombre}"?`)) return;
    const r = await fetch(`/api/productos/categorias/${id}`,{
      method:'DELETE', credentials:'include',
    }).then(r=>r.json());
    if (r.ok) cargarCatArbol();
    else alert(r.error || 'Error al eliminar');
  }
}

function catNuevoDepto() {
  document.getElementById('catModalTitle').textContent = '+ Nuevo departamento';
  document.getElementById('catModalOkBtn').textContent = 'Crear';
  document.getElementById('catModalBody').innerHTML = `
    <p style="font-size:12px;color:var(--text-dim);margin-bottom:14px;">
      Crea el departamento y luego añade categorías con [+ Categoría].
    </p>
    <div class="form-group" style="margin-bottom:12px;">
      <label>Nombre del departamento</label>
      <input id="catInNombre" class="cat-input" placeholder="Ej: Electrónica">
    </div>
    <div class="form-group">
      <label>Ícono (emoji)</label>
      <input id="catInIcono" class="cat-input" placeholder="💡" value="📦">
    </div>`;
  _catModalFn = async () => {
    const nombre = document.getElementById('catInNombre').value.trim();
    if (!nombre) { document.getElementById('catInNombre').focus(); return; }
    const r = await fetch('/api/productos/departamentos',{
      method:'POST', credentials:'include',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({nombre}),
    }).then(r=>r.json());
    if (r.ok) {
      catCerrarModal();
      _catArbol[nombre] = [];
      renderCatArbol(_catArbol, _catDeptoActivo);
    } else {
      alert(r.error || 'Error al crear departamento');
    }
  };
  _catAbrirModal();
}

function _catAbrirModal() {
  document.getElementById('catModalOverlay').classList.add('open');
  setTimeout(() => document.getElementById('catInNombre')?.focus(), 60);
}

function catCerrarModal() {
  document.getElementById('catModalOverlay').classList.remove('open');
  document.getElementById('catModalOkBtn').textContent = 'Guardar';
  _catModalFn = null;
}

async function catModalOk() {
  if (_catModalFn) await _catModalFn();
}

init();

// ── Equipo: Usuarios + Sucursales ─────────────────────────────────────────────

let _sucursales = [];

async function cargarEquipo() {
  await Promise.all([cargarSucursales(), cargarUsuarios()]);
  cargarAsistencia();
}

async function cargarAsistencia() {
  const el = document.getElementById('tablaAsistencia');
  if (!el) return;
  el.innerHTML = '<p style="color:var(--text-dim);font-size:13px">Cargando...</p>';
  try {
    const rows = await fetch('/api/auth/asistencia?semana=actual', {credentials:'include'}).then(r=>r.json());
    if (!rows.length) { el.innerHTML = '<p style="color:var(--text-dim);font-size:13px">Sin registros esta semana.</p>'; return; }

    // Obtener resúmenes para barra de progreso
    const resumenes = await fetch('/api/auth/asistencia/resumen', {credentials:'include'}).then(r=>r.json()).catch(()=>[]);
    const resumMap = {};
    (Array.isArray(resumenes) ? resumenes : [resumenes]).forEach(r => { resumMap[r.usuario_id] = r; });

    el.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="color:var(--text-dim)">
        <th style="text-align:left;padding:6px 8px">Fecha</th>
        <th style="text-align:left;padding:6px 8px">Usuario</th>
        <th style="text-align:left;padding:6px 8px">Entrada</th>
        <th style="text-align:left;padding:6px 8px">Colación</th>
        <th style="text-align:left;padding:6px 8px">Regreso</th>
        <th style="text-align:left;padding:6px 8px">Salida</th>
        <th style="text-align:left;padding:6px 8px">Horas</th>
      </tr></thead>
      <tbody>
        ${rows.map(d => {
          const col = d.salida_colacion ? `${d.salida_colacion}` : '—';
          const reg = d.entrada_colacion ? `${d.entrada_colacion}` : '—';
          const hrs = d.horas !== null ? `${d.horas}h` : '—';
          return `<tr style="border-top:1px solid var(--border)">
            <td style="padding:8px;color:var(--text-dim)">${d.fecha}</td>
            <td style="padding:8px;font-weight:600">${d.usuario_nombre}</td>
            <td style="padding:8px">${d.entrada || '—'}</td>
            <td style="padding:8px;color:var(--text-dim)">${col}</td>
            <td style="padding:8px;color:var(--text-dim)">${reg}</td>
            <td style="padding:8px">${d.salida || '—'}</td>
            <td style="padding:8px;font-weight:600;color:${d.horas>=8?'#22c55e':'var(--text)'}">${hrs}</td>
          </tr>`;
        }).join('')}
      </tbody></table>
    ${Object.values(resumMap).map(r => {
      const pct = Math.min(100, Math.round((r.horas_semana / r.jornada_pactada) * 100));
      const color = pct >= 100 ? '#ef4444' : pct >= 90 ? '#f59e0b' : '#22c55e';
      return `<div style="margin-top:8px;font-size:12px;color:var(--text-dim)">
        <span style="font-weight:600;color:var(--text)">${r.usuario_nombre}</span>
        — ${r.horas_semana}h de ${r.jornada_pactada}h pactadas (${pct}%)
        <div style="height:6px;background:var(--surface2);border-radius:3px;margin-top:4px;overflow:hidden">
          <div style="height:100%;width:${pct}%;background:${color};border-radius:3px;transition:width .4s"></div>
        </div></div>`;
    }).join('')}`;
  } catch(e) {
    el.innerHTML = '<p style="color:#ef4444;font-size:13px">Error cargando asistencia.</p>';
  }
}

async function cargarSucursales() {
  const rows = await fetch('/api/auth/sucursales', {credentials:'include'}).then(r=>r.json()).catch(()=>[]);
  _sucursales = Array.isArray(rows) ? rows : [];
  const el = document.getElementById('listaSucursales');
  if (!_sucursales.length) {
    el.innerHTML = '<p style="color:var(--text-dim);font-size:13px">Sin sucursales registradas. El sistema funciona sin sucursales.</p>';
    return;
  }
  el.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:13px">
    <thead><tr style="color:var(--text-dim)">
      <th style="text-align:left;padding:6px 8px">Nombre</th>
      <th style="text-align:left;padding:6px 8px">Dirección</th>
      <th style="text-align:left;padding:6px 8px">Estado</th>
      <th style="padding:6px 8px"></th>
    </tr></thead>
    <tbody>
      ${_sucursales.map(s=>`<tr style="border-top:1px solid var(--border)">
        <td style="padding:8px">${s.nombre}</td>
        <td style="padding:8px;color:var(--text-dim)">${s.direccion||'—'}</td>
        <td style="padding:8px"><span style="background:${s.activa?'#0f2d1a':'#2d1515'};color:${s.activa?'#86efac':'#f87171'};border-radius:4px;padding:2px 8px;font-size:11px">${s.activa?'Activa':'Inactiva'}</span></td>
        <td style="padding:8px"><button class="btn" style="padding:4px 10px;font-size:12px" onclick="editarSucursal(${s.id})">Editar</button></td>
      </tr>`).join('')}
    </tbody></table>`;
}

async function cargarUsuarios() {
  const rows = await fetch('/api/auth/usuarios', {credentials:'include'}).then(r=>r.json()).catch(()=>[]);
  const el = document.getElementById('listaUsuarios');
  const ROLES_LABEL = {admin:'Admin',supervisor:'Supervisor',cajero:'Cajero',vendedor:'Vendedor',bodega:'Bodega',delivery:'Delivery',cocina:'Cocina'};
  const suc_map = Object.fromEntries(_sucursales.map(s=>[s.id, s.nombre]));
  el.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:13px">
    <thead><tr style="color:var(--text-dim)">
      <th style="text-align:left;padding:6px 8px">Nombre</th>
      <th style="text-align:left;padding:6px 8px">Rol</th>
      <th style="text-align:left;padding:6px 8px">Sucursal</th>
      <th style="text-align:left;padding:6px 8px">Estado</th>
      <th style="padding:6px 8px"></th>
    </tr></thead>
    <tbody>
      ${rows.map(u=>`<tr style="border-top:1px solid var(--border)">
        <td style="padding:8px;font-weight:${u.rol==='admin'?'700':'400'}">${u.nombre}</td>
        <td style="padding:8px;color:var(--text-dim)">${ROLES_LABEL[u.rol]||u.rol}</td>
        <td style="padding:8px;color:var(--text-dim)">${suc_map[u.sucursal_id]||'—'}</td>
        <td style="padding:8px"><span style="background:${u.activo?'#0f2d1a':'#2d1515'};color:${u.activo?'#86efac':'#f87171'};border-radius:4px;padding:2px 8px;font-size:11px">${u.activo?'Activo':'Inactivo'}</span></td>
        <td style="padding:8px;display:flex;gap:6px">
          <button class="btn" style="padding:4px 10px;font-size:12px" onclick="editarUsuario(${u.id})">Editar</button>
          ${u.rol!=='admin'?`<button class="btn" style="padding:4px 10px;font-size:12px;background:${u.activo?'#2d1515':'#0f2d1a'}" onclick="toggleUsuario(${u.id},${u.activo})">${u.activo?'Desactivar':'Activar'}</button>`:''}
        </td>
      </tr>`).join('')}
    </tbody></table>`;
}

function abrirModalSucursal(id) {
  const m = document.getElementById('modalSucursal');
  document.getElementById('sucId').value = id || '';
  document.getElementById('modalSucursalTitulo').textContent = id ? 'Editar Sucursal' : 'Nueva Sucursal';
  const suc = _sucursales.find(s=>s.id===id);
  document.getElementById('sucNombre').value = suc?.nombre || '';
  document.getElementById('sucDireccion').value = suc?.direccion || '';
  document.getElementById('sucTelefono').value = suc?.telefono || '';
  m.style.display = 'flex';
}

function editarSucursal(id) { abrirModalSucursal(id); }

async function guardarSucursal() {
  const id = document.getElementById('sucId').value;
  const body = {
    nombre: document.getElementById('sucNombre').value.trim(),
    direccion: document.getElementById('sucDireccion').value.trim(),
    telefono: document.getElementById('sucTelefono').value.trim(),
  };
  if (!body.nombre) return alert('El nombre es requerido');
  const url = id ? `/api/auth/sucursales/${id}` : '/api/auth/sucursales';
  const r = await fetch(url, {method: id?'PUT':'POST', credentials:'include', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  if (r.ok) { document.getElementById('modalSucursal').style.display='none'; cargarEquipo(); }
  else alert('Error al guardar');
}

const _PERMISOS_ROL_DEFAULT = {
  admin:      {puede_anular_ventas:true,puede_ver_reportes:true,puede_editar_precios:true,puede_gestionar_stock:true,puede_hacer_descuentos:true,descuento_maximo_pct:100},
  supervisor: {puede_anular_ventas:true,puede_ver_reportes:true,puede_editar_precios:true,puede_gestionar_stock:true,puede_hacer_descuentos:true,descuento_maximo_pct:20},
  cajero:     {puede_anular_ventas:false,puede_ver_reportes:false,puede_editar_precios:false,puede_gestionar_stock:false,puede_hacer_descuentos:true,descuento_maximo_pct:5},
  vendedor:   {puede_anular_ventas:false,puede_ver_reportes:false,puede_editar_precios:false,puede_gestionar_stock:false,puede_hacer_descuentos:false,descuento_maximo_pct:0},
  bodega:     {puede_anular_ventas:false,puede_ver_reportes:true,puede_editar_precios:false,puede_gestionar_stock:true,puede_hacer_descuentos:false,descuento_maximo_pct:0},
  delivery:   {puede_anular_ventas:false,puede_ver_reportes:false,puede_editar_precios:false,puede_gestionar_stock:false,puede_hacer_descuentos:false,descuento_maximo_pct:0},
  cocina:     {puede_anular_ventas:false,puede_ver_reportes:false,puede_editar_precios:false,puede_gestionar_stock:false,puede_hacer_descuentos:false,descuento_maximo_pct:0},
};

function actualizarPermisosUI() {
  const rol = document.getElementById('usuRol').value;
  const p = _PERMISOS_ROL_DEFAULT[rol] || {};
  document.getElementById('pAnular').checked = p.puede_anular_ventas || false;
  document.getElementById('pReportes').checked = p.puede_ver_reportes || false;
  document.getElementById('pPrecios').checked = p.puede_editar_precios || false;
  document.getElementById('pStock').checked = p.puede_gestionar_stock || false;
  document.getElementById('pDescuento').checked = p.puede_hacer_descuentos || false;
  document.getElementById('pDescuentoMax').value = p.descuento_maximo_pct || 0;
}

function abrirModalUsuario() {
  const m = document.getElementById('modalUsuario');
  document.getElementById('usuId').value = '';
  document.getElementById('modalUsuarioTitulo').textContent = 'Nuevo Usuario';
  document.getElementById('usuNombre').value = '';
  document.getElementById('usuPin').value = '';
  document.getElementById('usuRol').value = 'cajero';
  // Llenar select de sucursales
  const sel = document.getElementById('usuSucursal');
  sel.innerHTML = '<option value="">Sin sucursal (ve todo)</option>' +
    _sucursales.filter(s=>s.activa).map(s=>`<option value="${s.id}">${s.nombre}</option>`).join('');
  sel.value = '';
  actualizarPermisosUI();
  m.style.display = 'flex';
}

function _onJornadaChange() {
  const v = document.getElementById('usuJornada').value;
  document.getElementById('jornadaCustomDiv').style.display = v === '0' ? '' : 'none';
}

async function editarUsuario(id) {
  const rows = await fetch('/api/auth/usuarios', {credentials:'include'}).then(r=>r.json()).catch(()=>[]);
  const u = rows.find(r=>r.id===id);
  if (!u) return;
  document.getElementById('usuId').value = id;
  document.getElementById('modalUsuarioTitulo').textContent = 'Editar Usuario';
  document.getElementById('usuNombre').value = u.nombre;
  document.getElementById('usuPin').value = '';
  document.getElementById('usuRol').value = u.rol;
  const sel = document.getElementById('usuSucursal');
  sel.innerHTML = '<option value="">Sin sucursal (ve todo)</option>' +
    _sucursales.filter(s=>s.activa).map(s=>`<option value="${s.id}">${s.nombre}</option>`).join('');
  sel.value = u.sucursal_id || '';
  // Jornada
  const jh = u.jornada_horas_semanales ?? 45;
  const jornadaOpts = [45,40,30,20];
  if (jornadaOpts.includes(jh)) {
    document.getElementById('usuJornada').value = String(jh);
    document.getElementById('jornadaCustomDiv').style.display = 'none';
  } else {
    document.getElementById('usuJornada').value = '0';
    document.getElementById('usuJornadaCustom').value = jh;
    document.getElementById('jornadaCustomDiv').style.display = '';
  }
  // Aplicar permisos custom si existen
  actualizarPermisosUI();
  if (u.permisos) {
    try {
      const p = JSON.parse(u.permisos);
      if ('puede_anular_ventas'    in p) document.getElementById('pAnular').checked = p.puede_anular_ventas;
      if ('puede_ver_reportes'     in p) document.getElementById('pReportes').checked = p.puede_ver_reportes;
      if ('puede_editar_precios'   in p) document.getElementById('pPrecios').checked = p.puede_editar_precios;
      if ('puede_gestionar_stock'  in p) document.getElementById('pStock').checked = p.puede_gestionar_stock;
      if ('puede_hacer_descuentos' in p) document.getElementById('pDescuento').checked = p.puede_hacer_descuentos;
      if ('descuento_maximo_pct'   in p) document.getElementById('pDescuentoMax').value = p.descuento_maximo_pct;
    } catch(e) {}
  }
  document.getElementById('modalUsuario').style.display = 'flex';
}

async function guardarUsuario() {
  const id = document.getElementById('usuId').value;
  const nombre = document.getElementById('usuNombre').value.trim();
  const pin = document.getElementById('usuPin').value.trim();
  const rol = document.getElementById('usuRol').value;
  const suc = document.getElementById('usuSucursal').value;
  const permisos = {
    puede_anular_ventas:    document.getElementById('pAnular').checked,
    puede_ver_reportes:     document.getElementById('pReportes').checked,
    puede_editar_precios:   document.getElementById('pPrecios').checked,
    puede_gestionar_stock:  document.getElementById('pStock').checked,
    puede_hacer_descuentos: document.getElementById('pDescuento').checked,
    descuento_maximo_pct:   parseInt(document.getElementById('pDescuentoMax').value) || 0,
  };

  if (!nombre) return alert('El nombre es requerido');
  if (!id && (pin.length !== 4 || !/^\d{4}$/.test(pin))) return alert('PIN de 4 dígitos requerido');

  const jornadaSel = document.getElementById('usuJornada').value;
  const jornada = jornadaSel === '0'
    ? (parseInt(document.getElementById('usuJornadaCustom').value) || 45)
    : parseInt(jornadaSel);
  const body = { nombre, rol, sucursal_id: suc ? parseInt(suc) : null, permisos,
                 jornada_horas_semanales: jornada };
  if (pin) body.pin = pin;

  const url = id ? `/api/auth/usuarios/${id}` : '/api/auth/usuarios';
  const method = id ? 'PUT' : 'POST';
  const r = await fetch(url, {method, credentials:'include', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  if (r.ok) { document.getElementById('modalUsuario').style.display='none'; cargarEquipo(); }
  else { const e = await r.json(); alert('Error: ' + (e.error||'No se pudo guardar')); }
}

async function toggleUsuario(id, activo) {
  if (!confirm(activo ? '¿Desactivar este usuario?' : '¿Activar este usuario?')) return;
  await fetch(`/api/auth/usuarios/${id}`, {method:'PUT', credentials:'include', headers:{'Content-Type':'application/json'}, body:JSON.stringify({activo: activo ? 0 : 1})});
  cargarEquipo();
}

function _initApariencia() {
  // Sync toggle buttons to current state
  const temaActual  = localStorage.getItem('zero-tema')  || 'oscuro';
  const colorActual = localStorage.getItem('zero-color') || 'zero';
  document.querySelectorAll('.btn-tema').forEach(b => b.classList.toggle('activo', b.dataset.tema === temaActual));
  document.querySelectorAll('.circulo-color[data-color]').forEach(b => b.classList.toggle('activo', b.dataset.color === colorActual));
}


/* ── Apariencia tab HTML (generado dinámicamente) ──────────────── */
// Append apariencia tab HTML dynamically to keep file structure clean
(function() {
  const div = document.createElement('div');
  div.className = 'tab-content';
  div.id = 'tab-apariencia';
  div.innerHTML = `
    <h2>🎨 Apariencia</h2>
    <div class="apariencia-section">
      <h3>Tema</h3>
      <div class="selector-tema">
        <button class="btn-tema" data-tema="oscuro" onclick="aplicarTema('oscuro')">🌙 Oscuro</button>
        <button class="btn-tema" data-tema="claro"  onclick="aplicarTema('claro')">☀️ Claro</button>
      </div>

      <h3>Color principal</h3>
      <div class="paleta-colores">
        <button class="circulo-color" data-color="zero"    style="background:#22c55e" onclick="aplicarColor('zero')"    title="ZERO (morado)"></button>
        <button class="circulo-color" data-color="verde"   style="background:#22c55e" onclick="aplicarColor('verde')"   title="Verde"></button>
        <button class="circulo-color" data-color="azul"    style="background:#3b82f6" onclick="aplicarColor('azul')"    title="Azul"></button>
        <button class="circulo-color" data-color="rojo"    style="background:#ef4444" onclick="aplicarColor('rojo')"    title="Rojo"></button>
        <button class="circulo-color" data-color="naranja" style="background:#f97316" onclick="aplicarColor('naranja')" title="Naranja"></button>
        <button class="circulo-color" data-color="rosa"    style="background:#ec4899" onclick="aplicarColor('rosa')"    title="Rosa"></button>
        <button onclick="abrirSelectorColor()" title="Color personalizado" style="
          width:44px;height:44px;border-radius:50%;
          background:conic-gradient(#ef4444,#f97316,#f59e0b,#22c55e,#3b82f6,#22c55e,#ec4899,#ef4444);
          border:3px solid var(--surface2);cursor:pointer;
          display:flex;align-items:center;justify-content:center;
          transition:transform 0.2s;flex-shrink:0;
        " onmouseover="this.style.transform='scale(1.1)'"
           onmouseout="this.style.transform='scale(1)'">
        </button>
      </div>

      <h3>Preview</h3>
      <div class="preview-tema">
        <div class="preview-card">
          <div class="preview-topbar">ZERO<span style="color:var(--accent)">POS</span></div>
          <div class="preview-producto">Coca-Cola 1.5L <span>$1.890</span></div>
          <button class="preview-btn">Cobrar $1.890</button>
        </div>
      </div>
    </div>
  `;
  document.querySelector('.content').appendChild(div);
  _initApariencia();
})();


/* ── Service Worker registration ──────────────────────────────── */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', {scope: '/'})
      .catch(err => console.log('SW error:', err));
  });
}


/* ── FAB Comando Stock ─────────────────────────────────────────── */
// Mostrar FAB solo en la sección stock/inventario
function _actualizarFabStock() {
  const fab = document.getElementById('fabComandoStockAdmin');
  if (!fab) return;
  const seccionActiva = document.querySelector('.nav-item.active')?.dataset?.seccion || '';
  fab.style.display = ['stock', 'inventario', 'productos'].includes(seccionActiva) ? 'flex' : 'none';
}
document.addEventListener('click', _actualizarFabStock);

function _showToastAdmin(msg) {
  if (typeof showToast === 'function') { showToast(msg); return; }
  const t = document.createElement('div');
  t.textContent = msg;
  Object.assign(t.style, {
    position:'fixed', bottom:'24px', left:'50%', transform:'translateX(-50%)',
    background:'#333', color:'#fff', padding:'12px 20px', borderRadius:'10px',
    zIndex:'9999', fontSize:'14px',
  });
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

function abrirComandoStockAdmin() {
  document.getElementById('panelComandoStockAdmin').style.transform = 'translateY(0)';
  document.getElementById('overlayComandoStockAdmin').style.display = 'block';
  document.getElementById('resultadoComandoStockAdmin').style.display = 'none';
  document.getElementById('inputComandoStockAdmin').value = '';
  setTimeout(() => document.getElementById('inputComandoStockAdmin')?.focus(), 300);
}

function cerrarComandoStockAdmin() {
  document.getElementById('panelComandoStockAdmin').style.transform = 'translateY(100%)';
  document.getElementById('overlayComandoStockAdmin').style.display = 'none';
  document.getElementById('resultadoComandoStockAdmin').style.display = 'none';
  document.getElementById('inputComandoStockAdmin').value = '';
  if (document.activeElement) document.activeElement.blur();
}

async function procesarComandoStockAdmin() {
  const input = document.getElementById('inputComandoStockAdmin');
  const texto = input?.value.trim();
  const resultado = document.getElementById('resultadoComandoStockAdmin');
  if (!texto) return;

  resultado.style.display = 'block';
  resultado.style.background = '#1e1e2e';
  resultado.style.border = '1px solid #444';
  resultado.style.color = '#ccc';
  resultado.innerHTML = '⏳ Procesando...';

  try {
    const resp = await fetch('/api/voz/comando-stock', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texto }),
    });
    const data = await resp.json();

    if (data.status === 'success') {
      resultado.style.background = '#0f2d1a';
      resultado.style.border = '1px solid #22c55e';
      resultado.style.color = '#86efac';
      resultado.innerHTML = data.mensaje;
      input.value = '';
      setTimeout(() => cerrarComandoStockAdmin(), 2500);
    } else {
      resultado.style.background = '#2d1111';
      resultado.style.border = '1px solid #ef4444';
      resultado.style.color = '#fca5a5';
      resultado.innerHTML = data.mensaje || 'Error desconocido';
    }
  } catch(e) {
    resultado.style.background = '#2d1111';
    resultado.style.color = '#fca5a5';
    resultado.innerHTML = '❌ Error de conexión';
  }
}

function activarVozStockAdmin() {
  const btn = document.getElementById('btnVozStockAdmin');
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    _showToastAdmin('⚠️ Tu navegador no soporta voz. Escribe el comando.');
    return;
  }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const recognition = new SR();
  recognition.lang = 'es-CL';
  recognition.continuous = false;
  recognition.interimResults = true;

  btn.innerHTML = '🔴 Escuchando...';
  btn.style.background = '#ef4444';
  btn.style.border = '1px solid #ef4444';

  const inputA = document.getElementById('inputComandoStockAdmin');

  recognition.onresult = (e) => {
    const interino = Array.from(e.results).map(r => r[0].transcript).join('');
    inputA.value = interino;
    if (e.results[e.results.length - 1].isFinal) {
      btn.innerHTML = '🎤 Hablar';
      btn.style.background = '';
      btn.style.border = '';
      procesarComandoStockAdmin();
    }
  };
  recognition.onerror = () => {
    btn.innerHTML = '🎤 Hablar';
    btn.style.background = '';
    btn.style.border = '';
    _showToastAdmin('No se escuchó nada. Intenta de nuevo.');
  };
  recognition.onend = () => {
    btn.innerHTML = '🎤 Hablar';
    btn.style.background = '';
    btn.style.border = '';
  };
  recognition.start();
}

// ── Publicidad ────────────────────────────────────────────────────────────────
let _pubSlides = [];
let _pubEditId = null;

async function pubCargar() {
  const lista = document.getElementById('pubListaSlides');
  if (!lista) return;
  lista.innerHTML = '<div style="color:var(--text-dim);font-size:14px">Cargando...</div>';
  try {
    const r = await fetch('/api/publicidad', {credentials:'include'});
    _pubSlides = await r.json();
    pubRenderLista();
  } catch(e) {
    lista.innerHTML = '<div style="color:#ef4444">Error al cargar slides</div>';
  }
  try {
    const cfg = await fetch('/api/publicidad/config', {credentials:'include'}).then(r=>r.json());
    document.getElementById('pubIntervalo').value = cfg.intervalo || 5;
    document.getElementById('pubTransicion').value = cfg.transicion || 'fade';
    document.getElementById('pubMostrarTexto').checked = cfg.mostrar_texto !== false;
  } catch(e) {}
}

function pubRenderLista() {
  const lista = document.getElementById('pubListaSlides');
  if (!lista) return;
  if (!_pubSlides.length) {
    lista.innerHTML = '<div style="color:var(--text-dim);font-size:14px;padding:12px 0">Sin slides. Agrega uno con el botón +.</div>';
    return;
  }
  lista.innerHTML = _pubSlides.map(s => {
    const plantInfo = s.plantilla_id ? PUB_PLANTILLAS.find(p => p.id === s.plantilla_id) : null;
    const miniatura = s.imagen_url
      ? `<img src="${s.imagen_url}" style="width:60px;height:40px;object-fit:cover;border-radius:6px;flex-shrink:0">`
      : plantInfo
        ? `<div style="width:60px;height:40px;border-radius:6px;background:linear-gradient(135deg,${plantInfo.color},${plantInfo.color}99);display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0">${plantInfo.icono}</div>`
        : `<div style="width:60px;height:40px;border-radius:6px;background:linear-gradient(135deg,${s.color||'#22c55e'},${s.color2||'#22c55e'});flex-shrink:0"></div>`;
    const badge = plantInfo
      ? `<span style="font-size:10px;background:#22c55e22;color:#94a3b8;border-radius:6px;padding:1px 6px;border:1px solid #22c55e40">🎨 ${plantInfo.nombre}</span>`
      : `<span style="font-size:10px;background:#ffffff0a;color:var(--text-dim);border-radius:6px;padding:1px 6px;border:1px solid var(--border)">🖼️ Imagen</span>`;
    return `
    <div style="display:flex;align-items:center;gap:12px;background:var(--surface2);border-radius:10px;padding:10px 14px">
      ${miniatura}
      <div style="flex:1;min-width:0">
        <div style="font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${_esc(s.titulo) || '(sin título)'}</div>
        <div style="font-size:12px;color:var(--text-dim);display:flex;gap:6px;align-items:center;margin-top:2px">
          ${badge}
          <span>${s.duracion}s</span>
        </div>
      </div>
      <div style="display:flex;gap:6px;flex-shrink:0">
        <button class="btn" style="padding:4px 10px;font-size:12px" onclick="pubAbrirModal(${s.id})">✏️</button>
        <button class="btn" style="padding:4px 10px;font-size:12px;background:#dc2626" onclick="pubEliminar(${s.id})">🗑️</button>
      </div>
    </div>`;
  }).join('');
}

// ── Metadata de plantillas ────────────────────────────────────────────────────
const PUB_PLANTILLAS = [
  {id:'producto_destacado',  icono:'🛍️',  nombre:'Producto',  color:'#22c55e',
   campos:[
    {key:'titulo',    label:'Nombre producto', type:'text', src:'slide', ph:'Manzana Roja'},
    {key:'subtitulo', label:'Descripción',     type:'text', src:'slide', ph:'Oferta de hoy'},
    {key:'precio',    label:'Precio',          type:'text', src:'datos', ph:'$990'},
    {key:'color_texto',label:'Color texto',    type:'color',src:'datos', def:'#ffffff'},
    {key:'imagen',    label:'Imagen',          type:'file', src:'slide'},
  ]},
  {id:'oferta_2x1',          icono:'🎯',  nombre:'2×1',       color:'#ef4444',
   campos:[
    {key:'titulo',    label:'Producto',      type:'text', src:'slide', ph:'Bebida 500ml'},
    {key:'precio_unit',label:'Precio c/u',   type:'text', src:'datos', ph:'$1.200 c/u'},
    {key:'color1',    label:'Color 1',       type:'color',src:'datos', def:'#ef4444'},
    {key:'color2',    label:'Color 2',       type:'color',src:'datos', def:'#f97316'},
  ]},
  {id:'precio_especial',     icono:'💰',  nombre:'Descuento', color:'#f59e0b',
   campos:[
    {key:'titulo',      label:'Producto',        type:'text', src:'slide', ph:'Queso Mantecoso'},
    {key:'precio_antes',label:'Precio anterior', type:'text', src:'datos', ph:'$2.500'},
    {key:'precio_hoy',  label:'Precio hoy',      type:'text', src:'datos', ph:'$1.890'},
    {key:'color1',      label:'Color acento',    type:'color',src:'datos', def:'#f59e0b'},
  ]},
  {id:'wifi_gratis',         icono:'📶',  nombre:'WiFi',      color:'#06b6d4',
   campos:[
    {key:'ssid',     label:'Red WiFi (SSID)', type:'text', src:'datos', ph:'MiNegocioWiFi'},
    {key:'password', label:'Contraseña',      type:'text', src:'datos', ph:'mi_clave'},
    {key:'color1',   label:'Color 1',         type:'color',src:'datos', def:'#06b6d4'},
    {key:'color2',   label:'Color 2',         type:'color',src:'datos', def:'#0ea5e9'},
  ]},
  {id:'metodos_pago',        icono:'💳',  nombre:'Pagos',     color:'#22c55e',
   campos:[
    {key:'titulo',        label:'Título',        type:'text',    src:'datos', ph:'Aceptamos'},
    {key:'efectivo',      label:'Efectivo',      type:'checkbox',src:'datos', def:true},
    {key:'transferencia', label:'Transferencia', type:'checkbox',src:'datos', def:true},
    {key:'tarjeta',       label:'Tarjeta',       type:'checkbox',src:'datos', def:false},
    {key:'khipu',         label:'Khipu',         type:'checkbox',src:'datos', def:false},
    {key:'color1',        label:'Color 1',       type:'color',   src:'datos', def:'#22c55e'},
    {key:'color2',        label:'Color 2',       type:'color',   src:'datos', def:'#22c55e'},
  ]},
  {id:'horario',             icono:'🕐',  nombre:'Horario',   color:'#10b981',
   campos:[
    {key:'titulo',        label:'Título',        type:'text', src:'slide', ph:'Horario de atención'},
    {key:'lunes_viernes', label:'Lun–Vie',       type:'text', src:'datos', ph:'08:00 – 21:00'},
    {key:'sabado',        label:'Sábado',        type:'text', src:'datos', ph:'09:00 – 20:00'},
    {key:'domingo',       label:'Domingo',       type:'text', src:'datos', ph:'Cerrado'},
    {key:'color1',        label:'Color 1',       type:'color',src:'datos', def:'#10b981'},
    {key:'color2',        label:'Color 2',       type:'color',src:'datos', def:'#059669'},
  ]},
  {id:'promocion_semana',    icono:'⏰',  nombre:'Promoción', color:'#f97316',
   campos:[
    {key:'titulo',    label:'Título',       type:'text', src:'slide', ph:'Oferta de la semana'},
    {key:'subtitulo', label:'Descripción',  type:'text', src:'slide', ph:'En lácteos seleccionados'},
    {key:'fecha_fin', label:'Válido hasta', type:'date', src:'datos'},
    {key:'color1',    label:'Color 1',      type:'color',src:'datos', def:'#f97316'},
    {key:'color2',    label:'Color 2',      type:'color',src:'datos', def:'#ef4444'},
  ]},
  {id:'nuevo_producto',      icono:'✨',  nombre:'Nuevo',     color:'#ec4899',
   campos:[
    {key:'titulo',      label:'Nombre producto', type:'text', src:'slide', ph:'Granola Artesanal'},
    {key:'descripcion', label:'Descripción',     type:'text', src:'datos', ph:'Sin azúcar agregada'},
    {key:'precio',      label:'Precio',          type:'text', src:'datos', ph:'$1.490'},
    {key:'color1',      label:'Color 1',         type:'color',src:'datos', def:'#ec4899'},
    {key:'color2',      label:'Color 2',         type:'color',src:'datos', def:'#22c55e'},
    {key:'imagen',      label:'Imagen',          type:'file', src:'slide'},
  ]},
  {id:'solo_imagen',         icono:'🖼️', nombre:'Imagen',    color:'#64748b',
   campos:[
    {key:'imagen', label:'Imagen (pantalla completa)', type:'file', src:'slide'},
  ]},
  {id:'bienvenida',          icono:'👋',  nombre:'Bienvenida',color:'#0ea5e9',
   campos:[
    {key:'nombre_negocio', label:'Nombre del negocio', type:'text', src:'datos', ph:'Mi Tienda'},
    {key:'frase',          label:'Frase del día',      type:'text', src:'datos', ph:'Tu compra de confianza'},
    {key:'color1',         label:'Color 1',            type:'color',src:'datos', def:'#22c55e'},
    {key:'color2',         label:'Color 2',            type:'color',src:'datos', def:'#22c55e'},
  ]},
];

const _INPUT_STYLE = 'width:100%;padding:8px 12px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:14px;box-sizing:border-box';
const _LABEL_STYLE = 'font-size:13px;color:var(--text-dim);display:block;margin-bottom:4px';

let _pubModoActual = 'imagen'; // 'plantilla' | 'imagen'
let _pubDatosActuales = {};
let _pubSlideActual = {};

// ── Selector de modo A / B ────────────────────────────────────────────────────
function pubSeleccionarModo(modo) {
  _pubModoActual = modo;
  const btnA = document.getElementById('pubBtnModoA');
  const btnB = document.getElementById('pubBtnModoB');
  const secA = document.getElementById('pubSeccionA');
  const secB = document.getElementById('pubSeccionB');
  if (btnA) { btnA.style.borderColor = modo === 'plantilla' ? '#22c55e' : 'var(--border)'; btnA.style.background = modo === 'plantilla' ? '#22c55e30' : 'var(--surface2)'; }
  if (btnB) { btnB.style.borderColor = modo === 'imagen'    ? '#22c55e' : 'var(--border)'; btnB.style.background = modo === 'imagen'    ? '#22c55e30' : 'var(--surface2)'; }
  if (secA) secA.style.display = modo === 'plantilla' ? 'flex' : 'none';
  if (secB) secB.style.display = modo === 'imagen'    ? 'flex' : 'none';
  if (modo === 'plantilla' && !document.querySelector('.pub-plantilla-card')) {
    pubRenderGrid();
  }
}

// ── Grid de plantillas (Sección A) ────────────────────────────────────────────
function pubRenderGrid() {
  const grid = document.getElementById('pubGridPlantillas');
  if (!grid) return;
  grid.innerHTML = PUB_PLANTILLAS.map(p => `
    <div class="pub-plantilla-card" data-pid="${p.id}"
      onclick="pubSeleccionarPlantilla('${p.id}')"
      style="cursor:pointer;border-radius:10px;padding:10px 6px;text-align:center;
             background:var(--surface2);border:2px solid var(--border);transition:all .15s;
             display:flex;flex-direction:column;gap:4px;align-items:center">
      <div style="font-size:22px;line-height:1">${p.icono}</div>
      <div style="font-size:11px;font-weight:600;color:var(--text-dim);line-height:1.2">${p.nombre}</div>
    </div>
  `).join('');
}

function pubSeleccionarPlantilla(pid) {
  const plantilla = PUB_PLANTILLAS.find(p => p.id === pid);
  if (!plantilla) return;
  document.getElementById('pubModalPlantillaSeleccionada').value = pid;
  document.querySelectorAll('.pub-plantilla-card').forEach(c => {
    const sel = c.dataset.pid === pid;
    c.style.borderColor = sel ? plantilla.color : 'var(--border)';
    c.style.background  = sel ? `${plantilla.color}22` : 'var(--surface2)';
  });
  const datos = _pubDatosActuales || {};
  const slide = _pubSlideActual || {};
  const cont  = document.getElementById('pubCamposDinamicos');
  cont.innerHTML = '';
  const colorRow = [];
  plantilla.campos.forEach(campo => {
    if (campo.type === 'color') { colorRow.push(campo); return; }
    const wrap = document.createElement('div');
    if (campo.type === 'file') {
      wrap.innerHTML = `
        <label style="${_LABEL_STYLE}">${campo.label}</label>
        <input id="pubField_${campo.key}" type="file" accept="image/*,video/mp4"
          style="width:100%;padding:8px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px;box-sizing:border-box"
          onchange="pubOnImagenChange(this)">`;
    } else if (campo.type === 'checkbox') {
      const val = campo.src==='datos' ? datos[campo.key] : slide[campo.key];
      const chk = val !== undefined ? !!val : (campo.def !== undefined ? campo.def : false);
      wrap.style.cssText = 'display:flex;align-items:center;gap:10px';
      wrap.innerHTML = `
        <input id="pubField_${campo.key}" type="checkbox" ${chk?'checked':''} style="width:18px;height:18px;cursor:pointer">
        <label for="pubField_${campo.key}" style="font-size:14px;cursor:pointer">${campo.label}</label>`;
    } else {
      const val = campo.src==='datos' ? datos[campo.key] : (campo.src==='slide' ? slide[campo.key] : '');
      wrap.innerHTML = `
        <label style="${_LABEL_STYLE}">${campo.label}</label>
        <input id="pubField_${campo.key}" type="${campo.type}" placeholder="${campo.ph||''}"
          value="${_esc(val||campo.def||'')}" style="${_INPUT_STYLE}">`;
    }
    cont.appendChild(wrap);
  });
  if (colorRow.length) {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:12px';
    colorRow.forEach(campo => {
      const val = campo.src==='datos' ? datos[campo.key] : (slide[campo.key] || campo.def || '#22c55e');
      const div = document.createElement('div');
      div.style.flex = '1';
      div.innerHTML = `
        <label style="${_LABEL_STYLE}">${campo.label}</label>
        <input id="pubField_${campo.key}" type="color" value="${val||campo.def||'#22c55e'}"
          style="width:100%;height:38px;border-radius:8px;border:1px solid var(--border);cursor:pointer;padding:2px">`;
      row.appendChild(div);
    });
    cont.appendChild(row);
  }
}

function pubOnImagenChange(input) {
  const file = input.files[0];
  const prev = document.getElementById('pubModalPreview');
  if (file) { prev.src = URL.createObjectURL(file); prev.style.display = 'block'; }
}

// ── Abrir / cerrar modal ──────────────────────────────────────────────────────
function pubAbrirModal(id) {
  _pubEditId = id;
  const slide = id ? _pubSlides.find(s => s.id === id) : null;
  _pubSlideActual = slide || {};
  try { _pubDatosActuales = JSON.parse(slide?.datos_plantilla || '{}'); } catch(e) { _pubDatosActuales = {}; }

  document.getElementById('pubModalTitulo').textContent = slide ? 'Editar slide' : 'Nuevo slide';
  document.getElementById('pubModalId').value   = id || '';
  document.getElementById('pubModalDuracion').value = slide?.duracion || 5;
  document.getElementById('pubModalPlantillaSeleccionada').value = '';

  // Preview imagen
  const prev = document.getElementById('pubModalPreview');
  prev.src = slide?.imagen_url || '';
  prev.style.display = slide?.imagen_url && !slide?.plantilla_id ? 'block' : 'none';

  // Modo inicial según si tiene plantilla o no
  const modoInicial = slide?.plantilla_id ? 'plantilla' : 'imagen';
  // Reset botones antes de aplicar modo
  ['pubBtnModoA','pubBtnModoB'].forEach(bid => {
    const b = document.getElementById(bid);
    if (b) b.style.cssText = b.getAttribute('style') || '';
  });
  pubSeleccionarModo(modoInicial);

  // Si tenía plantilla, pre-seleccionarla
  if (modoInicial === 'plantilla') {
    pubRenderGrid();
    pubSeleccionarPlantilla(slide.plantilla_id);
  }

  // Pre-rellenar campos Sección B
  const tEl = document.getElementById('pubB_titulo');
  const sEl = document.getElementById('pubB_subtitulo');
  const c1El = document.getElementById('pubB_color1');
  const c2El = document.getElementById('pubB_color2');
  if (tEl)  tEl.value  = slide?.titulo    || '';
  if (sEl)  sEl.value  = slide?.subtitulo || '';
  if (c1El) c1El.value = slide?.color     || '#22c55e';
  if (c2El) c2El.value = slide?.color2    || '#22c55e';

  document.getElementById('pubModal').style.display = 'flex';
}

function pubCerrarModal() {
  document.getElementById('pubModal').style.display = 'none';
}

// ── Guardar ───────────────────────────────────────────────────────────────────
async function pubGuardarSlide() {
  const id  = document.getElementById('pubModalId').value;
  const fd  = new FormData();
  fd.append('duracion', document.getElementById('pubModalDuracion').value);

  if (_pubModoActual === 'plantilla') {
    // Sección A
    const pid = document.getElementById('pubModalPlantillaSeleccionada').value;
    if (!pid) { alert('Elige una plantilla antes de guardar.'); return; }
    const plantilla = PUB_PLANTILLAS.find(p => p.id === pid);
    const datosObj  = {};
    plantilla?.campos.forEach(campo => {
      const el = document.getElementById('pubField_' + campo.key);
      if (!el) return;
      if (campo.type === 'file') {
        if (el.files[0]) fd.append('imagen', el.files[0]);
      } else if (campo.type === 'checkbox') {
        if (campo.src === 'slide') fd.append(campo.key, el.checked ? '1' : '0');
        else datosObj[campo.key] = el.checked;
      } else {
        if (campo.src === 'slide') fd.append(campo.key, el.value);
        else datosObj[campo.key] = el.value;
      }
    });
    if (!fd.has('titulo'))    fd.append('titulo',    _pubSlideActual.titulo    || '');
    if (!fd.has('subtitulo')) fd.append('subtitulo', _pubSlideActual.subtitulo || '');
    if (!fd.has('color'))     fd.append('color',     _pubSlideActual.color     || '#22c55e');
    if (!fd.has('color2'))    fd.append('color2',    _pubSlideActual.color2    || '#22c55e');
    fd.append('plantilla_id',    pid);
    fd.append('datos_plantilla', JSON.stringify(datosObj));

  } else {
    // Sección B — flujo imagen original
    fd.append('titulo',    document.getElementById('pubB_titulo').value);
    fd.append('subtitulo', document.getElementById('pubB_subtitulo').value);
    fd.append('color',     document.getElementById('pubB_color1').value);
    fd.append('color2',    document.getElementById('pubB_color2').value);
    const img = document.getElementById('pubB_imagen').files[0];
    if (img) fd.append('imagen', img);
    fd.append('datos_plantilla', '{}');
    // plantilla_id vacío → NULL en el backend
  }

  try {
    const url    = id ? `/api/publicidad/${id}` : '/api/publicidad';
    const method = id ? 'PUT' : 'POST';
    const r = await fetch(url, {method, body: fd, credentials:'include'});
    if (!r.ok) throw new Error(await r.text());
    pubCerrarModal();
    pubCargar();
  } catch(e) {
    alert('Error al guardar: ' + e.message);
  }
}

async function pubEliminar(id) {
  if (!confirm('¿Eliminar este slide?')) return;
  await fetch(`/api/publicidad/${id}`, {method:'DELETE', credentials:'include'});
  pubCargar();
}

async function pubGuardarConfig() {
  const body = {
    intervalo: parseInt(document.getElementById('pubIntervalo').value),
    transicion: document.getElementById('pubTransicion').value,
    mostrar_texto: document.getElementById('pubMostrarTexto').checked,
  };
  const r = await fetch('/api/publicidad/config', {
    method:'PUT', credentials:'include',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(body),
  });
  if (r.ok) { const btn=event.target; const o=btn.textContent; btn.textContent='✓ Guardado'; setTimeout(()=>btn.textContent=o,1500); }
}

// Hover effect FAB admin
const _fabA = document.getElementById('fabComandoStockAdmin');
if (_fabA) {
  _fabA.addEventListener('mouseenter', () => {
    _fabA.style.transform = 'scale(1.05)';
    _fabA.style.boxShadow = '0 6px 24px rgba(0,0,0,0.5)';
  });
  _fabA.addEventListener('mouseleave', () => {
    _fabA.style.transform = '';
    _fabA.style.boxShadow = '0 4px 16px rgba(0,0,0,0.4)';
  });
}
