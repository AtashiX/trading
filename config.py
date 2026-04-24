"""
config.py — Configuración central del bot de scalping
Edita SOLO este archivo. No toques los demás.

En local: las keys se leen desde .env (nunca subas ese archivo a GitHub).
En Render: se leen desde las variables de entorno del panel.
En ambos casos el código es idéntico — dotenv solo actúa si existe el .env.
"""

import os
from dotenv import load_dotenv

# Carga el .env si existe (local). En Render no existe y no hace nada.
load_dotenv()

# ─── Credenciales Alpaca ───────────────────────────────────────────────────────
ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")
MODE              = os.environ.get("MODE", "paper")   # "paper" = simulación | "live" = real

if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
    raise ValueError(
        "Faltan las credenciales de Alpaca.\n"
        "En local: crea un archivo .env con ALPACA_API_KEY y ALPACA_SECRET_KEY.\n"
        "En Render: añádelas como variables de entorno en el panel."
    )

ALPACA_BASE_URL = {
    "paper": "https://paper-api.alpaca.markets",
    "live":  "https://api.alpaca.markets",
}[MODE]

# ─── Capital y objetivos ──────────────────────────────────────────────────────
CAPITAL_INICIAL    = 100.0   # USD de partida (referencia para cálculos)
OBJETIVO_DIARIO    = 25.0     # USD: no abrir nuevas posiciones al alcanzarlo
OBJETIVO_MENSUAL   = 100.0   # USD: referencia para calcular retiro mensual
MAX_PERDIDA_DIARIA = 8.0     # USD: detener el bot si se supera en el día
MAX_PERDIDA_TOTAL  = 75.0    # USD: límite absoluto (nunca perder más del 75%)

# ─── Gestión de posiciones ────────────────────────────────────────────────────
STOP_LOSS_PCT    = 0.006    # −0.6% stop-loss fijo por operación
TAKE_PROFIT_PCT  = 0.008    # +0.8% take-profit base — se alcanza antes, mas rotacion
MAX_POSICIONES   = 3         # Máximo de posiciones abiertas simultáneas
MAX_GASTO_POR_TRADE = 0.30  # gastar max 30% del capital por orden (con 3 pos max = 90 USD usados)
REINVERTIR_PCT   = 0.50     # 50% de beneficios extra sobre objetivo → reinvertir

# ─── Trailing stop ────────────────────────────────────────────────────────────
# Se activa solo si hay volumen fuerte Y el precio sigue acelerando al llegar al +1%.
TRAILING_ACTIVAR       = True
TRAILING_DISTANCIA_PCT = 0.004  # Distancia del trailing al precio máximo
VOL_MULTIPLICADOR      = 1.5    # Volumen actual debe ser > media × 1.5
MOMENTUM_MIN_PCT       = 0.005  # Precio debe haber subido > 0.5% desde entrada

# ─── Símbolos ─────────────────────────────────────────────────────────────────
# Tier 1 primero (más seguros). Tier 3 al final (más especulativos).
# El bot itera en orden: empieza por los primeros.
SIMBOLOS = [
    # Núcleo (top calidad para scalping agresivo)
    "SPY", "QQQ", "IWM",
    "NVDA", "AMD",
    "AAPL", "MSFT",
    "TSLA", "META", "AMZN", "GOOGL",
    # Alta volatilidad “buena” (para más agresividad)
    "NFLX", "COIN", "SMCI", "ARM", "MU", "INTC",
    # Volatilidad media-alta (opcionales pero útiles)
    "PLTR", "HOOD", "SOFI", "SNAP"
]

# ─── Estrategia EMA + RSI + volumen ──────────────────────────────────────────
EMA_RAPIDA      = 5     # EMA muy reactiva
EMA_LENTA       = 8     # Bajado de 13: cruces mas frecuentes
RSI_PERIODO     = 7     # RSI corto para scalping
RSI_SOBRECOMPRA = 65    # Subido de 60: ventana de entrada mas amplia
VOL_MEDIA_N     = 20    # Velas para calcular volumen medio
EXIGIR_VOLUMEN  = False # False: no exigir confirmacion de volumen para entrar

INTERVALO_BARS = "1Min"
N_BARRAS       = 60     # Últimas 60 velas de 1 minuto

# ─── Timing ───────────────────────────────────────────────────────────────────
SLEEP_SEGUNDOS = 30     # Ciclo cada 30 segundos
LOG_FILE       = "trades.csv"
DASHBOARD_PORT = 8080