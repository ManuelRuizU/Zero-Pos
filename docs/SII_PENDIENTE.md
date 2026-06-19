# SII — Pendiente Implementar

## Prerequisitos necesarios
- RUT empresa con giro comercio activo
- CAF autorizado por SII (tipo DTE 39 — Boleta)
- Certificado digital empresa (.pfx)
- Ambiente certificación SII aprobado
- ZERO CLOUD funcionando (para sync)

## Ya implementado (base lista)
- Tablas cafs + boletas (_m021_sii) ✅
- Columna neto en ventas ✅
- IVA separado en ticket ✅
- Validación formato RUT ✅
- Worker scheduler (base para sync) ✅
- event_log (base para auditoría) ✅

## Pendiente implementar

### 1. Worker sync_boletas.py
- Lee boletas WHERE estado='pendiente_sync'
- Firma XML con CAF + certificado digital
- Envía a API DTE
- Reintentos exponenciales
- Alerta roja si >47 horas sin sync

### 2. Gestión CAF
- Endpoint POST /api/sii/caf (subir CAF)
- Endpoint GET /api/sii/folios (estado folios)
- Alerta cuando quedan <50 folios

### 3. Firma XML
- Implementar firma con pyhanko o xmlsec
- Certificado empresa en /ssl/cert_empresa.pfx
- TED (Timbre Electrónico DTE)

### 4. Backup incluye CAF
- En crear_backup_cifrado() incluir:
  - /ssl/cert_empresa.pfx
  - /cafs/*.xml

### 5. Validación RUT completa
- Agregar verificación dígito verificador
- Hoy solo valida formato

### 6. /health endpoint con alerta SII
- GET /health retorna alerta si hay boletas
  pendientes > 47 horas

## Flujo completo cuando esté listo
Venta → INSERT boletas(estado='pendiente_sync')
→ Worker cada 5min → Firma XML → API DTE
→ UPDATE estado='enviada'
→ Si falla: reintento exponencial
→ Si >47hrs: alerta roja en dashboard
