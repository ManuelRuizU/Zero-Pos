# ZERO POS — HTTPS con mkcert y PWA
# Guía de instalación de certificado SSL local
# Fecha: Junio 2026

---

## ¿Por qué necesitamos esto?

Sin HTTPS válido:
- La cámara (getUserMedia) no funciona en iOS
- No se puede instalar como PWA
- Chrome/Safari muestran "No seguro"

Con mkcert:
- Certificado SSL gratuito, sin internet
- Válido en red local para siempre (hasta 2028)
- La cámara funciona en iPhone/iPad
- Se instala como app nativa (PWA)

---

## Paso 1 — Instalar mkcert en el PC (Linux)

```bash
# Instalar dependencia
sudo apt install libnss3-tools

# Descargar mkcert
wget https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-linux-amd64

# Mover a PATH y dar permisos
sudo mv mkcert-v1.4.4-linux-amd64 /usr/local/bin/mkcert
sudo chmod +x /usr/local/bin/mkcert
```

---

## Paso 2 — Instalar la CA local

```bash
mkcert -install
```

Salida esperada:
```
Created a new local CA 💥
The local CA is now installed in the system trust store! ⚡️
The local CA is now installed in the Firefox and/or Chrome/Chromium trust store! 🦊
```

---

## Paso 3 — Generar certificado para la IP local

```bash
mkcert 192.168.50.183 localhost 127.0.0.1
```

> ⚠️ Reemplazar 192.168.50.183 con la IP real del PC servidor.

Salida esperada:
```
Created a new certificate valid for the following names 📜
 - "192.168.50.183"
 - "localhost"
 - "127.0.0.1"

The certificate is at "./192.168.50.183+2.pem"
The key is at "./192.168.50.183+2-key.pem"
It will expire on 12 September 2028 🗓
```

---

## Paso 4 — Copiar certificados a ZERO POS

```bash
# Crear carpeta de certificados
mkdir -p ~/Proyectos/zero_pos/certs

# Mover archivos generados
mv 192.168.50.183+2.pem ~/Proyectos/zero_pos/certs/cert.pem
mv 192.168.50.183+2-key.pem ~/Proyectos/zero_pos/certs/key.pem

# Copiar al directorio ssl que usa app.py
cp ~/Proyectos/zero_pos/certs/cert.pem ~/Proyectos/zero_pos/ssl/cert.pem
cp ~/Proyectos/zero_pos/certs/key.pem ~/Proyectos/zero_pos/ssl/key.pem
```

---

## Paso 5 — Reiniciar ZERO POS

```bash
sudo systemctl restart zeropos
```

---

## Paso 6 — Verificar en Chrome (laptop)

1. Cerrar Chrome completamente: `pkill -f chrome`
2. Abrir Chrome
3. Ir a `https://192.168.50.183:5001`
4. Debe mostrar 🔒 candado verde sin warnings

---

## Paso 7 — Instalar CA en iPhone/iPad

### 7.1 — Servir el archivo CA por HTTP

```bash
cp ~/.local/share/mkcert/rootCA.pem ~/Proyectos/zero_pos/static/rootCA.pem
```

### 7.2 — Descargar en el iPhone

En Safari del iPhone, abrir:
```
http://192.168.50.183:5000/static/rootCA.pem
```

Aparece: *"Perfil descargado. Revisa el perfil en la app Configuración."*
→ Tocar **Cerrar**

### 7.3 — Instalar el perfil

1. **Configuración** → **General** → **VPN y gestión de dispositivos**
2. Tocar el perfil `mkcert development CA`
3. Tocar **Instalar** → ingresar PIN → **Instalar**

### 7.4 — Activar confianza (CRÍTICO)

1. **Configuración** → **General** → **Acerca de**
2. **Ajustes de confianza de certificados**
3. Activar el toggle de `mkcert development CA`
4. Confirmar **Continuar**

> ⚠️ Sin este paso el certificado está instalado pero NO es confiable.

---

## Paso 8 — Verificar en iPhone

En Safari del iPhone:
```
https://192.168.50.183:5001
```
Debe abrir ZERO POS directamente sin warnings ni errores SSL.

---

## Paso 9 — Instalar como PWA en iPhone

1. Abrir Safari en el iPhone
2. Ir a `https://192.168.50.183:5001/static/pos.html`
3. Tocar el botón **Compartir** (cuadrado con flecha ↑)
4. Tocar **Agregar a pantalla de inicio**
5. Nombre: `ZERO POS` → **Agregar**

El ícono aparece en la pantalla de inicio.
Al abrirlo: pantalla completa sin barra de URL, como app nativa. ✅

---

## Paso 10 — Instalar PWA pantalla cliente en iPad

1. Abrir Safari en el iPad
2. Ir a `https://192.168.50.183:5001/static/cliente.html`
3. Tocar **Compartir** → **Agregar a pantalla de inicio**
4. Nombre: `ZERO Cliente` → **Agregar**

---

## Datos importantes

| Item | Valor |
|------|-------|
| IP servidor | 192.168.50.183 |
| Puerto POS (HTTPS) | 5001 |
| Puerto clientes (HTTP) | 5000 |
| Certificado | ~/Proyectos/zero_pos/ssl/cert.pem |
| Clave | ~/Proyectos/zero_pos/ssl/key.pem |
| CA root | ~/.local/share/mkcert/rootCA.pem |
| Vencimiento cert | 12 Septiembre 2028 |

---

## Para Android

1. Abrir Chrome en Android
2. Ir a `http://192.168.50.183:5000/static/rootCA.pem`
3. Descargar el archivo
4. **Configuración** → **Seguridad** → **Instalar certificado** → **CA**
5. Seleccionar el archivo descargado
6. Confirmar instalación

---

## Comandos útiles

```bash
# Ver ubicación de la CA
mkcert -CAROOT

# Reinstalar CA en browsers
mkcert -install

# Reiniciar ZERO POS
sudo systemctl restart zeropos

# Ver logs en tiempo real
journalctl -u zeropos -f

# Ver estado del servicio
sudo systemctl status zeropos
```

---

## Notas para el futuro instalador (pendrive)

- El binario `mkcert` debe incluirse en el pendrive
- `INSTALAR.sh` debe ejecutar los pasos 1-5 automáticamente
- La página de bienvenida post-instalación debe mostrar:
  - QR para instalar CA en móviles (apunta a rootCA.pem)
  - Instrucciones adaptadas por OS (iOS/Android/PC)
  - Botón "Abrir ZERO POS"
- La IP se detecta automáticamente con `hostname -I`
- El certificado se regenera automáticamente con la IP detectada
