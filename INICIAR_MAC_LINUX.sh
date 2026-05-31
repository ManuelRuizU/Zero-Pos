#!/bin/bash
cd "$(dirname "$0")"

# Activar entorno virtual
source venv/bin/activate

# Verificar pyzbar (necesario para detección de códigos de barras)
python3 -c "from pyzbar import pyzbar" 2>/dev/null || {
  echo "Instalando pyzbar..."
  sudo apt-get install -y libzbar0 -q 2>/dev/null || true
  pip install pyzbar Pillow -q
}

# Arrancar ZERO POS
python3 app.py
