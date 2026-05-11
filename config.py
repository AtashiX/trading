"""
config.py — Configuración central del bot de scalping
Edita SOLO este archivo. No toques los demás.

En local: las keys se leen desde .env (nunca subas ese archivo a GitHub).
En Render: se leen desde las variables de entorno del panel.
En ambos casos el código es idéntico — dotenv solo actúa si existe el .env.

PARÁMETROS ACTUALIZADOS CON BACKTEST (2026-05-11)
  Universo: 480 símbolos S&P500 | Histórico: 1 año | Configs probadas: 8300
  Config ganadora: EMA 2/7, RSI5<55, SL 1.1%, TP 0.5% → win rate 68.1%
  Símbolos top: STX, WDC, TER, KLAC, MU, LRCX, AMD, PWR, JBL, MPWR
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
OBJETIVO_DIARIO    = 25.0    # USD: no abrir nuevas posiciones al alcanzarlo
OBJETIVO_MENSUAL   = 100.0   # USD: referencia para calcular retiro mensual
MAX_PERDIDA_DIARIA = 8.0     # USD: detener el bot si se supera en el día
MAX_PERDIDA_TOTAL  = 75.0    # USD: límite absoluto (nunca perder más del 75%)

# ─── Gestión de posiciones ────────────────────────────────────────────────────
# BACKTEST: SL 1.1% / TP 0.5% con win rate 68.1% es matemáticamente rentable.
# Ganas más veces (68%) aunque cada ganancia sea menor que cada pérdida.
STOP_LOSS_PCT       = 0.011  # −1.1% stop-loss (backtest óptimo)
TAKE_PROFIT_PCT     = 0.005  # +0.5% take-profit (backtest óptimo)
MAX_POSICIONES      = 3      # Máximo de posiciones abiertas simultáneas
MAX_GASTO_POR_TRADE = 0.30   # 30% del capital por orden (3 pos × 30 USD = 90 USD)
REINVERTIR_PCT      = 0.50   # 50% de beneficios extra sobre objetivo → reinvertir

# ─── Trailing stop ────────────────────────────────────────────────────────────
# Con TP de solo 0.5%, el trailing tiene menos margen para activarse.
# Se mantiene activo pero con distancia ajustada.
TRAILING_ACTIVAR       = True
TRAILING_DISTANCIA_PCT = 0.003  # Reducido de 0.4% a 0.3% (acorde al TP más ajustado)
VOL_MULTIPLICADOR      = 1.5    # Volumen actual debe ser > media × 1.5
MOMENTUM_MIN_PCT       = 0.003  # Reducido de 0.5% a 0.3% (acorde al TP más ajustado)

# ─── Símbolos ─────────────────────────────────────────────────────────────────
# Lista actualizada con resultados del backtest.
# Orden: mejores performers primero (el bot itera en orden).
# Top backtest: STX, WDC, TER, KLAC, MU, LRCX, AMD, PWR, JBL, MPWR
SIMBOLOS = [
    # Top performers backtest (semiconductores y tech mediana cap)
    "STX", "WDC", "TER", "KLAC", "MU", "LRCX", "AMD", "PWR", "JBL", "MPWR",
    # Segunda línea backtest
    "GLW", "APA", "INTC", "WBD",
    # Núcleo original de alta liquidez (mantener como referencia)
    "SPY", "QQQ", "NVDA", "TSLA", "META",
    # Alta volatilidad útil
    "COIN", "PLTR",
]

# ─── Estrategia EMA + RSI + volumen ──────────────────────────────────────────
# BACKTEST: EMA 2/7 + RSI período 5 umbral <55 → win rate 68.1%
# EMA muy reactiva (2/7) genera más cruces pero el filtro RSI<55 los filtra bien.
EMA_RAPIDA      = 2      # Muy reactiva (backtest óptimo)
EMA_LENTA       = 7      # Backtest óptimo
RSI_PERIODO     = 5      # RSI ultrarrápido para scalping (backtest óptimo)
RSI_SOBRECOMPRA = 55     # Más restrictivo que antes: solo entradas más limpias
VOL_MEDIA_N     = 20     # Velas para calcular volumen medio
EXIGIR_VOLUMEN  = False  # False: no exigir confirmación de volumen para entrar
CRUCE_VENTANA   = 3      # Buscar cruce en las últimas N velas (backtest óptimo)

INTERVALO_BARS = "1Min"
N_BARRAS       = 60      # Últimas 60 velas de 1 minuto

# ─── Timing ───────────────────────────────────────────────────────────────────
SLEEP_SEGUNDOS = 30      # Ciclo cada 30 segundos
LOG_FILE       = "trades.csv"
DASHBOARD_PORT = 8080