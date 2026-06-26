/* ═══════════════════════════════════════════════════════════════
   ZERO POS — pos.js
   Lógica principal de la pantalla de caja (pos.html)
   Depende de: zero-utils.js, zero-config.js, zero-temas.js
═══════════════════════════════════════════════════════════════ */

/* ── Marca nav item activo en el drawer ─────────────────────── */
(function() {
  const p = window.location.pathname;
  const map = {
    '/static/admin.html':      'navAdmin',
    '/static/inventario.html': 'navInventario',
  };
  const id = map[p];
  if (id) document.getElementById(id)?.classList.add('activo');
  if (p === '/static/pedidos.html') {
    document.querySelector('[data-navid="navPedidos"]')?.classList.add('activo');
  }
})();

/* ── Variables globales, carrito, productos, init ─────────────── */
let productos = [];
let carrito = [];
let cfgApp = {};  // config del negocio cargada al inicio
let _meId     = null;
let _meRol    = null;
let _meNombre = '';

function _actualizarTurnoBadge(abierto) {
  const el = document.getElementById('turnoBadge');
  if (!el) return;
  if (abierto) {
    const terminal = cfgApp.nombre_terminal || cfgApp.nombre_negocio || 'Caja';
    document.getElementById('turnoBadgeTexto').textContent =
      `Turno abierto · ${terminal} · ${_meNombre}`;
    el.style.display = 'flex';
  } else {
    el.style.display = 'none';
  }
}
let _fetchProductosCtrl = null;

// ── Cart localStorage ────────────────────────────────────────
window.guardarCarritoLocal = function(items, usuarioId) {
  if (items.length > 200) {
    typeof showToast === 'function' && showToast('Máximo 200 productos por venta', 'warning');
    return;
  }
  try {
    localStorage.setItem('zero_carrito_v1', JSON.stringify({
      items: items.map(item => ({
        id: item.producto_id,
        nombre: item.nombre,
        cantidad: item.cantidad,
        variante_id: item.variante_id || null,
        precio: item.precio_unit
      })),
      usuario_id: usuarioId,
      timestamp: Date.now()
    }));
  } catch(e) { console.warn('localStorage lleno:', e); }
};
window.recuperarCarritoLocal = function(usuarioId) {
  try {
    const raw = localStorage.getItem('zero_carrito_v1');
    if (!raw) return [];
    const data = JSON.parse(raw);
    if (data.usuario_id !== usuarioId) return [];
    if (Date.now() - data.timestamp > 86400000) return [];
    return data.items || [];
  } catch(e) { return []; }
};
window.limpiarCarritoLocal = function() {
  localStorage.removeItem('zero_carrito_v1');
};
let modoVista = localStorage.getItem('modo_vista') || 'grid';
let categoriaActual = '';
let subcatActual = '';
let catIconoMap = {};
const ICONOS_CATEGORIA = {
  'Bebidas':           '🥤',
  'Lácteos':           '🥛',
  'Lácteos y Huevos':  '🥚',
  'Snacks':            '🍿',
  'Cereales':          '🌾',
  'Pastas y Arroz':    '🍝',
  'Pan y Panadería':   '🥖',
  'Conservas':         '🥫',
  'Condimentos':       '🧂',
  'Limpieza e Higiene':'🧼',
  'Aceites':           '🫙',
  'Abarrotes':         '🛒',
  'Otros':             '📦',
};

let productoMap = {};
let todosProductos = [];    // always the full unfiltered list, for voice search
let todosProductosMap = {}; // id → product, from todosProductos
let indiceCodigo = new Map();  // codigo_barras → product (O(1) scan lookup)
let indiceId = new Map();       // product.id → product
const scanTiempos = [];
let metodoPago = 'efectivo';
let total = 0;
let _creditClienteId = null;
let _creditClienteNuevo = false;

// Smart emoji: category icon → category name map → name-based keyword → fallback
function getProductEmoji(prod) {
  const catIco = catIconoMap[prod.categoria_id];
  if (catIco && catIco !== '📦') return catIco;
  const catNombreIco = ICONOS_CATEGORIA[prod.categoria_nombre];
  if (catNombreIco && catNombreIco !== '📦') return catNombreIco;
  const n = (prod.nombre || '').toLowerCase();
  // Bebidas con gas / soft drinks
  if (/coca[\s-]?cola|coca/.test(n)) return '🥤';
  if (/pepsi/.test(n)) return '🥤';
  if (/fanta/.test(n)) return '🧡';
  if (/sprite/.test(n)) return '🍋';
  if (/7[\s-]?up/.test(n)) return '🍋';
  if (/bilz|pap[iy]/.test(n)) return '🥤';
  if (/gaseosa|refresco|bebida\s+gaseo/.test(n)) return '🥤';
  if (/monster|red\s*bull|energizante|energy/.test(n)) return '⚡';
  // Agua
  if (/agua\s+min|agua\s+sin\s+gas|agua\s+con\s+gas|agua/.test(n)) return '💧';
  // Jugos / néctares
  if (/jugo|n[eé]ctar|limonada|naranjada/.test(n)) return '🧃';
  // Leche / lácteos
  if (/leche/.test(n)) return '🥛';
  if (/yogur|yoghurt/.test(n)) return '🍶';
  if (/queso/.test(n)) return '🧀';
  if (/mantequilla|manteca|margarina/.test(n)) return '🧈';
  if (/crema/.test(n)) return '🥛';
  // Pan
  if (/marraqueta|hallulla|baguette|pan\s+integral|pan\s+de\s+molde|pan/.test(n)) return '🍞';
  if (/tostada|tostado|galleta\s+de\s+agua|galleta\s+sal/.test(n)) return '🥨';
  // Café / té / infusiones
  if (/nescaf[eé]|lavazza|starbucks|caf[eé]\s+inst/.test(n)) return '☕';
  if (/caf[eé]|espresso|latte|cappuccino/.test(n)) return '☕';
  if (/t[eé]\s+en\s+bolsa|t[eé]\s+negro|t[eé]\s+verde|t[eé]\s+menta|t[eé]/.test(n)) return '🍵';
  if (/hierba\s+mate|mate/.test(n)) return '🧉';
  if (/cacao|cocoa|milo|nesquik/.test(n)) return '🍫';
  // Alcohol
  if (/cerveza|birra|schop/.test(n)) return '🍺';
  if (/vino\s+tinto|vino\s+blanco|vino\s+ros[aá]do|vino/.test(n)) return '🍷';
  if (/pisco|ron|vodka|whisky|whiskey|tequila|gin|brandy|cognac/.test(n)) return '🥃';
  if (/champa[ñn]a|espumante|cava/.test(n)) return '🍾';
  if (/sidra/.test(n)) return '🍺';
  // Conservas / enlatados
  if (/at[uú]n|sardina|anchoa/.test(n)) return '🐟';
  if (/tomate\s+en\s+lata|tomate\s+triturado|pasta\s+de\s+tomate/.test(n)) return '🍅';
  if (/lenteja|garbanzo|poroto|fr[eé]jol|arveja|choclo/.test(n)) return '🫘';
  // Carnes
  if (/pollo|pechuga|muslo|pavo/.test(n)) return '🍗';
  if (/vacuno|carne\s+molida|filete|bistec|asado|lomo\s+vetado|lomo\s+liso/.test(n)) return '🥩';
  if (/cerdo|chuleta|costilla|tocino|panceta/.test(n)) return '🥓';
  if (/salchicha|vienesa|hot[\s-]?dog|salami|jamón|jamon/.test(n)) return '🌭';
  if (/chorizo/.test(n)) return '🌭';
  // Mariscos / pescados
  if (/salmon|salm[oó]n/.test(n)) return '🐟';
  if (/camarón|camaron|langostino|pulpo|calamar/.test(n)) return '🦐';
  // Cereales / granos
  if (/arroz/.test(n)) return '🍚';
  if (/fideos|pasta|tallar[ií]n|espagueti|penne/.test(n)) return '🍝';
  if (/harina/.test(n)) return '🌾';
  if (/avena/.test(n)) return '🌾';
  if (/corn\s*flakes|cereal|muesli/.test(n)) return '🥣';
  // Condimentos / salsas
  if (/aceite\s+de\s+oliva|aceite\s+vegetal|aceite/.test(n)) return '🫙';
  if (/vinagre/.test(n)) return '🫙';
  if (/sal|sal\s+de\s+mesa/.test(n)) return '🧂';
  if (/az[uú]car/.test(n)) return '🍬';
  if (/miel/.test(n)) return '🍯';
  if (/salsa\s+de\s+tomate|ketchup|ket?chup/.test(n)) return '🍅';
  if (/mayonesa|mayo/.test(n)) return '🫙';
  if (/mostaza/.test(n)) return '🌭';
  if (/mermelada|confit[uú]ra/.test(n)) return '🍓';
  if (/manjar|dulce\s+de\s+leche/.test(n)) return '🍮';
  // Frutas y verduras frescas
  if (/manzana/.test(n)) return '🍎';
  if (/pera/.test(n)) return '🍐';
  if (/naranja/.test(n)) return '🍊';
  if (/pl[aá]tano|banana/.test(n)) return '🍌';
  if (/frutilla|fresa/.test(n)) return '🍓';
  if (/uva/.test(n)) return '🍇';
  if (/lim[oó]n/.test(n)) return '🍋';
  if (/piña|ananá/.test(n)) return '🍍';
  if (/melón|melon/.test(n)) return '🍈';
  if (/sand[ií]a/.test(n)) return '🍉';
  if (/durazno|duraznos|melocot[oó]n/.test(n)) return '🍑';
  if (/kiwi/.test(n)) return '🥝';
  if (/mango/.test(n)) return '🥭';
  if (/tomate/.test(n)) return '🍅';
  if (/papa|patata/.test(n)) return '🥔';
  if (/cebolla/.test(n)) return '🧅';
  if (/ajo/.test(n)) return '🧄';
  if (/zanahoria/.test(n)) return '🥕';
  if (/lechuga|espinaca|acelga|kale/.test(n)) return '🥬';
  if (/brocol[ií]|coliflor/.test(n)) return '🥦';
  if (/pepino/.test(n)) return '🥒';
  if (/pimiento|pimentón|pimt[oó]n/.test(n)) return '🫑';
  if (/corn[oó]|choclo\s+fresco/.test(n)) return '🌽';
  if (/champi[ñn][oó]n|hongo/.test(n)) return '🍄';
  if (/palta|aguacate/.test(n)) return '🥑';
  // Huevos
  if (/huevo/.test(n)) return '🥚';
  // Snacks / dulces
  if (/chocolate/.test(n)) return '🍫';
  if (/galleta|cookie/.test(n)) return '🍪';
  if (/alfajor/.test(n)) return '🍪';
  if (/caramelo|gomita|gomitas/.test(n)) return '🍬';
  if (/chupete|lollipop/.test(n)) return '🍭';
  if (/chicle|goma\s+de\s+mascar/.test(n)) return '🫧';
  if (/maní|mani|nuez|almendra|castañ[ao]|fruto\s+seco/.test(n)) return '🥜';
  if (/papas\s+fritas|chips|palitos/.test(n)) return '🍟';
  if (/kuchen|torta|pastel|queque|cake/.test(n)) return '🎂';
  if (/helado|ice\s+cream|paleta\s+helada/.test(n)) return '🍦';
  // Comida preparada
  if (/pizza/.test(n)) return '🍕';
  if (/hamburgue/.test(n)) return '🍔';
  if (/hot[\s-]?dog|completo/.test(n)) return '🌭';
  if (/empanada/.test(n)) return '🥟';
  if (/sandwich|s[aá]ndwich/.test(n)) return '🥪';
  if (/sopa|caldo/.test(n)) return '🍲';
  if (/arroz\s+con\s+leche|postre/.test(n)) return '🍮';
  // Limpieza / aseo
  if (/jab[oó]n\s+de\s+mano|jab[oó]n\s+líquido|jab[oó]n/.test(n)) return '🧼';
  if (/detergente|lava\s+loza|lava-loza|omo|ariel/.test(n)) return '🫧';
  if (/suavizante|fab|downy/.test(n)) return '🫧';
  if (/cloro|lejía|lejia|hipoclorito/.test(n)) return '🧪';
  if (/desinfectante|lysol|pinesol/.test(n)) return '🧪';
  if (/shampoo|champ[úu]|head\s*&\s*shoulders|pantene|herbal/.test(n)) return '🧴';
  if (/acondicionador|tratamiento\s+capilar/.test(n)) return '🧴';
  if (/crema\s+corporal|crema\s+facial|loci[oó]n|body\s+lotion/.test(n)) return '🧴';
  if (/desodorante|antitranspirante|axe|rexona|dove/.test(n)) return '🧴';
  if (/pasta\s+dental|cepillo\s+dent|dent[ií]frico|colgate|oral[\s-]?b/.test(n)) return '🪥';
  if (/papel\s+higi[eé]nico|pa\.hig|toilette/.test(n)) return '🧻';
  if (/toalla\s+de\s+papel|servilleta/.test(n)) return '🧻';
  if (/pa[ñn]al|pampers|huggies/.test(n)) return '👶';
  if (/preservativo|cond[oó]n/.test(n)) return '💊';
  if (/pila\s+aa|pila\s+aaa|bater[ií]a\s+aa/.test(n)) return '🔋';
  if (/encendedor|fosforo|f[oó]sforo/.test(n)) return '🔥';
  if (/cigarro|tabaco|cigarrillo|marlboro|kent|belmont/.test(n)) return '🚬';
  // Farmacia / salud
  if (/paracetamol|ibuprofeno|aspirina|analg[eé]sico/.test(n)) return '💊';
  if (/vitamina|suplemento/.test(n)) return '💊';
  if (/cura\s+rápida|curita|venda\s+elástica/.test(n)) return '🩹';
  // Categoría nombre fallback
  const cn = (prod.categoria_nombre || '').toLowerCase();
  if (/bebi|drink|bebid/.test(cn)) return '🥤';
  if (/pan[ae]|bakery|pastel/.test(cn)) return '🍞';
  if (/carne|meat|pollo/.test(cn)) return '🥩';
  if (/fruta|verdur|vegetal/.test(cn)) return '🥕';
  if (/limp|clean|aseo|higiene/.test(cn)) return '🧼';
  if (/snack|dulce|confite/.test(cn)) return '🍫';
  if (/l[aá]cteo|queso|leche/.test(cn)) return '🥛';
  if (/licor|alcohol|vino|cerveza/.test(cn)) return '🍷';
  if (/congelado/.test(cn)) return '🧊';
  return catIco || '📦';
}

const _TABLER_CAT = {
  'Bebidas':             'ti-bottle',
  'Lácteos y Huevos':    'ti-egg',
  'Pan y Panadería':     'ti-bread',
  'Cereales':            'ti-bowl',
  'Condimentos':         'ti-salt',
  'Snacks':              'ti-cookie',
  'Carnes y Fiambres':   'ti-meat',
  'Frutas y Verduras':   'ti-apple',
  'Limpieza':            'ti-spray',
  'Higiene Personal':    'ti-droplet',
  'Mascotas':            'ti-paw',
  'Congelados':          'ti-snowflake',
  'Otros':               'ti-package',
};
function getProductTablerIcon(prod) {
  const cn = prod.categoria_nombre || '';
  if (_TABLER_CAT[cn]) return _TABLER_CAT[cn];
  const cnl = cn.toLowerCase();
  if (/bebid|drink/.test(cnl))               return 'ti-bottle';
  if (/l[aá]cteo|huevo|queso|leche/.test(cnl)) return 'ti-egg';
  if (/pan|panad|baker/.test(cnl))            return 'ti-bread';
  if (/cereal/.test(cnl))                     return 'ti-bowl';
  if (/condiment|salsa|aceite/.test(cnl))     return 'ti-salt';
  if (/snack|dulce|confite|galleta/.test(cnl)) return 'ti-cookie';
  if (/carne|fiambre|embutido|pollo/.test(cnl)) return 'ti-meat';
  if (/fruta|verdur|vegetal/.test(cnl))       return 'ti-apple';
  if (/limp|aseo|clean/.test(cnl))            return 'ti-spray';
  if (/higiene|personal|cuidado/.test(cnl))   return 'ti-droplet';
  if (/mascota|animal|pet/.test(cnl))         return 'ti-paw';
  if (/congelado|frozen/.test(cnl))           return 'ti-snowflake';
  if (/otro/.test(cnl))                       return 'ti-package';
  return 'ti-shopping-bag';
}

// ── Asistente de Voz ZERO ────────────────────────────────────
let vozActiva = localStorage.getItem('voz_activa') === 'true';
let vozKW = 'ZERO';
let vozVel = 0.8;
let vozTono_ = 1.0;
let vozVolumen = 1.0;
let vozVoz = null;       // SpeechSynthesisVoice seleccionada
let vozNombre = '';      // nombre guardado en config
let vozRecog = null;
let vozSynth = window.speechSynthesis;
let vozCbOk = null;
let vozTimer = null;
let vozCtxProd = '';

function _cargarVoz() {
  const voces = vozSynth ? vozSynth.getVoices() : [];
  if (!voces.length) return;
  vozVoz =
    (vozNombre && voces.find(v => v.name === vozNombre)) ||
    voces.find(v => v.name === 'Google español de Estados Unidos') ||
    voces.find(v => v.name === 'Google español') ||
    voces.find(v => v.lang && v.lang.toLowerCase().startsWith('es')) ||
    null;
}

// ─ Local keyword parser (fallback when API unavailable) ─
function _kwFallback(texto) {
  const t = texto.toLowerCase();
  let accion = 'desconocido';
  if (/agrega|agregar|suma|sumar|añade|añadir|pon |poner|mete|meter/.test(t)) accion = 'agregar';
  else if (/quita|quitar|elimina|eliminar|saca|borra|remueve/.test(t)) accion = 'quitar';
  else if (/cobra|cobrar|paga|pagar/.test(t)) accion = 'cobrar';
  else if (/limpia|limpiar|vacía|vaciar|borra todo/.test(t)) accion = 'limpiar';
  else if (/cuánto va|cuanto va|total|cuánto llevo|cuanto llevo/.test(t)) accion = 'consultar';

  const numMap = [['un ',1],['una ',1],['dos',2],['tres',3],['cuatro',4],['cinco',5],
    ['seis',6],['siete',7],['ocho',8],['nueve',9],['diez',10]];
  let cantidad = 1;
  for (const [w, n] of numMap) { if (t.includes(w)) { cantidad = n; break; } }
  const mn = t.match(/\b(\d+)\b/); if (mn) cantidad = parseInt(mn[1]);

  let variante = '';
  for (const [re, name] of [
    [/350\s*m?l/, '350ml'], [/500\s*m?l|media\s*litro/, '500ml'],
    [/1[.,]5\s*l|litro\s*y\s*medio/, '1.5L'], [/2\s*litros?|2\s*l\b/, '2L'],
    [/\bgrande\b/, 'grande'], [/\bchic[ao]\b|\bpequeñ[ao]\b/, 'chico'],
  ]) { if (re.test(t)) { variante = name; break; } }

  const stop = new Set(['zero','hal','jarvis','nova','agrega','agregar','suma','sumar',
    'añade','añadir','pon','poner','mete','quita','quitar','elimina','saca','borra',
    'cobra','cobrar','limpia','limpiar','un','una','uno','dos','tres','cuatro','cinco',
    'el','la','los','las','de','del','al','por','favor','me','te','se','que','y','a','en']);
  const palabras = t.split(/\s+/).filter(w => !stop.has(w) && !/^\d+$/.test(w) && w.length > 1);
  return { accion, producto: palabras.join(' '), cantidad, variante };
}

async function initVoz() {
  const cfg = await fetch('/api/voz/config', {credentials:'include'})
    .then(r => r.json()).catch(() => ({}));
  vozKW      = (cfg.voz_palabra_clave || 'ZERO').toUpperCase();
  vozVel     = parseFloat(cfg.voz_velocidad || '0.8');
  vozTono_   = parseFloat(cfg.voz_tono    || '1.0');
  vozVolumen = parseFloat(cfg.voz_volumen || '1.0');
  vozNombre  = cfg.voz_nombre || '';
  if (vozSynth) {
    vozSynth.onvoiceschanged = _cargarVoz;
    _cargarVoz();
  }

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    const btn = document.getElementById('btnVoz');
    if (btn) btn.style.display = 'none';
    return;
  }

  vozRecog = new SR();
  vozRecog.continuous = true;
  vozRecog.interimResults = false;
  vozRecog.lang = 'es-CL';
  vozRecog.maxAlternatives = 3;

  vozRecog.onresult = (e) => {
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (!e.results[i].isFinal) continue;
      // Collect up to 3 alternatives
      const alts = [];
      for (let j = 0; j < e.results[i].length; j++) {
        const t = e.results[i][j].transcript.trim();
        if (t) alts.push(t);
      }
      if (!alts.length) continue;
      const txt = alts[0];
      mostrarEscuche(txt);
      if (vozActiva) {
        // Button ON: process directly, no wake word needed
        if (esSaludo(txt)) { saludarVoz(); return; }
        procesarVoz(txt, alts.slice(1));
      } else {
        // Background mode: require wake word
        const up = txt.toUpperCase();
        const idx = up.indexOf(vozKW);
        if (idx === -1) continue;
        const cmd = txt.slice(idx + vozKW.length).trim();
        if (cmd.length < 2) { hablar('Dime'); return; }
        if (esSaludo(cmd)) { saludarVoz(); return; }
        procesarVoz(cmd, []);
      }
    }
  };
  vozRecog.onerror = (e) => {
    if (e.error !== 'no-speech' && e.error !== 'aborted') console.warn('[VOZ]', e.error);
  };
  vozRecog.onend = () => {
    if (vozActiva) setTimeout(() => { try { vozRecog.start(); } catch(e){} }, 300);
  };

  actualizarBtnVoz();
  if (vozActiva) { try { vozRecog.start(); } catch(e){} }
}

function toggleVoz() {
  if (!vozRecog) { showToast('Voz no disponible en este navegador', 'error'); return; }
  vozActiva = !vozActiva;
  localStorage.setItem('voz_activa', vozActiva);
  actualizarBtnVoz();
  if (vozActiva) {
    try { vozRecog.start(); } catch(e){}
    setTimeout(() => hablar('Modo consulta activo'), 400);
    showToast('Modo consulta activo.\nPregunta sobre ventas, stock o proveedores.', 'success');
  } else {
    try { vozRecog.stop(); } catch(e){}
  }
}

function actualizarBtnVoz() {
  const btn = document.getElementById('btnVoz');
  if (!btn) return;
  if (vozActiva) {
    btn.className = 'btn-voz activo';
    btn.innerHTML = `<span class="voz-ondas"><span class="voz-onda"></span><span class="voz-onda"></span><span class="voz-onda"></span><span class="voz-onda"></span><span class="voz-onda"></span></span><span class="voz-kw-label"> Escuchando...</span>`;
  } else {
    btn.className = 'btn-voz';
    btn.innerHTML = `🎤 <span class="voz-kw-label">${vozKW}</span>`;
  }
}

function mostrarEscuche(txt) {
  const el = document.getElementById('vozEscuche');
  if (!el) return;
  el.textContent = `🎤 "${txt}"`;
  el.classList.add('show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 3000);
}

function esSaludo(t) {
  t = t.toLowerCase();
  return /\b(hola|buenos\s*d[ií]as|buenas\s*tardes|buenas\s*noches|oye|hey|c[oó]mo\s*est[aá]s|qu[eé]\s*tal)\b/.test(t);
}

async function saludarVoz() {
  try {
    const r = await fetch('/api/voz/saludo', {credentials: 'include'});
    const j = r.ok ? await r.json() : null;
    const resp = (j && j.respuesta) || 'Buenos días. Listo para ayudarte.';
    hablar(resp);
    showToast('🎤 ' + resp.slice(0, 80), 'success');
  } catch(e) {
    hablar('Buenos días. Listo para ayudarte.');
  }
}

async function procesarVoz(cmd, alternativas = []) {
  console.log('[VOZ consulta] cmd:', cmd);
  await consultarVoz(cmd);
  return;

  // eslint-disable-next-line no-unreachable
  const textos = [cmd, ...alternativas];
  let interp = null;

  for (const txt of textos) {
    try {
      const r = await fetch('/api/voz/interpretar', {
        method: 'POST', credentials: 'include',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({texto: txt, total_carrito: calcCarritoTotal()}),
      });
      if (!r.ok) continue;
      const data = await r.json();
      if (data.accion !== 'desconocido' || data.producto_id || data.ambiguo) {
        interp = data;
        if (txt !== cmd) mostrarEscuche(txt);
        break;
      }
      if (!interp) interp = data;
    } catch(e) {
      if (!interp) interp = _kwFallback(txt);
    }
  }

  if (!interp) interp = _kwFallback(cmd);

  const {accion, producto, producto_id, candidatos, ambiguo, cantidad, variante, variante_hint,
         respuesta_voz, metodo, monto_recibido, vuelto} = interp;

  if (accion === 'agregar') return vozAgregar(producto, cantidad || 1, variante || '', variante_hint || null, producto_id || null, ambiguo ? candidatos : []);
  if (accion === 'quitar')  return vozQuitar(producto);
  if (accion === 'cobrar')  { hablar('Abriendo cobro'); abrirCobro(); return; }
  if (accion === 'limpiar') {
    vozConfirmar('¿Limpiar el carrito?', null, () => { limpiarCarrito(); hablar('Carrito limpio'); });
    return;
  }
  if (accion === 'consultar' || accion === 'ventas_hoy' || accion === 'stock') {
    return await consultarVoz(cmd);
  }

  // BUG 3 — Cobro con método de pago por voz
  if (accion === 'seleccionar_pago' && metodo) {
    hablar(respuesta_voz);
    if (carrito.length) {
      abrirCobro();
      // Pre-select the detected payment method
      const btnMet = document.querySelector(`[data-met="${metodo}"]`);
      if (btnMet) selMetodo(btnMet);
      // Pre-fill monto if provided
      if (monto_recibido) {
        const inp = document.getElementById('montoRecibido');
        if (inp) { inp.value = monto_recibido; inp.dispatchEvent(new Event('input')); }
      }
    }
    return;
  }

  // BUG 3 — Esperando monto: sólo hablar, el siguiente comando lo aportará
  if (accion === 'esperando_monto') {
    hablar(respuesta_voz || '¿Cuánto te dieron?');
    return;
  }

  hablar(respuesta_voz || 'No entendí. Prueba: agrega, quita o cobra');
}

function esConsultaVoz(t) {
  t = t.toLowerCase();
  const esAccion = /agrega|suma|pon|quita|elimina|cobra|limpia/.test(t);
  const esQuery  = /cuánto|cuánta|cuántos|cuántas|cuanto|cuanta|quedan|queda|hoy|stock|vendí|vendi|necesito|mañana|manana|más vendido|mas vendido/.test(t);
  return esQuery && !esAccion;
}

async function consultarVoz(txt) {
  try {
    const r = await fetch('/api/voz/consulta', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({texto: txt, contexto_producto: vozCtxProd}),
    });
    const data = await r.json();
    const resp = data.respuesta || 'No pude obtener esa información';
    hablar(resp);
    showToast('🎤 ' + resp, 'success');
  } catch(e) { hablar('Error al consultar'); }
}

async function vozAgregar(nombre, qty, variante, varianteHint, productoId, candidatos) {
  // Ambiguous: multiple matches from server — ask for clarification
  if (candidatos && candidatos.length > 1) {
    const nombres = candidatos.slice(0, 2).map(c => c.nombre).join(' o ');
    hablar(`Tengo ${nombres}. ¿Cuál quieres?`);
    return;
  }

  // Resolve product: prefer server-matched id, check full catalogue, fall back to text search
  let prod = null;
  if (productoId) {
    prod = productoMap[productoId] || todosProductosMap[productoId] || null;
  }
  if (!prod && candidatos && candidatos.length === 1) {
    const cid = candidatos[0].id;
    prod = productoMap[cid] || todosProductosMap[cid] || null;
  }
  if (!prod) {
    const matches = vozBuscar(nombre);
    if (!matches.length) {
      hablar(`No encontré ${nombre || 'el producto'}. ¿Puedes repetir?`);
      return;
    }
    prod = matches[0];
  }

  vozCtxProd = prod.nombre;

  if (prod.tiene_variantes) {
    const vvs = prod._variantes && prod._variantes.length
      ? prod._variantes
      : await fetch(`/api/productos/${prod.id}/variantes`, {credentials:'include'})
          .then(r => r.json()).catch(() => []);

    let vSel = variante ? vozMatchVariante(vvs, variante) : null;
    if (!vSel && varianteHint) vSel = vozSelectByHint(vvs, varianteHint);
    if (!vSel && vvs.length === 1) vSel = vvs[0];

    if (!vSel) {
      const sizes = vvs.map(v => v.nombre).join(', ');
      hablar(`Tengo ${prod.nombre} en: ${sizes}. ¿Cuál quieres?`);
      return;
    }

    vozConfirmar(`${qty > 1 ? qty + 'x ' : ''}${prod.nombre} ${vSel.nombre}`, vSel.precio * qty, () => {
      vozSetVariante(prod, vSel, qty);
      hablar(`${prod.nombre} ${vSel.nombre} agregado. Total: ${fmt(calcCarritoTotal())}`);
    });
    return;
  }

  vozConfirmar(`${qty > 1 ? qty + 'x ' : ''}${prod.nombre}`, prod.precio * qty, () => {
    vozSetProducto(prod, qty);
    hablar(`${prod.nombre} agregado. Total: ${fmt(calcCarritoTotal())}`);
  });
}

function vozSetProducto(prod, qty) {
  const idx = carrito.findIndex(i => i.producto_id === prod.id && !i.variante_id);
  if (idx >= 0) {
    carrito[idx].cantidad = Math.min(carrito[idx].cantidad + qty, prod.stock);
  } else {
    carrito.push({
      producto_id: prod.id, variante_id: null, nombre: prod.nombre,
      nombre_variante: '', precio_unit: prod.precio,
      cantidad: Math.min(qty, prod.stock), stock: prod.stock,
    });
  }
  renderCarrito();
}

function vozSetVariante(prod, v, qty) {
  const key = `${prod.id}_v${v.id}`;
  const idx = carrito.findIndex(i => i._key === key);
  if (idx >= 0) {
    carrito[idx].cantidad = Math.min(carrito[idx].cantidad + qty, v.stock);
  } else {
    carrito.push({
      _key: key, producto_id: prod.id, variante_id: v.id,
      nombre: `${prod.nombre} — ${v.nombre}`, nombre_variante: v.nombre,
      precio_unit: v.precio, cantidad: Math.min(qty, v.stock), stock: v.stock,
    });
  }
  renderCarrito();
}

function vozQuitar(nombre) {
  if (!carrito.length) { hablar('El carrito está vacío'); return; }
  if (!nombre || /último|ultima/.test(nombre.toLowerCase())) {
    const n = carrito[carrito.length - 1].nombre;
    carrito.splice(carrito.length - 1, 1);
    renderCarrito();
    hablar(`${n} eliminado`);
    return;
  }
  const idx = carrito.findIndex(i => vozNorm(i.nombre).includes(vozNorm(nombre)));
  if (idx === -1) { hablar(`No encontré ${nombre} en el carrito`); return; }
  const n = carrito[idx].nombre;
  carrito.splice(idx, 1);
  renderCarrito();
  hablar(`${n} eliminado`);
}

function vozBuscar(busqueda) {
  const words = vozNorm(busqueda).split(' ').filter(w => w.length > 2);
  if (!words.length) return [];
  // Always search the full catalogue, not just the current category view
  const fuente = todosProductos.length ? todosProductos : productos;
  return fuente.map(p => {
    const n = vozNorm(p.nombre);
    let s = 0;
    words.forEach(w => { if (n.includes(w)) s += 2; else if (n.split(' ').some(t => t.startsWith(w) || w.startsWith(t))) s += 1; });
    return {p, s};
  }).filter(x => x.s > 0).sort((a, b) => b.s - a.s).map(x => x.p);
}

function vozMatchVariante(vvs, texto) {
  const t = vozNorm(texto);
  let v = vvs.find(v => vozNorm(v.nombre) === t);
  if (v) return v;
  v = vvs.find(v => vozNorm(v.nombre).includes(t) || t.includes(vozNorm(v.nombre)));
  if (v) return v;
  if (/chic|peq|small|mini/.test(t)) return vvs.reduce((a, b) => a.precio < b.precio ? a : b);
  if (/grand|larg|big/.test(t))      return vvs.reduce((a, b) => a.precio > b.precio ? a : b);
  return null;
}

function vozSelectByHint(vvs, hint) {
  if (!hint || !vvs.length) return null;
  if (hint.tipo === 'exacta') {
    const val = vozNorm(hint.valor || '');
    return vvs.find(v => vozNorm(v.nombre).includes(val))
        || vvs.find(v => val.includes(vozNorm(v.nombre)))
        || null;
  }
  const sorted = [...vvs].sort((a, b) => a.precio - b.precio);
  if (hint.tipo === 'pequeña') return sorted[0];
  if (hint.tipo === 'grande')  return sorted[sorted.length - 1];
  if (hint.tipo === 'mediana') return sorted[Math.floor(sorted.length / 2)];
  return null;
}

function vozNorm(s) {
  return s.toLowerCase().normalize('NFD')
    .replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9 ]/g, ' ')
    .replace(/\s+/g, ' ').trim();
}

function calcCarritoTotal() {
  const sub = carrito.reduce((s, i) => s + i.precio_unit * i.cantidad, 0);
  const desc = parseFloat(document.getElementById('descuentoInput').value) || 0;
  return Math.max(0, sub - desc);
}

function vozConfirmar(texto, precio, cb) {
  cerrarVozConfirm();
  document.getElementById('vcTexto').textContent = texto;
  document.getElementById('vcPrecio').textContent = precio ? fmt(precio) : '';
  document.getElementById('vozConfirm').style.display = 'block';
  vozCbOk = cb;
  const fill = document.getElementById('vcFill');
  fill.style.transition = 'none';
  fill.style.width = '100%';
  requestAnimationFrame(() => requestAnimationFrame(() => {
    fill.style.transition = 'width 3s linear';
    fill.style.width = '0%';
  }));
  vozTimer = setTimeout(() => { if (vozCbOk) vozCbOk(); cerrarVozConfirm(); }, 3000);
}

function confirmarVozSi() { clearTimeout(vozTimer); if (vozCbOk) vozCbOk(); cerrarVozConfirm(); }
function confirmarVozNo() { clearTimeout(vozTimer); cerrarVozConfirm(); hablar('Cancelado'); }
function cerrarVozConfirm() {
  document.getElementById('vozConfirm').style.display = 'none';
  vozCbOk = null; vozTimer = null;
}

function hablar(txt) {
  if (!vozSynth) return;
  vozSynth.cancel();
  const u = new SpeechSynthesisUtterance(txt);
  u.lang = 'es-CL'; u.rate = vozVel; u.pitch = vozTono_; u.volume = vozVolumen;
  if (vozVoz) u.voice = vozVoz;
  vozSynth.speak(u);
}

// ── Init ─────────────────────────────────────────────────────
fetch('/api/config/sistema/sincronizar-hora', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({timestamp: Math.floor(Date.now() / 1000)})
}).catch(() => {});

let _permisosPOS = {};

async function init() {
  const me = await fetch('/api/auth/me', {credentials:'include'}).then(r => r.json()).catch(() => null);
  if (!me || me.error) { location.href = 'login.html'; return; }
  _meId     = me.id;
  _meRol    = me.rol || 'cajero';
  _meNombre = me.nombre || '';
  document.getElementById('cajeroNombre').textContent = me.nombre || '';
  const _sAvatar = document.getElementById('sidebarAvatar');
  if (_sAvatar) _sAvatar.textContent = (_meNombre[0] || '?').toUpperCase();
  _permisosPOS = me.permisos || {};
  _aplicarPermisosPOS(me);

  const estado = await fetch('/api/onboarding/estado', {credentials:'include'})
    .then(r => r.json()).catch(() => ({completado: true}));
  if (!estado.completado && !estado.hay_productos) {
    location.href = 'onboarding.html';
    return;
  }

  cfgApp = await fetch('/api/config', {credentials:'include'}).then(r => r.json()).catch(() => ({}));
  await window.ZERO?._initPromise;
  const deliveryActivo = cfgApp.modulo_delivery === '1' || cfgApp.modulo_delivery === true;
  const btnPedidos = document.querySelector('[onclick*="pedidos.html"]');
  if (btnPedidos) {
    // Store: show only if delivery module explicitly enabled
    // Food/Resto/Service: always show (delivery is native)
    btnPedidos.style.display = (!window.ZERO?.isStore() || deliveryActivo) ? '' : 'none';
  }

  const linkPedidos = document.getElementById('linkPedidosDrawer');
  if (linkPedidos) linkPedidos.style.display = deliveryActivo ? '' : 'none';

  // Mostrar botón cola solo si delivery activo
  const btnCola = document.getElementById('btnColaEspera');
  if (btnCola) btnCola.style.display = deliveryActivo ? '' : 'none';

  _initVista();
  await cargarCategorias();
  await cargarProductos();

  // Recuperar carrito guardado (validar que los productos siguen en el índice)
  const itemsGuardados = recuperarCarritoLocal(_meId);
  if (itemsGuardados.length > 0) {
    let recuperados = 0;
    itemsGuardados.forEach(item => {
      const prod = indiceId.get(parseInt(item.id));
      if (prod) {
        const existente = carrito.find(c =>
          c.producto_id === item.id && c.variante_id === item.variante_id
        );
        if (existente) {
          existente.cantidad = item.cantidad;
        } else {
          carrito.push({
            producto_id: prod.id,
            nombre: prod.nombre,
            precio_unit: item.precio_unit ?? item.precio ?? prod.precio,
            cantidad: item.cantidad,
            stock: prod.stock_real ?? prod.stock,
            modo_stock: prod.modo_stock || 'normal',
            variante_id: item.variante_id || null,
            nombre_variante: item.variante_nombre || null,
            imagen_url: item.imagen_url || null,
          });
        }
        recuperados++;
      }
    });
    if (recuperados > 0) {
      renderCarrito();
      setTimeout(() => showToast(
        `🛒 ${recuperados} producto${recuperados > 1 ? 's' : ''} en tu carrito`, 'info'
      ), 1500);
    }
  }

  verificarAlertas();
  verificarTurno(me);
  initVoz();
  iniciarPollCola();
  verificarEstadoImpresora();
  _verificarTicketsPendientes();
  cargarFiadosBadge();
}

async function _verificarTicketsPendientes() {
  try {
    const r = await fetch('/api/impresora/estado', {credentials: 'include'});
    if (!r.ok) return;
    const d = await r.json();
    const btn = document.getElementById('btnImpresoraBadge');
    const badge = document.getElementById('impresoraBadge');
    if (btn && badge) {
      if (d.pendientes > 0) {
        btn.style.display = 'block';
        badge.textContent = d.pendientes > 9 ? '9+' : d.pendientes;
      } else {
        btn.style.display = 'none';
      }
    }
    if (d.pendientes > 0) {
      mostrarToastPersistente(`🖨️ Hay ${d.pendientes} ticket(s) sin imprimir. Toca para gestionar.`, 'warning');
      if (_toastPersistente) {
        _toastPersistente.onclick = () => {
          _toastPersistente.remove();
          abrirModalImpresoraCola();
        };
      }
    }
  } catch(e) {}
}
setInterval(_actualizarBadgeImpresora, 60000);

function _aplicarPermisosPOS(me) {
  const p = me.permisos || {};
  // Botones solo para admin
  if (me.rol === 'admin') {
    document.getElementById('btnCerrarSesionMenu')?.style.setProperty('display', '');
    document.getElementById('btnCerrarSesionDropdown')?.style.setProperty('display', '');
    document.getElementById('btnDashboard')?.style.setProperty('display', '');
  }
  // Ocultar botón Admin si no puede ver reportes y no es admin
  if (me.rol !== 'admin' && !p.puede_ver_reportes) {
    const btnAdmin = document.querySelector('[onclick*="admin.html"]');
    if (btnAdmin) btnAdmin.style.display = 'none';
  }
  // Ocultar ZERO CREDIT para roles sin acceso
  if (['bodega', 'delivery', 'cocina'].includes(me.rol)) {
    document.getElementById('navCredito')?.remove();
  }
  // Mostrar botón descuento solo si tiene permiso
  const descBtnRow = document.getElementById('descuentoBtnRow');
  if (descBtnRow) {
    if (p.puede_hacer_descuentos) {
      descBtnRow.style.display = 'block';
      const descInput = document.getElementById('descuentoInput');
      if (descInput) {
        const maxPct = typeof p.descuento_maximo_pct === 'number' ? p.descuento_maximo_pct : 100;
        if (maxPct > 0) descInput.dataset.maxPct = maxPct;
      }
    }
  }
}

let _turnoModo = 'abrir'; // 'abrir' | 'cerrar'
let _turnoRequerirConteo = false;

async function verificarTurno(me) {
  const t = await fetch('/api/auth/turno/actual', {credentials:'include'}).then(r => r.json());
  if (!t.turno) {
    const overlay = document.getElementById('overlayTurnoCerrado');
    overlay.style.display = 'flex';
    const usr = document.getElementById('overlayTurnoUsuario');
    if (usr && me) usr.textContent = me.nombre || me.username || '';
  } else {
    document.getElementById('overlayTurnoCerrado').style.display = 'none';
  }
  document.body.classList.remove('cargando');
  _actualizarTurnoBadge(!!t.turno);
}

async function _irAColacion() {
  if (!confirm('¿Confirmas que vas a colación?')) return;

  const rAsist = await fetch('/api/auth/asistencia', {
    method: 'POST',
    credentials: 'include',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({tipo: 'salida_colacion'})
  }).then(r => r.json()).catch(() => ({}));

  await fetch('/api/auth/turno/cerrar', {
    method: 'POST',
    credentials: 'include',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({fondo_final: 0, denominaciones: {}})
  });

  const nombre = document.getElementById('overlayTurnoUsuario')?.textContent || '';
  const hora = rAsist.hora_salida
    || new Date().toLocaleTimeString('es-CL', {hour: '2-digit', minute: '2-digit'});
  document.getElementById('overlayColacionNombre').textContent = nombre;
  document.getElementById('overlayColacionHora').textContent = hora;
  document.getElementById('overlayColacion').style.display = 'flex';
  document.getElementById('overlayTurnoCerrado').style.display = 'none';
}

async function _abrirModalTurno(modo) {
  console.log('[ZERO] _abrirModalTurno:', modo);
  _turnoModo = modo;
  const cfg = await fetch('/api/config', {credentials:'include'}).then(r=>r.json()).catch(()=>({}));
  _turnoRequerirConteo = cfg.turno_contar_denominaciones === '1';

  const titulo = modo === 'abrir' ? '💵 Abrir turno' : '🔒 Cerrar turno';
  const desc   = modo === 'abrir'
    ? 'Registra el fondo inicial de caja para comenzar el turno.'
    : 'Registra el efectivo en caja al cerrar el turno.';
  const btnLabel = modo === 'abrir' ? 'Abrir turno' : 'Cerrar turno';

  document.getElementById('modalTurnoTitulo').textContent = titulo;
  document.getElementById('modalTurnoDesc').textContent   = desc;
  document.getElementById('modalTurnoBtn').textContent    = btnLabel;

  const denoms = document.getElementById('modalTurnoDenoms');
  denoms.style.display = '';
  document.querySelectorAll('#modalTurnoDenoms input[data-denom]').forEach(i => i.value = 0);
  _calcTurnoTotal();

  // Resumen de ventas al cerrar
  const resumenDiv = document.getElementById('turnoResumenCierre');
  if (modo === 'cerrar') {
    resumenDiv.style.display = '';
    fetch('/api/auth/turno/resumen', {credentials:'include'})
      .then(r => r.json()).then(res => {
        document.getElementById('trVentas').textContent   = res.ventas_count ?? 0;
        document.getElementById('trTotal').textContent    = fmt(res.total ?? 0);
        document.getElementById('trEfectivo').textContent = fmt(res.efectivo ?? 0);
        const otros = (res.tarjeta||0) + (res.transferencia||0) + (res.credito||0);
        document.getElementById('trOtros').textContent    = fmt(otros);
      }).catch(() => {});
  } else {
    resumenDiv.style.display = 'none';
  }

  document.getElementById('modalTurno').style.display = 'flex';
}

function _calcTurnoTotal() {
  let total = 0;
  document.querySelectorAll('#modalTurnoDenoms input[data-denom]').forEach(inp => {
    const denom = parseInt(inp.dataset.denom);
    const cant  = parseInt(inp.value) || 0;
    total += denom * cant;
  });
  document.getElementById('modalTurnoTotal').textContent = '$' + total.toLocaleString('es-CL');
  return total;
}

function _getDenominaciones() {
  const denoms = {};
  let hayAlgo = false;
  document.querySelectorAll('#modalTurnoDenoms input[data-denom]').forEach(inp => {
    const cant = parseInt(inp.value) || 0;
    denoms[inp.dataset.denom] = cant;
    if (cant > 0) hayAlgo = true;
  });
  return hayAlgo ? denoms : {};
}

async function _confirmarTurno() {
  const denoms = _getDenominaciones();
  const total  = _calcTurnoTotal();

  if (_turnoModo === 'abrir') {
    const body = denoms && Object.keys(denoms).length
      ? { denominaciones: denoms }
      : { fondo_inicial: total };
    const r = await fetch('/api/auth/turno/abrir', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body),
    });
    if (r.ok) {
      const td = await r.json().catch(() => ({}));
      if (td.turno_id) sessionStorage.setItem('turno_id', String(td.turno_id));
      document.getElementById('modalTurno').style.display = 'none';
      document.getElementById('overlayTurnoCerrado').style.display = 'none';
      document.getElementById('overlayColacion').style.display = 'none';
      showToast('Turno abierto — ¡Listo para vender!', 'success');
      _actualizarTurnoBadge(true);
    } else {
      const d = await r.json();
      showToast(d.error || 'Error al abrir turno', 'error');
    }
  } else {
    const body = denoms && Object.keys(denoms).length
      ? { denominaciones: denoms }
      : { fondo_final: total };
    const r = await fetch('/api/auth/turno/cerrar', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body),
    });
    if (r.ok) {
      document.getElementById('modalTurno').style.display = 'none';
      location.href = 'login.html?modo=salida';
    } else {
      const d = await r.json();
      showToast(d.error || 'Error al cerrar turno', 'error');
    }
  }
}

// ── Departamentos, Categorías y Subcategorías ────────────────
let catDeptoMap = {};
let deptoActual = '';

const _DEPTO_META = {
  'Alimentación':               { emoji: '🛒', label: 'Alimentos' },
  'Bebidas con Alcohol':        { emoji: '🍺', label: 'Alcohol' },
  'Belleza y Cuidado Personal': { emoji: '🧴', label: 'Cuidado' },
  'Limpieza del Hogar':         { emoji: '🏠', label: 'Limpieza' },
  'Mascotas':                   { emoji: '🐾', label: 'Mascotas' },
  'Mundo Bebé':                 { emoji: '👶', label: 'Bebé' },
  'Manualidades y Hogar':       { emoji: '🧵', label: 'Hogar' },
  'Juguetes y Entretencion':    { emoji: '🎮', label: 'Juguetes' },
  'Ferretería Básica':          { emoji: '🔧', label: 'Ferreter.' },
  'Tabaco':                     { emoji: '🚬', label: 'Tabaco' },
  'Otros':                      { emoji: '📦', label: 'Otros' },
};

async function cargarCategorias() {
  const data = await fetch('/api/productos/categorias', {credentials:'include'}).then(r => r.json()).catch(() => []);
  const div = document.getElementById('categorias');
  const deptos = document.getElementById('deptos');
  const seenDeptos = new Set();
  data.forEach(c => {
    catIconoMap[c.id] = c.icono || '📦';
    catDeptoMap[c.id] = c.departamento || 'Alimentación';
    const btn = document.createElement('button');
    btn.className = 'cat-btn';
    btn.dataset.id = c.id;
    btn.textContent = (c.icono || '') + ' ' + c.nombre;
    btn.onclick = () => selCat(btn, c.id);
    div.appendChild(btn);
    const d = c.departamento || 'Alimentación';
    if (!seenDeptos.has(d)) {
      seenDeptos.add(d);
      const meta = _DEPTO_META[d] || { emoji: '📦', label: d.substring(0, 8) };
      const db = document.createElement('button');
      db.className = 'depto-btn';
      db.dataset.depto = d;
      db.onclick = () => selDepto(db, d);
      db.textContent = `${meta.emoji} ${meta.label}`;
      deptos.appendChild(db);
    }
  });
}

function selDepto(btn, depto) {
  document.querySelectorAll('.depto-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  deptoActual = depto;
  document.querySelectorAll('#categorias .cat-btn:not([data-id=""])').forEach(b => {
    const d = catDeptoMap[b.dataset.id] || 'Alimentación';
    b.style.display = (!depto || d === depto) ? '' : 'none';
  });
  const allCatBtn = document.querySelector('#categorias .cat-btn[data-id=""]');
  if (allCatBtn) selCat(allCatBtn, '');
}

async function cargarSubcategorias(catId) {
  const row = document.getElementById('subcatRow');
  if (!catId) { row.classList.remove('visible'); row.innerHTML = ''; subcatActual = ''; return; }
  const subs = await fetch(`/api/productos/subcategorias?categoria_id=${catId}`, {credentials:'include'})
    .then(r => r.json()).catch(() => []);
  if (!subs.length) { row.classList.remove('visible'); row.innerHTML = ''; subcatActual = ''; return; }

  row.innerHTML = '';
  const allBtn = document.createElement('button');
  allBtn.className = 'subcat-btn active';
  allBtn.textContent = 'Todos';
  allBtn.dataset.id = '';
  allBtn.onclick = () => selSubcat(allBtn, '');
  row.appendChild(allBtn);

  subs.forEach(s => {
    const btn = document.createElement('button');
    btn.className = 'subcat-btn';
    btn.textContent = (s.icono || '') + ' ' + s.nombre;
    btn.dataset.id = s.id;
    btn.onclick = () => selSubcat(btn, s.id);
    row.appendChild(btn);
  });
  row.classList.add('visible');
  subcatActual = '';
}

function selCat(btn, id) {
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  categoriaActual = id;
  subcatActual = '';
  cargarSubcategorias(id);
  cargarProductos();
}

function selSubcat(btn, id) {
  document.querySelectorAll('.subcat-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  subcatActual = id;
  cargarProductos();
}

// ── Productos ─────────────────────────────────────────────────
async function cargarProductos() {
  if (_fetchProductosCtrl) _fetchProductosCtrl.abort();
  _fetchProductosCtrl = new AbortController();
  const _sig = _fetchProductosCtrl.signal;
  const q = document.getElementById('searchInput').value;

  // Initial unfiltered load: fetch everything (products + variants) in one request
  if (!categoriaActual && !q) {
    let prods;
    try {
      prods = await fetch('/api/productos/completos', {credentials:'include', signal: _sig}).then(r => r.json());
    } catch(e) { if (e.name === 'AbortError') return; prods = []; }
    todosProductos = prods;
    todosProductosMap = {};
    indiceCodigo = new Map();
    indiceId = new Map();
    prods.forEach(p => {
      todosProductosMap[p.id] = p;
      indiceId.set(p.id, p);
      if (p.codigo_barras) indiceCodigo.set(String(p.codigo_barras), p);
      if (p._variantes) {
        p._variantes.forEach(v => {
          if (v.codigo_barras) indiceCodigo.set(String(v.codigo_barras), {...p, variante_seleccionada: v});
        });
      }
    });
    if (subcatActual) prods = prods.filter(p => String(p.subcategoria_id) === String(subcatActual));
    productos = prods;
    renderProductos(productos);
    return;
  }

  // Filtered load: server-side search/category filter, variants from in-memory cache
  const url = `/api/productos?activos=1${categoriaActual ? '&categoria_id=' + categoriaActual : ''}${q ? '&q=' + encodeURIComponent(q) : ''}`;
  let prods;
  try {
    prods = await fetch(url, {credentials:'include', signal: _sig}).then(r => r.json());
  } catch(e) { if (e.name === 'AbortError') return; prods = []; }

  if (subcatActual) {
    prods = prods.filter(p => String(p.subcategoria_id) === String(subcatActual));
  }

  // Attach variants from in-memory map (already loaded by completos); fetch only if missing
  await Promise.all(prods.map(async p => {
    if (!p.tiene_variantes) return;
    const cached = todosProductosMap[p.id];
    if (cached && cached._variantes) {
      p._variantes = cached._variantes;
    } else {
      try {
        p._variantes = await fetch(`/api/productos/${p.id}/variantes`, {credentials:'include'}).then(r => r.json());
      } catch(e) { p._variantes = []; }
    }
  }));

  productos = prods;
  renderProductos(productos);
}

function renderProductos(lista) {
  const grid = document.getElementById('productosGrid');
  grid.innerHTML = '';
  productoMap = {};

  // Ordenar: con stock > 0 primero, variantes (stock=-1) segundo, sin stock al final
  lista = [...lista].sort((a, b) => {
    const aDisp = a.stock > 0 || a.stock === -1 || a.tiene_variantes;
    const bDisp = b.stock > 0 || b.stock === -1 || b.tiene_variantes;
    if (aDisp && !bDisp) return -1;
    if (!aDisp && bDisp) return 1;
    return 0;
  });

  // Sync list/grid class
  if (modoVista === 'lista') {
    grid.classList.add('modo-lista');
  } else {
    grid.classList.remove('modo-lista');
  }

  if (!lista.length) {
    grid.innerHTML = '<p style="color:var(--text-dim);font-size:13px;grid-column:1/-1;padding:20px;text-align:center">Sin productos</p>';
    return;
  }

  if (modoVista === 'lista') {
    _renderProductosLista(lista, grid);
    return;
  }

  _productosFiltrados = lista;
  _paginaProductos = 0;
  if (_observerVScroll) { _observerVScroll.disconnect(); _observerVScroll = null; }
  const _btnViejo = document.getElementById('btnVerMasProductos');
  if (_btnViejo) _btnViejo.remove();
  _renderPaginaGrid(grid, 0);
}

const PRODUCTOS_POR_PAGINA = 50;
let _productosFiltrados = [];
let _paginaProductos = 0;
let _observerVScroll = null;

function _renderPaginaGrid(grid, pagina) {
  const inicio = pagina * PRODUCTOS_POR_PAGINA;
  const fin    = inicio + PRODUCTOS_POR_PAGINA;
  const slice  = _productosFiltrados.slice(inicio, fin);

  slice.forEach(p => {
    productoMap[p.id] = p;
    const modoStock = p.modo_stock || 'normal';
    const sinStock = !p.tiene_variantes && modoStock !== 'sin_stock' && p.stock <= 0;
    const div = document.createElement('div');
    div.className = 'product-card' + (sinStock ? ' sin-stock' : '');
    div.setAttribute('data-producto-id', p.id);

    // Ícono: imagen si existe, sino Tabler por categoría
    const tablerIcon = getProductTablerIcon(p);
    let iconHTML;
    if (p.imagen_url) {
      iconHTML = `<img loading="lazy" src="${escH(p.imagen_url)}"` +
        ` onerror="this.style.display='none';this.nextElementSibling.style.display='inline-flex'"` +
        ` style="width:48px;height:48px;object-fit:cover;border-radius:10px;display:block">` +
        `<i class="ti ${tablerIcon}" style="display:none;font-size:36px;color:var(--accent)"></i>`;
    } else {
      iconHTML = `<i class="ti ${tablerIcon}" style="font-size:36px"></i>`;
    }

    // Meta: precio + badge variantes
    let precioHTML;
    let varianteBadge = '';
    if (p.tiene_variantes) {
      const precioMin = (p._variantes && p._variantes.length)
        ? Math.min(...p._variantes.map(v => v.precio))
        : (p.precio || 0);
      const nVar = p._variantes ? p._variantes.length : '';
      precioHTML = `<div class="price">desde ${fmt(precioMin)}</div>`;
      varianteBadge = `<div class="badge-variants"><i class="ti ti-circle-dot" style="font-size:11px"></i>${nVar ? ' ' + nVar + ' var.' : ''}</div>`;
    } else {
      precioHTML = `<div class="price">${fmt(p.precio)}</div>`;
    }

    // Indicador de stock
    let stockHTML = '';
    if (sinStock) {
      stockHTML = `<div class="stock-out">Sin stock</div>`;
    } else if (modoStock === 'produccion') {
      const agotado = p.stock <= 0;
      if (agotado) {
        div.classList.add('sin-stock');
        stockHTML = `<div class="stock-out">AGOTADO</div>`;
      } else {
        stockHTML = `<div class="stock-low">Disponibles: ${p.stock}</div>`;
      }
    } else if (modoStock === 'normal') {
      const bajo = p.stock > 0 && p.stock <= p.stock_minimo;
      if (bajo) stockHTML = `<div class="stock-low">Quedan ${p.stock}</div>`;
    }

    div.innerHTML = `
      <div class="picon">${iconHTML}</div>
      <div class="pname">${escH(p.nombre)}</div>
      <div class="meta">${precioHTML}${varianteBadge}${stockHTML}</div>`;

    // Click handlers — lógica sin cambios
    if (p.tiene_variantes) {
      div.onclick = () => abrirVariantes(p);
    } else if (modoStock === 'produccion') {
      if (p.stock > 0) div.onclick = () => agregarAlCarrito(p);
    } else if (!sinStock) {
      div.onclick = () => agregarAlCarrito(p);
    }

    grid.appendChild(div);
  });

  const hayMas = fin < _productosFiltrados.length;
  if (hayMas) {
    let btn = document.getElementById('btnVerMasProductos');
    if (!btn) {
      btn = document.createElement('button');
      btn.id = 'btnVerMasProductos';
      btn.className = 'btn';
      btn.style.cssText = 'width:100%;margin:8px 0;padding:12px;grid-column:1/-1';
      grid.parentElement.appendChild(btn);
    }
    btn.textContent = `Ver más (${_productosFiltrados.length - fin} restantes)`;
    btn.onclick = () => { _paginaProductos++; _renderPaginaGrid(grid, _paginaProductos); };
    const cards = grid.querySelectorAll('.product-card');
    if (cards.length > 0) {
      if (_observerVScroll) _observerVScroll.disconnect();
      _observerVScroll = new IntersectionObserver(entries => {
        if (entries[0].isIntersecting) {
          _observerVScroll.disconnect();
          _paginaProductos++;
          _renderPaginaGrid(grid, _paginaProductos);
        }
      }, {threshold: 0.1});
      _observerVScroll.observe(cards[cards.length - 1]);
    }
  } else {
    const btn = document.getElementById('btnVerMasProductos');
    if (btn) btn.remove();
    if (_observerVScroll) { _observerVScroll.disconnect(); _observerVScroll = null; }
  }
}

function agregarVarianteById(prodId, varId) {
  const prod = productoMap[prodId];
  if (!prod || !prod._variantes) return;
  const v = prod._variantes.find(v => v.id === varId);
  if (!v || v.stock <= 0) return;
  agregarAlCarritoConVariante(prod, v);
}

function filtrar() {
  clearTimeout(filtrar._t);
  filtrar._t = setTimeout(cargarProductos, 250);
}

// ── Precio rápido para productos sin precio ──────────────────
let _prodPrecioRapido = null;

function abrirModalPrecio(prod) {
  _prodPrecioRapido = prod;
  document.getElementById('modalPrecioTitle').textContent = prod.nombre;
  document.getElementById('precioRapidoInput').value = '';
  document.getElementById('modalPrecioRapido').classList.add('active');
  setTimeout(() => document.getElementById('precioRapidoInput').focus(), 80);
}

function cerrarPrecioRapido() {
  _prodPrecioRapido = null;
  document.getElementById('modalPrecioRapido').classList.remove('active');
  cerrarPanelSinTeclado();
}

async function confirmarPrecioRapido() {
  const precio = parseInt(document.getElementById('precioRapidoInput').value) || 0;
  if (precio <= 0) { showToast('Ingresa un precio mayor a 0', 'error'); return; }
  const prod = _prodPrecioRapido;
  cerrarPrecioRapido();
  // Save price persistently
  await fetch(`/api/productos/${prod.id}`, {
    method: 'PUT', credentials: 'include',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({precio}),
  }).catch(() => {});
  // Update local product object so cart shows correct price
  prod.precio = precio;
  if (indiceId.has(prod.id)) indiceId.get(prod.id).precio = precio;
  agregarAlCarrito(prod);
}

// ── Modificadores ─────────────────────────────────────────────
let _modifProd      = null;   // producto pendiente de modificadores
let _modifGrupos    = [];     // grupos cargados
let _modifSelec     = {};     // {modificador_id: [opcion_id, ...]}

async function agregarAlCarrito(prod) {
  if (!prod.precio || prod.precio === 0) { abrirModalPrecio(prod); return; }
  if (prod.tiene_modificadores) {
    try {
      const grupos = await fetch(`/api/modificadores/por-producto/${prod.id}`, {credentials:'include'}).then(r=>r.json());
      if (grupos && grupos.length) { abrirModalModificadores(prod, grupos); return; }
    } catch(e) { /* continuar sin modificadores */ }
  }
  _agregarProdAlCarrito(prod, null, 0);
}

function abrirModalModificadores(prod, grupos) {
  _modifProd   = prod;
  _modifGrupos = grupos;
  _modifSelec  = {};
  document.getElementById('modifProdNombre').textContent = prod.nombre;

  const container = document.getElementById('modifGrupos');
  container.innerHTML = '';
  grupos.forEach(g => {
    _modifSelec[g.id] = [];
    const esObl = g.tipo === 'obligatorio';
    const esUnico = g.seleccion === 'unico';
    const wrap = document.createElement('div');
    wrap.style.cssText = 'margin-bottom:18px';
    wrap.innerHTML = `<div style="font-size:13px;font-weight:700;color:${esObl ? '#f59e0b' : '#94a3b8'};margin-bottom:10px;text-transform:uppercase;letter-spacing:.5px">${g.nombre}${esObl ? ' *' : ''}</div>`;
    const optsDiv = document.createElement('div');
    optsDiv.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px';
    g.opciones.forEach(op => {
      const btn = document.createElement('button');
      btn.dataset.gid = g.id;
      btn.dataset.oid = op.id;
      btn.dataset.precio = op.precio_extra;
      btn.dataset.nombre = op.nombre;
      btn.style.cssText = 'padding:8px 14px;border-radius:20px;border:1.5px solid #2d2d44;background:#1e1e2e;color:#94a3b8;font-size:13px;cursor:pointer;transition:all .12s;user-select:none';
      btn.textContent = op.nombre + (op.precio_extra > 0 ? ` +$${op.precio_extra.toLocaleString('es-CL')}` : '');
      btn.onclick = () => _toggleModifOpcion(g.id, op.id, esUnico, btn);
      optsDiv.appendChild(btn);
    });
    wrap.appendChild(optsDiv);
    container.appendChild(wrap);
  });

  document.getElementById('modalModificadores').style.display = 'flex';
}

function _toggleModifOpcion(gid, oid, esUnico, btn) {
  const sel = _modifSelec[gid];
  const idx = sel.indexOf(oid);
  if (esUnico) {
    // deselect all in group
    document.querySelectorAll(`[data-gid="${gid}"]`).forEach(b => {
      b.style.background = '#1e1e2e';
      b.style.color = '#94a3b8';
      b.style.borderColor = '#2d2d44';
    });
    _modifSelec[gid] = (idx >= 0) ? [] : [oid];
  } else {
    if (idx >= 0) sel.splice(idx, 1); else sel.push(oid);
  }
  // refresh styles for this group
  document.querySelectorAll(`[data-gid="${gid}"]`).forEach(b => {
    const activo = _modifSelec[gid].includes(parseInt(b.dataset.oid));
    b.style.background    = activo ? '#22c55e' : '#1e1e2e';
    b.style.color         = activo ? '#fff'    : '#94a3b8';
    b.style.borderColor   = activo ? '#22c55e' : '#2d2d44';
  });
}

function confirmarModificadores() {
  // Validate mandatory groups
  for (const g of _modifGrupos) {
    if (g.tipo === 'obligatorio' && _modifSelec[g.id].length === 0) {
      showToast(`Selecciona "${g.nombre}"`, 'error'); return;
    }
  }
  // Build desc string and price extra
  const partes = [];
  let precioExtra = 0;
  _modifGrupos.forEach(g => {
    const oids = _modifSelec[g.id];
    if (!oids.length) return;
    oids.forEach(oid => {
      const btn = document.querySelector(`[data-gid="${g.id}"][data-oid="${oid}"]`);
      if (btn) {
        partes.push(btn.dataset.nombre);
        precioExtra += parseInt(btn.dataset.precio || 0);
      }
    });
  });
  const modifDesc = partes.length ? partes.join(', ') : null;
  cerrarModalModificadores();
  _agregarProdAlCarrito(_modifProd, modifDesc, precioExtra);
}

function cerrarModalModificadores() {
  document.getElementById('modalModificadores').style.display = 'none';
  _modifProd = null;
  cerrarPanelSinTeclado();
}

function _agregarProdAlCarrito(prod, modifDesc, precioExtra) {
  const modoStock = prod.modo_stock || 'normal';
  const precioFinal = prod.precio + (precioExtra || 0);
  // Items with modificadores are never merged (each selection is unique)
  if (!modifDesc) {
    const idx = carrito.findIndex(i => i.producto_id === prod.id && !i.variante_id && !i.modificadores_desc);
    if (idx >= 0) {
      carrito[idx].cantidad++;
      renderCarrito();
      const stockDisp = prod.stock_real ?? prod.stock;
      if (modoStock !== 'sin_stock' && stockDisp > 0 && carrito[idx].cantidad > stockDisp) {
        showToast(`⚠️ Stock insuficiente — quedan ${stockDisp} unidades`, 'warning');
      } else {
        showToast('+ ' + prod.nombre, 'success');
      }
      return;
    }
  }
  carrito.push({
    producto_id: prod.id, nombre: prod.nombre,
    precio_unit: precioFinal, cantidad: 1,
    stock: prod.stock_real ?? prod.stock,
    modo_stock: modoStock,
    modificadores_desc: modifDesc || null,
    _new: true,
  });
  renderCarrito();
  showToast('+ ' + prod.nombre, 'success');
}

// ── Carrito ───────────────────────────────────────────────────

function cambiarCantidad(idx, delta) {
  carrito[idx].cantidad += delta;
  if (carrito[idx].cantidad <= 0) { carrito.splice(idx, 1); renderCarrito(); _pushPantallaIdle(); return; }
  const item = carrito[idx];
  if (delta > 0 && item.modo_stock !== 'sin_stock' && item.stock > 0 && item.cantidad > item.stock) {
    showToast(`⚠️ Stock insuficiente — quedan ${item.stock} unidades`, 'warning');
  }
  renderCarrito();
  if (carrito.length === 0) _pushPantallaIdle();
}

function _setItemCantidad(idx, val) {
  val = parseInt(val) || 1;
  if (val <= 0) { eliminarItem(idx); return; }
  carrito[idx].cantidad = val;
  const item = carrito[idx];
  if (item && item.modo_stock !== 'sin_stock' && item.stock > 0 && val > item.stock) {
    showToast(`⚠️ Stock insuficiente — quedan ${item.stock} unidades`, 'warning');
  }
  renderCarrito();
  if (carrito.length === 0) _pushPantallaIdle();
}

function eliminarItem(idx) { carrito.splice(idx, 1); renderCarrito(); if (carrito.length === 0) _pushPantallaIdle(); }

let _pantallaLock = false;
let _pantallaTimer = null;

function limpiarCarrito() { carrito = []; renderCarrito(); _pushPantallaIdle(); }

function renderCarrito() {
  const _uid = _meId || null;
  if (_uid) {
    if (carrito.length) guardarCarritoLocal(carrito, _uid);
    else limpiarCarritoLocal();
  }

  const el = document.getElementById('carritoItems');
  const totalItems = carrito.reduce((s, i) => s + i.cantidad, 0);
  document.getElementById('itemCount').textContent = totalItems;

  if (!carrito.length) {
    el.innerHTML = '<div class="carrito-empty"><span style="font-size:32px">🛒</span><span>Toca un producto para agregar</span></div>';
    document.getElementById('btnCobrar').disabled = true;
    recalcular();
    return;
  }

  el.innerHTML = '';
  carrito.forEach((item, idx) => {
    const sub = item.precio_unit * item.cantidad;
    const div = document.createElement('div');
    const esNuevo = item._new;
    if (esNuevo) item._new = false;
    div.className = 'carrito-item' + (esNuevo ? ' carrito-item-new' : '');
    const loteTag = item.lote_id
      ? `<div style="font-size:10px;color:var(--text-dim);margin-top:2px">📦 ${item.lote_numero || 'L-'+item.lote_id}${item.vencimiento ? ' · ' + item.vencimiento.slice(5).replace('-','/') : ''}</div>`
      : '';
    const modifTag = item.modificadores_desc
      ? `<div style="font-size:10px;color:var(--text-dim);margin-top:2px">└ ${item.modificadores_desc}</div>`
      : '';
    const _stk = (item.modo_stock !== 'sin_stock' && item.stock != null) ? item.stock : Infinity;
    const _cantColor = item.cantidad > _stk ? '#ef4444' : item.cantidad === _stk ? '#facc15' : 'var(--text)';
    div.innerHTML = `
      <div class="item-nombre">${item.nombre}${loteTag}${modifTag}</div>
      <div class="item-controles">
        <button class="qty-btn" onclick="cambiarCantidad(${idx},-1)">−</button>
        <input type="number" inputmode="numeric" value="${item.cantidad}" min="1"
          style="width:60px;text-align:center;background:none;border:none;color:${_cantColor};font-size:16px;font-weight:700;cursor:pointer"
          onchange="_setItemCantidad(${idx}, parseInt(this.value)||1)"
          onclick="this.select()">
        <button class="qty-btn" onclick="cambiarCantidad(${idx},+1)">+</button>
      </div>
      <div class="item-subtotal">${fmt(sub)}</div>
      <button class="item-del" onclick="eliminarItem(${idx})">✕</button>`;
    el.appendChild(div);
  });

  document.getElementById('btnCobrar').disabled = false;
  const _insufBtn = verificarStockCarrito();
  const _btnCobrar = document.getElementById('btnCobrar');
  if (_insufBtn.length) {
    _btnCobrar.style.background = 'linear-gradient(135deg,#f59e0b,#d97706)';
    _btnCobrar.style.boxShadow = '0 4px 20px rgba(245,158,11,.4)';
    _btnCobrar.textContent = '⚠️ Cobrar →';
  } else {
    _btnCobrar.style.background = '';
    _btnCobrar.style.boxShadow = '';
    _btnCobrar.textContent = '✓ Cobrar →';
  }
  recalcular();
  pushPantallaCliente();
}

function pushPantallaCliente(extra = {}) {
  if (_pantallaLock && !extra.estado) return;
  const subtotalBruto = carrito.reduce((s, i) => s + i.precio_unit * i.cantidad, 0);
  const desc = parseFloat(document.getElementById('descuentoInput')?.value) || 0;
  const t = Math.max(0, subtotalBruto - desc);
  const ivaPct = parseFloat(cfgApp.iva_porcentaje || 19);
  const iva = Math.round(t * ivaPct / (100 + ivaPct));
  const payload = {
    items: carrito.map(i => ({
      nombre: i.nombre + (i.nombre_variante ? ' ' + i.nombre_variante : ''),
      cantidad: i.cantidad,
      precio_unit: i.precio_unit,
      subtotal: i.precio_unit * i.cantidad,
      imagen_url: i.imagen_url || null,
    })),
    total: t,
    subtotal: subtotalBruto,
    iva,
    ...extra,
  };
  fetch('/api/ventas/pantalla-cliente/estado', {
    method: 'POST', credentials: 'include',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  }).catch(() => {});
}

function _pushPantallaIdle() {
  fetch('/api/ventas/pantalla-cliente/estado', {
    method: 'POST', credentials: 'include',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({items: [], total: 0, estado: 'idle'})
  }).catch(() => {});
}

function recalcular() {
  const subtotal = carrito.reduce((s, i) => s + i.precio_unit * i.cantidad, 0);
  const desc = parseFloat(document.getElementById('descuentoInput').value) || 0;
  total = Math.max(0, subtotal - desc);
  document.getElementById('subtotalDisp').textContent = fmt(subtotal);
  document.getElementById('totalDisp').textContent = fmt(total);
  // Descuento badge
  const badgeRow = document.getElementById('descuentoBadgeRow');
  if (badgeRow) {
    badgeRow.style.display = desc > 0 ? 'flex' : 'none';
    const badgeVal = document.getElementById('descuentoBadgeVal');
    if (badgeVal) badgeVal.textContent = '-' + fmt(desc);
  }
  actualizarFAB();
}

function quitarDescuento() {
  document.getElementById('descuentoInput').value = '';
  const vis = document.getElementById('descuentoInputVisible');
  if (vis) vis.value = '';
  document.getElementById('descuentoInputRow').style.display = 'none';
  recalcular();
}

function abrirInputDescuento() {
  const row = document.getElementById('descuentoInputRow');
  if (!row) return;
  row.style.display = row.style.display === 'block' ? 'none' : 'block';
  if (row.style.display === 'block') {
    setTimeout(() => document.getElementById('descuentoInputVisible')?.focus(), 50);
  }
}

function actualizarFAB() {
  const totalItems = carrito.reduce((s, i) => s + i.cantidad, 0);
  const fab = document.getElementById('fabCarrito');
  if (!fab) return;
  if (totalItems === 0) {
    fab.classList.add('oculto');
    return;
  }
  const fc = document.getElementById('fabCount');
  const ft = document.getElementById('fabTotal');
  if (fc) fc.textContent = totalItems;
  if (ft) ft.textContent = fmt(total);
  fab.classList.remove('oculto');
}

// ── Helpers móvil ────────────────────────────────────────────
const esMobil = () => /iPhone|iPad|Android/i.test(navigator.userAgent) || window.innerWidth < 768;

function cerrarPanelSinTeclado() {
  if (document.activeElement && document.activeElement !== document.body) {
    document.activeElement.blur();
  }
  document.body.setAttribute('tabindex', '-1');
  document.body.focus();
  document.body.removeAttribute('tabindex');
}
function _blurActivo() { cerrarPanelSinTeclado(); }

// ── Mobile cart toggle ───────────────────────────────────────
function toggleCarritoMobile() {
  const cart = document.getElementById('carrito');
  const overlay = document.getElementById('cartOverlay');
  const fab = document.getElementById('fabCarrito');
  const isOpen = cart.classList.contains('open');
  if (isOpen) {
    cart.classList.remove('open');
    overlay.classList.remove('active');
    fab?.classList.remove('oculto');
    _blurActivo();
  } else {
    cart.classList.add('open');
    overlay.classList.add('active');
    fab?.classList.add('oculto');
    _blurActivo();
  }
}

// ── Cobro ─────────────────────────────────────────────────────
// ── Entrega ──────────────────────────────────────────────────
let entregaActual = {tipo:'local',nombre:'',tel:'',tel2:'',email:'',direccion:'',depto:'',referencia:'',comuna:'',notas:'',hora_retiro:'',receptor_nombre:null,receptor_tel:null};

function verificarStockCarrito() {
  return carrito.filter(i =>
    i.modo_stock !== 'sin_stock' && i.stock != null && i.cantidad > i.stock
  );
}

function _mostrarModalStockInsuficiente(items) {
  const ul = document.getElementById('listaStockInsuficiente');
  ul.innerHTML = items.map(i =>
    `<li>${i.nombre}: tienes <b>${i.stock}</b>, vendes <b>${i.cantidad}</b></li>`
  ).join('');
  document.getElementById('modalStockInsuficiente').classList.add('active');
}

function cerrarModalStockInsuficiente() {
  document.getElementById('modalStockInsuficiente').classList.remove('active');
}

function confirmarVentaConStockBajo() {
  cerrarModalStockInsuficiente();
  _procesarCobro();
}

function abrirCobro() {
  if (!carrito.length) return;
  const turnoActivo = sessionStorage.getItem('turno_id') || window._turnoId;
  if (!turnoActivo) { showToast('Debes abrir el turno antes de cobrar', 'error'); return; }
  const insuf = verificarStockCarrito();
  if (insuf.length) { _mostrarModalStockInsuficiente(insuf); return; }
  _procesarCobro();
}

function _procesarCobro() {
  carrito = carrito.filter(i => !i.es_reparto);
  recalcular();
  const deliveryActivo = cfgApp.modulo_delivery === '1' || cfgApp.modulo_delivery === true;
  if (deliveryActivo) {
    // Modo mesas: ocultar "aquí mismo" si modo_mesas es false
    const modoMesas = cfgApp.modo_mesas === '1' || cfgApp.modo_mesas === true;
    document.getElementById('btnEntregaLocal').style.display = modoMesas === false ? 'none' : '';
    entregaActual = {tipo:'local',nombre:'',tel:'',tel2:'',direccion:'',depto:'',referencia:'',comuna:'',notas:'',hora_retiro:'',receptor_nombre:null,receptor_tel:null};
    document.getElementById('modalEntrega').classList.add('active');
  } else {
    _abrirModalCobro();
  }
}

function cerrarEntregaModal() {
  document.getElementById('modalEntrega').classList.remove('active');
  cerrarPanelSinTeclado();
}

function selEntrega(tipo) {
  cerrarEntregaModal();
  entregaActual.tipo = tipo;
  if (tipo === 'local') {
    _abrirModalCobro();
  } else if (tipo === 'retiro') {
    ['retiroNombre','retiroTel','retiroEmail','retiroHora','retiroNotas'].forEach(id => {
      const el = document.getElementById(id); if (el) el.value = '';
    });
    document.getElementById('modalRetiro').classList.add('active');
  } else {
    _limpiarFormDelivery();
    _iniciarDistanciaRow();
    document.getElementById('modalDelivery').classList.add('active');
  }
}

function volverEntrega() {
  document.getElementById('modalRetiro').classList.remove('active');
  document.getElementById('modalDelivery').classList.remove('active');
  document.getElementById('modalEntrega').classList.add('active');
}

function continuar_retiro() {
  const nombre = document.getElementById('retiroNombre').value.trim();
  if (!nombre) { showToast('Ingresa un nombre', 'error'); return; }
  entregaActual.nombre     = nombre;
  entregaActual.tel        = document.getElementById('retiroTel').value.trim();
  entregaActual.email      = document.getElementById('retiroEmail').value.trim();
  entregaActual.hora_retiro = document.getElementById('retiroHora').value;
  entregaActual.notas      = document.getElementById('retiroNotas').value.trim();
  document.getElementById('modalRetiro').classList.remove('active');
  mostrarVerificacionFinal();
}

function continuar_delivery() {
  const nombre = document.getElementById('delNombre').value.trim();
  const tel    = document.getElementById('delTel').value.trim();
  const calle  = document.getElementById('delCalle').value.trim();
  const numero = document.getElementById('delNumero').value.trim();
  if (!nombre || !tel || !calle) { showToast('Nombre, teléfono y calle son obligatorios', 'error'); return; }
  const chkRec = document.getElementById('delChkReceptor');
  if (chkRec?.checked && !document.getElementById('delReceptorNombre').value.trim()) {
    showToast('Ingresa el nombre de quien recibe', 'error'); return;
  }
  entregaActual.nombre    = nombre;
  entregaActual.tel       = tel;
  entregaActual.tel2      = document.getElementById('delTel2').value.trim();
  entregaActual.email     = document.getElementById('delEmail').value.trim();
  entregaActual.direccion = numero ? `${calle} ${numero}` : calle;
  entregaActual.depto     = document.getElementById('delDepto').value.trim();
  entregaActual.comuna    = document.getElementById('delComuna').value.trim() || cfgApp.comuna_negocio || '';
  entregaActual.referencia = document.getElementById('delReferencia').value.trim();
  entregaActual.notas     = document.getElementById('delNotas').value.trim();
  entregaActual.receptor_nombre = chkRec?.checked
    ? document.getElementById('delReceptorNombre').value.trim() || null : null;
  entregaActual.receptor_tel = chkRec?.checked
    ? document.getElementById('delReceptorTel').value.trim() || null : null;
  const km = document.querySelector('input[name="delKm"]:checked')?.value || 'km1';
  _actualizarItemReparto(_calcularCostoReparto(km), km);
  document.getElementById('modalDelivery').classList.remove('active');
  mostrarVerificacionFinal();
}

let _delReceptorSugerido = null;

function toggleDelReceptor() {
  const chk = document.getElementById('delChkReceptor');
  const campos = document.getElementById('delCamposReceptor');
  campos.style.display = chk.checked ? 'block' : 'none';
  if (chk.checked) document.getElementById('delReceptorNombre').focus();
}

function mostrarSugerenciaReceptorDel(rf) {
  _delReceptorSugerido = rf;
  const veces = rf.veces === 1 ? 'la última vez' : `las últimas ${rf.veces} veces`;
  document.getElementById('delReceptorSugerenciaTexto').textContent =
    `¿Entregamos a ${rf.nombre} como ${veces}?`;
  document.getElementById('delReceptorSugerencia').style.display = '';
}

function aceptarDelReceptorSugerido() {
  if (!_delReceptorSugerido) return;
  document.getElementById('delChkReceptor').checked = true;
  toggleDelReceptor();
  document.getElementById('delReceptorNombre').value = _delReceptorSugerido.nombre;
  document.getElementById('delReceptorTel').value    = _delReceptorSugerido.tel || '';
  document.getElementById('delReceptorSugerencia').style.display = 'none';
  _delReceptorSugerido = null;
}

function rechazarDelReceptorSugerido() {
  document.getElementById('delReceptorSugerencia').style.display = 'none';
  _delReceptorSugerido = null;
  document.getElementById('delChkReceptor').checked = true;
  toggleDelReceptor();
}

// ── Autocomplete + validación dirección (modal delivery) ──────────────────────
let _delDirTimer = null;

function onDelDirInput(val) {
  clearTimeout(_delDirTimer);
  document.getElementById('delAlertaDireccion').style.display = 'none';
  document.getElementById('delCalle').style.borderColor = '';
  if (!val || val.length < 3) {
    document.getElementById('delDirAutocomplete').style.display = 'none';
    return;
  }
  _delDirTimer = setTimeout(() => _buscarDelDir(val), 320);
}

async function _buscarDelDir(q) {
  const comuna = document.getElementById('delComuna').value.trim() || cfgApp.comuna_negocio || '';
  const params = new URLSearchParams({q});
  if (comuna) params.set('comuna', comuna);
  try {
    const r = await fetch(`/api/direcciones/buscar?${params}`, {credentials:'include'}).then(r=>r.json());
    const ac = document.getElementById('delDirAutocomplete');
    if (!r || !r.length) { ac.style.display = 'none'; return; }
    window._sugerenciasActuales = r;
    ac.innerHTML = r.map((item, i) => {
      return `<div onmousedown="event.preventDefault()" onclick="seleccionarDelDir(${i})"
                   style="padding:9px 12px;cursor:pointer;font-size:13px;
                          border-bottom:1px solid rgba(255,255,255,.07);
                          display:flex;justify-content:space-between;align-items:center;">
        <span>📍 ${item.calle}</span>
        <span style="font-size:11px;color:#94a3b8;">${item.comuna || ''}${item.fuente==='nominatim' ? ' 🌐' : ''}</span>
      </div>`;
    }).join('');
    ac.style.display = '';
  } catch(e) {
    document.getElementById('delDirAutocomplete').style.display = 'none';
  }
}

function seleccionarDelDir(index) {
  const s = (window._sugerenciasActuales || [])[index];
  if (!s) return;
  document.getElementById('delCalle').value = s.calle;
  document.getElementById('delDirAutocomplete').style.display = 'none';
  document.getElementById('delAlertaDireccion').style.display = 'none';
  document.getElementById('delCalle').style.borderColor = '#22c55e';
  if (s.comuna && !document.getElementById('delComuna').value.trim()) {
    document.getElementById('delComuna').value = s.comuna;
  }
  document.getElementById('delNumero').focus();
}

function usarSugerenciaDelDir(calle) {
  document.getElementById('delCalle').value = calle;
  document.getElementById('delAlertaDireccion').style.display = 'none';
  document.getElementById('delCalle').style.borderColor = '#22c55e';
}

document.addEventListener('DOMContentLoaded', () => {
  const inputDir = document.getElementById('delCalle');
  if (!inputDir) return;

  inputDir.addEventListener('blur', async () => {
    setTimeout(() => {
      document.getElementById('delDirAutocomplete').style.display = 'none';
    }, 200);
    const calle  = inputDir.value.trim();
    const comuna = document.getElementById('delComuna').value.trim() || cfgApp.comuna_negocio || '';
    if (!calle || calle.length < 4) return;
    try {
      const res = await fetch('/api/direcciones/validar', {
        method: 'POST', credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({calle, comuna}),
      }).then(r => r.json());
      const alertaEl = document.getElementById('delAlertaDireccion');
      if (res.valida) {
        alertaEl.style.display = 'none';
        inputDir.style.borderColor = '#22c55e';
        if (res.nombre_oficial && res.nombre_oficial !== calle) {
          inputDir.value = res.nombre_oficial;
        }
        if (res.alerta) {
          alertaEl.innerHTML = `ℹ️ ${res.alerta}`;
          alertaEl.style.background = 'rgba(34,197,94,.08)';
          alertaEl.style.borderColor = 'rgba(34,197,94,.3)';
          alertaEl.style.color = '#22c55e';
          alertaEl.style.display = '';
        }
      } else {
        inputDir.style.borderColor = '#ef4444';
        if (res.sugerencias?.length) {
          const btns = res.sugerencias.map(s => {
            const esc = s.replace(/'/g, "\\'");
            return `<button onclick="usarSugerenciaDelDir('${esc}')"
                      style="margin:2px 4px 2px 0;background:rgba(239,68,68,.15);
                             border:1px solid rgba(239,68,68,.4);border-radius:5px;
                             padding:2px 8px;font-size:11px;cursor:pointer;
                             color:#ef4444;font-family:inherit;">${s}</button>`;
          }).join('');
          alertaEl.innerHTML = `⚠️ ${res.alerta}<br>${btns}`;
        } else {
          alertaEl.innerHTML = `⚠️ ${res.alerta || ''}`;
        }
        alertaEl.style.background = 'rgba(239,68,68,.1)';
        alertaEl.style.borderColor = 'rgba(239,68,68,.4)';
        alertaEl.style.color = '#ef4444';
        if (res.alerta) alertaEl.style.display = '';
      }
    } catch(e) {}
  });

  document.addEventListener('click', e => {
    if (!e.target.closest('#delCalle') && !e.target.closest('#delDirAutocomplete')) {
      document.getElementById('delDirAutocomplete').style.display = 'none';
    }
  });
});

async function buscarClientePorTel() {
  const tel = document.getElementById('delBuscarTel').value.trim();
  if (!tel) return;
  try {
    const r = await fetch(`/api/clientes/buscar?tel=${encodeURIComponent(tel)}`, {credentials:'include'}).then(r => r.json());
    if (r && r.nombre) {
      document.getElementById('delNombre').value  = r.nombre || '';
      document.getElementById('delTel').value     = r.telefono || tel;
      document.getElementById('delTel2').value    = r.telefono2 || '';
      document.getElementById('delEmail').value   = r.email || '';
      document.getElementById('delCalle').value   = r.direccion || '';
      document.getElementById('delNumero').value  = '';
      document.getElementById('delDepto').value   = r.depto || '';
      document.getElementById('delComuna').value  = r.comuna || '';
      showToast(`Cliente encontrado: ${r.nombre}`, 'success');
      if (r.receptores_frecuentes && r.receptores_frecuentes.length > 0) {
        mostrarSugerenciaReceptorDel(r.receptores_frecuentes[0]);
      }
    } else {
      document.getElementById('delTel').value = tel;
      showToast('Cliente nuevo', 'info');
    }
  } catch(e) { document.getElementById('delTel').value = tel; }
}

function _limpiarFormDelivery() {
  ['delBuscarTel','delNombre','delTel','delTel2','delEmail','delCalle','delNumero',
   'delDepto','delComuna','delReferencia','delNotas','delReceptorNombre','delReceptorTel']
    .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  const chk = document.getElementById('delChkReceptor');
  if (chk) chk.checked = false;
  document.getElementById('delCamposReceptor').style.display = 'none';
  document.getElementById('delReceptorSugerencia').style.display = 'none';
  document.getElementById('delDirAutocomplete').style.display = 'none';
  document.getElementById('delAlertaDireccion').style.display = 'none';
  document.getElementById('delCalle').style.borderColor = '';
  const firstKm = document.querySelector('input[name="delKm"][value="km1"]');
  if (firstKm) firstKm.checked = true;
  actualizarPrecioReparto();
  _delReceptorSugerido = null;
}

// ── Verificación final ────────────────────────────────────────────────────────
function mostrarVerificacionFinal() {
  const ea = entregaActual;
  const tipoLabel = ea.tipo === 'delivery' ? '🛵 DELIVERY' : '🏠 RETIRO EN LOCAL';
  let info = '';
  info += `<div style="font-size:14px;margin-bottom:4px;font-weight:600;">👤 ${ea.nombre}`;
  if (ea.tel) info += ` — ${ea.tel}`;
  info += '</div>';
  if (ea.email) info += `<div style="font-size:12px;color:var(--text-dim);margin-bottom:2px;">✉️ ${ea.email}</div>`;
  if (ea.tipo === 'delivery' && ea.direccion) {
    let dir = ea.direccion;
    if (ea.depto) dir += ', ' + ea.depto;
    if (ea.comuna) dir += ', ' + ea.comuna;
    info += `<div style="font-size:13px;color:var(--text-dim);margin-bottom:2px;">📍 ${dir}</div>`;
  }
  if (ea.hora_retiro) info += `<div style="font-size:12px;color:var(--text-dim);margin-bottom:2px;">🕐 Retiro: ${ea.hora_retiro}</div>`;
  if (ea.receptor_nombre) info += `<div style="font-size:12px;color:var(--accent2);margin-bottom:2px;">📦 Entregar a: ${ea.receptor_nombre}</div>`;
  if (ea.notas) info += `<div style="font-size:12px;color:var(--text-dim);">📝 ${ea.notas}</div>`;

  const itemsHtml = carrito.map(i => {
    const sub = i.precio_unit * i.cantidad;
    return `<div style="display:flex;justify-content:space-between;font-size:13px;padding:4px 0;border-bottom:1px solid rgba(255,255,255,.05);">
      <span>${i.cantidad}× ${i.nombre}</span>
      <span style="white-space:nowrap;font-weight:500;">${fmt(sub)}</span>
    </div>`;
  }).join('');

  document.getElementById('verContenido').innerHTML = `
    <div style="background:var(--surface2);border-radius:8px;padding:12px;margin-bottom:10px;">
      <div style="font-weight:700;font-size:12px;color:var(--accent);letter-spacing:.05em;margin-bottom:8px;">${tipoLabel}</div>
      ${info}
    </div>
    <div style="background:var(--surface2);border-radius:8px;padding:12px;margin-bottom:10px;">${itemsHtml}</div>
    <div style="background:var(--surface2);border-radius:8px;padding:10px 12px;display:flex;justify-content:space-between;font-weight:700;font-size:15px;">
      <span>TOTAL</span><span>${fmt(total)}</span>
    </div>`;
  document.getElementById('modalVerificacion').classList.add('active');
}

function confirmarVerificacion() {
  document.getElementById('modalVerificacion').classList.remove('active');
  _abrirModalCobro();
}

function volverDeVerificacion() {
  document.getElementById('modalVerificacion').classList.remove('active');
  if (entregaActual.tipo === 'delivery') {
    carrito = carrito.filter(i => !i.es_reparto);
    recalcular();
    document.getElementById('modalDelivery').classList.add('active');
  } else {
    document.getElementById('modalRetiro').classList.add('active');
  }
}

// ── Reparto ───────────────────────────────────────────────────────────────────
function _calcularCostoReparto(km) {
  const tipo = cfgApp.delivery_tarifa_tipo || 'gratis';
  if (tipo === 'gratis') return 0;
  if (tipo === 'fijo')   return parseInt(cfgApp.delivery_precio_fijo || 0);
  const mapa = {
    km1:  parseInt(cfgApp.delivery_precio_km1  || 0),
    km3:  parseInt(cfgApp.delivery_precio_km3  || 0),
    km5:  parseInt(cfgApp.delivery_precio_km5  || 0),
    mas5: parseInt(cfgApp.delivery_precio_mas5 || 0),
  };
  return mapa[km] ?? 0;
}

function _actualizarItemReparto(precio, km) {
  carrito = carrito.filter(i => !i.es_reparto);
  if (precio > 0) {
    const texto  = cfgApp.delivery_texto || 'Reparto';
    const etiq   = {km1:'hasta 1km', km3:'1-3km', km5:'3-5km', mas5:'+5km'};
    carrito.push({
      nombre:      `${texto} (${etiq[km] || km})`,
      precio_unit: precio,
      cantidad:    1,
      subtotal:    precio,
      es_reparto:  true,
      producto_id: null,
      variante_id: null,
    });
  }
  recalcular();
  renderCarrito();
}

function actualizarPrecioReparto() {
  const km   = document.querySelector('input[name="delKm"]:checked')?.value || 'km1';
  const cost = _calcularCostoReparto(km);
  const prev = document.getElementById('delCostoPreview');
  if (prev) {
    const texto = cfgApp.delivery_texto || 'Reparto';
    prev.textContent = cost > 0 ? `${texto}: ${fmt(cost)}` : `${texto}: Gratis`;
  }
}

function _iniciarDistanciaRow() {
  const tipo = cfgApp.delivery_tarifa_tipo || 'gratis';
  const row  = document.getElementById('delDistanciaRow');
  if (row) row.style.display = tipo === 'distancia' ? '' : 'none';
  actualizarPrecioReparto();
}

function _abrirModalCobro() {
  document.getElementById('modalTotal').textContent = fmt(total);
  document.getElementById('montoRecibido').value = '';
  document.getElementById('vueltoRow').style.display = 'none';
  document.getElementById('modalCobro').classList.add('active');
  // No pre-seleccionar — el cajero debe elegir explícitamente el método
  document.querySelectorAll('.metodo-btn, .metodo-credito-btn').forEach(b => b.classList.remove('selected'));
  document.getElementById('secEfectivo').style.display = 'none';
  document.getElementById('secTransferencia').style.display = 'none';
  document.getElementById('secKhipu').style.display = 'none';
  document.getElementById('secSumup').style.display = 'none';
  document.getElementById('secCredito').style.display = 'none';
  metodoPago = '';
}

function _resetFooterCobro() {
  document.getElementById('footerCobro').innerHTML =
    '<button class="btn-cancelar" onclick="cerrarCobro()">Cancelar</button>' +
    '<button class="btn-confirmar" id="btnConfirmar" onclick="confirmarPago()">✓ Confirmar pago</button>';
}

function cerrarCobro() {
  document.getElementById('modalCobro').classList.remove('active');
  _resetFooterCobro();
  entregaActual = {tipo:'local',nombre:'',tel:'',tel2:'',direccion:'',depto:'',referencia:'',comuna:'',notas:'',hora_retiro:'',receptor_nombre:null,receptor_tel:null};
  _blurActivo();
}

function selMetodo(btn) {
  document.querySelectorAll('.metodo-btn, .metodo-credito-btn').forEach(b => b.classList.remove('selected'));
  btn.classList.add('selected');
  metodoPago = btn.dataset.met;
  document.getElementById('secEfectivo').style.display = metodoPago === 'efectivo' ? 'block' : 'none';
  document.getElementById('secTransferencia').style.display = metodoPago === 'transferencia' ? 'block' : 'none';
  document.getElementById('secKhipu').style.display = metodoPago === 'khipu' ? 'block' : 'none';
  document.getElementById('secSumup').style.display = metodoPago === 'sumup' ? 'block' : 'none';
  document.getElementById('secCredito').style.display = metodoPago === 'credito' ? 'block' : 'none';
  if (metodoPago === 'transferencia') cargarQrPago();
  if (metodoPago === 'credito') {
    _creditClienteId = null;
    _creditClienteNuevo = false;
    renderPasoCredito();
    _resetFooterCobro();
  }
}

async function cargarQrPago() {
  const img = document.getElementById('qrTransferencia');
  const msg = document.getElementById('qrMsg');
  img.style.display = 'none';
  msg.textContent = 'Generando QR...';
  try {
    const r = await fetch('/api/qr/pago', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({monto: total, concepto: 'Pago en tienda'}),
    }).then(r => r.json());
    if (r.qr_base64) {
      img.src = 'data:image/png;base64,' + r.qr_base64;
      img.style.display = 'block';
      msg.textContent = '';
    } else {
      msg.textContent = r.texto || 'QR no disponible';
    }
  } catch(e) { msg.textContent = 'Error al generar QR'; }
}

function calcularVuelto() {
  const recibido = parseFloat(document.getElementById('montoRecibido').value) || 0;
  const vuelto = recibido - total;
  const row = document.getElementById('vueltoRow');
  if (recibido > 0) {
    row.style.display = 'flex';
    document.getElementById('vueltoMonto').textContent = fmt(Math.max(0, vuelto));
    row.style.borderColor = vuelto < 0 ? 'rgba(239,68,68,.3)' : 'rgba(34,197,94,.2)';
  } else {
    row.style.display = 'none';
  }
}

async function confirmarPago() {
  if (!metodoPago) { showToast('Selecciona un método de pago', 'error'); return; }
  if (metodoPago === 'efectivo') {
    const recibido = parseFloat(document.getElementById('montoRecibido').value) || 0;
    if (recibido < total) { showToast('Monto insuficiente', 'error'); return; }
  }
  if (metodoPago === 'credito' && !_creditClienteId) {
    showToast('Selecciona un cliente para fiado', 'error'); return;
  }
  if (metodoPago === 'khipu') { await crearPagoKhipu(); return; }
  if (metodoPago === 'sumup')  { await cobrarConSumUp(); return; }

  const btn = document.getElementById('btnConfirmar') || document.getElementById('btnConfirmarCredito');
  if (btn) { btn.disabled = true; btn.textContent = 'Procesando...'; }

  let ventaRealizada = false;
  const desc = parseFloat(document.getElementById('descuentoInput').value) || 0;
  // Validar descuento máximo por permisos
  if (desc > 0) {
    if (!_permisosPOS.puede_hacer_descuentos) {
      showToast('No tienes permiso para aplicar descuentos', 'error');
      if (btn) { btn.disabled = false; btn.textContent = 'Confirmar pago'; }
      return;
    }
    const maxPct = typeof _permisosPOS.descuento_maximo_pct === 'number' ? _permisosPOS.descuento_maximo_pct : 100;
    if (maxPct > 0 && total > 0 && (desc / total * 100) > maxPct) {
      showToast(`Descuento máximo permitido: ${maxPct}%`, 'error');
      if (btn) { btn.disabled = false; btn.textContent = 'Confirmar pago'; }
      return;
    }
  }
  const itemsNormales = carrito.filter(i => !i._rapida && i.producto_id && !i._pedido_item);
  const itemsRapidosCarrito = carrito.filter(i => i._rapida);
  const pedidoItemsCarrito = carrito.filter(i => i._pedido_item);
  const pedidoIdActual = window._pedidoActual || null;

  try {
    let ventaId = null;

    // Para delivery/retiro: crear el pedido PRIMERO para obtener pedido_id
    let pedidoIdParaVenta = pedidoIdActual;
    if (entregaActual.tipo !== 'local') {
      const rped = await fetch('/api/pedidos', {
        method: 'POST', credentials: 'include',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({
          tipo:           entregaActual.tipo,
          cliente_nombre: entregaActual.nombre,
          cliente_tel:    entregaActual.tel,
          cliente_tel2:   entregaActual.tel2 || null,
          cliente_email:  entregaActual.email || null,
          direccion:      entregaActual.direccion || null,
          depto:          entregaActual.depto || null,
          referencia:     entregaActual.referencia || null,
          comuna:         entregaActual.comuna || null,
          notas:          entregaActual.notas || null,
          hora_retiro:    entregaActual.hora_retiro || null,
          receptor_nombre: entregaActual.receptor_nombre || null,
          receptor_tel:   entregaActual.receptor_tel || null,
          metodo_pago:    metodoPago,
          items: carrito.map(i => ({
            producto_id: i.producto_id || null,
            variante_id: i.variante_id || null,
            nombre:      i.nombre + (i.nombre_variante ? ' ' + i.nombre_variante : ''),
            cantidad:    i.cantidad,
            precio:      i.precio_unit,
            subtotal:    i.precio_unit * i.cantidad,
          })),
        }),
      });
      if (rped.ok) {
        const dped = await rped.json();
        pedidoIdParaVenta = dped.id || dped.pedido_id || null;
      }
    }

    // Si el carrito viene de un pedido del mesón, crear venta rápida con esos items
    if (pedidoIdActual && pedidoItemsCarrito.length) {
      const rp = await fetch('/api/ventas/rapida', {
        method:'POST', credentials:'include',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          items: pedidoItemsCarrito.map(i => ({nombre: i.nombre, precio_unit: i.precio_unit, cantidad: i.cantidad})),
          metodo_pago: metodoPago,
          descuento: desc,
          pedido_id: pedidoIdActual,
        }),
      });
      const dp = await rp.json();
      if (!rp.ok) { showToast(dp.error || 'Error en venta mesón', 'error'); return; }
      ventaId = dp.venta_id;
      window._pedidoActual = null;
    }

    if (itemsNormales.length) {
      const payload = {
        items: itemsNormales.map(i => ({
          producto_id: i.producto_id,
          variante_id: i.variante_id || null,
          nombre_variante: i.nombre_variante || '',
          cantidad: i.cantidad,
          modificadores_desc: i.modificadores_desc || null,
        })),
        metodo_pago: metodoPago,
        descuento: itemsRapidosCarrito.length ? 0 : desc,
        pedido_id: pedidoIdParaVenta || null,
      };
      const r = await fetch('/api/ventas', {
        method: 'POST', credentials: 'include',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payload),
      });
      const data = await r.json();
      if (!r.ok) {
        if (r.status === 409) {
          // 409 en reintento puede significar que la venta anterior sí se guardó
          try {
            const recientes = await fetch('/api/ventas?limit=1', {credentials:'include'})
              .then(rr => rr.ok ? rr.json() : []).catch(() => []);
            if (Array.isArray(recientes) && recientes.length > 0 &&
                Date.now() - new Date(recientes[0].creado_en).getTime() < 15000) {
              ventaId = recientes[0].id;
            } else {
              showToast(data.error || 'Stock insuficiente', 'error'); return;
            }
          } catch(e2) { showToast(data.error || 'Stock insuficiente', 'error'); return; }
        } else {
          showToast(data.error || 'Error al registrar venta', 'error'); return;
        }
      } else {
        ventaId = data.venta_id;
      }
    }

    if (itemsRapidosCarrito.length) {
      const guardar = itemsRapidosCarrito.some(i => i._guardar);
      const payloadR = {
        items: itemsRapidosCarrito.map(i => ({
          nombre: i.nombre, precio_unit: i.precio_unit, cantidad: i.cantidad,
        })),
        metodo_pago: metodoPago, descuento: desc, guardar_productos: guardar,
        pedido_id: pedidoIdParaVenta || null,
      };
      const r2 = await fetch('/api/ventas/rapida', {
        method: 'POST', credentials: 'include',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify(payloadR),
      });
      const data2 = await r2.json();
      if (!r2.ok) { showToast(data2.error || 'Error en venta rápida', 'error'); return; }
      ventaId = ventaId || data2.venta_id;
    }

    ventaRealizada = true;
    try {
      const _recibido = metodoPago === 'efectivo' ? (parseFloat(document.getElementById('montoRecibido').value) || 0) : 0;
      const _vuelto = metodoPago === 'efectivo' ? Math.max(0, _recibido - total) : 0;
      pushPantallaCliente({estado: 'pagado', metodo_pago: metodoPago, monto_recibido: _recibido, vuelto: _vuelto});
      _pantallaLock = true;
      if (_pantallaTimer) clearTimeout(_pantallaTimer);
      _pantallaTimer = setTimeout(() => { _pantallaLock = false; _pushPantallaIdle(); }, 10000);
      if (metodoPago === 'credito' && _creditClienteId && ventaId) {
        await _postVentaCredito(ventaId);
      }
      cerrarCobro();
      if (document.getElementById('carrito').classList.contains('open')) toggleCarritoMobile();
      limpiarCarrito();
      document.getElementById('descuentoInput').value = '';
      const _dv = document.getElementById('descuentoInputVisible'); if (_dv) _dv.value = '';
      const _dr = document.getElementById('descuentoInputRow'); if (_dr) _dr.style.display = 'none';
      showToast(`✓ Venta #${ventaId} — ${fmt(total)}`, 'success');
      setTimeout(() => cargarProductos(), 500);
    } catch(postErr) {
      console.error('Error post-venta (venta guardada):', postErr);
      try { cerrarCobro(); } catch(e2) {}
      try { limpiarCarrito(); } catch(e2) {}
      showToast(`✓ Venta #${ventaId} completada`, 'success');
    }
  } catch(e) {
    if (!ventaRealizada) showToast('Error de conexión', 'error');
  } finally {
    if (!ventaRealizada && btn) { btn.disabled = false; btn.textContent = '✓ Confirmar pago'; }
  }
}

// ── ZERO CREDIT ──────────────────────────────────────────────
function escH(s) {
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ── Paso 1: 3 opciones ────────────────────────────────────────
function renderPasoCredito() {
  document.getElementById('secCredito').innerHTML = `
    <div style="padding:4px 0 10px;text-align:center;font-size:13px;color:var(--text-dim);font-weight:500">
      ¿Cómo identificas al cliente?
    </div>
    <div style="display:flex;flex-direction:column;gap:10px">
      <button onclick="flujoEscanearQR()"
        style="min-height:64px;background:var(--surface2);border:1px solid var(--border);border-radius:12px;color:var(--text);font-size:15px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:14px;padding:0 18px;width:100%;text-align:left;transition:.15s"
        onmousedown="this.style.background='var(--surface)'" onmouseup="this.style.background='var(--surface2)'" onmouseleave="this.style.background='var(--surface2)'">
        <span style="font-size:26px;flex-shrink:0">📷</span>
        <div><div>Escanear tarjeta QR</div><div style="font-size:12px;font-weight:400;color:var(--text-dim)">Apunta al código de la tarjeta</div></div>
      </button>
      <button onclick="flujoBuscarCliente()"
        style="min-height:64px;background:var(--surface2);border:1px solid var(--border);border-radius:12px;color:var(--text);font-size:15px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:14px;padding:0 18px;width:100%;text-align:left;transition:.15s"
        onmousedown="this.style.background='var(--surface)'" onmouseup="this.style.background='var(--surface2)'" onmouseleave="this.style.background='var(--surface2)'">
        <span style="font-size:26px;flex-shrink:0">🔍</span>
        <div><div>Buscar cliente</div><div style="font-size:12px;font-weight:400;color:var(--text-dim)">Por nombre o teléfono</div></div>
      </button>
      <button onclick="flujoNuevoCliente()"
        style="min-height:64px;background:rgba(34,197,94,.07);border:1px dashed var(--accent);border-radius:12px;color:var(--accent);font-size:15px;font-weight:600;cursor:pointer;display:flex;align-items:center;gap:14px;padding:0 18px;width:100%;text-align:left;transition:.15s"
        onmousedown="this.style.background='rgba(34,197,94,.15)'" onmouseup="this.style.background='rgba(34,197,94,.07)'" onmouseleave="this.style.background='rgba(34,197,94,.07)'">
        <span style="font-size:26px;flex-shrink:0">➕</span>
        <div><div>Nuevo cliente</div><div style="font-size:12px;font-weight:400;color:var(--text-dim)">Registrar en ZERO CREDIT</div></div>
      </button>
    </div>`;
}

// ── Paso 2A: escanear QR ──────────────────────────────────────
function _extraerTokenCredit(codigo) {
  const s = (codigo || '').trim();
  if (s.includes('/credit/')) return s.split('/credit/')[1].split('?')[0].split('/')[0];
  if (s.includes('ZERO:CREDIT:')) return s.split('ZERO:CREDIT:')[1];
  return s;
}
function flujoEscanearQR() {
  abrirEscanerVideo(codigo => {
    const token = _extraerTokenCredit(codigo);
    if (!token || token.length < 6) { showToast('QR no válido para ZERO CREDIT', 'error'); return; }
    fetch(`/api/fiado/token/${encodeURIComponent(token)}`, {credentials:'include'})
      .then(r => r.json())
      .then(c => { if (c.id) seleccionarClienteCredito(c); else showToast('Cliente no encontrado', 'error'); })
      .catch(() => showToast('Error al buscar cliente', 'error'));
  });
}

// ── Paso 2B: buscar cliente (overlay full-screen) ─────────────
let _buscarCreditTimer = null;
function flujoBuscarCliente() {
  const overlay = document.getElementById('modalBuscarCredito');
  overlay.style.display = 'flex';
  document.getElementById('buscarCreditoInput').value = '';
  document.getElementById('buscarCreditoResultados').innerHTML = '';
  setTimeout(() => document.getElementById('buscarCreditoInput').focus(), 80);
}
function cerrarBuscarCredito() {
  document.getElementById('modalBuscarCredito').style.display = 'none';
  _blurActivo();
}
function buscarClientesCredito(q) {
  clearTimeout(_buscarCreditTimer);
  const div = document.getElementById('buscarCreditoResultados');
  if (!q || q.length < 2) { div.innerHTML = ''; return; }
  _buscarCreditTimer = setTimeout(async () => {
    div.innerHTML = '<div style="color:var(--text-dim);font-size:13px;padding:10px 0">Buscando...</div>';
    const res = await fetch(`/api/fiado/buscar?q=${encodeURIComponent(q)}`,{credentials:'include'}).then(r=>r.json()).catch(()=>[]);
    if (!res.length) {
      div.innerHTML = `
        <div style="color:var(--text-dim);font-size:13px;padding:14px 0;text-align:center">Sin resultados para "<strong>${escH(q)}</strong>"</div>
        <button onclick="cerrarBuscarCredito();flujoNuevoCliente(${JSON.stringify(q).replace(/"/g,'&quot;')})"
          style="width:100%;min-height:54px;background:none;border:1px dashed var(--accent);border-radius:12px;color:var(--accent);font-size:14px;font-weight:600;cursor:pointer;margin-top:4px">
          ➕ Crear nuevo cliente
        </button>`;
      return;
    }
    div.innerHTML = res.map(c => {
      const ini = (c.nombre||'?').charAt(0).toUpperCase();
      const dc = c.estado === 'vencido' ? '#ef4444' : c.deuda_actual > 0 ? '#f59e0b' : '#22c55e';
      return `<div onclick="cerrarBuscarCredito();seleccionarClienteCredito(${JSON.stringify(c).replace(/"/g,'&quot;')})"
        style="display:flex;align-items:center;gap:14px;padding:14px 0;border-bottom:1px solid var(--border);cursor:pointer">
        <div style="width:44px;height:44px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:18px;color:#fff;flex-shrink:0">${ini}</div>
        <div style="flex:1;min-width:0">
          <div style="font-weight:600;font-size:15px">${escH(c.nombre)} ${escH(c.apellido||'')}</div>
          <div style="font-size:12px;color:var(--text-dim)">${escH(c.telefono||'')}</div>
        </div>
        <div style="text-align:right;flex-shrink:0">
          <div style="font-size:13px;font-weight:700;color:${dc}">$${(c.deuda_actual||0).toLocaleString('es-CL')}</div>
          <div style="font-size:11px;color:var(--text-dim)">deuda</div>
        </div>
      </div>`;
    }).join('');
  }, 280);
}

// ── Paso 2C: nuevo cliente (overlay full-screen) ──────────────
let _ncLimiteSeleccionado = 10000;
let _ncLimiteCustom = null;
let _ncDiaPago = 15;
let _opcionalesNCAbiert = false;

function flujoNuevoCliente(preNombre) {
  document.getElementById('modalNuevoCredito').style.display = 'flex';
  document.getElementById('ncNombre').value = preNombre || '';
  document.getElementById('ncTelefono').value = '';
  document.getElementById('ncLimiteCustom').value = '';
  document.getElementById('ncDireccion') && (document.getElementById('ncDireccion').value = '');
  document.getElementById('ncCorreo') && (document.getElementById('ncCorreo').value = '');
  _ncLimiteCustom = null;
  _opcionalesNCAbiert = false;
  const co = document.getElementById('contenidoOpcionales');
  const ic = document.getElementById('iconoOpcionales');
  if (co) co.style.display = 'none';
  if (ic) ic.style.transform = 'rotate(0deg)';
  seleccionarLimite(10000);
  seleccionarDiaPago(15);
  setTimeout(() => document.getElementById('ncNombre').focus(), 80);
}
function cerrarNuevoCredito() {
  document.getElementById('modalNuevoCredito').style.display = 'none';
  _blurActivo();
}
function seleccionarLimite(val) {
  _ncLimiteSeleccionado = val;
  _ncLimiteCustom = null;
  document.getElementById('ncLimiteCustom').value = '';
  document.querySelectorAll('.nc-limite-btn').forEach(b => {
    const sel = parseInt(b.dataset.val) === val;
    b.style.background = sel ? 'var(--accent)' : 'var(--surface2)';
    b.style.color = sel ? '#fff' : 'var(--text)';
    b.style.borderColor = sel ? 'var(--accent)' : 'var(--border)';
  });
}
function seleccionarDiaPago(dia) {
  _ncDiaPago = dia;
  const inp = document.getElementById('ncDiaPago');
  if (inp) inp.value = dia;
  document.querySelectorAll('.btn-dia-pago').forEach(b => {
    const sel = parseInt(b.dataset.dia) === dia;
    b.style.background = sel ? 'var(--accent)' : 'var(--surface2)';
    b.style.color = sel ? '#fff' : 'var(--text-dim)';
    b.style.borderColor = sel ? 'var(--accent)' : 'var(--border)';
  });
}
function toggleOpcionalesNC() {
  _opcionalesNCAbiert = !_opcionalesNCAbiert;
  const co = document.getElementById('contenidoOpcionales');
  const ic = document.getElementById('iconoOpcionales');
  if (co) co.style.display = _opcionalesNCAbiert ? 'flex' : 'none';
  if (ic) ic.style.transform = _opcionalesNCAbiert ? 'rotate(180deg)' : 'rotate(0deg)';
}
async function guardarNuevoCliente() {
  const nombre = document.getElementById('ncNombre').value.trim();
  const telefono = document.getElementById('ncTelefono').value.trim();
  if (!nombre || !telefono) { showToast('Nombre y teléfono son obligatorios', 'error'); return; }
  const limite = _ncLimiteCustom || _ncLimiteSeleccionado;
  const dia_pago = _ncDiaPago || 15;
  const direccion = (document.getElementById('ncDireccion')?.value || '').trim() || undefined;
  const email = (document.getElementById('ncCorreo')?.value || '').trim() || undefined;
  const btn = document.getElementById('btnGuardarNuevoCredito');
  btn.disabled = true; btn.textContent = 'Guardando...';
  try {
    const r = await fetch('/api/fiado/clientes', {
      method:'POST', credentials:'include',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({nombre, telefono, limite_credito: limite,
        frecuencia_pago: 'dia_fijo', dia_pago, direccion, email})
    });
    const data = await r.json();
    if (!r.ok || data.error) { showToast(data.error || 'Error al crear cliente', 'error'); return; }
    cerrarNuevoCredito();
    await _imprimirTarjetaCredit(data.id);
    seleccionarClienteCredito(data);
    showToast(`Cliente ${nombre} creado`, 'success');
  } catch(e) {
    showToast('Error de conexión', 'error');
  } finally {
    btn.disabled = false; btn.textContent = 'Guardar y continuar →';
  }
}

// ── Paso 3: confirmación con resumen deuda ────────────────────
function seleccionarClienteCredito(c) {
  mostrarConfirmacionCredito(c);
}

function mostrarConfirmacionCredito(c) {
  const nuevaDeuda = (c.deuda_actual || 0) + total;
  const disponible = (c.limite_credito || 0) - (c.deuda_actual || 0);
  const supera = total > disponible;
  const ini = (c.nombre || '?').charAt(0).toUpperCase();

  document.getElementById('secCredito').innerHTML = `
    <div style="background:var(--surface2);border:1px solid var(--border);border-radius:12px;overflow:hidden">
      <div style="padding:14px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px">
        <div style="width:44px;height:44px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:20px;color:#fff;flex-shrink:0">${escH(ini)}</div>
        <div style="min-width:0">
          <div style="font-weight:700;font-size:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escH(c.nombre)} ${escH(c.apellido || '')}</div>
          <div style="font-size:12px;color:var(--text-dim)">${escH(c.telefono || 'Sin teléfono')}</div>
        </div>
      </div>
      <div style="padding:14px 16px;display:flex;flex-direction:column;gap:9px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="color:var(--text-dim);font-size:13px">Deuda anterior</span>
          <span style="font-weight:600;font-size:14px">$${(c.deuda_actual || 0).toLocaleString('es-CL')}</span>
        </div>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span style="color:var(--text-dim);font-size:13px">Esta compra</span>
          <span style="font-weight:600;font-size:14px;color:var(--accent)">+ $${total.toLocaleString('es-CL')}</span>
        </div>
        <div style="border-top:1px solid var(--border);padding-top:9px;display:flex;justify-content:space-between;align-items:center">
          <span style="font-weight:700;font-size:14px">Nueva deuda</span>
          <span style="font-weight:700;font-size:17px;color:${supera ? '#ef4444' : 'var(--text)'}">${fmt(nuevaDeuda)}</span>
        </div>
        ${supera ? `<div style="background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);border-radius:8px;padding:9px 12px;font-size:12px;color:#ef4444;font-weight:600">⛔ Supera el límite de ${fmt(c.limite_credito || 0)}. Disponible: ${fmt(Math.max(0, disponible))}</div>` : ''}
      </div>
    </div>`;

  document.getElementById('footerCobro').innerHTML =
    `<button class="btn-cancelar" onclick="renderPasoCredito();_resetFooterCobro()">← Cambiar</button>` +
    `<button class="btn-confirmar" id="btnConfirmarCredito" ${supera ? 'disabled style="opacity:.4;cursor:not-allowed"' : ''} onclick="confirmarVentaCredito(${c.id})">✓ Confirmar venta</button>`;

  _creditClienteId = supera ? null : c.id;
}

function confirmarVentaCredito(clienteId) {
  _creditClienteId = clienteId;
  confirmarPago();
}

async function _postVentaCredito(ventaId) {
  if (!_creditClienteId || !ventaId) return;
  const cid = _creditClienteId;
  const esNuevo = _creditClienteNuevo;
  _creditClienteId = null;
  _creditClienteNuevo = false;
  try {
    await fetch('/api/fiado/cargo', {
      method:'POST', credentials:'include',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({cliente_id: cid, monto: total, venta_id: ventaId})
    });
    if (esNuevo) await _imprimirTarjetaCredit(cid);
  } catch(e) { console.warn('fiado/cargo error:', e); }
}
async function _imprimirTarjetaCredit(cid) {
  try {
    await fetch(`/api/fiado/clientes/${cid}/imprimir_tarjeta`, {
      method:'POST', credentials:'include'
    });
  } catch(e) { console.warn('tarjeta credit print error:', e); }
}
async function cargarFiadosBadge() {
  try {
    const r = await fetch('/api/fiado/resumen',{credentials:'include'}).then(r=>r.json());
    const n = r.vencidos || 0;
    const btn = document.getElementById('btnCreditBadge');
    const badge = document.getElementById('creditBadge');
    if (btn && badge) {
      btn.style.display = n > 0 ? '' : 'none';
      badge.textContent = n > 9 ? '9+' : n;
    }
  } catch(_) {}
}

async function crearPagoKhipu() {
  const btn = document.getElementById('btnConfirmar');
  btn.disabled = true; btn.textContent = 'Creando link...';
  try {
    const r = await fetch('/api/khipu/crear_pago', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({monto: total, concepto: 'Compra en tienda'}),
    }).then(r => r.json());
    if (r.payment_url) {
      window.open(r.payment_url, '_blank');
      showToast('Link Khipu abierto', 'success');
    } else {
      showToast(r.error || 'Error Khipu', 'error');
    }
  } catch(e) {
    showToast('Error de conexión', 'error');
  } finally {
    btn.disabled = false; btn.textContent = '✓ Confirmar pago';
  }
}

// ── SumUp Air ────────────────────────────────────────────────
let _sumupPollingInterval = null;

async function cobrarConSumUp() {
  if (_sumupPollingInterval) { clearInterval(_sumupPollingInterval); _sumupPollingInterval = null; }
  const btn = document.getElementById('btnConfirmar');
  btn.disabled = true;
  btn.textContent = 'Iniciando SumUp...';
  try {
    const resp = await fetch('/api/sumup/crear_link_pago', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({monto: total, descripcion: `Venta ZERO POS #${Date.now()}`}),
    });
    const data = await resp.json();
    if (!data.ok) {
      showToast(data.error || 'Error SumUp', 'error');
      btn.disabled = false; btn.textContent = '✓ Confirmar pago';
      return;
    }
    // Mostrar QR en pantalla cliente
    try {
      await fetch('/api/ventas/pantalla-cliente/estado', {
        method: 'POST', credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          estado:      'cobrar_tarjeta',
          total,
          checkout_id: data.checkout_id,
          link_pago:   data.link_pago,
        }),
      });
    } catch(e) { /* pantalla cliente opcional */ }
    btn.textContent = '⏳ Esperando pago...';
    showToast('💳 El cliente puede escanear el QR o usar el lector Air', 'info');
    _iniciarPollingCheckout(data.checkout_id);
  } catch(e) {
    showToast('Error de conexión', 'error');
    btn.disabled = false; btn.textContent = '✓ Confirmar pago';
  }
}

function _iniciarPollingCheckout(checkoutId) {
  const MAX_ESPERA = 120;
  let segundos = 0;
  _sumupPollingInterval = setInterval(async () => {
    segundos += 3;
    if (segundos >= MAX_ESPERA) {
      clearInterval(_sumupPollingInterval); _sumupPollingInterval = null;
      showToast('Tiempo de espera SumUp agotado', 'error');
      const btn = document.getElementById('btnConfirmar');
      if (btn) { btn.disabled = false; btn.textContent = '✓ Confirmar pago'; }
      return;
    }
    try {
      const r = await fetch(`/api/sumup/estado/${checkoutId}`, {credentials: 'include'});
      const estado = await r.json();
      if (estado.pagado) {
        clearInterval(_sumupPollingInterval); _sumupPollingInterval = null;
        showToast('✅ Pago aprobado con SumUp', 'success');
        metodoPago = 'tarjeta';
        await confirmarPago();
      }
    } catch(e) { /* ignorar errores transitorios de red */ }
  }, 3000);
}

// ── Variantes (modal fallback) ───────────────────────────────
let productoActual = null;

// ── Variantes — bottom sheet Aurora v2 ──────────────────────────
let _varianteSeleccionada = null;
let _varianteQty = 1;
let _varianteProd = null;

async function abrirVariantes(prod) {
  productoActual = prod;
  _varianteProd = prod;
  _varianteSeleccionada = null;
  _varianteQty = 1;

  document.getElementById('variantesTitulo').textContent = prod.nombre;
  document.getElementById('variantesSubtitulo').textContent = 'Elige una presentación';
  document.getElementById('variantesQtyDisplay').textContent = '1';
  document.getElementById('variantesAddLabel').textContent = 'Selecciona una opción';
  document.getElementById('variantesAddPrice').textContent = '';
  document.getElementById('variantesAddBtn').disabled = true;

  // Ícono del producto en el sheet header
  const tablerIcon = getProductTablerIcon(prod);
  document.getElementById('variantesSheetIcon').innerHTML =
    `<i class="ti ${tablerIcon}"></i>`;

  document.getElementById('variantesGrid').innerHTML =
    '<div style="color:var(--text-dim);font-size:13px;padding:20px 22px;">Cargando...</div>';
  document.getElementById('modalVariantes').classList.add('active');

  const variantes = prod._variantes && prod._variantes.length
    ? prod._variantes
    : await fetch(`/api/productos/${prod.id}/variantes`, {credentials:'include'})
        .then(r => r.json()).catch(() => []);

  const list = document.getElementById('variantesGrid');
  if (!variantes.length) {
    list.innerHTML = '<div style="color:var(--text-dim);font-size:13px;padding:20px 22px;">Sin variantes disponibles</div>';
    return;
  }

  document.getElementById('variantesSubtitulo').textContent =
    `${variantes.length} ${variantes.length === 1 ? 'formato' : 'formatos'} disponibles`;

  list.innerHTML = '';
  variantes.forEach((v, i) => {
    const row = document.createElement('div');
    const agotada = v.stock <= 0;
    row.className = 'variant-row' + (agotada ? ' sin-stock' : '');
    if (agotada) row.style.opacity = '0.45';

    const stockBajo = !agotada && v.stock > 0 && v.stock < 5;
    const esMasVendido = i === 0 && variantes.length > 2;
    const badgeTop = esMasVendido ? '<span class="badge-top">MÁS VENDIDO</span>' : '';
    const descLine = agotada
      ? `<div class="vdesc" style="color:var(--danger)">Sin stock</div>`
      : stockBajo
        ? `<div class="vdesc low">⚠ quedan ${v.stock}</div>`
        : `<div class="vdesc">Stock: ${v.stock}</div>`;

    row.innerHTML = `
      <i class="ti ti-circle vr-radio"></i>
      <div class="vinfo">
        <div class="vtop"><span class="vname">${escH(v.nombre)}</span>${badgeTop}</div>
        ${descLine}
      </div>
      <div class="vprice">${fmt(v.precio)}</div>`;

    if (!agotada) {
      row.onclick = () => _seleccionarVariante(row, v);
    }
    list.appendChild(row);
  });
}

function _seleccionarVariante(row, variante) {
  document.querySelectorAll('#variantesGrid .variant-row').forEach(r => {
    r.classList.remove('selected');
    r.querySelector('.vr-radio').className = 'ti ti-circle vr-radio';
  });
  row.classList.add('selected');
  row.querySelector('.vr-radio').className = 'ti ti-circle-check-filled vr-radio';
  _varianteSeleccionada = variante;
  _actualizarSheetBtn();
}

function _actualizarSheetBtn() {
  if (!_varianteSeleccionada) return;
  const qty = _varianteQty;
  document.getElementById('variantesAddLabel').textContent =
    `Agregar${qty > 1 ? ' ' + qty + ' ×' : ''} ${_varianteSeleccionada.nombre}`;
  document.getElementById('variantesAddPrice').textContent =
    fmt(_varianteSeleccionada.precio * qty);
  document.getElementById('variantesAddBtn').disabled = false;
}

function _varianteStepper(delta) {
  _varianteQty = Math.max(1, Math.min(99, _varianteQty + delta));
  document.getElementById('variantesQtyDisplay').textContent = _varianteQty;
  if (_varianteSeleccionada) _actualizarSheetBtn();
}

function _confirmarVarianteSeleccionada() {
  if (!_varianteSeleccionada || !_varianteProd) return;
  agregarAlCarritoConVariante(_varianteProd, _varianteSeleccionada);
  if (_varianteQty > 1) {
    const key = `${_varianteProd.id}_v${_varianteSeleccionada.id}`;
    const idx = carrito.findIndex(i => i._key === key);
    if (idx >= 0) { carrito[idx].cantidad += (_varianteQty - 1); renderCarrito(); }
  }
  cerrarVariantes();
}

function cerrarVariantes() {
  document.getElementById('modalVariantes').classList.remove('active');
  productoActual = null;
  _varianteSeleccionada = null;
  _varianteProd = null;
  _varianteQty = 1;
  cerrarPanelSinTeclado();
}

function agregarAlCarritoConVariante(prod, variante) {
  const key = `${prod.id}_v${variante.id}`;
  const idx = carrito.findIndex(i => i._key === key);
  let _stockWarn = false;
  if (idx >= 0) {
    carrito[idx].cantidad++;
    if (variante.stock > 0 && carrito[idx].cantidad > variante.stock) {
      _stockWarn = true;
      showToast(`⚠️ Stock insuficiente — quedan ${variante.stock} unidades`, 'warning');
    }
  } else {
    carrito.push({
      _key: key, producto_id: prod.id, variante_id: variante.id,
      nombre: `${prod.nombre} — ${variante.nombre}`, nombre_variante: variante.nombre,
      precio_unit: variante.precio, cantidad: 1, stock: variante.stock,
    });
  }
  renderCarrito();
  if (!_stockWarn) showToast(`+ ${prod.nombre} (${variante.nombre})`, 'success');
}

// ── Venta rápida ─────────────────────────────────────────────
let itemsRapidos = [];
let lookupTimer = null;

function abrirVentaRapida() {
  itemsRapidos = [];
  document.getElementById('rapidaNombre').value = '';
  document.getElementById('rapidaPrecio').value = '';
  document.getElementById('rapidaCantidad').value = '1';
  document.getElementById('rapidaBarras').value = '';
  document.getElementById('lookupResult').style.display = 'none';
  document.getElementById('rapidaItems').innerHTML = '';
  document.getElementById('modalRapida').classList.add('active');
}

function cerrarVentaRapida() { document.getElementById('modalRapida').classList.remove('active'); cerrarPanelSinTeclado(); }

function lookupRapida(codigo) {
  clearTimeout(lookupTimer);
  if (codigo.length < 6) { document.getElementById('lookupResult').style.display = 'none'; return; }
  lookupTimer = setTimeout(async () => {
    const r = await fetch(`/api/productos/barras/${encodeURIComponent(codigo)}/lookup`, {credentials:'include'})
      .then(r => r.json()).catch(() => null);
    const box = document.getElementById('lookupResult');
    if (r && r.encontrado) {
      document.getElementById('lookupNombre').textContent = r.nombre || r.producto_nombre || '';
      const fuentes = {local:'✓ En tu catálogo', catalogo_base:'📋 Catálogo base', open_food_facts:'🌐 Open Food Facts'};
      document.getElementById('lookupFuente').textContent = fuentes[r.fuente] || r.fuente;
      box.style.display = 'block';
      if (!document.getElementById('rapidaNombre').value)
        document.getElementById('rapidaNombre').value = r.nombre || r.producto_nombre || '';
      if (!document.getElementById('rapidaPrecio').value && r.precio_sugerido)
        document.getElementById('rapidaPrecio').value = r.precio_sugerido;
    } else {
      box.style.display = 'none';
    }
  }, 500);
}

function agregarItemRapido() {
  const nombre = document.getElementById('rapidaNombre').value.trim();
  const precio = parseFloat(document.getElementById('rapidaPrecio').value) || 0;
  const cantidad = parseInt(document.getElementById('rapidaCantidad').value) || 1;
  if (!nombre) { showToast('Ingresa una descripción', 'error'); return; }
  if (precio <= 0) { showToast('Ingresa un precio', 'error'); return; }
  itemsRapidos.push({nombre, precio_unit: precio, cantidad});
  document.getElementById('rapidaNombre').value = '';
  document.getElementById('rapidaPrecio').value = '';
  document.getElementById('rapidaCantidad').value = '1';
  document.getElementById('rapidaBarras').value = '';
  document.getElementById('lookupResult').style.display = 'none';
  renderItemsRapidos();
}

function renderItemsRapidos() {
  const el = document.getElementById('rapidaItems');
  el.innerHTML = '';
  itemsRapidos.forEach((it, idx) => {
    const div = document.createElement('div');
    div.className = 'rapida-item';
    div.innerHTML = `
      <div class="rapida-item-nombre">${it.nombre} x${it.cantidad}</div>
      <div class="rapida-item-precio">${fmt(it.precio_unit * it.cantidad)}</div>
      <button class="rapida-item-del" onclick="eliminarItemRapido(${idx})">✕</button>`;
    el.appendChild(div);
  });
}

function eliminarItemRapido(idx) { itemsRapidos.splice(idx, 1); renderItemsRapidos(); }

function confirmarVentaRapida() {
  if (!itemsRapidos.length) { showToast('Agrega al menos un item', 'error'); return; }
  itemsRapidos.forEach(it => {
    carrito.push({
      _key: `rapida_${Date.now()}_${Math.random()}`,
      producto_id: null, variante_id: null,
      nombre: it.nombre, nombre_variante: '',
      precio_unit: it.precio_unit, cantidad: it.cantidad, stock: 9999,
      _rapida: true,
      _guardar: document.getElementById('rapidaGuardar').checked,
    });
  });
  cerrarVentaRapida();
  renderCarrito();
}

// ── Extras ───────────────────────────────────────────────────
async function verificarAlertas() {
  const data = await fetch('/api/productos/alertas', {credentials:'include'}).then(r => r.json()).catch(() => []);
  if (data.length > 0) {
    const btn = document.getElementById('btnAlertas');
    if (btn) btn.innerHTML = `⚠️ <span class="badge-alert">${data.length}</span>`;
  }
}

function verAlertas() { location.href = 'inventario.html'; }
// ── Escáner: input[type=file] + BarcodeDetector/ZXing ────────────────────────

function _escanerOverlay(msg) {
  const el = document.getElementById('escanerOverlay');
  if (msg) {
    document.getElementById('escanerOverlayMsg').textContent = msg;
    el.style.display = 'flex';
  } else {
    el.style.display = 'none';
  }
}

async function detectarConZXing(file) {
  try {
    await Escaner._cargarZXing();
    if (typeof ZXing === 'undefined') return null;
    return new Promise(resolve => {
      const img = new Image();
      const url = URL.createObjectURL(file);
      img.onload = () => {
        const MAX = 1200;
        let w = img.width, h = img.height;
        if (w > MAX || h > MAX) {
          const ratio = Math.min(MAX / w, MAX / h);
          w = Math.floor(w * ratio); h = Math.floor(h * ratio);
        }
        const canvas = document.createElement('canvas');
        canvas.width = w; canvas.height = h;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, w, h);
        console.log('[ZERO] Canvas ZXing:', w, 'x', h);
        try {
          const d = ctx.getImageData(0, 0, w, h);
          const lum = new ZXing.RGBLuminanceSource(d.data, w, h);
          const bin = new ZXing.BinaryBitmap(new ZXing.HybridBinarizer(lum));
          const r = new ZXing.MultiFormatReader().decode(bin);
          URL.revokeObjectURL(url);
          console.log('[ZERO] ZXing encontró:', r.getText());
          resolve(r.getText());
        } catch (e) {
          try {
            const cx = Math.floor(w * 0.1), cy = Math.floor(h * 0.1);
            const cw = Math.floor(w * 0.8), ch = Math.floor(h * 0.8);
            const d2 = ctx.getImageData(cx, cy, cw, ch);
            const lum2 = new ZXing.RGBLuminanceSource(d2.data, cw, ch);
            const bin2 = new ZXing.BinaryBitmap(new ZXing.HybridBinarizer(lum2));
            const r2 = new ZXing.MultiFormatReader().decode(bin2);
            URL.revokeObjectURL(url);
            console.log('[ZERO] ZXing centro:', r2.getText());
            resolve(r2.getText());
          } catch (e2) {
            URL.revokeObjectURL(url);
            console.warn('[ZERO] ZXing no detectó código');
            resolve(null);
          }
        }
      };
      img.onerror = () => { URL.revokeObjectURL(url); resolve(null); };
      img.src = url;
    });
  } catch (e) {
    console.error('[ZERO] Error ZXing:', e);
    return null;
  }
}

const Escaner = {
  stream:        null,
  activo:        false,
  detector:      null,
  canvas:        null,
  ctx:           null,
  video:         null,
  ultimoScan:    0,
  _callback:     null,
  _procesando:   false,
  _zxingPromise: null,
  INTERVALO_MS:  800,

  _cargarZXing() {
    if (typeof ZXing !== 'undefined') return Promise.resolve();
    if (this._zxingPromise) return this._zxingPromise;
    this._zxingPromise = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/@zxing/library@0.20.0/umd/index.min.js';
      s.onload = () => { console.log('[ZERO] ZXing cargado OK'); setTimeout(resolve, 100); };
      s.onerror = e => { console.error('[ZERO] ZXing falló al cargar:', e); reject(e); };
      document.head.appendChild(s);
    });
    return this._zxingPromise;
  },

  async init() {
    this.video  = document.getElementById('videoEscaner');
    this.canvas = document.getElementById('canvasEscaner');
    this.ctx    = this.canvas.getContext('2d', {willReadFrequently: true, alpha: false});

    if ('BarcodeDetector' in window) {
      try {
        this.detector = new BarcodeDetector({
          formats: ['ean_13', 'ean_8', 'code_128', 'code_39', 'upc_a', 'upc_e'],
        });
        console.log('[ZERO] BarcodeDetector nativo disponible');
      } catch(e) { this.detector = null; }
    }

    if (!this.detector) await this._cargarZXing().catch(() => {});
  },

  async abrir(onCodigo) {
    this._callback = onCodigo || null;
    if (!this.video) await this.init();
    document.getElementById('modalEscaner').style.display = 'flex';
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: 'environment',
          width:  {ideal: 1280, max: 1920},
          height: {ideal: 720,  max: 1080},
          frameRate: {ideal: 30},
        },
      });
      this.video.srcObject = this.stream;
      await this.video.play();
      this.video.addEventListener('loadedmetadata', () => {
        const w = this.video.videoWidth, h = this.video.videoHeight;
        this.canvas.width  = Math.floor(w * 0.6);
        this.canvas.height = Math.floor(h * 0.4);
      }, {once: true});
      this.activo = true;
      this._bucle();
    } catch(err) {
      console.error('[ZERO] Error cámara:', err);
      this.cerrar();
      showToast('No se pudo acceder a la cámara', 'error');
      document.getElementById('searchInput').focus();
    }
  },

  _bucle() {
    const tick = async () => {
      requestAnimationFrame(tick);
      if (!this.activo || this._pausado) return;
      const ahora = performance.now();
      if (ahora - this.ultimoScan >= this.INTERVALO_MS) {
        this.ultimoScan = ahora;
        await this._procesarFrame();
      }
    };
    requestAnimationFrame(tick);
  },

  async _procesarFrame() {
    if (this._procesando) return;
    this._procesando = true;
    if (!this.video || this.video.readyState < 2) { this._procesando = false; return; }
    const vw = this.video.videoWidth, vh = this.video.videoHeight;
    if (!vw || !vh) { this._procesando = false; return; }

    const sx = Math.floor(vw * 0.2), sy = Math.floor(vh * 0.3);
    const sw = Math.floor(vw * 0.6), sh = Math.floor(vh * 0.4);
    if (!this.canvas.width) { this.canvas.width = sw; this.canvas.height = sh; }
    this.ctx.drawImage(this.video, sx, sy, sw, sh, 0, 0, this.canvas.width, this.canvas.height);

    let codigo = null;

    if (this.detector) {
      try {
        const res = await this.detector.detect(this.canvas);
        if (res.length) codigo = res[0].rawValue;
      } catch(e) {}
    }

    if (!codigo) {
      try {
        await new Promise(resolve => {
          this.canvas.toBlob(async blob => {
            if (!blob) { resolve(); return; }
            const fd = new FormData();
            fd.append('imagen', blob, 'frame.jpg');
            const resp = await fetch('/api/productos/detectar-codigo', {
              method: 'POST',
              credentials: 'include',
              body: fd
            });
            const data = await resp.json();
            if (data.ok && data.codigo) codigo = data.codigo;
            resolve();
          }, 'image/jpeg', 0.8);
        });
      } catch(e) {}
    }

    if (codigo) {
      this._procesando = false;
      this._onDetectado(codigo);
    } else {
      this._procesando = false;
    }
  },

  _onDetectado(codigo) {
    this._feedbackExito();
    if (navigator.vibrate) navigator.vibrate(50);
    const cb = this._callback;
    if (cb) {
      cb(codigo);
      this.cerrar();
    } else {
      procesarCodigo(codigo);
      this._pausado = true;
      setTimeout(() => { this._pausado = false; }, 1500);
    }
  },

  _feedbackExito() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 1800;
      osc.type = 'sine';
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.15);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.15);
    } catch(e) {}
    const fb = document.getElementById('feedbackEscaner');
    const marco = document.getElementById('marcoEscaneo');
    if (fb) { fb.textContent = '✓ Detectado'; fb.classList.add('show'); }
    if (marco) marco.style.borderColor = '#22c55e';
    setTimeout(() => {
      if (fb) fb.classList.remove('show');
      if (marco) marco.style.borderColor = '#22c55e';
    }, 300);
  },

  cerrar() {
    this.activo = false;
    this._procesando = false;
    this._callback = null;
    if (this.stream) {
      this.stream.getTracks().forEach(t => t.stop());
      this.stream = null;
    }
    document.getElementById('modalEscaner').style.display = 'none';
    const si = document.getElementById('searchInput');
    // no focus — evita teclado en móvil
  },
};

function abrirEscanerVideo(onCodigo) { Escaner.abrir(onCodigo); }

function abrirEscanerArchivo(onCodigo) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*';
  if (/iPhone|iPad|Android/i.test(navigator.userAgent)) input.capture = 'environment';
  input.style.display = 'none';
  document.body.appendChild(input);
  input.addEventListener('change', async e => {
    const file = e.target.files?.[0];
    document.body.removeChild(input);
    if (!file) return;
    showToast('🔍 Analizando...', 'info');
    try {
      const fd = new FormData();
      fd.append('imagen', file);
      const resp = await fetch('/api/productos/detectar-codigo', { method: 'POST', credentials: 'include', body: fd });
      const data = await resp.json();
      if (data.ok && data.codigo) {
        onCodigo(data.codigo);
      } else {
        showToast('No detectado — ingresa el código', 'error');
        const campo = document.getElementById('searchInput');
        if (campo && !esMobil()) { campo.focus(); campo.select(); }
      }
    } catch(e) {
      showToast('Error al procesar imagen', 'error');
    }
  });
  input.click();
}

function abrirEscaner() { Escaner.abrir(); }
function abrirScanner() { Escaner.abrir(); }
async function cerrarSesion() {
  const t = await fetch('/api/auth/turno/actual', {credentials:'include'}).then(r=>r.json()).catch(()=>({}));
  if (t.turno) {
    showToast('Debes cerrar el turno antes de cerrar sesión', 'error');
    return;
  }
  limpiarCarritoLocal();
  await fetch('/api/auth/logout', {method:'POST', credentials:'include'});
  location.href = 'login.html';
}

function showToast(msg, type = 'success') {
  document.querySelectorAll('.zero-toast').forEach(t => t.classList.remove('show'));
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast zero-toast show ${type}`;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => t.classList.remove('show'), 3000);
}

// ── Escáner optimizado — O(1) lookup en índice local ─────────────────────────

function procesarCodigo(codigo) {
  codigo = String(codigo || '').trim();
  if (!codigo) return;
  const inicio = performance.now();

  // QR de lote ZERO (JSON {t:'L',...})
  if (codigo.startsWith('{')) {
    buscarCodigo(codigo, inicio);
    return;
  }

  // Granel EAN-13 (prefijo 2)
  if (codigo.startsWith('2') && /^\d{13}$/.test(codigo)) {
    procesarCodigoGranel(codigo);
    return;
  }

  // Búsqueda O(1) en índice local
  const producto = indiceCodigo.get(codigo);
  if (producto) {
    agregarAlCarritoLocal(producto);
    const ms = performance.now() - inicio;
    medirScan(ms);
    console.log(`[ZERO] Escaneado en ${ms.toFixed(1)}ms`);
    return;
  }

  // Fallback: servidor
  buscarEnServidor(codigo, inicio);
}

async function buscarCodigo(codigo, inicioMs) {
  try {
    const r = await fetch('/api/productos/buscar-codigo', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({codigo}),
    });
    const data = await r.json();

    if (r.status === 400 && data.vencido) {
      mostrarAlertaVencido(data);
      return;
    }
    if (!r.ok) { showToast(data.error || 'Código no encontrado', 'error'); return; }

    if (data.id) {
      // Agregar con info de lote si aplica
      agregarAlCarritoLocal({
        ...data,
        _lote_id:     data.lote_id     || null,
        _lote_numero: data.lote_numero || null,
        _vencimiento: data.vencimiento || null,
      });
      const ms = performance.now() - (inicioMs || performance.now());
      console.log(`[ZERO] QR lote escaneado en ${ms.toFixed(1)}ms`);
    } else {
      showToast('Producto no encontrado', 'error');
    }
  } catch(e) {
    showToast('Error buscando código', 'error');
  }
}

let _vencidoDatos = null;

function mostrarAlertaVencido(data) {
  _vencidoDatos = data;
  document.getElementById('vencidoNombre').textContent = data.nombre || 'Producto vencido';
  const fecha = data.vencimiento ? `Venció el ${data.vencimiento}` : 'Fecha de vencimiento desconocida';
  document.getElementById('vencidoFecha').textContent = fecha;
  document.getElementById('modalVencido').style.display = 'flex';
}

async function _registrarMermaVencido() {
  if (!_vencidoDatos) return;
  try {
    const body = {
      lote_id:    _vencidoDatos.lote_id    || null,
      producto_id: _vencidoDatos.id,
      cantidad:   1,
      motivo:     'vencimiento',
    };
    const r = await fetch('/api/inventario/mermas', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    if (r.ok) {
      showToast('Merma registrada', 'success');
    } else {
      const d = await r.json();
      showToast(d.error || 'Error al registrar merma', 'error');
    }
  } catch(e) {
    showToast('Error al registrar merma', 'error');
  } finally {
    document.getElementById('modalVencido').style.display = 'none';
    _vencidoDatos = null;
  }
}

function procesarCodigoGranel(codigo) {
  const pesoGramos = parseInt(codigo.slice(7, 12)) / 1000;
  const codBase = '2' + codigo.slice(1, 7);
  const prod = indiceCodigo.get(codBase) || (() => {
    for (const [, p] of indiceId) {
      if (p.es_granel && p.codigo_barras && String(p.codigo_barras).startsWith('2'))
        return p;
    }
    return null;
  })();
  if (prod) {
    carrito.push({
      producto_id: prod.id,
      variante_id: null,
      nombre: `${prod.nombre} (${pesoGramos}kg)`,
      nombre_variante: '',
      precio_unit: Math.round((prod.precio || 0) * pesoGramos),
      cantidad: 1,
      stock: prod.stock_real ?? prod.stock,
      modo_stock: prod.modo_stock || 'normal',
      _new: true,
    });
    renderCarrito();
    flashProducto(prod.id);
    limpiarYEnfocarBusqueda();
  } else {
    buscarEnServidor(codigo, performance.now());
  }
}

async function buscarEnServidor(codigo, inicioMs) {
  try {
    const r = await fetch(`/api/productos/barras/${encodeURIComponent(codigo)}`, {credentials:'include'});
    const data = await r.json();
    if (data && data.id) {
      if (data.codigo_barras) indiceCodigo.set(String(data.codigo_barras), data);
      indiceId.set(data.id, data);
      agregarAlCarritoLocal(data);
      const ms = performance.now() - inicioMs;
      medirScan(ms);
      console.log(`[ZERO] Escaneado vía servidor en ${ms.toFixed(1)}ms`);
    } else {
      showToast('Producto no encontrado: ' + codigo, 'error');
    }
  } catch(e) {
    showToast('Error buscando código', 'error');
  }
}

function agregarAlCarritoLocal(producto) {
  const vSel = producto.variante_seleccionada || null;
  const varianteId = vSel ? vSel.id : null;
  const precio = vSel ? vSel.precio : producto.precio;
  const nombreFull = producto.nombre + (vSel ? ' ' + vSel.nombre : '');
  const stockDisp = vSel ? (vSel.stock ?? 9999) : (producto.stock_real ?? producto.stock ?? 9999);
  const modoStock = producto.modo_stock || 'normal';

  const idx = carrito.findIndex(i => i.producto_id === producto.id && i.variante_id === varianteId);
  if (idx >= 0) {
    if (modoStock !== 'sin_stock' && carrito[idx].cantidad >= stockDisp) {
      showToast('Stock máximo alcanzado', 'error'); return;
    }
    carrito[idx].cantidad++;
  } else {
    carrito.push({
      producto_id: producto.id,
      variante_id: varianteId,
      nombre: nombreFull,
      nombre_variante: vSel ? vSel.nombre : '',
      precio_unit: precio,
      cantidad: 1,
      stock: stockDisp,
      modo_stock: modoStock,
      lote_id:     producto._lote_id     || null,
      lote_numero: producto._lote_numero || null,
      vencimiento: producto._vencimiento || null,
      _new: true,
    });
  }
  renderCarrito();
  flashProducto(producto.id);
  limpiarYEnfocarBusqueda();
}

function _renderProductosLista(lista, grid) {
  const _COLORES_LISTA = ['#0ea5e9','#14b8a6','#06b6d4','#10b981','#f59e0b','#ef4444','#ec4899'];
  lista.forEach((p, idx) => {
    productoMap[p.id] = p;
    const modoStock = p.modo_stock || 'normal';
    const sinStock = !p.tiene_variantes && modoStock !== 'sin_stock' && p.stock <= 0;
    const color = _COLORES_LISTA[idx % _COLORES_LISTA.length];
    const nombreSafe = escH(p.nombre);

    const fila = document.createElement('div');
    fila.className = 'prod-fila' + (sinStock ? ' sin-stock' : '');
    fila.setAttribute('data-producto-id', p.id);

    let imgHtml;
    if (p.imagen_url) {
      imgHtml = `<div class="fila-img" style="background:${color}20"><img loading="lazy" src="${escH(p.imagen_url)}" onerror="this.style.display='none'"></div>`;
    } else {
      imgHtml = `<div class="fila-img" style="background:${color}20">${getProductEmoji(p)}</div>`;
    }

    let subHtml, precio;
    if (p.tiene_variantes) {
      const nVar = p._variantes ? p._variantes.length : '?';
      subHtml = `<div class="fila-sub variante">${nVar} variantes</div>`;
      precio = p._variantes && p._variantes.length ? fmt(Math.min(...p._variantes.map(v => v.precio))) : '—';
    } else {
      const bajo = p.stock > 0 && p.stock <= p.stock_minimo;
      const stockTxt = modoStock === 'sin_stock' ? '' : `Stock: ${p.stock}${bajo ? ' ⚠️':''}`;
      subHtml = stockTxt ? `<div class="fila-sub">${stockTxt}</div>` : '';
      precio = fmt(p.precio);
    }

    const precioColor = p.precio > 0 ? '#22c55e' : 'var(--text-dim)';
    fila.innerHTML = `
      ${imgHtml}
      <div class="fila-info">
        <div class="fila-nombre">${nombreSafe}</div>
        ${subHtml}
      </div>
      <div class="fila-precio" style="color:${precioColor}">${precio}</div>`;

    if (!sinStock) {
      if (p.tiene_variantes) {
        fila.onclick = () => abrirVariantes(p);
      } else {
        fila.onclick = () => agregarAlCarrito(p);
      }
    }
    grid.appendChild(fila);
  });
}

function flashProducto(productoId) {
  const card = document.querySelector(`[data-producto-id="${productoId}"]`);
  if (!card) return;
  card.classList.remove('flash');
  void card.offsetWidth; // reflow to restart animation
  card.classList.add('flash');
  setTimeout(() => card.classList.remove('flash'), 200);
}

function limpiarYEnfocarBusqueda() {
  const campo = document.getElementById('searchInput');
  if (!campo) return;
  campo.value = '';
  if (!esMobil()) campo.focus();
}

function medirScan(ms) {
  scanTiempos.push(ms);
  if (scanTiempos.length % 10 === 0) {
    const promedio = scanTiempos.slice(-10).reduce((a, b) => a + b, 0) / 10;
    console.log(`[ZERO] Promedio últimos 10 scans: ${promedio.toFixed(1)}ms`);
  }
}

// ── Navbar ───────────────────────────────────────────────────────
async function cargarBadgeCredito() {
  try {
    const data = await fetch('/api/fiado/resumen', {credentials:'include'}).then(r => r.json());
    const badge = document.getElementById('badgeCreditoNav');
    if (badge) {
      if (data.vencidos > 0) { badge.textContent = data.vencidos; badge.style.display = 'inline-block'; }
      else badge.style.display = 'none';
    }
  } catch(e) {}
}

function toggleUserMenu() {
  const dd = document.getElementById('userMenuDropdown');
  if (!dd) return;
  dd.style.display = dd.style.display === 'block' ? 'none' : 'block';
}
document.addEventListener('click', e => {
  const btn = document.getElementById('btnUserMenu');
  const dd = document.getElementById('userMenuDropdown');
  if (dd && btn && !btn.contains(e.target) && !dd.contains(e.target)) {
    dd.style.display = 'none';
  }
});

function abrirNavbar() {
  const nombre = document.getElementById('cajeroNombre')?.textContent || '';
  document.getElementById('menuCajeroNombre').textContent = nombre;
  document.getElementById('navbarDrawer').classList.add('abierto');
  document.getElementById('navbarOverlay').classList.add('visible');
  _blurActivo();
  cargarBadgeCredito();
}
function cerrarNavbar() {
  document.getElementById('navbarDrawer').classList.remove('abierto');
  document.getElementById('navbarOverlay').classList.remove('visible');
  _blurActivo();
}
// Alias legacy (en caso de referencias pendientes)
function abrirDrawerMenu() { abrirNavbar(); }
function cerrarDrawerMenu() { cerrarNavbar(); }

// Swipe para cerrar navbar y carrito
document.addEventListener('DOMContentLoaded', () => {
  // En móvil: interceptar foco no-confiable en searchInput (causado por blur de otros elementos)
  if (esMobil()) {
    const si = document.getElementById('searchInput');
    si?.addEventListener('focus', e => {
      if (!e.isTrusted) { e.preventDefault(); si.blur(); }
    });
  }

  // ── Navbar swipe ──
  const navDrawer = document.getElementById('navbarDrawer');
  let startX = 0, isDraggingNav = false;
  navDrawer?.addEventListener('touchstart', e => {
    startX = e.touches[0].clientX;
    isDraggingNav = true;
    navDrawer.style.transition = 'none';
  }, { passive: true });
  navDrawer?.addEventListener('touchmove', e => {
    if (!isDraggingNav) return;
    const diff = startX - e.touches[0].clientX;
    if (diff > 0) navDrawer.style.transform = `translateX(-${diff}px)`;
  }, { passive: true });
  navDrawer?.addEventListener('touchend', e => {
    if (!isDraggingNav) return;
    isDraggingNav = false;
    navDrawer.style.transition = '';
    navDrawer.style.transform = '';
    if (startX - e.changedTouches[0].clientX > 80) cerrarNavbar();
  }, { passive: true });

  // ── Carrito swipe hacia abajo ──
  const sheet = document.getElementById('carrito');
  const handle = document.getElementById('carritoHandle');
  let startY = 0, isDraggingCart = false;
  handle?.addEventListener('touchstart', e => {
    startY = e.touches[0].clientY;
    isDraggingCart = true;
    sheet.style.transition = 'none';
  }, { passive: true });
  document.addEventListener('touchmove', e => {
    if (!isDraggingCart) return;
    const diff = e.touches[0].clientY - startY;
    if (diff > 0) sheet.style.transform = `translateY(${diff}px)`;
  }, { passive: true });
  document.addEventListener('touchend', e => {
    if (!isDraggingCart) return;
    isDraggingCart = false;
    sheet.style.transition = '';
    sheet.style.transform = '';
    if (e.changedTouches[0].clientY - startY > 100 && sheet.classList.contains('open')) {
      toggleCarritoMobile();
    }
  }, { passive: true });
});
async function _cargarVersion() {
  try {
    const d = await fetch('/api/sistema/version', {credentials:'include'}).then(r=>r.json());
    const el = document.getElementById('menuVersion');
    if (el) el.textContent = `ZERO POS v${d.version || '1.0.0'}`;
  } catch(e) {}
}

// ── Historial de ventas agrupado por fecha ────────────────────────
let _detalleVentaActual = null;
let _todasVentasHistorial = [];

async function abrirHistorial() {
  cerrarDrawerMenu();
  document.getElementById('drawerHistorial').style.display = '';
  document.getElementById('historialLista').innerHTML =
    '<div style="padding:20px;text-align:center;color:var(--text-dim);font-size:13px">Cargando...</div>';

  try {
    const raw = await fetch('/api/ventas?limit=100', {credentials:'include'}).then(r=>r.json()).catch(()=>[]);
    const arr = Array.isArray(raw) ? raw : [];
    const map = new Map();
    arr.forEach(v => map.set(v.id, v));
    _todasVentasHistorial = [...map.values()];
    _renderFiltrosHistorial();
    _aplicarFiltrosHistorial();
  } catch(e) {
    document.getElementById('historialLista').innerHTML =
      '<div style="padding:20px;text-align:center;color:var(--text-dim)">Error cargando historial</div>';
  }
}

function cerrarHistorial() {
  document.getElementById('drawerHistorial').style.display = 'none';
  cerrarPanelSinTeclado();
}

function _renderFiltrosHistorial() {
  const wrapper = document.getElementById('historialFiltros');
  if (!wrapper) return;
  wrapper.innerHTML = `
    <div style="display:flex;flex-wrap:wrap;gap:8px;padding:10px 12px;border-bottom:1px solid var(--border);background:var(--surface)">
      <input id="hFiltroTexto" oninput="_aplicarFiltrosHistorial()" placeholder="Cajero o #ticket…"
        style="flex:1;min-width:120px;padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:13px">
      <select id="hFiltroMetodo" onchange="_aplicarFiltrosHistorial()"
        style="padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:13px">
        <option value="">Todos los pagos</option>
        <option value="efectivo">💵 Efectivo</option>
        <option value="tarjeta">💳 Tarjeta</option>
        <option value="transferencia">📲 Transferencia</option>
      </select>
      <select id="hFiltroEstado" onchange="_aplicarFiltrosHistorial()"
        style="padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:13px">
        <option value="">Todos los estados</option>
        <option value="completada">Completadas</option>
        <option value="anulada">Anuladas</option>
      </select>
      <select id="hFiltroOrden" onchange="_aplicarFiltrosHistorial()"
        style="padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:13px">
        <option value="reciente">Más reciente</option>
        <option value="antiguo">Más antiguo</option>
        <option value="mayor">Mayor monto</option>
        <option value="menor">Menor monto</option>
      </select>
    </div>`;
}

function _aplicarFiltrosHistorial() {
  const texto  = (document.getElementById('hFiltroTexto')?.value  || '').toLowerCase();
  const metodo = (document.getElementById('hFiltroMetodo')?.value || '');
  const estado = (document.getElementById('hFiltroEstado')?.value || '');
  const orden  = (document.getElementById('hFiltroOrden')?.value  || 'reciente');

  let ventas = _todasVentasHistorial.filter(v => {
    if (metodo && v.metodo_pago !== metodo) return false;
    if (estado && v.estado !== estado) return false;
    if (texto) {
      const cajero = (v.cajero || v.usuario || '').toLowerCase();
      const id = String(v.id);
      if (!cajero.includes(texto) && !id.includes(texto)) return false;
    }
    return true;
  });

  const cmp = {
    reciente: (a, b) => (b.creado_en||'').localeCompare(a.creado_en||''),
    antiguo:  (a, b) => (a.creado_en||'').localeCompare(b.creado_en||''),
    mayor:    (a, b) => (b.total||0) - (a.total||0),
    menor:    (a, b) => (a.total||0) - (b.total||0),
  };
  ventas = ventas.sort(cmp[orden] || cmp.reciente);

  _renderHistorial(ventas);
}

function _renderHistorial(ventas) {
  const container = document.getElementById('historialLista');
  if (!ventas.length) {
    container.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-dim);font-size:13px">Sin ventas registradas</div>';
    return;
  }

  // Agrupar por fecha
  const grupos = {};
  ventas.forEach(v => {
    const fecha = (v.creado_en || '').slice(0, 10);
    if (!grupos[fecha]) grupos[fecha] = [];
    grupos[fecha].push(v);
  });

  const _DIAS = ['domingo','lunes','martes','miércoles','jueves','viernes','sábado'];
  const _MESES = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];

  let html = '';
  Object.keys(grupos).sort().reverse().forEach(fecha => {
    const dt = new Date(fecha + 'T12:00:00');
    const label = `${_DIAS[dt.getDay()]}, ${dt.getDate()} ${_MESES[dt.getMonth()]} ${dt.getFullYear()}`;
    html += `<div style="padding:8px 16px;background:#0f0f1a;color:var(--text-dim);font-size:12px;font-weight:700;position:sticky;top:0;text-transform:capitalize;border-bottom:1px solid var(--border)">${label}</div>`;
    grupos[fecha].forEach(v => {
      const estadoColor = v.estado === 'anulada' ? '#ef4444' : v.estado === 'completada' ? '#22c55e' : '#94a3b8';
      const hora = (v.creado_en || '').slice(11, 16);
      const metodoIcon = {'efectivo':'💵','tarjeta':'💳','transferencia':'📲'}[v.metodo_pago] || '💰';
      const esAnulada = v.estado === 'anulada';
      html += `<div style="display:flex;align-items:center;padding:12px 16px;border-bottom:1px solid var(--border);transition:background .12s;${esAnulada?'background:rgba(239,68,68,0.05)':''}" onmouseenter="this.style.background='${esAnulada?'rgba(239,68,68,0.1)':'var(--surface-hover)'}'" onmouseleave="this.style.background='${esAnulada?'rgba(239,68,68,0.05)':'none'}'">
        <div onclick="abrirDetalleVenta(${v.id})" style="flex:1;min-width:0;cursor:pointer">
          <div style="font-size:14px;font-weight:600;color:${esAnulada?'#ef4444':'var(--text)'};display:flex;align-items:center;gap:6px">
            <span style="${esAnulada?'text-decoration:line-through;opacity:.7':''}">#${v.id}</span>
            ${esAnulada?'<span style="font-size:10px;font-weight:700;background:#ef4444;color:white;border-radius:4px;padding:1px 5px;letter-spacing:.3px">ANULADA</span>':''}
            ${!esAnulada?metodoIcon:''}
          </div>
          <div style="font-size:12px;color:var(--text-dim);margin-top:2px">${hora} · ${v.cajero||v.usuario||'—'}</div>
        </div>
        <div style="font-size:15px;font-weight:700;color:${estadoColor};text-decoration:${esAnulada?'line-through':'none'};margin-right:8px;opacity:${esAnulada?'.6':'1'}">${fmt(v.total)}</div>
        ${!esAnulada?`<button onclick="_reimprimirDesdeHistorial(${v.id},event)" title="Reimprimir ticket" style="background:var(--surface);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:13px;cursor:pointer;padding:8px 10px;flex-shrink:0;min-width:44px;min-height:44px;display:flex;align-items:center;justify-content:center">🖨️</button>`:''}
      </div>`;
    });
  });
  container.innerHTML = html;
}

async function abrirDetalleVenta(id) {
  document.getElementById('modalDetalleVenta').style.display = 'flex';
  document.getElementById('dvNumero').textContent = `#${id}`;
  document.getElementById('dvTotal').textContent = '...';
  document.getElementById('dvMeta').innerHTML = '';
  document.getElementById('dvItems').innerHTML = '<div style="color:var(--text-dim);font-size:13px">Cargando...</div>';

  try {
    const v = await fetch(`/api/ventas/${id}`, {credentials:'include'}).then(r=>r.json());
    console.log('[ZERO] detalle venta:', v);
    _detalleVentaActual = v;
    _renderDetalleVenta(v);
  } catch(e) {
    document.getElementById('dvItems').innerHTML = '<div style="color:#ef4444;font-size:13px">Error cargando venta</div>';
  }
}

function _renderDetalleVenta(v) {
  const venta = v.venta || v;
  const items = v.items || [];

  document.getElementById('dvNumero').textContent = `#${venta.id||'—'}`;
  document.getElementById('dvTotal').textContent = fmt(venta.total || 0);
  if (venta.estado === 'anulada') {
    document.getElementById('dvTotal').style.color = '#ef4444';
    document.getElementById('dvTotal').style.textDecoration = 'line-through';
  } else {
    document.getElementById('dvTotal').style.color = '#22c55e';
    document.getElementById('dvTotal').style.textDecoration = 'none';
  }

  // Ocultar botón anular si ya está anulada
  document.getElementById('dvBtnAnular').style.display = venta.estado === 'anulada' ? 'none' : '';

  // Meta
  const tipoIcon = {'delivery':'🛵','retiro':'🏠','local':'🏪'}[venta.tipo||'local'] || '🏪';
  const meta = [];
  if (venta.cajero || venta.usuario) meta.push(`<div style="display:flex;justify-content:space-between"><span style="color:var(--text-dim)">Cajero</span><span>${venta.cajero||venta.usuario}</span></div>`);
  if (venta.metodo_pago) meta.push(`<div style="display:flex;justify-content:space-between"><span style="color:var(--text-dim)">Pago</span><span>${venta.metodo_pago}</span></div>`);
  if (venta.cliente_nombre) meta.push(`<div style="display:flex;justify-content:space-between"><span style="color:var(--text-dim)">Cliente</span><span>${venta.cliente_nombre}</span></div>`);
  if (venta.tipo && venta.tipo !== 'local') meta.push(`<div style="display:flex;justify-content:space-between"><span style="color:var(--text-dim)">Tipo</span><span>${tipoIcon} ${venta.tipo}</span></div>`);
  if (venta.direccion) meta.push(`<div style="display:flex;justify-content:space-between;gap:12px"><span style="color:var(--text-dim);flex-shrink:0">Dirección</span><span style="text-align:right">${venta.direccion}</span></div>`);
  document.getElementById('dvMeta').innerHTML = meta.join('');

  // Items
  let itemsHtml = `<div style="font-size:11px;font-weight:700;color:var(--text-dim);display:grid;grid-template-columns:1fr auto auto;gap:8px;margin-bottom:8px;text-transform:uppercase;letter-spacing:.5px"><span>Producto</span><span style="text-align:center">Cant</span><span style="text-align:right">Precio</span></div>`;
  items.forEach(i => {
    itemsHtml += `<div style="display:grid;grid-template-columns:1fr auto auto;gap:8px;align-items:center;padding:6px 0;border-bottom:1px solid var(--border)20">
      <div>
        <div style="font-size:13px;font-weight:600">${(i.nombre||i.producto_nombre||'').replace(/&/g,'&amp;')}</div>
        ${i.modificadores_desc ? `<div style="font-size:11px;color:var(--text-dim)">└─ ${i.modificadores_desc}</div>` : ''}
        ${i.notas ? `<div style="font-size:11px;color:var(--text-dim)">📝 ${i.notas}</div>` : ''}
      </div>
      <div style="text-align:center;font-size:13px;color:var(--text-dim)">×${i.cantidad}</div>
      <div style="text-align:right;font-size:13px;font-weight:700;color:#f1f5f9">${fmt(i.subtotal||i.precio_unit*i.cantidad)}</div>
    </div>`;
  });
  document.getElementById('dvItems').innerHTML = itemsHtml;

  // Totales
  const totales = [];
  if (venta.descuento > 0) totales.push(`<div style="display:flex;justify-content:space-between;color:#f59e0b"><span>Descuento</span><span>-${fmt(venta.descuento)}</span></div>`);
  if (venta.costo_delivery > 0) totales.push(`<div style="display:flex;justify-content:space-between"><span>Despacho</span><span>${fmt(venta.costo_delivery)}</span></div>`);
  if (venta.neto && venta.impuesto > 0) {
    const ivaPct = Math.round((venta.impuesto / venta.neto) * 100);
    totales.push(`<div style="display:flex;justify-content:space-between;color:var(--text-dim);font-size:12px"><span>Neto</span><span>${fmt(venta.neto)}</span></div>`);
    totales.push(`<div style="display:flex;justify-content:space-between;color:var(--text-dim);font-size:12px"><span>IVA (${ivaPct}%)</span><span>${fmt(venta.impuesto)}</span></div>`);
  }
  totales.push(`<div style="display:flex;justify-content:space-between;font-weight:700;font-size:15px"><span>Total</span><span>${fmt(venta.total)}</span></div>`);
  totales.push(`<div style="display:flex;justify-content:space-between;color:var(--text-dim)"><span style="text-transform:capitalize">${venta.metodo_pago||'—'}</span><span>${fmt(venta.total)}</span></div>`);
  document.getElementById('dvTotales').innerHTML = totales.join('');

  // Footer
  const fecha = venta.creado_en ? new Date(venta.creado_en).toLocaleString('es-CL', {dateStyle:'short', timeStyle:'short'}) : '—';
  document.getElementById('dvFooter').innerHTML = `<span>${fecha}</span><span>#${venta.id}</span>`;
}

function _anularVentaDetalle() {
  if (!_detalleVentaActual) return;
  const conf = document.getElementById('dvAnularConfirm');
  const inp  = document.getElementById('dvAnularMotivo');
  if (conf) { inp.value = ''; conf.style.display = ''; inp.focus(); }
}

function _cancelarAnularDetalle() {
  const conf = document.getElementById('dvAnularConfirm');
  if (conf) conf.style.display = 'none';
}

async function _confirmarAnularDetalle() {
  if (!_detalleVentaActual) return;
  const motivo = document.getElementById('dvAnularMotivo')?.value.trim() || '';
  const r = await fetch(`/api/ventas/${_detalleVentaActual.venta?.id || _detalleVentaActual.id}/anular`, {
    method: 'POST', credentials: 'include',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({motivo}),
  });
  if (r.ok) {
    showToast('Venta anulada', 'success');
    document.getElementById('dvAnularConfirm').style.display = 'none';
    document.getElementById('modalDetalleVenta').style.display = 'none';
    document.getElementById('drawerHistorial').style.display = '';
    cargarProductos();
  } else {
    const d = await r.json();
    showToast(d.error || 'Error al anular', 'error');
  }
}

async function _reimprimirVentaDetalle() {
  if (!_detalleVentaActual) return;
  await fetch('/api/impresora/reimprimir', {
    method:'POST', credentials:'include',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({venta_id: _detalleVentaActual.venta?.id || _detalleVentaActual.id}),
  });
  showToast('Reimprimiendo...', 'info');
}

async function _reimprimirDesdeHistorial(ventaId, event) {
  event.stopPropagation();
  try {
    const r = await fetch('/api/impresora/reimprimir', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({venta_id: ventaId}),
    });
    const d = await r.json();
    showToast(d.ok ? 'Reimprimiendo...' : (d.error || 'Error al reimprimir'), d.ok ? 'info' : 'error');
  } catch(e) {
    showToast('Error de conexión', 'error');
  }
}

async function abrirModalImpresoraCola() {
  document.getElementById('modalImpresoraCola').style.display = 'flex';
  const lista = document.getElementById('colaImpresoraLista');
  lista.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-dim);font-size:13px">Cargando...</div>';
  try {
    const r = await fetch('/api/impresora/cola', {credentials: 'include'});
    const rows = await r.json();
    if (!rows.length) {
      lista.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-dim);font-size:13px">Sin tickets pendientes</div>';
      return;
    }
    lista.innerHTML = rows.map(t => `
      <div style="display:flex;align-items:center;padding:11px 16px;border-bottom:1px solid var(--border);gap:12px">
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;font-weight:600">Venta #${t.venta_id || '—'}</div>
          <div style="font-size:11px;color:var(--text-dim);margin-top:2px">${t.estado} · ${t.intentos} intento${t.intentos!==1?'s':''}</div>
          ${t.error_msg ? `<div style="font-size:11px;color:#ef4444;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${t.error_msg}</div>` : ''}
        </div>
        <button onclick="_reimprimirColaItem(${t.venta_id},${t.id},this)" style="padding:6px 12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;font-size:12px;cursor:pointer;color:var(--text)">🖨️</button>
      </div>`).join('');
  } catch(e) {
    lista.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444;font-size:13px">Error al cargar</div>';
  }
}

async function _reimprimirColaItem(ventaId, colaId, btn) {
  btn.disabled = true; btn.textContent = '...';
  try {
    const payload = ventaId ? {venta_id: ventaId} : {cola_id: colaId};
    const r = await fetch('/api/impresora/reimprimir', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    btn.textContent = d.ok ? '✓' : '✗';
    if (d.ok) { btn.style.color = '#22c55e'; btn.disabled = true; }
    else { btn.style.color = '#ef4444'; btn.disabled = false; btn.textContent = '↺'; }
  } catch(e) {
    btn.textContent = '↺'; btn.disabled = false;
  }
}

async function _colaReintentarTodos() {
  try {
    await fetch('/api/impresora/reimprimir', {
      method: 'POST', credentials: 'include',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({accion: 'procesar_pendientes'}),
    });
    showToast('Reintentando todos los tickets...', 'info');
    document.getElementById('modalImpresoraCola').style.display = 'none';
    setTimeout(_actualizarBadgeImpresora, 3000);
  } catch(e) {
    showToast('Error de conexión', 'error');
  }
}

async function _actualizarBadgeImpresora() {
  try {
    const r = await fetch('/api/impresora/estado', {credentials: 'include'});
    if (!r.ok) return;
    const d = await r.json();
    const btn = document.getElementById('btnImpresoraBadge');
    const badge = document.getElementById('impresoraBadge');
    if (btn && badge) {
      if (d.pendientes > 0) {
        btn.style.display = 'block';
        badge.textContent = d.pendientes > 9 ? '9+' : d.pendientes;
      } else {
        btn.style.display = 'none';
      }
    }
  } catch(e) {}
}

// ── Vista grid/lista ─────────────────────────────────────────────
function toggleVista() {
  modoVista = modoVista === 'grid' ? 'lista' : 'grid';
  localStorage.setItem('modo_vista', modoVista);
  const btn = document.getElementById('btnVista');
  if (btn) btn.textContent = modoVista === 'lista' ? '⊞' : '≡';
  // Re-render con la vista actual (filtrar re-llama renderProductos)
  filtrar();
}

function _initVista() {
  const btn = document.getElementById('btnVista');
  if (btn) btn.textContent = modoVista === 'lista' ? '⊞' : '≡';
  if (modoVista === 'lista') {
    document.getElementById('productosGrid').classList.add('modo-lista');
  }
}

// ── Impresora ─────────────────────────────────────────────────────
let _impEstado = null;

async function verificarEstadoImpresora() {
  try {
    const r = await fetch('/api/impresora/estado', {credentials: 'include'});
    if (!r.ok) { _setImpDot('gris'); return; }
    const d = await r.json();
    _impEstado = d;
    if (!d.conectada) { _setImpDot('rojo'); return; }
    if (d.sin_papel || d.poco_papel) { _setImpDot('amarillo'); return; }
    _setImpDot('verde');
    if (d.pendientes > 0) mostrarToastPersistente(`🖨️ ${d.pendientes} ticket(s) pendientes`, 'warning');
  } catch(e) {
    _setImpDot('gris');
  }
}

function _setImpDot(color) {
  const dot = document.getElementById('impDot');
  if (!dot) return;
  const map = {verde:'#22c55e', amarillo:'#f59e0b', rojo:'#ef4444', gris:'#6b7280'};
  dot.style.background = map[color] || map.gris;
}

let _toastPersistente = null;
function mostrarToastPersistente(msg, tipo) {
  if (_toastPersistente) _toastPersistente.remove();
  const el = document.createElement('div');
  el.style.cssText = `position:fixed;bottom:80px;right:16px;z-index:9999;padding:12px 16px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;max-width:280px;box-shadow:0 4px 12px rgba(0,0,0,.3)`;
  el.style.background = tipo === 'warning' ? '#f59e0b' : '#3b82f6';
  el.style.color = '#000';
  el.textContent = msg;
  el.onclick = () => el.remove();
  document.body.appendChild(el);
  _toastPersistente = el;
}

function mostrarAlertaImpresora() {
  if (!_impEstado) { showToast('Sin datos de impresora', 'info'); return; }
  const d = _impEstado;
  let msg = d.conectada ? '✅ Conectada' : '❌ Sin conexión';
  if (d.sin_papel)  msg += ' · Sin papel';
  if (d.poco_papel) msg += ' · Poco papel';
  if (d.pendientes > 0) msg += ` · ${d.pendientes} pendiente(s)`;
  showToast(msg, d.conectada ? 'success' : 'error');
}

// Verificar estado cada 30 segundos
setInterval(verificarEstadoImpresora, 30000);

// Auto-foco en búsqueda solo en desktop (móvil: el teclado se abre solo si hacemos focus)
document.addEventListener('click', e => {
  if (esMobil()) return;
  if (!e.target.closest('button, input, select, textarea, .modal, .modal-overlay, [role="dialog"]')) {
    const campo = document.getElementById('searchInput');
    if (campo) campo.focus();
  }
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    if (Escaner.activo) { Escaner.cerrar(); return; }
    cerrarCobro(); cerrarVariantes(); cerrarVentaRapida(); cerrarPrecioRapido();
  }
});

console.log('[ZERO] Botón cámara:', document.getElementById('btnCamara'));

document.getElementById('btnCamara')?.addEventListener('click', () => {
  Escaner.abrir();
});

// Pre-cargar ZXing en segundo plano si BarcodeDetector no está disponible
if (!('BarcodeDetector' in window)) {
  setTimeout(() => Escaner._cargarZXing().catch(() => {}), 0);
}

init();

// ── Cola de espera (mesón) ────────────────────────────────────────────────────
let _colaAbierta = false;
let _pedidosCola = [];

function toggleColaEspera() {
  _colaAbierta = !_colaAbierta;
  document.getElementById('colaPanel').classList.toggle('open', _colaAbierta);
  if (_colaAbierta) cargarCola();
}

async function cargarCola() {
  try {
    const lista = await fetch('/api/pedidos/en-espera', {credentials:'include'}).then(r=>r.json());
    _pedidosCola = lista;
    renderCola(lista);
    actualizarBadgeCola(lista.length);
  } catch(e) {}
}

function renderCola(lista) {
  const el = document.getElementById('colaItems');
  if (!lista.length) {
    el.innerHTML = '<div class="cola-empty">Sin pedidos en espera</div>';
    return;
  }
  el.innerHTML = lista.map(p => {
    const hora = new Date(p.creado_en).toLocaleTimeString('es-CL', {hour:'2-digit',minute:'2-digit'});
    return `<div class="cola-item">
      <div style="display:flex;align-items:center;gap:8px">
        <span class="cola-num">#${p.numero}</span>
        <div>
          <div class="cola-nombre">${p.cliente_nombre}</div>
          <div class="cola-meta">${hora} · ${p.cajero_nombre||'—'}</div>
        </div>
        <span class="cola-total" style="margin-left:auto">${fmt(p.total)}</span>
      </div>
      <div class="cola-actions">
        <button class="cola-btn" onclick="cargarPedidoEnCaja(${p.id})">📋 Cargar</button>
        <button class="cola-btn call" onclick="llamarCliente(${p.id})">🔔 Llamar</button>
      </div>
    </div>`;
  }).join('');
}

function actualizarBadgeCola(n) {
  const badge = document.getElementById('colaCount');
  const btnCola = document.getElementById('btnColaEspera');
  if (n > 0) {
    badge.textContent = n > 9 ? '9+' : n;
    badge.style.display = 'flex';
    btnCola.style.background = 'rgba(239,68,68,0.15)';
  } else {
    badge.style.display = 'none';
    btnCola.style.background = '';
  }
  document.getElementById('colaBadge').textContent = n;
}

async function cargarPedidoEnCaja(pid) {
  const p = _pedidosCola.find(x=>x.id===pid);
  if (!p) return;

  // Confirmar si carrito tiene items
  if (carrito.length && !confirm('¿Reemplazar el carrito actual con este pedido?')) return;

  // Cargar items del pedido en el carrito
  carrito = (p.items || []).map(item => ({
    producto_id: item.producto_id || null,
    nombre: item.nombre,
    cantidad: item.cantidad,
    precio_unit: item.precio,
    subtotal: item.subtotal,
    _pedido_id: p.id,
    _pedido_item: true,
  }));

  // Guardar pedido_id para asociar la venta
  window._pedidoActual = p.id;

  renderCarrito();
  if (document.getElementById('carrito').classList.contains('open') === false) {
    toggleCarritoMobile && toggleCarritoMobile();
  }

  // Cerrar panel cola
  _colaAbierta = false;
  document.getElementById('colaPanel').classList.remove('open');
  showToast(`Pedido #${p.numero} — ${p.cliente_nombre} cargado`, 'success');
}

async function llamarCliente(pid) {
  await fetch(`/api/pedidos/${pid}/llamar`, {
    method:'POST', credentials:'include',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({}),
  }).catch(()=>{});
  showToast('Llamada enviada al mesón', 'success');
}

function iniciarPollCola() {
  if (!cfgApp || (cfgApp.modulo_delivery !== '1' && cfgApp.modulo_delivery !== true)) return;
  setInterval(async () => {
    try {
      const lista = await fetch('/api/pedidos/en-espera', {credentials:'include'}).then(r=>r.json());
      _pedidosCola = lista;
      if (_colaAbierta) renderCola(lista);
      actualizarBadgeCola(lista.length);
    } catch(e) {}
  }, 5000);
}

/* ── Service Worker registration ──────────────────────────────── */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', {scope: '/'})
      .catch(err => console.log('SW error:', err));
  });
}
