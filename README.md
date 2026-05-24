# ZERO POS

**Sin internet obligatorio. Sin suscripción. Sin comisiones. El negocio y los datos viven solo en tu dispositivo.**

## Inicio rápido

```bash
# Mac / Linux
chmod +x INICIAR_MAC_LINUX.sh
./INICIAR_MAC_LINUX.sh

# O manualmente
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
python3 app.py
```

Abre → http://127.0.0.1:5000  
PIN por defecto: **1234**

## Pantallas

| URL | Descripción |
|-----|-------------|
| `/static/login.html` | Login PIN |
| `/static/pos.html` | **Caja principal** (cajero) |
| `/static/admin.html` | Dashboard + IA + reportes |
| `/static/inventario.html` | Productos + proveedores |
| `/static/cocina.html` | Cola de pedidos (cocina) |
| `/static/cliente.html` | Pantalla cliente con QR |
| `/static/scanner.html` | Escáner código de barras |
| `/static/multi.html` | Multi-sucursal |

## Stack

- **Backend**: Python + Flask 3 + SQLite (WAL mode)
- **IA local**: TinyLlama via Ollama (opcional — fallback sin IA)
- **Frontend**: HTML + CSS + JS puro (sin frameworks)
- **Pagos**: Khipu (1% comisión, opcional)

## IA local (TinyLlama)

```bash
# Instalar Ollama: https://ollama.ai
ollama pull tinyllama
ollama serve
```

El análisis de IA funciona sin Ollama — devuelve análisis estático.

## Backup

- Backup automático diario a las 03:00
- Cifrado con AES-256 (Fernet)
- Máximo 7 backups guardados
- Panel: Admin → Config → Backups

## Configuración Khipu

En la base de datos (`config`):
- `khipu_receiver_id`: Tu ID de receptor
- `khipu_secret`: Tu secreto API

## Estructura

```
zero_pos/
├── app.py              # Entry point
├── database.py         # SQLite + WAL + init_db
├── routes/             # Blueprints Flask
├── utils/              # Lógica auxiliar
├── static/             # HTML del frontend
└── models/             # Schema SQL
```
