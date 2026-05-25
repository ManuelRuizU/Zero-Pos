#!/bin/bash
cd "$(dirname "$0")"

# Activar entorno virtual
source venv/bin/activate

# Arrancar ZERO POS
python3 app.py
