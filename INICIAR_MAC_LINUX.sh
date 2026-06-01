#!/bin/bash
cd "$(dirname "$0")"

# Cargar variables de entorno desde .env si existe
if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

# Activar entorno virtual
source venv/bin/activate

# Verificar pyzbar (necesario para detección de códigos de barras)
python3 -c "from pyzbar import pyzbar" 2>/dev/null || {
  echo "Instalando pyzbar..."
  sudo apt-get install -y libzbar0 -q 2>/dev/null || true
  pip install pyzbar Pillow -q
}

# Verificar pytesseract (OCR offline para leer etiquetas de productos)
python3 -c "import pytesseract" 2>/dev/null || pip install pytesseract -q
tesseract --version 2>/dev/null || {
  echo "Instalando Tesseract OCR..."
  sudo apt-get install -y tesseract-ocr tesseract-ocr-spa -q 2>/dev/null || true
}

# Arrancar ZERO POS
python3 app.py
