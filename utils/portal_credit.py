"""Portal web ZERO CREDIT — página standalone para que el cliente vea su deuda."""
from datetime import date


def generar_portal_html(cliente: dict, negocio: dict, movimientos: list) -> str:
    nombre = cliente.get('nombre', '')
    apellido = cliente.get('apellido') or ''
    nombre_completo = f"{nombre} {apellido}".strip()

    deuda = int(cliente.get('deuda_actual') or 0)
    limite = int(cliente.get('limite_credito') or 10000)
    pct = min(int((deuda / limite) * 100), 100) if limite > 0 else 0
    disponible = max(0, limite - deuda)

    venc_str = cliente.get('proximo_vencimiento')
    dias_restantes = None
    estado = 'al_dia'
    if venc_str and deuda > 0:
        try:
            venc = date.fromisoformat(str(venc_str)[:10])
            dias_restantes = (venc - date.today()).days
            if dias_restantes < 0:
                estado = 'vencido'
            elif dias_restantes <= 7:
                estado = 'por_vencer'
        except ValueError:
            pass

    # Colores de estado
    if deuda == 0:
        bar_color = '#22c55e'
        estado_label = '¡Sin deuda!'
        estado_css = 'estado-ok'
    elif estado == 'vencido':
        bar_color = '#ef4444'
        estado_label = '⚠️ Deuda vencida'
        estado_css = 'estado-vencido'
    elif pct >= 80:
        bar_color = '#f97316'
        estado_label = '⚠️ Crédito casi agotado'
        estado_css = 'estado-naranja'
    elif pct >= 50:
        bar_color = '#f59e0b'
        estado_label = 'Crédito en uso'
        estado_css = 'estado-amarillo'
    else:
        bar_color = '#22c55e'
        estado_label = 'Al día'
        estado_css = 'estado-ok'

    # Información de vencimiento
    if dias_restantes is not None and deuda > 0:
        if dias_restantes < 0:
            venc_texto = f"Venció hace {-dias_restantes} día(s)"
        elif dias_restantes == 0:
            venc_texto = "Vence hoy"
        elif dias_restantes == 1:
            venc_texto = "Vence mañana"
        else:
            venc_texto = f"Vence en {dias_restantes} días"
    else:
        venc_texto = ""

    # Movimientos HTML
    movs_html = ""
    for m in movimientos:
        tipo = m.get('tipo', '')
        monto = int(m.get('monto') or 0)
        creado = str(m.get('creado_en') or '')[:16].replace('T', ' ')
        descripcion = m.get('descripcion') or ''
        if tipo == 'cargo':
            icon = '🔴'
            monto_str = f'+${monto:,}'.replace(',', '.')
            color = '#ef4444'
        elif tipo == 'abono':
            icon = '🟢'
            monto_str = f'-${monto:,}'.replace(',', '.')
            color = '#22c55e'
        else:
            icon = '🔵'
            monto_str = f'${monto:,}'.replace(',', '.')
            color = '#6366f1'

        desc_html = f'<span class="mov-desc">— {descripcion}</span>' if descripcion else ''
        movs_html += f"""
        <div class="mov-item">
          <div class="mov-left">
            <span class="mov-icon">{icon}</span>
            <div>
              <div class="mov-tipo">{tipo.title()}{desc_html}</div>
              <div class="mov-fecha">{creado}</div>
            </div>
          </div>
          <div class="mov-monto" style="color:{color}">{monto_str}</div>
        </div>"""

    if not movs_html:
        movs_html = '<div class="sin-movs">Sin movimientos registrados</div>'

    # Sección transferencia bancaria
    banco = negocio.get('banco_nombre', '')
    banco_cuenta = negocio.get('banco_cuenta', '')
    banco_tipo = negocio.get('banco_tipo', '')
    banco_rut = negocio.get('banco_rut', '')
    banco_email = negocio.get('banco_email', '')
    banco_html = ''
    if banco or banco_cuenta:
        banco_html = f"""
      <div class="seccion">
        <div class="seccion-titulo">🏦 Pagar por transferencia</div>
        <div class="banco-info">
          {f'<div class="banco-row"><span>Banco</span><strong>{banco}</strong></div>' if banco else ''}
          {f'<div class="banco-row"><span>Tipo</span><strong>{banco_tipo}</strong></div>' if banco_tipo else ''}
          {f'<div class="banco-row"><span>Cuenta</span><strong>{banco_cuenta}</strong></div>' if banco_cuenta else ''}
          {f'<div class="banco-row"><span>RUT</span><strong>{banco_rut}</strong></div>' if banco_rut else ''}
          {f'<div class="banco-row"><span>Email</span><strong>{banco_email}</strong></div>' if banco_email else ''}
        </div>
      </div>"""

    # Botón WhatsApp
    telefono_negocio = negocio.get('telefono_negocio', '') or negocio.get('whatsapp_negocio', '')
    wa_html = ''
    if telefono_negocio:
        tel_limpio = ''.join(c for c in telefono_negocio if c.isdigit())
        nombre_negocio = negocio.get('nombre_negocio', 'la tienda')
        wa_msg = (
            f"Hola {nombre_negocio}, soy {nombre_completo} y quiero consultar sobre mi cuenta ZERO CREDIT. "
            f"Mi deuda actual es ${deuda:,}."
        ).replace(',', '.')
        import urllib.parse
        wa_encoded = urllib.parse.quote(wa_msg)
        wa_html = f"""
      <div class="seccion">
        <a href="https://wa.me/56{tel_limpio}?text={wa_encoded}" class="btn-wa" target="_blank">
          📱 Contactar por WhatsApp
        </a>
      </div>"""

    nombre_negocio = negocio.get('nombre_negocio', 'ZERO POS')
    qr_token = cliente.get('qr_token', '')
    tema_color = negocio.get('tema_color', '#6366f1')

    # Banner PWA
    pwa_banner = """
    <div id="pwa-banner" style="display:none;position:fixed;bottom:0;left:0;right:0;background:#1e1e2e;border-top:1px solid #333;padding:12px 16px;display:flex;align-items:center;gap:12px;z-index:1000">
      <div style="flex:1;font-size:13px">📲 Instala esta app para ver tu deuda sin internet</div>
      <button onclick="installPWA()" style="background:#6366f1;border:none;color:white;padding:8px 16px;border-radius:8px;cursor:pointer;font-size:13px">Instalar</button>
      <button onclick="document.getElementById('pwa-banner').style.display='none'" style="background:none;border:none;color:#888;cursor:pointer;font-size:18px">×</button>
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <meta name="theme-color" content="#0f0f1a">
  <title>ZERO CREDIT — {nombre_completo}</title>
  <link rel="manifest" href="/credit/manifest/{qr_token}">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0f0f1a;
      color: #e2e8f0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      min-height: 100vh;
      padding-bottom: 80px;
    }}
    .header {{
      background: linear-gradient(135deg, #1e1e2e 0%, #0f0f1a 100%);
      border-bottom: 1px solid #2d2d3d;
      padding: 20px 16px 16px;
      text-align: center;
    }}
    .logo {{
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 3px;
      color: {tema_color};
      text-transform: uppercase;
      margin-bottom: 8px;
    }}
    .logo span {{ color: #e2e8f0; }}
    .nombre-cliente {{
      font-size: 20px;
      font-weight: 700;
      color: #f1f5f9;
    }}
    .negocio-nombre {{
      font-size: 12px;
      color: #64748b;
      margin-top: 4px;
    }}
    .main {{ max-width: 480px; margin: 0 auto; padding: 20px 16px; }}
    .deuda-card {{
      background: #1e1e2e;
      border: 1px solid #2d2d3d;
      border-radius: 16px;
      padding: 24px;
      text-align: center;
      margin-bottom: 16px;
    }}
    .deuda-label {{
      font-size: 12px;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 8px;
    }}
    .deuda-monto {{
      font-size: 48px;
      font-weight: 800;
      color: {bar_color};
      line-height: 1;
      margin-bottom: 8px;
    }}
    .estado-badge {{
      display: inline-block;
      padding: 4px 14px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 600;
      margin-bottom: 16px;
    }}
    .estado-ok {{ background: rgba(34,197,94,.15); color: #22c55e; }}
    .estado-vencido {{ background: rgba(239,68,68,.15); color: #ef4444; animation: pulse 1.5s infinite; }}
    .estado-naranja {{ background: rgba(249,115,22,.15); color: #f97316; }}
    .estado-amarillo {{ background: rgba(245,158,11,.15); color: #f59e0b; }}
    @keyframes pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:.6; }} }}
    .progress-track {{
      background: #2d2d3d;
      border-radius: 8px;
      height: 10px;
      overflow: hidden;
      margin-bottom: 12px;
    }}
    .progress-fill {{
      height: 100%;
      width: {pct}%;
      background: {bar_color};
      border-radius: 8px;
      transition: width .5s;
    }}
    .deuda-desglose {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      font-size: 13px;
    }}
    .desglose-item {{ text-align: center; }}
    .desglose-label {{ color: #64748b; margin-bottom: 2px; }}
    .desglose-valor {{ font-weight: 700; font-size: 16px; }}
    .venc-texto {{
      font-size: 12px;
      color: {'#ef4444' if estado == 'vencido' else '#94a3b8'};
      margin-top: 10px;
    }}
    .seccion {{
      background: #1e1e2e;
      border: 1px solid #2d2d3d;
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 12px;
    }}
    .seccion-titulo {{
      font-size: 12px;
      font-weight: 700;
      color: #64748b;
      text-transform: uppercase;
      letter-spacing: 1px;
      margin-bottom: 12px;
    }}
    .mov-item {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 0;
      border-bottom: 1px solid #2d2d3d;
    }}
    .mov-item:last-child {{ border-bottom: none; }}
    .mov-left {{ display: flex; align-items: center; gap: 10px; }}
    .mov-icon {{ font-size: 18px; }}
    .mov-tipo {{ font-size: 13px; font-weight: 600; }}
    .mov-desc {{ font-weight: 400; color: #64748b; }}
    .mov-fecha {{ font-size: 11px; color: #64748b; margin-top: 2px; }}
    .mov-monto {{ font-size: 14px; font-weight: 700; white-space: nowrap; }}
    .sin-movs {{ color: #64748b; font-size: 13px; text-align: center; padding: 16px 0; }}
    .banco-info {{ display: flex; flex-direction: column; gap: 8px; }}
    .banco-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 13px;
    }}
    .banco-row span {{ color: #64748b; }}
    .btn-wa {{
      display: block;
      background: #25d366;
      color: white;
      text-decoration: none;
      text-align: center;
      padding: 14px;
      border-radius: 10px;
      font-weight: 700;
      font-size: 15px;
    }}
    .btn-wa:hover {{ background: #20bd5a; }}
    .footer {{
      text-align: center;
      color: #475569;
      font-size: 11px;
      padding: 16px;
      margin-top: 8px;
    }}
  </style>
</head>
<body>
  <div class="header">
    <div class="logo">ZERO<span>CREDIT</span></div>
    <div class="nombre-cliente">{nombre_completo}</div>
    <div class="negocio-nombre">{nombre_negocio}</div>
  </div>

  <div class="main">
    <div class="deuda-card">
      <div class="deuda-label">Tu deuda actual</div>
      <div class="deuda-monto">${deuda:,}</div>
      <div class="estado-badge {estado_css}">{estado_label}</div>
      <div class="progress-track">
        <div class="progress-fill"></div>
      </div>
      <div class="deuda-desglose">
        <div class="desglose-item">
          <div class="desglose-label">Límite</div>
          <div class="desglose-valor">${limite:,}</div>
        </div>
        <div class="desglose-item">
          <div class="desglose-label">Disponible</div>
          <div class="desglose-valor" style="color:#22c55e">${disponible:,}</div>
        </div>
      </div>
      {f'<div class="venc-texto">{venc_texto}</div>' if venc_texto else ''}
    </div>

    <div class="seccion">
      <div class="seccion-titulo">📋 Últimos movimientos</div>
      {movs_html}
    </div>

    {banco_html}
    {wa_html}

    <div class="footer">
      Actualizado: {date.today().strftime('%d/%m/%Y')} · ZERO CREDIT
    </div>
  </div>

  {pwa_banner}

  <script>
    let deferredPrompt;
    window.addEventListener('beforeinstallprompt', e => {{
      e.preventDefault();
      deferredPrompt = e;
      const banner = document.getElementById('pwa-banner');
      if (banner) banner.style.display = 'flex';
    }});

    function installPWA() {{
      if (deferredPrompt) {{
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then(() => {{
          deferredPrompt = null;
          const banner = document.getElementById('pwa-banner');
          if (banner) banner.style.display = 'none';
        }});
      }}
    }}

    if ('serviceWorker' in navigator) {{
      navigator.serviceWorker.register('/credit/sw/{qr_token}.js', {{scope: '/credit/'}})
        .catch(e => console.warn('SW registration failed:', e));
    }}
  </script>
</body>
</html>"""

    return html
