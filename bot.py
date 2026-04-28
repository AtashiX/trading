"""
bot.py — Bot de scalping 1 minuto + dashboard web
Estrategia: EMA(5/8) + RSI(7) + confirmación de volumen

Arranque local:
    python bot.py
    → Dashboard en http://localhost:8080

En Render:
    Start command: python bot.py

FIXES APLICADOS:
    1. limpiar_posiciones_al_arrancar sincroniza RiskManager
    2. Evaluación de posiciones usa precio de quote en tiempo real
    3. Protección de horario de mercado (09:30–16:00 ET)
    4. Threading lock en risk.resumen() / trailing dict
    5. calcular_cantidad usa floor a 2 decimales (compatible con Alpaca)
"""

import math
import time
import logging
import csv
import os
from datetime import datetime, timezone, time as dtime
from threading import Thread, Lock
import zoneinfo

import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template_string

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

import config
from risk_manager import RiskManager

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("bot")

# ─── Clientes Alpaca ──────────────────────────────────────────────────────────
trading_client = TradingClient(
    config.ALPACA_API_KEY,
    config.ALPACA_SECRET_KEY,
    paper=(config.MODE == "paper"),
)
data_client = StockHistoricalDataClient(
    config.ALPACA_API_KEY,
    config.ALPACA_SECRET_KEY,
)
risk = RiskManager()

# FIX 4 — Lock para proteger accesos concurrentes al RiskManager desde
# el hilo del bot y el hilo de Flask.
risk_lock = Lock()

# ─── Zona horaria del mercado ─────────────────────────────────────────────────
ET = zoneinfo.ZoneInfo("America/New_York")
MARKET_OPEN  = dtime(9, 30)
MARKET_CLOSE = dtime(16, 0)


# ─── FIX 3 — Protección de horario de mercado ─────────────────────────────────
def mercado_abierto() -> bool:
    """Devuelve True solo si estamos dentro del horario regular de NYSE."""
    ahora = datetime.now(ET)
    # Fin de semana
    if ahora.weekday() >= 5:
        return False
    hora_et = ahora.time().replace(second=0, microsecond=0)
    return MARKET_OPEN <= hora_et < MARKET_CLOSE


# ─── FIX 2 — Precio de mercado en tiempo real via quote ──────────────────────
def obtener_precio_real(simbolo: str) -> float | None:
    """
    Obtiene el mid-price del último quote (bid+ask)/2.
    Más preciso que el close de la última vela para evaluar SL/TP.
    Retorna None si falla.
    """
    try:
        req = StockLatestQuoteRequest(symbol_or_symbols=simbolo)
        quote = data_client.get_stock_latest_quote(req)[simbolo]
        bid = float(quote.bid_price)
        ask = float(quote.ask_price)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
    except Exception as e:
        logger.debug(f"Quote fallback {simbolo}: {e}")
    return None


# ─── Datos e indicadores ──────────────────────────────────────────────────────

def obtener_barras(simbolo: str) -> pd.DataFrame:
    req = StockBarsRequest(
        symbol_or_symbols=simbolo,
        timeframe=TimeFrame(1, TimeFrameUnit.Minute),
        limit=config.N_BARRAS,
    )
    df = data_client.get_stock_bars(req).df
    if isinstance(df.index, pd.MultiIndex):
        df = df.loc[simbolo]
    df = df.reset_index()
    if df.empty or "close" not in df.columns:
        raise ValueError(f"Sin datos de mercado para {simbolo} (¿mercado cerrado?)")
    return df


def calcular_indicadores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema_r"]     = df["close"].ewm(span=config.EMA_RAPIDA, adjust=False).mean()
    df["ema_l"]     = df["close"].ewm(span=config.EMA_LENTA,  adjust=False).mean()
    delta           = df["close"].diff()
    gan             = delta.clip(lower=0).ewm(span=config.RSI_PERIODO, adjust=False).mean()
    perd            = (-delta.clip(upper=0)).ewm(span=config.RSI_PERIODO, adjust=False).mean()
    df["rsi"]       = 100 - (100 / (1 + gan / perd.replace(0, np.nan)))
    df["vol_media"] = df["volume"].rolling(config.VOL_MEDIA_N).mean()
    return df


def señal_entrada(df: pd.DataFrame) -> bool:
    if len(df) < config.EMA_LENTA + 2:
        return False
    ult, prev = df.iloc[-1], df.iloc[-2]
    cruce  = (prev["ema_r"] <= prev["ema_l"]) and (ult["ema_r"] > ult["ema_l"])
    # RSI_SOBRECOMPRA actúa como umbral de NO-entrada (RSI debe estar por debajo)
    rsi_ok = ult["rsi"] < config.RSI_SOBRECOMPRA
    vol_ok = ult["volume"] > ult["vol_media"]
    if config.EXIGIR_VOLUMEN:
        return cruce and rsi_ok and vol_ok
    return cruce and rsi_ok


# ─── Utilidades de trading ────────────────────────────────────────────────────

def portfolio_value() -> float:
    try:
        return float(trading_client.get_account().portfolio_value)
    except Exception as e:
        logger.error(f"Error portfolio: {e}")
        return config.CAPITAL_INICIAL


def posiciones_abiertas() -> dict:
    try:
        return {p.symbol: p for p in trading_client.get_all_positions()}
    except Exception as e:
        logger.error(f"Error posiciones: {e}")
        return {}


def registrar_csv(simbolo, lado, cantidad, precio, pnl=None, motivo=""):
    nuevo = not os.path.isfile(config.LOG_FILE)
    with open(config.LOG_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["timestamp", "simbolo", "lado", "cantidad",
                        "precio", "pnl", "motivo"])
        w.writerow([
            datetime.now(timezone.utc).isoformat(),
            simbolo, lado, cantidad, f"{precio:.4f}",
            f"{pnl:.4f}" if pnl is not None else "",
            motivo,
        ])


def abrir_posicion(simbolo: str, precio: float):
    # FIX 5 aplicado en RiskManager.calcular_cantidad (ver risk_manager.py)
    cantidad = risk.calcular_cantidad(precio)
    if cantidad <= 0:
        return
    try:
        trading_client.submit_order(MarketOrderRequest(
            symbol=simbolo,
            qty=cantidad,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        ))
        with risk_lock:  # FIX 4
            risk.registrar_apertura(simbolo, precio)
        logger.info(f"COMPRA {simbolo}: {cantidad} acc @ ~{precio:.4f} "
                    f"| SL {precio*(1-config.STOP_LOSS_PCT):.4f} "
                    f"| TP {precio*(1+config.TAKE_PROFIT_PCT):.4f}")
        registrar_csv(simbolo, "buy", cantidad, precio)
    except Exception as e:
        logger.error(f"Error abriendo {simbolo}: {e}")


def cerrar_posicion(simbolo: str, posicion, motivo: str):
    try:
        qty     = abs(float(posicion.qty))
        entrada = float(posicion.avg_entry_price)
        actual  = float(posicion.current_price)
        pnl     = (actual - entrada) * qty
        trading_client.close_position(simbolo)
        with risk_lock:  # FIX 4
            risk.registrar_cierre(simbolo, pnl)
        registrar_csv(simbolo, "sell", qty, actual, pnl, motivo)
        logger.info(f"CIERRE {simbolo} [{motivo}]: {pnl:+.4f} USD")
    except Exception as e:
        logger.error(f"Error cerrando {simbolo}: {e}")


# ─── Ciclo principal ──────────────────────────────────────────────────────────

def ciclo():
    posiciones = posiciones_abiertas()

    for simbolo in config.SIMBOLOS:
        try:
            df         = obtener_barras(simbolo)
            df         = calcular_indicadores(df)
            ult        = df.iloc[-1]
            vol_actual = float(ult["volume"])
            vol_media  = float(ult["vol_media"]) if not np.isnan(ult["vol_media"]) else vol_actual

            # FIX 2 — Usar precio real de quote para evaluar SL/TP/trailing
            precio = obtener_precio_real(simbolo) or float(ult["close"])

            # Gestión de posición existente
            if simbolo in posiciones:
                with risk_lock:  # FIX 4
                    accion = risk.evaluar_posicion(simbolo, precio, vol_actual, vol_media)
                if accion == "salir_take":
                    cerrar_posicion(simbolo, posiciones[simbolo], "take-profit")
                elif accion == "salir_stop":
                    cerrar_posicion(simbolo, posiciones[simbolo], "stop-loss")
                elif accion == "salir_trail":
                    cerrar_posicion(simbolo, posiciones[simbolo], "trailing-stop")
                continue

            # Nueva entrada
            if not señal_entrada(df):
                continue

            with risk_lock:  # FIX 4
                ok, motivo_bloqueo = risk.puede_operar()
            if not ok:
                logger.debug(f"No operar: {motivo_bloqueo}")
                continue
            abrir_posicion(simbolo, precio)

        except Exception as e:
            logger.error(f"Error {simbolo}: {e}")

    with risk_lock:
        r = risk.resumen()
    logger.info(f"PnL dia: {r['pnl_diario']:+.2f} | Total: {r['pnl_total']:+.2f} USD")


# ─── FIX 1 — Arranque limpio con sincronización de RiskManager ────────────────

def limpiar_posiciones_al_arrancar():
    """
    Cierra todas las posiciones abiertas al arrancar el bot Y registra
    cada cierre en el RiskManager para mantener el PnL consistente.
    """
    try:
        abiertas = trading_client.get_all_positions()
        if not abiertas:
            logger.info("Arranque limpio: sin posiciones abiertas.")
            return
        logger.info(f"Cerrando {len(abiertas)} posicion(es) abiertas al arrancar...")
        for p in abiertas:
            simbolo = p.symbol
            try:
                qty     = abs(float(p.qty))
                entrada = float(p.avg_entry_price)
                actual  = float(p.current_price)
                pnl     = (actual - entrada) * qty
                # FIX 1 — Registrar en RiskManager antes de enviar la orden
                # (registrar_apertura necesita existir para que registrar_cierre funcione)
                if simbolo not in risk.trailing:
                    risk.registrar_apertura(simbolo, entrada)
                risk.registrar_cierre(simbolo, pnl)
                registrar_csv(simbolo, "sell", qty, actual, pnl, "arranque-limpieza")
                logger.info(f"  Cerrada posicion previa {simbolo}: {pnl:+.4f} USD")
            except Exception as e:
                logger.error(f"  Error procesando {simbolo} al arrancar: {e}")
        # Cierre masivo en Alpaca tras registrar todo
        trading_client.close_all_positions(cancel_orders=True)
        logger.info("Posiciones cerradas y PnL sincronizado. Bot listo.")
    except Exception as e:
        logger.error(f"Error cerrando posiciones al arrancar: {e}")


def bucle_principal():
    logger.info(f"Bot arrancado | Modo: {config.MODE.upper()}")
    _ciclos_cerrado = 0
    while True:
        try:
            if mercado_abierto():
                _ciclos_cerrado = 0
                ciclo()
            else:
                # Log solo cada 120 ciclos (~1h) para no saturar los logs
                if _ciclos_cerrado % 120 == 0:
                    logger.info("Mercado cerrado. Esperando apertura...")
                _ciclos_cerrado += 1
        except Exception as e:
            logger.error(f"Error en ciclo: {e}")
        time.sleep(config.SLEEP_SEGUNDOS)


# ─── Dashboard Flask ──────────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="15">
<title>Scalping Bot</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0d0f1a;color:#e0e0e0;padding:20px}
h1{color:#7c6af5;font-size:20px;margin-bottom:3px}
.sub{color:#555;font-size:12px;margin-bottom:20px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:20px}
.card{background:#151724;border-radius:10px;padding:14px;border:1px solid #1e2236}
.card-label{font-size:10px;color:#555;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}
.card-value{font-size:24px;font-weight:600}
.pos{color:#4caf50}.neg{color:#f44336}.neu{color:#7c6af5}
table{width:100%;border-collapse:collapse;background:#151724;border-radius:10px;overflow:hidden;margin-bottom:20px;font-size:12px}
th{background:#1e2236;padding:8px 10px;text-align:left;color:#555;text-transform:uppercase;font-size:10px;letter-spacing:.4px}
td{padding:8px 10px;border-top:1px solid #1a1d2e}
h2{font-size:11px;color:#555;text-transform:uppercase;letter-spacing:.5px;margin:14px 0 7px}
.badge{padding:2px 6px;border-radius:4px;font-size:10px;font-weight:700}
.paper{background:#1e2236;color:#7c6af5}.live{background:#1a2e1a;color:#4caf50}
.mercado-off{background:#2e1a1a;color:#f44336}
code{font-family:monospace;font-size:11px;color:#aaa}
</style>
</head>
<body>
<h1>Scalping Bot</h1>
<p class="sub">
  Modo: <span class="badge {{ modo }}">{{ modo.upper() }}</span>
  &nbsp;·&nbsp; {{ ahora }}
  &nbsp;·&nbsp; Mercado: <span class="badge {{ 'paper' if mercado_ok else 'mercado-off' }}">{{ 'ABIERTO' if mercado_ok else 'CERRADO' }}</span>
  &nbsp;·&nbsp; refresh 15s
</p>
<div class="cards">
  <div class="card">
    <div class="card-label">PnL hoy</div>
    <div class="card-value {{ clase_d }}">{{ pnl_diario }} USD</div>
  </div>
  <div class="card">
    <div class="card-label">Objetivo dia</div>
    <div class="card-value {{ 'pos' if objetivo_ok else 'neu' }}">
      {{ 'Alcanzado' if objetivo_ok else objetivo_diario|string + ' USD' }}
    </div>
  </div>
  <div class="card">
    <div class="card-label">PnL total</div>
    <div class="card-value {{ clase_t }}">{{ pnl_total }} USD</div>
  </div>
  <div class="card">
    <div class="card-label">Retiro disponible</div>
    <div class="card-value neu">{{ retiro }} USD</div>
  </div>
  <div class="card">
    <div class="card-label">Posiciones</div>
    <div class="card-value neu">{{ n_pos }} / {{ max_pos }}</div>
  </div>
</div>

<h2>Posiciones abiertas</h2>
<table>
  <tr><th>Simbolo</th><th>Qty</th><th>Entrada</th><th>Actual</th><th>PnL no realizado</th><th>Estado</th></tr>
  {% for p in posiciones %}
  <tr>
    <td><strong>{{ p.symbol }}</strong></td>
    <td>{{ p.qty }}</td>
    <td><code>{{ p.avg_entry_price }}</code></td>
    <td><code>{{ p.current_price }}</code></td>
    <td class="{{ p.pl_clase }}">{{ p.pl_valor }} USD</td>
    <td>{{ 'Trailing activo' if p.trailing else 'Esperando TP' }}</td>
  </tr>
  {% else %}
  <tr><td colspan="6" style="color:#333;text-align:center;padding:16px">Sin posiciones abiertas</td></tr>
  {% endfor %}
</table>

<h2>Ultimos 20 trades</h2>
<table>
  <tr><th>Hora</th><th>Simbolo</th><th>Lado</th><th>Qty</th><th>Precio</th><th>PnL</th><th>Motivo</th></tr>
  {% for t in trades %}
  <tr>
    <td style="color:#555">{{ t.hora }}</td>
    <td><strong>{{ t.simbolo }}</strong></td>
    <td class="{{ 'pos' if t.lado == 'buy' else 'neg' }}">{{ t.lado.upper() }}</td>
    <td>{{ t.cantidad }}</td>
    <td><code>{{ t.precio }}</code></td>
    <td class="{{ t.pl_clase }}">{{ t.pnl or '—' }}</td>
    <td style="color:#555;font-size:10px">{{ t.motivo }}</td>
  </tr>
  {% else %}
  <tr><td colspan="7" style="color:#333;text-align:center;padding:16px">Sin trades aun</td></tr>
  {% endfor %}
</table>
</body></html>"""

app = Flask(__name__)


@app.route("/")
def dashboard():
    with risk_lock:  # FIX 4
        r = risk.resumen()

    posiciones = []
    try:
        for p in trading_client.get_all_positions():
            pl = float(p.unrealized_pl)
            posiciones.append({
                "symbol":          p.symbol,
                "qty":             p.qty,
                "avg_entry_price": p.avg_entry_price,
                "current_price":   p.current_price,
                "pl_valor":        f"{pl:+.2f}",
                "pl_clase":        "pos" if pl >= 0 else "neg",
                "trailing":        r["trailing_activos"].get(p.symbol, False),
            })
    except Exception:
        pass

    trades = []
    if os.path.isfile(config.LOG_FILE):
        with open(config.LOG_FILE) as f:
            rows = list(csv.reader(f))
        for row in rows[-21:-1][::-1]:
            pnl_str = row[5] if len(row) > 5 else ""
            try:
                pl_clase = "pos" if float(pnl_str) >= 0 else "neg"
            except (ValueError, IndexError):
                pl_clase = "neu"
            trades.append({
                "hora":     row[0][11:19] if row[0] else "",
                "simbolo":  row[1] if len(row) > 1 else "",
                "lado":     row[2] if len(row) > 2 else "",
                "cantidad": row[3] if len(row) > 3 else "",
                "precio":   row[4] if len(row) > 4 else "",
                "pnl":      pnl_str,
                "pl_clase": pl_clase,
                "motivo":   row[6] if len(row) > 6 else "",
            })

    return render_template_string(
        DASHBOARD_HTML,
        modo=config.MODE,
        ahora=datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        mercado_ok=mercado_abierto(),
        pnl_diario=f"{r['pnl_diario']:+.2f}",
        pnl_total=f"{r['pnl_total']:+.2f}",
        retiro=r["retiro"]["retiro"],
        n_pos=len(posiciones),
        max_pos=config.MAX_POSICIONES,
        objetivo_ok=r["objetivo_ok"],
        objetivo_diario=config.OBJETIVO_DIARIO,
        posiciones=posiciones,
        trades=trades,
        clase_d="pos" if r["pnl_diario"] >= 0 else "neg",
        clase_t="pos" if r["pnl_total"]  >= 0 else "neg",
    )


@app.route("/api/status")
def api_status():
    with risk_lock:  # FIX 4
        return jsonify(risk.resumen())


@app.route("/health")
def health():
    return jsonify({
        "status":       "ok",
        "mode":         config.MODE,
        "mercado":      mercado_abierto(),
    }), 200


# ─── Arranque del hilo del bot ───────────────────────────────────────────────
# Compatible con python bot.py (desarrollo) Y gunicorn --preload (producción).
# El flag _bot_iniciado evita arrancar el hilo dos veces si Gunicorn
# hace múltiples imports del módulo.

_bot_iniciado = False

def iniciar_bot():
    global _bot_iniciado
    if _bot_iniciado:
        return
    _bot_iniciado = True
    limpiar_posiciones_al_arrancar()
    t = Thread(target=bucle_principal, daemon=False)  # daemon=False: sobrevive al main
    t.start()
    logger.info("Hilo del bot arrancado.")

# Gunicorn importa este módulo en el worker → iniciar_bot() se llama aquí
iniciar_bot()

if __name__ == "__main__":
    logger.info(f"Dashboard en http://localhost:{config.DASHBOARD_PORT}")
    app.run(host="0.0.0.0", port=config.DASHBOARD_PORT, debug=False)