"""
risk_manager.py — Protección de capital y trailing stop
Ninguna orden llega a Alpaca sin pasar por aquí.
"""

import logging
from datetime import date
from config import (
    MAX_PERDIDA_DIARIA, MAX_PERDIDA_TOTAL, OBJETIVO_DIARIO, OBJETIVO_MENSUAL,
    MAX_POSICIONES, RIESGO_POR_TRADE, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    REINVERTIR_PCT, TRAILING_ACTIVAR, TRAILING_DISTANCIA_PCT,
    VOL_MULTIPLICADOR, MOMENTUM_MIN_PCT,
)

logger = logging.getLogger("risk")


class TrailingState:
    """Estado del trailing stop para una posición abierta."""

    def __init__(self, precio_entrada: float):
        self.entrada    = precio_entrada
        self.activo     = False
        self.precio_max = precio_entrada
        self.stop_trail = precio_entrada * (1 - TRAILING_DISTANCIA_PCT)

    def actualizar(self, precio: float, vol: float, vol_media: float) -> str:
        """
        Retorna: 'hold' | 'salir_take' | 'salir_stop' | 'salir_trail'
        """
        ganancia_pct = (precio - self.entrada) / self.entrada

        # 1. Stop-loss duro — siempre tiene prioridad
        if ganancia_pct <= -STOP_LOSS_PCT:
            return "salir_stop"

        if not self.activo:
            # 2. ¿Llegamos al take-profit base?
            if ganancia_pct >= TAKE_PROFIT_PCT:
                vol_fuerte     = vol >= vol_media * VOL_MULTIPLICADOR
                momento_fuerte = ganancia_pct >= MOMENTUM_MIN_PCT
                if TRAILING_ACTIVAR and vol_fuerte and momento_fuerte:
                    self.activo     = True
                    self.precio_max = precio
                    self.stop_trail = precio * (1 - TRAILING_DISTANCIA_PCT)
                    logger.info(f"Trailing activado @ {precio:.4f} "
                                f"(vol x{vol/vol_media:.1f}, +{ganancia_pct*100:.2f}%)")
                    return "hold"
                return "salir_take"
        else:
            # 3. Trailing activo — subir el stop si el precio sigue subiendo
            if precio > self.precio_max:
                self.precio_max = precio
                self.stop_trail = precio * (1 - TRAILING_DISTANCIA_PCT)
            if precio <= self.stop_trail:
                return "salir_trail"

        return "hold"


class RiskManager:

    def __init__(self):
        self.pnl_diario  = 0.0
        self.pnl_total   = 0.0
        self.fecha_hoy   = date.today()
        self.objetivo_ok = False
        self.trailing: dict[str, TrailingState] = {}

    # ── Reseteo automático al cambiar de día ──────────────────────────────────
    def _check_dia(self):
        hoy = date.today()
        if hoy != self.fecha_hoy:
            logger.info(f"Nuevo dia. PnL ayer: {self.pnl_diario:+.2f} USD")
            self.pnl_diario  = 0.0
            self.fecha_hoy   = hoy
            self.objetivo_ok = False

    # ── Registrar apertura ────────────────────────────────────────────────────
    def registrar_apertura(self, simbolo: str, precio: float):
        self.trailing[simbolo] = TrailingState(precio)

    # ── Registrar cierre ──────────────────────────────────────────────────────
    def registrar_cierre(self, simbolo: str, ganancia_usd: float):
        self._check_dia()
        self.pnl_diario += ganancia_usd
        self.pnl_total  += ganancia_usd
        self.trailing.pop(simbolo, None)
        tag = "GANANCIA" if ganancia_usd >= 0 else "PERDIDA"
        logger.info(f"[{tag}] {simbolo}: {ganancia_usd:+.2f} USD | "
                    f"Dia: {self.pnl_diario:+.2f} | Total: {self.pnl_total:+.2f}")
        if self.pnl_diario >= OBJETIVO_DIARIO and not self.objetivo_ok:
            self.objetivo_ok = True
            logger.info(f"OBJETIVO DIARIO alcanzado ({OBJETIVO_DIARIO} USD). "
                        "Sin nuevas entradas hoy.")

    # ── Evaluar posición abierta ───────────────────────────────────────────────
    def evaluar_posicion(self, simbolo: str, precio: float,
                         vol: float, vol_media: float) -> str:
        if simbolo not in self.trailing:
            return "hold"
        return self.trailing[simbolo].actualizar(precio, vol, vol_media)

    # ── ¿Podemos abrir más posiciones? ───────────────────────────────────────
    def puede_operar(self, n_posiciones: int) -> tuple[bool, str]:
        self._check_dia()
        if self.pnl_total <= -MAX_PERDIDA_TOTAL:
            return False, f"STOP GLOBAL: perdida total {self.pnl_total:.2f} USD"
        if self.pnl_diario <= -MAX_PERDIDA_DIARIA:
            return False, f"STOP DIARIO: perdida hoy {self.pnl_diario:.2f} USD"
        if self.objetivo_ok:
            return False, "Objetivo diario alcanzado."
        if n_posiciones >= MAX_POSICIONES:
            return False, f"Maximo de posiciones ({MAX_POSICIONES}) alcanzado."
        return True, "OK"

    # ── Tamaño de posición ────────────────────────────────────────────────────
    def calcular_cantidad(self, precio: float, portfolio_value: float) -> float:
        capital_en_riesgo  = portfolio_value * RIESGO_POR_TRADE
        perdida_por_accion = precio * STOP_LOSS_PCT
        if perdida_por_accion <= 0:
            return 0.0
        return round(max(capital_en_riesgo / perdida_por_accion, 0.01), 4)

    # ── Calcular retiro mensual ───────────────────────────────────────────────
    def calcular_retiro(self) -> dict:
        if self.pnl_total <= OBJETIVO_MENSUAL:
            return {"retiro": 0.0, "reinversion": 0.0}
        extra       = self.pnl_total - OBJETIVO_MENSUAL
        retiro      = round(OBJETIVO_MENSUAL + extra * (1 - REINVERTIR_PCT), 2)
        reinversion = round(extra * REINVERTIR_PCT, 2)
        return {"retiro": retiro, "reinversion": reinversion}

    # ── Resumen para el dashboard ─────────────────────────────────────────────
    def resumen(self) -> dict:
        self._check_dia()
        return {
            "pnl_diario":       round(self.pnl_diario, 2),
            "pnl_total":        round(self.pnl_total, 2),
            "objetivo_ok":      self.objetivo_ok,
            "retiro":           self.calcular_retiro(),
            "trailing_activos": {s: t.activo for s, t in self.trailing.items()},
        }