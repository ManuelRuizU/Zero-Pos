#!/bin/bash
# Ejecutar una sola vez al instalar en Orange Pi
RULE="www-data ALL=(ALL) NOPASSWD: /bin/date"
echo "$RULE" | sudo tee /etc/sudoers.d/zeropos-date
sudo chmod 440 /etc/sudoers.d/zeropos-date
echo "Permiso de sincronización de hora configurado"
