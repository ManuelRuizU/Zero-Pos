#!/bin/bash
# ZERO POS — Configurar hotspot WiFi
# Ejecutar UNA VEZ en el Orange Pi

echo "⚡ ZERO POS — Configurando hotspot..."

# Instalar dependencias
sudo apt update
sudo apt install -y hostapd dnsmasq

# Detener servicios
sudo systemctl stop hostapd
sudo systemctl stop dnsmasq

# Configurar hostapd
sudo tee /etc/hostapd/hostapd.conf > /dev/null << EOF
interface=wlan0
driver=nl80211
ssid=ZEROPOS
hw_mode=g
channel=6
wmm_enabled=0
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=zeropos2024
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
echo "Red WiFi: ZEROPOS"
echo "Contraseña: zeropos2024"
echo "IP del servidor: 192.168.4.1"
echo "URL: https://192.168.4.1:5001"
echo ""
echo "Conecta tus dispositivos a ZEROPOS"
echo "y abre https://192.168.4.1:5001"
