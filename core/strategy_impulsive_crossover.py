from __future__ import annotations

import logging
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any, Optional

from .indicators import ema, sma, adx, atr, rsi

trade_logger = logging.getLogger("trades")

class StrategyImpulsiveCrossover:
    """
    Impulsive Crossover Strategy V2 (Rule-Based)
    
    Timeframes:
    - H1: Trend Confirmation (89 EMA vs 200 SMA)
    - M15: Execution (RSI Crossover + EMA Alignment)
    
    Filters:
    - ADX > 25 (Choppy Market Filter)
    - SMA Slope Check (Flat Market Filter)
    - ATR Volatility Check
    - Session Filter (London/NY Only)
    """

    def __init__(self, config: dict):
        self.config = config
        self.settings = config.get("strategy_settings", {}).get("impulsive_crossover", {})
        
        # Parameters
        self.ema_period = 89
        self.sma_period = 200
        self.rsi_period = 14
        self.adx_period = 14
        self.atr_period = 14
        
        self.adx_threshold = 25
        self.slope_threshold = self.settings.get("slope_threshold", 0.05)  
        
        # Risk
        self.risk_reward_ratio = 1.5
        self.tp2_ratio = 3.0
        
        # Session times (UTC assumed, user customizable)
        self.london_start = 8   # 08:00
        self.ny_end = 21       # 21:00
        
        # --- REGIME LOCKOUT SYSTEM ---
        self.NORMAL_TRADING = "NORMAL_TRADING"
        self.REGIME_LOCKED = "REGIME_LOCKED"
        self.regime_state = self.NORMAL_TRADING
        self.consecutive_losses = 0
        self.lockout_triggered_at = 0
        self.lockout_candle_count = 0
        self.lockout_slope_sign = 0  # +1 or -1
        self.ema_slope_stable_count = 0
        
        # Lockout parameters from config
        self.param_loss_streak_limit = self.settings.get("loss_streak_limit", 3)
        self.param_slope_stability_count = self.settings.get("lockout_slope_stability_count", 3)
        
        # Lockout metrics
        self.lockout_metrics = {
            "total_lockouts": 0,
            "total_lockout_candles": 0,
            "longest_lockout": 0,
            "signals_blocked": 0,
            "unlock_reasons": {}
        }
        
        # --- TRAILING STOP PARAMETERS ---
        self.trail_activation_r = self.settings.get("trail_activation_r", 1.75)
        self.trail_weak_multiplier = self.settings.get("trail_weak_multiplier", 1.2)
        self.trail_strong_multiplier = self.settings.get("trail_strong_multiplier", 1.6)
        self.strong_regime_slope_multiplier = self.settings.get("strong_regime_slope_multiplier", 2.0)
        
        # --- STATISTICS TRACKING ---
        self.stats = {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "be_exits": 0
        }
        
        self.rejection_stats = {
            "adx_too_low": 0,
            "slope_flat": 0,
            "outside_session": 0,
            "regime_locked": 0,
            "no_trend": 0
        }

    def check_trend(self, df_h1: pd.DataFrame) -> str:
        """Determines H1 trend bias."""
        if df_h1 is None or len(df_h1) < max(self.sma_period, self.ema_period):
            return "neutral"
            
        ema(df_h1, self.ema_period, name="ema_89")
        sma(df_h1, self.sma_period, name="sma_200")
        
        last = df_h1.iloc[-1]
        
        if last["ema_89"] > last["sma_200"]:
            return "bullish"
        elif last["ema_89"] < last["sma_200"]:
            return "bearish"
            
        return "neutral"

    def _slope_sign(self, slope: float) -> int:
        """Return +1 for positive slope, -1 for negative."""
        return 1 if slope > 0 else -1

    def update_regime_state(self, df_h1: pd.DataFrame, current_time: int):
        """Update regime lockout state based on consecutive losses and H1 EMA slope.
        
        IMPORTANT: Call this ONCE per candle to avoid double-evaluation bug.
        """
        if df_h1 is None or len(df_h1) < max(self.ema_period, self.sma_period):
            return
        
        # Calculate H1 EMA slope
        from .indicators import ema
        ema(df_h1, self.ema_period, name="ema_89")
        
        if len(df_h1) < 6:
            return
            
        ema_current = float(df_h1["ema_89"].iloc[-1])
        ema_prev = float(df_h1["ema_89"].iloc[-6])
        ema_slope_1h = ema_current - ema_prev
        
        # --- CHECK LOCKOUT CONDITIONS ---
        if self.regime_state == self.REGIME_LOCKED:
            # Increment lockout duration
            self.lockout_candle_count += 1
            self.lockout_metrics["total_lockout_candles"] += 1
            
            # Check if slope sign has flipped
            current_slope_sign = self._slope_sign(ema_slope_1h)
            
            if current_slope_sign != self.lockout_slope_sign:
                # Slope flipped! Start counting stable candles
                self.ema_slope_stable_count += 1
            else:
                # Reset stability counter if slope reverted
                self.ema_slope_stable_count = 0
            
            # UNLOCK if slope has been stable for N candles
            if self.ema_slope_stable_count >= self.param_slope_stability_count:
                met = "slope_sign_flip"
                self.lockout_metrics["unlock_reasons"][met] = self.lockout_metrics["unlock_reasons"].get(met, 0) + 1
                self.lockout_metrics["longest_lockout"] = max(
                    self.lockout_metrics["longest_lockout"], self.lockout_candle_count
                )
                
                trade_logger.info(
                    f"[REGIME UNLOCK] duration={self.lockout_candle_count} candles | reset_by={met}"
                )
                
                # Unlock
                self.regime_state = self.NORMAL_TRADING
                self.consecutive_losses = 0
                self.lockout_triggered_at = 0
                self.lockout_candle_count = 0
                self.ema_slope_stable_count = 0
        
        else:
            # NORMAL_TRADING - check if we should enter lockout
            if self.consecutive_losses >= self.param_loss_streak_limit:
                self.regime_state = self.REGIME_LOCKED
                self.lockout_triggered_at = current_time
                self.lockout_candle_count = 0
                self.lockout_metrics["total_lockouts"] += 1
                
                self.lockout_slope_sign = self._slope_sign(ema_slope_1h)
                self.ema_slope_stable_count = 0
                
                trade_logger.warning(
                    f"[REGIME LOCKOUT] triggered_after={self.consecutive_losses} losses | "
                    f"lockout_sign={self.lockout_slope_sign}"
                )

    def trading_allowed(self) -> bool:
        """Check if trading is allowed (not in lockout)."""
        if self.regime_state == self.REGIME_LOCKED:
            self.lockout_metrics["signals_blocked"] += 1
            return False
        return True

    def check_filters(self, df_m15: pd.DataFrame, current_hour: int) -> dict:
        """Checks execution filters (ADX, Slope, Session)."""
        reasons = []
        passed = True
        
        # 1. Session Filter
        if not (self.london_start <= current_hour < self.ny_end):
             reasons.append("Outside London/NY Session")
             passed = False

        if df_m15 is None or len(df_m15) < max(self.sma_period, self.adx_period):
            return {"passed": False, "reasons": ["Insufficient Data"]}

        # 2. Chop Filter (ADX)
        adx(df_m15, self.adx_period, name="adx")
        last = df_m15.iloc[-1]
        if last["adx"] < self.adx_threshold:
            reasons.append(f"ADX Too Low ({last['adx']:.1f} < {self.adx_threshold})")
            passed = False
            
        # 3. Flat Market Filter (SMA Slope)
        # Calculate slope over last 5 candles
        sma(df_m15, self.sma_period, name="sma_200")
        prev_sma = df_m15["sma_200"].iloc[-6]
        curr_sma = df_m15["sma_200"].iloc[-1]
        
        # Normalize slope implies price change percentage over 5 bars
        slope = (curr_sma - prev_sma) / prev_sma * 100
        if abs(slope) < 0.005: # Very flat
            reasons.append("SMA Slope Flat")
            passed = False
            
        return {"passed": passed, "reasons": reasons}

    def generate_signals(self, df_m15: pd.DataFrame, df_h1: pd.DataFrame) -> pd.DataFrame:
        """Generates trade signals based on H1 trend and M15 entry."""
        if df_m15 is None or df_m15.empty:
            return df_m15
            
        df_m15 = df_m15.copy()
        df_m15["signal"] = 0
        df_m15["sl_distance"] = 0.0
        df_m15["tp_distance"] = 0.0
        
        # Compute indicators
        ema(df_m15, self.ema_period, name="ema_89")
        sma(df_m15, self.sma_period, name="sma_200")
        rsi(df_m15, self.rsi_period, name="rsi")
        atr(df_m15, self.atr_period, name="atr")
        
        # Current States
        current_time = df_m15.index[-1] if isinstance(df_m15.index, pd.DatetimeIndex) else pd.to_datetime(df_m15["timestamp"].iloc[-1])
        current_hour = current_time.hour
        current_timestamp = int(current_time.timestamp() * 1000) if isinstance(current_time, datetime) else current_time
        
        # --- UPDATE REGIME STATE (ONCE PER CANDLE) ---
        self.update_regime_state(df_h1, current_timestamp)
        
        # --- CHECK REGIME LOCKOUT ---
        if not self.trading_allowed():
            self.rejection_stats["regime_locked"] += 1
            return df_m15
        
        # Check Filters
        filters = self.check_filters(df_m15, current_hour)
        if not filters["passed"]:
            # Track rejection reasons
            for reason in filters["reasons"]:
                if "ADX" in reason:
                    self.rejection_stats["adx_too_low"] += 1
                elif "Slope" in reason:
                    self.rejection_stats["slope_flat"] += 1
                elif "Session" in reason:
                    self.rejection_stats["outside_session"] += 1
            return df_m15

        # Check Trend
        trend = self.check_trend(df_h1)
        if trend == "neutral":
            self.rejection_stats["no_trend"] += 1
            return df_m15

        # Signal Logic
        # We need crossover detection, so we look at previous candle too
        curr = df_m15.iloc[-1]
        prev = df_m15.iloc[-2]
        
        atr_val = curr["atr"]
        if atr_val <= 0:
            return df_m15

        # --- LONG ---
        if trend == "bullish":
            # M15 Alignment: 89 > 200
            aligned = curr["ema_89"] > curr["sma_200"]
            
            # RSI Crossover: Crossed ABOVE 50
            rsi_cross = prev["rsi"] <= 50 and curr["rsi"] > 50
            
            if aligned and rsi_cross:
                df_m15.at[df_m15.index[-1], "signal"] = 1
                sl_dist = 1.5 * atr_val
                df_m15.at[df_m15.index[-1], "sl_distance"] = sl_dist
                df_m15.at[df_m15.index[-1], "tp_distance"] = sl_dist * self.risk_reward_ratio

        # --- SHORT ---
        elif trend == "bearish":
            # M15 Alignment: 89 < 200
            aligned = curr["ema_89"] < curr["sma_200"]
            
            # RSI Crossover: Crossed BELOW 50
            rsi_cross = prev["rsi"] >= 50 and curr["rsi"] < 50
            
            if aligned and rsi_cross:
                df_m15.at[df_m15.index[-1], "signal"] = -1
                sl_dist = 1.5 * atr_val
                df_m15.at[df_m15.index[-1], "sl_distance"] = sl_dist
                df_m15.at[df_m15.index[-1], "tp_distance"] = sl_dist * self.risk_reward_ratio

        return df_m15

    def record_trade_result(self, trade_result: str):
        """Record trade result for statistics tracking.
        
        Args:
            trade_result: "win", "loss", or "be" (break-even)
        """
        self.stats["trades"] += 1
        
        if trade_result == "win":
            self.stats["wins"] += 1
            self.consecutive_losses = 0  # Reset on win
        elif trade_result == "loss":
            self.stats["losses"] += 1
            self.consecutive_losses += 1  # Increment on loss
        elif trade_result == "be":
            self.stats["be_exits"] += 1
            self.consecutive_losses = 0  # BE doesn't count as loss

    def print_statistics(self):
        """Print performance statistics to console."""
        print("=" * 60)
        print("IMPULSIVE CROSSOVER STRATEGY STATISTICS")
        print("=" * 60)
        print(f"Total Trades: {self.stats['trades']}")
        print(f"Wins:        {self.stats['wins']}")
        print(f"Losses:      {self.stats['losses']}")
        print(f"BE Exits:    {self.stats['be_exits']}")
        print("-" * 60)
        print("LOCKOUT METRICS")
        print("-" * 60)
        print(f"Total Lockouts:        {self.lockout_metrics['total_lockouts']}")
        print(f"Total Lockout Candles: {self.lockout_metrics['total_lockout_candles']}")
        print(f"Longest Lockout:       {self.lockout_metrics['longest_lockout']}")
        print(f"Signals Blocked:       {self.lockout_metrics['signals_blocked']}")
        if self.lockout_metrics["unlock_reasons"]:
            print("\nUnlock Reason Distribution:")
            for k, v in sorted(self.lockout_metrics["unlock_reasons"].items(), key=lambda x: x[1], reverse=True):
                print(f"  {k}: {v}")
        print("-" * 60)
        print("REJECTION STATS")
        print("-" * 60)
        for k, v in self.rejection_stats.items():
            print(f"{k:>15}: {v}")
        print("=" * 60 + "\n")
