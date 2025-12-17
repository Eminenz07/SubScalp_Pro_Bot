from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from .indicators import ema, atr, rsi, fibonacci_retracement, is_impulse_candle
from .liquidity_sweep import detect_liquidity_sweep
from .multi_timeframe_analysis import get_trend_bias, is_choppy
from .structure import regime_analysis, detect_bos_choch, is_structurally_broken, count_impulse_legs, label_structure, detect_equal_levels, mark_inducement_zones, detect_bos_choch_pivots, detect_trend_exhaustion, get_last_impulse_leg
from .exhaustion_event import ExhaustionEventManager


class StrategyLSMC:
    """Liquidity Sweep Momentum Continuation (LSMC) trading strategy (Engine A)."""

    def __init__(self, config: dict, analytics=None):
        self.config = config
        self.strategy_settings = config["strategy_settings"]["engine_a_lsmc"]
        self.liquidity_sweep_settings = config["strategy_settings"]["liquidity_sweep"]
        self.htf_trend_timeframe = config["htf_trend_timeframe"]
        self.analytics = analytics

        self.impulse_atr_multiplier = self.strategy_settings["impulse_atr_multiplier"]
        self.ema_fast_period = self.strategy_settings["ema_fast_period"]
        self.ema_slow_period = self.strategy_settings["ema_slow_period"]
        self.rsi_period = self.strategy_settings["rsi_period"]
        self.fib_pullback_depth = self.strategy_settings["fib_pullback_depth"]
        self.tp_rr_min = self.strategy_settings["tp_rr_min"]
        self.tp_rr_max = self.strategy_settings["tp_rr_max"]
        self.event_manager = ExhaustionEventManager(max_age_minutes=60)  # Persistent exhaustion event manager

    def _compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.set_index("timestamp", inplace=True)
        ema(df, self.ema_fast_period, name=f"ema_{self.ema_fast_period}")
        ema(df, self.ema_slow_period, name=f"ema_{self.ema_slow_period}")
        atr(df, self.rsi_period, name=f"atr_{self.rsi_period}") # Using RSI period for ATR as a placeholder, adjust if needed
        rsi(df, self.rsi_period, name=f"rsi_{self.rsi_period}")
        return df

    def generate_signals(self, df_m5: pd.DataFrame, df_m15: pd.DataFrame) -> pd.DataFrame:
        df_m5 = self._compute_indicators(df_m5)
        df_m5["engine"] = "A"

        regime = self.regime_classifier.classify(df_m5, df_m15)
        if regime != "TRENDING":
            df_m5["signal"] = 0
            df_m5["sl_distance"] = 0.0
            df_m5["tp_distance"] = 0.0
            return df_m5

        trend_bias = get_trend_bias(df_m15, 50)

        bullish_sweep = detect_liquidity_sweep(
            df_m5,
            self.liquidity_sweep_settings["lookback_candles_min"],
            self.liquidity_sweep_settings["lookback_candles_max"],
            True,
        )
        bearish_sweep = detect_liquidity_sweep(
            df_m5,
            self.liquidity_sweep_settings["lookback_candles_min"],
            self.liquidity_sweep_settings["lookback_candles_max"],
            False,
        )

        df_m5["signal"] = 0
        df_m5["sl_distance"] = 0.0
        df_m5["tp_distance"] = 0.0
        df_m5["engine"] = "A"  # Mark as Engine A signal

        last = df_m5.iloc[-1]
        atr_col = f"atr_{self.rsi_period}"
        atr_val = float(last.get(atr_col, 0.0) or 0.0)
        if atr_val <= 0:
            return df_m5

        impulse = is_impulse_candle(last, atr_val, self.impulse_atr_multiplier)
        sl_dist = atr_val
        tp_dist = self.tp_rr_min * sl_dist

        if trend_bias == "bullish" and bullish_sweep and impulse:
            df_m5.at[df_m5.index[-1], "signal"] = 1
            df_m5.at[df_m5.index[-1], "sl_distance"] = sl_dist
            df_m5.at[df_m5.index[-1], "tp_distance"] = tp_dist
        elif trend_bias == "bearish" and bearish_sweep and impulse:
            df_m5.at[df_m5.index[-1], "signal"] = -1
            df_m5.at[df_m5.index[-1], "sl_distance"] = sl_dist
            df_m5.at[df_m5.index[-1], "tp_distance"] = tp_dist

        return df_m5

    def mark_engine_b_consumed(self, symbol: str, trade_id: str = None):
        self.event_manager.mark_engine_b_triggered(symbol, trade_id)
        df_m5 = self._compute_indicators(df_m5)

        trend_bias = get_trend_bias(df_m15, 50)
        if trend_bias == "neutral" or is_choppy(df_m15, 50):
            df_m5["signal"] = 0
            df_m5["sl_distance"] = 0.0
            df_m5["tp_distance"] = 0.0
            return df_m5

        bullish_sweep = detect_liquidity_sweep(
            df_m5,
            self.liquidity_sweep_settings["lookback_candles_min"],
            self.liquidity_sweep_settings["lookback_candles_max"],
            True,
        )
        bearish_sweep = detect_liquidity_sweep(
            df_m5,
            self.liquidity_sweep_settings["lookback_candles_min"],
            self.liquidity_sweep_settings["lookback_candles_max"],
            False,
        )

        df_m5["signal"] = 0
        df_m5["sl_distance"] = 0.0
        df_m5["tp_distance"] = 0.0

        last = df_m5.iloc[-1]
        atr_col = f"atr_{self.rsi_period}"
        atr_val = float(last.get(atr_col, 0.0) or 0.0)
        if atr_val <= 0:
            return df_m5

        impulse = is_impulse_candle(last, atr_val, self.impulse_atr_multiplier)
        sl_dist = atr_val
        tp_dist = self.tp_rr_min * sl_dist

        if trend_bias == "bullish" and bullish_sweep and impulse:
            df_m5.at[df_m5.index[-1], "signal"] = 1
            df_m5.at[df_m5.index[-1], "sl_distance"] = sl_dist
            df_m5.at[df_m5.index[-1], "tp_distance"] = tp_dist
        elif trend_bias == "bearish" and bearish_sweep and impulse:
            df_m5.at[df_m5.index[-1], "signal"] = -1
            df_m5.at[df_m5.index[-1], "sl_distance"] = sl_dist
            df_m5.at[df_m5.index[-1], "tp_distance"] = tp_dist

        return df_m5

    def evaluate_market(self, df_m5: pd.DataFrame, df_m15: pd.DataFrame, symbol: str) -> tuple[str, dict]:
        df_m5 = self._compute_indicators(df_m5)
        bias = get_trend_bias(df_m15, 50)
        if bias == "neutral" or is_choppy(df_m15, 50):
            return ("BLOCK_ALL_TRADES", {"reason": "htf_chop"})

        if is_structurally_broken(df_m5, df_m15):
            return ("BLOCK_ALL_TRADES", {"reason": "structure_broken"})
        struct_label = label_structure(df_m5)
        if struct_label == "mixed":
            return ("BLOCK_ALL_TRADES", {"reason": "structure_mixed"})

        atr_col = f"atr_{self.rsi_period}"
        last = df_m5.iloc[-1]
        atr_val = float(last.get(atr_col, 0.0) or 0.0)
        if atr_val <= 0:
            return ("BLOCK_ALL_TRADES", {"reason": "no_atr"})

        sweep_bull = detect_liquidity_sweep(
            df_m5,
            self.liquidity_sweep_settings["lookback_candles_min"],
            self.liquidity_sweep_settings["lookback_candles_max"],
            True,
        )
        sweep_bear = detect_liquidity_sweep(
            df_m5,
            self.liquidity_sweep_settings["lookback_candles_min"],
            self.liquidity_sweep_settings["lookback_candles_max"],
            False,
        )

        impulse = is_impulse_candle(last, atr_val, self.impulse_atr_multiplier)
        ema_fast = df_m5[f"ema_{self.ema_fast_period}"]
        ema_slow = df_m5[f"ema_{self.ema_slow_period}"]


        legs = count_impulse_legs(df_m5, bias, atr_period=self.rsi_period, multiplier=self.impulse_atr_multiplier)
        last_leg = get_last_impulse_leg(df_m5, bias, atr_period=self.rsi_period, multiplier=self.impulse_atr_multiplier)
        sr = regime_analysis(df_m5, df_m15)
        bos_choch = detect_bos_choch(df_m5, bias)
        piv = detect_bos_choch_pivots(df_m5, bias)
        equal_levels = detect_equal_levels(df_m5)
        inducement = mark_inducement_zones(df_m5)

        window = df_m5.iloc[-30:]
        swing_high = float(window["high"].max())
        swing_low = float(window["low"].min())
        ctx = {
            "atr": atr_val,
            "bias": bias,
            "swing_high": swing_high,
            "swing_low": swing_low,
            "impulse_legs": legs,
            "last_impulse_start": last_leg["start_price"],
            "last_impulse_end": last_leg["end_price"],
            "regime": sr,
            "bos": bos_choch.get("bos"),
            "choch": bos_choch.get("choch"),
            "bos_pivot": piv.get("bos_pivot"),
            "choch_pivot": piv.get("choch_pivot"),
            "last_pivot_high_price": piv.get("last_pivot_high_price"),
            "last_pivot_low_price": piv.get("last_pivot_low_price"),
            "structure": struct_label,
            "equal_highs": equal_levels.get("equal_highs"),
            "equal_lows": equal_levels.get("equal_lows"),
            "inducement_high": inducement.get("inducement_high"),
            "inducement_low": inducement.get("inducement_low"),
            "is_impulse": impulse,
            "sweep_bull": sweep_bull,
            "sweep_bear": sweep_bear,
        }

        if bias == "bullish":
            if ctx.get("choch_pivot"):
                return ("BLOCK_ALL_TRADES", {**ctx, "reason": "choch_pivot"})
            if not sweep_bull:
                return ("BLOCK_ALL_TRADES", {**ctx, "reason": "no_sweep"})
            exhaustion_info = detect_trend_exhaustion(df_m5, bias, ema_period=self.ema_slow_period, atr_period=self.rsi_period, k=2.0, max_legs=3, max_trend_candles=30, pullback_threshold=0.5, impulse_multiplier=self.impulse_atr_multiplier)
            trend_exhausted = exhaustion_info["exhausted"]
            ctx["trend_exhausted"] = trend_exhausted
            if trend_exhausted:
                ctx["exhaustion_type"] = ", ".join(exhaustion_info["reasons"])
            if impulse and not trend_exhausted and regime == "TRENDING":
                return ("ALLOW_ENGINE_A_TRADE", ctx)
            if trend_exhausted:
                event = self.event_manager.get_current_event(symbol)
                if not event:
                    # New exhaustion event
                    event = self.event_manager.create_exhaustion_event(
                        symbol=symbol,
                        exhaustion_type=ctx.get("exhaustion_type", "unknown"),
                        context=ctx
                    )
                    # Record in analytics
                    if self.analytics:
                        self.analytics.record_exhaustion_event(
                            symbol=symbol,
                            exhaustion_type=event.exhaustion_type,
                            event_id=event.exhaustion_id,
                            context=event.context
                        )
                ctx["exhaustion_event_id"] = event.exhaustion_id
                ctx["engine_b_consumed"] = event.engine_b_consumed
                if event.engine_b_consumed:
                    return ("BLOCK_ALL_TRADES", {**ctx, "reason": "exhaustion_consumed"})
                else:
                    return ("ALLOW_ENGINE_B_EVALUATION", {**ctx, "reason": "trend_exhausted"})
            else:
                return ("BLOCK_ALL_TRADES", {**ctx, "reason": "no_exhaustion"})

        if bias == "bearish":
            if ctx.get("choch_pivot"):
                return ("BLOCK_ALL_TRADES", {**ctx, "reason": "choch_pivot"})
            if not sweep_bear:
                return ("BLOCK_ALL_TRADES", {**ctx, "reason": "no_sweep"})
            exhaustion_info = detect_trend_exhaustion(df_m5, bias, ema_period=self.ema_slow_period, atr_period=self.rsi_period, k=2.0, max_legs=3, max_trend_candles=30, pullback_threshold=0.5, impulse_multiplier=self.impulse_atr_multiplier)
            trend_exhausted = exhaustion_info["exhausted"]
            ctx["trend_exhausted"] = trend_exhausted
            if trend_exhausted:
                ctx["exhaustion_type"] = ", ".join(exhaustion_info["reasons"])
            if impulse and not trend_exhausted and regime == "TRENDING":
                return ("ALLOW_ENGINE_A_TRADE", ctx)
            if trend_exhausted:
                event = self.event_manager.get_current_event(symbol)
                if not event:
                    # New exhaustion event
                    event = self.event_manager.create_exhaustion_event(
                        symbol=symbol,
                        exhaustion_type=ctx.get("exhaustion_type", "unknown"),
                        context=ctx
                    )
                    # Record in analytics
                    if self.analytics:
                        self.analytics.record_exhaustion_event(
                            symbol=symbol,
                            exhaustion_type=event.exhaustion_type,
                            event_id=event.exhaustion_id,
                            context=event.context
                        )
                ctx["exhaustion_event_id"] = event.exhaustion_id
                ctx["engine_b_consumed"] = event.engine_b_consumed
                if event.engine_b_consumed:
                    return ("BLOCK_ALL_TRADES", {**ctx, "reason": "exhaustion_consumed"})
                else:
                    return ("ALLOW_ENGINE_B_EVALUATION", {**ctx, "reason": "trend_exhausted"})
            else:
                return ("BLOCK_ALL_TRADES", {**ctx, "reason": "no_exhaustion"})

    def mark_engine_b_consumed(self, symbol: str):
        if symbol in self.exhaustion_states:
            self.exhaustion_states[symbol]["consumed"] = True

        return ("BLOCK_ALL_TRADES", {**ctx, "reason": "invalid"})