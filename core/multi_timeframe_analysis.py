import pandas as pd
from .indicators import ema

def get_trend_bias(df_htf: pd.DataFrame, ema_period: int) -> str:
    """Determines the trend bias based on the EMA on a higher timeframe.

    Args:
        df_htf: Higher timeframe OHLCV DataFrame.
        ema_period: The period for the EMA (e.g., 50).

    Returns:
        'bullish', 'bearish', or 'neutral'.
    """
    if df_htf is None or df_htf.empty or len(df_htf) < ema_period:
        return "neutral"

    df_htf = ema(df_htf.copy(), ema_period, name=f"ema_{ema_period}")
    current_ema = df_htf[f"ema_{ema_period}"].iloc[-1]
    previous_ema = df_htf[f"ema_{ema_period}"].iloc[-2]

    if current_ema > previous_ema:
        return "bullish"
    elif current_ema < previous_ema:
        return "bearish"
    else:
        return "neutral"

def is_choppy(df_htf: pd.DataFrame, ema_period: int, threshold: float = 0.0001) -> bool:
    """Checks if the higher timeframe EMA is flat or chopping.

    Args:
        df_htf: Higher timeframe OHLCV DataFrame.
        ema_period: The period for the EMA (e.g., 50).
        threshold: The percentage change threshold to consider EMA as chopping.

    Returns:
        True if the EMA is chopping, False otherwise.
    """
    if df_htf is None or df_htf.empty or len(df_htf) < ema_period:
        return True

    df_htf = ema(df_htf.copy(), ema_period, name=f"ema_{ema_period}")
    ema_series = df_htf[f"ema_{ema_period}"]

    # Calculate the percentage change of the EMA over a short period
    # For example, check the last 5 candles' EMA movement
    if len(ema_series) < 5:
        return True

    recent_ema_change = abs(ema_series.iloc[-1] - ema_series.iloc[-5]) / ema_series.iloc[-5]

    return recent_ema_change < threshold