from __future__ import annotations
import json
import random
from pathlib import Path
import pandas as pd
from .indicators import atr


class StrategyRandom:
    """Random trading strategy for testing trade execution and risk management."""

    def __init__(self, strategies_path: Path | str, signal_probability: float = 0.3):
        """
        Initialize random strategy.
        
        Args:
            strategies_path: Path to strategies configuration file
            signal_probability: Probability of generating a signal (0.0 to 1.0)
        """
        self.params = json.loads(Path(strategies_path).read_text(encoding="utf-8"))
        self.signal_probability = signal_probability
        self.atr_period = int(self.params["atr"]["period"])
        self.atr_mult = float(self.params["atr"]["multiplier"])
        self.rr = float(self.params.get("risk_reward", 2.0))

    def _compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute basic indicators needed for risk management."""
        df = df.copy()
        df.set_index("timestamp", inplace=True)
        atr(df, self.atr_period, name=f"atr_{self.atr_period}")
        return df

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate random buy/sell signals for testing.
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            DataFrame with signal, sl_distance, and tp_distance columns
        """
        df = self._compute(df)
        atr_col = df[f"atr_{self.atr_period}"]
        
        # Generate random signals
        n_rows = len(df)
        signals = [0] * n_rows
        
        # Generate random signals with specified probability
        for i in range(n_rows):
            rand = random.random()
            if rand < self.signal_probability:
                # Randomly choose buy or sell
                signals[i] = 1 if random.random() < 0.5 else -1
        
        df["signal"] = signals
        
        # Set stop loss and take profit distances based on ATR
        df["sl_distance"] = self.atr_mult * atr_col
        df["tp_distance"] = self.rr * df["sl_distance"]
        
        return df

    def set_signal_probability(self, probability: float):
        """Update the signal probability for testing different scenarios."""
        self.signal_probability = max(0.0, min(1.0, probability))
        
    def get_strategy_info(self) -> dict:
        """Get information about the current strategy settings."""
        return {
            "strategy_type": "random",
            "signal_probability": self.signal_probability,
            "atr_period": self.atr_period,
            "atr_multiplier": self.atr_mult,
            "risk_reward": self.rr
        }