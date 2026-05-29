#!/bin/bash
# ZERO POS — Configurar hotspot WiFi personalizado
# Ejecutar UNA VEZ en el Orange Pi

echo "⚡ ZERO POS — Configurando hotspot personalizado..."
echo ""

echo "¿Nombre de tu red WiFi? (ej: MiSushi)"
read SSID

echo "¿Contraseña? (mínimo 8 caracteres)"
read PASSWORD

if [ ${#PASSWORD} -lt 8 ]; then
  echo "❌ La contraseña debe tener al menos 8 caracteres"
  exit 1
fi

echo ""
echo "Configurando red: $SSID"

# Instalar dependencias
sudo apt update
sudo apt install -y hostapd dnsmasq

# Detener servicios
sudo systemctl stop hostapd
sudo systemctl stop dnsmasq

# Configurar hostapd con nombre y contraseña personalizados
sudo tee /etc/hostapd/hostapd.conf > /dev/null << EOF
interface=wlan0
driver=nl80211
ssid=$SSID
hw_mode=g
channel=6
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=$PASSWORD
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF

# Apuntar hostapd al config
echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' \
  | sudo tee /etc/default/hostapd

# Configurar dnsmasq
sudo tee /etc/dnsmasq.conf > /dev/null << EOF
interface=wlan0
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
domain=local
address=/zeropos.local/192.168.4.1
EOF

# IP fija para el Orange Pi en wlan0
sudo tee -a /etc/dhcpcd.conf > /dev/null << EOF

interface wlan0
static ip_address=192.168.4.1/24
nohook wpa_supplicant
EOF

# Habilitar servicios al arrancar
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
sudo systemctl enable dnsmasq

# Habilitar IP forwarding (opcional para internet)
echo "net.ipv4.ip_forward=1" \
  | sudo tee -a /etc/sysctl.conf

# Reiniciar
sudo systemctl restart dhcpcd
sudo systemctl start hostapd
sudo systemctl start dnsmasq

echo ""
echo "✅ Hotspot configurado exitosamente"
echo ""
echo "Red WiFi: $SSID"
echo "Contraseña: $PASSWORD"
echo "IP del servidor: 192.168.4.1"
echo "URL: https://192.168.4.1:5001"
echo ""
echo "Conecta tus dispositivos a $SSID"
echo "y abre https://192.168.4.1:5001"
