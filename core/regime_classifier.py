import pandas as pd
from .indicators import ema, atr

class RegimeClassifier:
    """Centralized regime classification module for market state determination."""

    def __init__(self, ema_period: int = 50, atr_period: int = 14, slope_threshold_high: float = 0.5, slope_threshold_low: float = 0.2, volatility_multiplier: float = 1.8, chop_threshold: float = 0.0001):
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.slope_threshold_high = slope_threshold_high  # For TRENDING
        self.slope_threshold_low = slope_threshold_low    # For TRANSITION vs RANGE
        self.volatility_multiplier = volatility_multiplier
        self.chop_threshold = chop_threshold

    def classify(self, df_m5: pd.DataFrame, df_m15: pd.DataFrame) -> str:
        """
        Classify the market regime based on multi-timeframe analysis.
        
        Returns one of: 'TRENDING', 'RANGE', 'TRANSITION', 'VOLATILITY_SPIKE'
        """
        if df_m15.empty or len(df_m15) < self.ema_period + 5:
            return 'RANGE'  # Default to safe regime

        # Compute EMA on M15
        ema(df_m15, self.ema_period, name=f"ema_{self.ema_period}")
        ema_series = df_m15[f"ema_{self.ema_period}"]

        # Slope calculation (last 5 periods)
        slope = float(ema_series.iloc[-1] - ema_series.iloc[-5])
        rng = float((df_m15["high"].iloc[-5:] - df_m15["low"].iloc[-5:]).mean())
        if rng <= 0:
            return 'RANGE'
        slope_ratio = abs(slope) / rng

        # Check for volatility spike on M5
        if not df_m5.empty:
            atr(df_m5, self.atr_period, name=f"atr_{self.atr_period}")
            avg_range = float((df_m5["high"] - df_m5["low"]).rolling(50).mean().iloc[-1])
            current_atr = float(df_m5[f"atr_{self.atr_period}"].iloc[-1])
            if avg_range > 0 and current_atr > self.volatility_multiplier * avg_range:
                return 'VOLATILITY_SPIKE'

        # Choppiness check
        recent_ema_change = abs(ema_series.iloc[-1] - ema_series.iloc[-5]) / ema_series.iloc[-5]
        is_choppy_market = recent_ema_change < self.chop_threshold

        # Regime classification
        if slope_ratio > self.slope_threshold_high and not is_choppy_market:
            return 'TRENDING'
        elif slope_ratio > self.slope_threshold_low and not is_choppy_market:
            return 'TRANSITION'
        else:
            return 'RANGE'
