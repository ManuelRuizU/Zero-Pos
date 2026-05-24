#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo -e "${GREEN}╔════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         ZERO POS  v1.0             ║${NC}"
echo -e "${GREEN}║  Sin internet. Sin comisiones.     ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════╝${NC}"
echo ""

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Error: python3 no está instalado.${NC}"
    exit 1
fi

VENV_DIR="$DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}Creando entorno virtual...${NC}"
    python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"

echo -e "${YELLOW}Instalando dependencias...${NC}"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo -e "${GREEN}Iniciando ZERO POS...${NC}"
echo ""
python3 app.py
