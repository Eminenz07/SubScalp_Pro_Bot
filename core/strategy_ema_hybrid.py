from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from .indicators import ema, atr, rsi, stochastic


class StrategyEMAHybrid:
    """EMA Trend + ATR Volatility + RSI + Stochastic hybrid strategy."""

    def __init__(self, strategies_path: Path | str):
        self.params = json.loads(Path(strategies_path).read_text(encoding="utf-8"))
        self.fast = int(self.params["ema"]["fast_period"])
        self.slow = int(self.params["ema"]["slow_period"])
        self.atr_period = int(self.params["atr"]["period"])
        self.atr_mult = float(self.params["atr"]["multiplier"])
        self.rsi_period = int(self.params["rsi"]["period"])
        self.rr = float(self.params.get("risk_reward", 2.0))
        self.k_period = int(self.params["stochastic"]["k_period"])
        self.d_period = int(self.params["stochastic"]["d_period"]) 
        self.smooth = int(self.params["stochastic"]["smooth"]) 

    def _compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.set_index("timestamp", inplace=True)
        ema(df, self.fast, name=f"ema_{self.fast}")
        ema(df, self.slow, name=f"ema_{self.slow}")
        atr(df, self.atr_period, name=f"atr_{self.atr_period}")
        rsi(df, self.rsi_period, name=f"rsi_{self.rsi_period}")
        stochastic(df, self.k_period, self.d_period, self.smooth,
                   name_k=f"stoch_k_{self.k_period}", name_d=f"stoch_d_{self.d_period}")
        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._compute(df)
        fema = df[f"ema_{self.fast}"]
        sema = df[f"ema_{self.slow}"]
        rsi_col = df[f"rsi_{self.rsi_period}"]
        k = df[f"stoch_k_{self.k_period}"]
        d = df[f"stoch_d_{self.d_period}"]
        atr_col = df[f"atr_{self.atr_period}"]

        bull_cross = (k.shift(1) < d.shift(1)) & (k > d)
        bear_cross = (k.shift(1) > d.shift(1)) & (k < d)

        buy = (fema > sema) & (rsi_col > 50) & bull_cross
        sell = (fema < sema) & (rsi_col < 50) & bear_cross

        df["signal"] = 0
        df.loc[buy, "signal"] = 1
        df.loc[sell, "signal"] = -1

        df["sl_distance"] = self.atr_mult * atr_col
        df["tp_distance"] = self.rr * df["sl_distance"]
        return df