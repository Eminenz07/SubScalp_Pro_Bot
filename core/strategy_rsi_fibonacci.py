from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import numpy as np

from .indicators import (
    atr,
    rsi,
    fibonacci_retracement,
    rsi_divergence,
)

def is_bullish_rejection(row: pd.Series) -> bool:
    body = abs(row['close'] - row['open'])
    lower_wick = min(row['open'], row['close']) - row['low']
    return lower_wick > 2 * body and row['close'] > row['open']

def is_bearish_rejection(row: pd.Series) -> bool:
    body = abs(row['close'] - row['open'])
    upper_wick = max(row['open'], row['close']) - row['high']
    return upper_wick > 2 * body and row['close'] < row['open']



class StrategyRSIFibonacci:
    """
    RSI + Fibonacci trading strategy (Engine B).
    This engine is strictly conditional and must only run
    when explicitly allowed by Engine A (LSMC).
    """

    def __init__(self, config: dict, analytics=None):
        self.config = config
        self.strategy_settings = config["strategy_settings"]["engine_b_rsi_fibonacci"]
        self.liquidity_sweep_settings = config["strategy_settings"]["liquidity_sweep"]
        self.htf_trend_timeframe = config["htf_trend_timeframe"]
        self.analytics = analytics

        self.impulse_atr_multiplier = self.strategy_settings["impulse_atr_multiplier"]
        self.ema_fast_period = self.strategy_settings["ema_fast_period"]
        self.ema_slow_period = self.strategy_settings["ema_slow_period"]
        self.rsi_period = self.strategy_settings["rsi_period"]
        self.fib_pullback_min = self.strategy_settings["fib_pullback_min"]
        self.fib_pullback_max = self.strategy_settings["fib_pullback_max"]
        self.tp_rr_min = self.strategy_settings["tp_rr_min"]
        self.tp_rr_max = self.strategy_settings["tp_rr_max"]

        # ATR MUST be fixed and independent of RSI
        self.atr_period = 14

    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.set_index("timestamp", inplace=True)

        atr(df, self.atr_period, name=f"atr_{self.atr_period}")
        rsi(df, self.rsi_period, name=f"rsi_{self.rsi_period}")

        return df

    def generate_signals(
        self,
        df_m5: pd.DataFrame,
        df_m15: pd.DataFrame,
        market_state: str = "BLOCK_ALL_TRADES",
        symbol: str = "",
        ctx: dict = None,
    ) -> pd.DataFrame:
        if ctx is None:
            ctx = {}
        df_m5 = self._compute_indicators(df_m5)
        df_m5["engine"] = "B"

        # --------------------------------------------------
        # HARD GATE: Engine B ONLY runs if explicitly allowed
        # --------------------------------------------------
        if market_state != "ALLOW_ENGINE_B_EVALUATION":
            df_m5["signal"] = 0
            df_m5["sl_distance"] = 0.0
            df_m5["tp_distance"] = 0.0
            return df_m5

        # Exhaustion Event Lock
        if ctx.get("engine_b_consumed", False):
            # Record false positive - Engine B blocked due to consumption
            if self.analytics:
                self.analytics.record_false_positive(
                    engine="B",
                    symbol=symbol,
                    reason="exhaustion_consumed",
                    context={"market_state": market_state, "ctx": ctx}
                )
            df_m5["signal"] = 0
            df_m5["sl_distance"] = 0.0
            df_m5["tp_distance"] = 0.0
            return df_m5

        # Require valid exhaustion event
        if "exhaustion_event_id" not in ctx:
            if self.analytics:
                self.analytics.record_false_positive(
                    engine="B",
                    symbol=symbol,
                    reason="missing_exhaustion_event",
                    context={"market_state": market_state, "ctx": ctx}
                )
            df_m5["signal"] = 0
            df_m5["sl_distance"] = 0.0
            df_m5["tp_distance"] = 0.0
            return df_m5

        # Full context enforcement including impulse boundaries
        if (not ctx or
            ctx.get("regime") != "TRENDING" or
            ctx.get("bias") == "neutral" or
            ctx.get("structure") == "mixed" or
            ctx.get("choch", False) or
            ctx.get("last_impulse_start") is None or
            ctx.get("last_impulse_end") is None):
            # Record false positive - Engine B blocked due to invalid/missing context
            if self.analytics:
                self.analytics.record_false_positive(
                    engine="B",
                    symbol=symbol,
                    reason="invalid_context",
                    context={
                        "regime": ctx.get("regime"),
                        "bias": ctx.get("bias"),
                        "structure": ctx.get("structure"),
                        "choch": ctx.get("choch"),
                        "has_impulse": ctx.get("last_impulse_start") is not None and ctx.get("last_impulse_end") is not None
                    }
                )
            df_m5["signal"] = 0
            df_m5["sl_distance"] = 0.0
            df_m5["tp_distance"] = 0.0
            return df_m5

        # --------------------------------------------------
        # HARD BLOCK: Engine B forbidden on BOOM / CRASH
        # --------------------------------------------------
        if symbol and ("BOOM" in symbol.upper() or "CRASH" in symbol.upper()):
            # Record false positive - Engine B blocked due to symbol restriction
            if self.analytics:
                self.analytics.record_false_positive(
                    engine="B",
                    symbol=symbol,
                    reason="symbol_restriction",
                    context={"symbol": symbol}
                )
            df_m5["signal"] = 0
            df_m5["sl_distance"] = 0.0
            df_m5["tp_distance"] = 0.0
            return df_m5





        # --------------------------------------------------
        # Defaults
        # --------------------------------------------------
        df_m5["signal"] = 0
        df_m5["sl_distance"] = 0.0
        df_m5["tp_distance"] = 0.0

        last = df_m5.iloc[-1]

        atr_col = f"atr_{self.atr_period}"
        atr_val = float(last.get(atr_col, 0.0) or 0.0)

        rsi_col = f"rsi_{self.rsi_period}"
        rsi_val = float(last.get(rsi_col, 50.0) or 50.0)

        if atr_val <= 0:
            return df_m5

        bias = ctx.get("bias", "neutral")
        is_impulse = ctx.get("is_impulse", False)

        sl_dist = 0.8 * atr_val  # Tighter SL for Engine B
        tp_dist = 1.75 * sl_dist  # Lower RR for Engine B

        # --------------------------------------------------
        # Structure & Fibonacci - Hardened anchoring
        # --------------------------------------------------
        impulse_start = ctx["last_impulse_start"]
        impulse_end = ctx["last_impulse_end"]

        # Harden: Validate impulse leg direction matches bias
        if bias == "bullish" and impulse_start >= impulse_end:
            if self.analytics:
                self.analytics.record_false_positive(
                    engine="B",
                    symbol=symbol,
                    reason="invalid_impulse_direction_bullish",
                    context={"impulse_start": impulse_start, "impulse_end": impulse_end}
                )
            df_m5["signal"] = 0
            df_m5["sl_distance"] = 0.0
            df_m5["tp_distance"] = 0.0
            return df_m5

        if bias == "bearish" and impulse_start <= impulse_end:
            if self.analytics:
                self.analytics.record_false_positive(
                    engine="B",
                    symbol=symbol,
                    reason="invalid_impulse_direction_bearish",
                    context={"impulse_start": impulse_start, "impulse_end": impulse_end}
                )
            df_m5["signal"] = 0
            df_m5["sl_distance"] = 0.0
            df_m5["tp_distance"] = 0.0
            return df_m5

        price = float(last["close"])

        # --------------------------------------------------
        # RSI Divergence
        # --------------------------------------------------
        div = rsi_divergence(df_m5, self.rsi_period)

        rejection = is_bullish_rejection(last) if bias == "bullish" else is_bearish_rejection(last) if bias == "bearish" else False
        structure_hold = False
        if bias == "bullish":
            pivot_low = ctx.get("last_pivot_low_price", np.nan)
            if not np.isnan(pivot_low):
                structure_hold = last["close"] > pivot_low and not ctx.get("choch", False)
        elif bias == "bearish":
            pivot_high = ctx.get("last_pivot_high_price", np.nan)
            if not np.isnan(pivot_high):
                structure_hold = last["close"] < pivot_high and not ctx.get("choch", False)
        sweep_confirmation = ctx.get("sweep_bull", False) if bias == "bullish" else ctx.get("sweep_bear", False) if bias == "bearish" else False
        has_confluence = rejection or structure_hold or sweep_confirmation

        # =======================
        # BULLISH SETUP
        # =======================
        fib_bull = fibonacci_retracement(impulse_end, impulse_start)
        in_bull_zone = fib_bull["0.618"] <= price <= fib_bull["0.5"]

        if (
            bias == "bullish"
            and not is_impulse
            and div == "bullish"
            and has_confluence
            and in_bull_zone
        ):
            df_m5.at[df_m5.index[-1], "signal"] = 1
            df_m5.at[df_m5.index[-1], "sl_distance"] = sl_dist
            df_m5.at[df_m5.index[-1], "tp_distance"] = tp_dist

        # =======================
        # BEARISH SETUP
        # =======================
        fib_bear = fibonacci_retracement(impulse_start, impulse_end)
        in_bear_zone = fib_bear["0.618"] <= price <= fib_bear["0.5"]

        if (
            bias == "bearish"
            and not is_impulse
            and div == "bearish"
            and has_confluence
            and in_bear_zone
        ):
            df_m5.at[df_m5.index[-1], "signal"] = -1
            df_m5.at[df_m5.index[-1], "sl_distance"] = sl_dist
            df_m5.at[df_m5.index[-1], "tp_distance"] = tp_dist
            if self.partial_tp_enabled:
                partial_tp_dist = sl_dist * self.partial_tp_rr
                df_m5.at[df_m5.index[-1], "partial_tp_distance"] = partial_tp_dist
                df_m5.at[df_m5.index[-1], "partial_fraction"] = self.partial_fraction

        return df_m5
