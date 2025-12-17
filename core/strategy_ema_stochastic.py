from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from .indicators import ema, atr, stochastic


class StrategyEMAStochastic:
    """EMA + Stochastic Oscillator multi-timeframe strategy."""

    def __init__(self, config_path: Path | str):
        cfg = json.loads(Path(str(config_path)).read_text(encoding="utf-8"))
        self.ema_period = int(cfg["ema_period"])
        self.trend_ema_period = int(cfg["trend_ema_period"])
        self.trend_ema_long_period = int(cfg["trend_ema_long_period"])
        self.k = int(cfg["stochastic"]["k_period"])
        self.d = int(cfg["stochastic"]["d_period"])
        self.slow = int(cfg["stochastic"]["slowing"])
        self.overbought = float(cfg["stochastic"]["level_overbought"])
        self.oversold = float(cfg["stochastic"]["level_oversold"])
        self.atr_period = int(cfg["atr"]["period"])
        self.sl_mult = float(cfg["atr"]["sl_multiplier"])
        self.tp_mult = float(cfg["atr"]["tp_multiplier"])
        self.rr = float(cfg.get("risk_reward", 2.0))

    def load_params(self, config_path: Path | str):
        """Load parameters from JSON config."""
        cfg = json.loads(Path(str(config_path)).read_text(encoding="utf-8"))
        self.ema_period = int(cfg["ema_period"])
        self.trend_ema_period = int(cfg["trend_ema_period"])
        self.trend_ema_long_period = int(cfg["trend_ema_long_period"])
        self.k = int(cfg["stochastic"]["k_period"])
        self.d = int(cfg["stochastic"]["d_period"])
        self.slow = int(cfg["stochastic"]["slowing"])
        self.overbought = float(cfg["stochastic"]["level_overbought"])
        self.oversold = float(cfg["stochastic"]["level_oversold"])
        self.atr_period = int(cfg["atr"]["period"])
        self.sl_mult = float(cfg["atr"]["sl_multiplier"])
        self.tp_mult = float(cfg["atr"]["tp_multiplier"])
        self.rr = float(cfg.get("risk_reward", 2.0))

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute EMA, Stochastic, ATR and append to DataFrame."""
        df = df.copy()
        if 'timestamp' in df.columns:
            df.set_index('timestamp', inplace=True)
        ema(df, self.ema_period, name="ema_signal")
        atr(df, self.atr_period, name="atr")
        stochastic(df, k_period=self.k, d_period=self.d, smooth=self.slow,
                   name_k="stoch_k", name_d="stoch_d")
        return df

    def check_trend(self, higher_tf_df: pd.DataFrame) -> str:
        """Determine trend direction from higher timeframe data."""
        higher_tf_df = higher_tf_df.copy()
        if 'timestamp' in higher_tf_df.columns:
            higher_tf_df.set_index('timestamp', inplace=True)
        ema(higher_tf_df, self.trend_ema_period, name="ema50")
        ema(higher_tf_df, self.trend_ema_long_period, name="ema200")
        latest = higher_tf_df.iloc[-1]
        if latest["ema50"] > latest["ema200"]:
            return "bullish"
        elif latest["ema50"] < latest["ema200"]:
            return "bearish"
        return "neutral"

    def generate_signals(self, df: pd.DataFrame, trend_direction: str) -> pd.DataFrame:
        """Generate buy/sell signals based on multi-timeframe rules."""
        df = self.compute_indicators(df)
        k = df["stoch_k"]
        d = df["stoch_d"]
        atr_col = df["atr"]

        df["signal"] = 0
        df["sl_distance"] = 0.0
        df["tp_distance"] = 0.0
        df["trend"] = trend_direction

        if trend_direction == "bullish":
            # Buy: stochastic dips below oversold then crosses back above and close > EMA10
            dipped = (k <= self.oversold) | (d <= self.oversold)
            crossed_up = (k.shift(1) <= self.oversold) & (k > self.oversold)
            above_ema = df['close'] > df['ema_signal']
            buy = dipped & crossed_up & above_ema
            df.loc[buy, "signal"] = 1
        elif trend_direction == "bearish":
            # Sell: stochastic rises above overbought then crosses back below and close < EMA10
            rose = (k >= self.overbought) | (d >= self.overbought)
            crossed_down = (k.shift(1) >= self.overbought) & (k < self.overbought)
            below_ema = df['close'] < df['ema_signal']
            sell = rose & crossed_down & below_ema
            df.loc[sell, "signal"] = -1

        # Assign SL/TP distances where signals exist
        signaled = df["signal"] != 0
        df.loc[signaled, "sl_distance"] = self.sl_mult * atr_col[signaled]
        df.loc[signaled, "tp_distance"] = self.tp_mult * atr_col[signaled]

        return df