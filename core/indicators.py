from __future__ import annotations
import pandas as pd
import numpy as np


def ema(df: pd.DataFrame, period: int, column: str = "close", name: str | None = None) -> pd.DataFrame:
    """Append Exponential Moving Average to DataFrame.

    Args:
        df: OHLCV DataFrame with at least the column provided.
        period: EMA span.
        column: Source column, default 'close'.
        name: Optional output column name. Defaults to 'ema_{period}'.

    Returns:
        DataFrame with EMA column appended.
    """
    if df is None or df.empty:
        return df
    name = name or f"ema_{period}"
    df[name] = df[column].ewm(span=period, adjust=False).mean()
    return df


def atr(df: pd.DataFrame, period: int, name: str | None = None) -> pd.DataFrame:
    """Append Average True Range to DataFrame.

    Args:
        df: OHLCV DataFrame with high, low, close.
        period: ATR period.
        name: Optional output column name. Defaults to 'atr_{period}'.
    """
    if df is None or df.empty:
        return df
    name = name or f"atr_{period}"
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    df[name] = tr.ewm(span=period, adjust=False).mean()
    return df


def rsi(df: pd.DataFrame, period: int, column: str = "close", name: str | None = None) -> pd.DataFrame:
    """Append Relative Strength Index to DataFrame.

    Uses Wilder's smoothing approximation with EMA.
    """
    if df is None or df.empty:
        return df
    name = name or f"rsi_{period}"
    delta = df[column].diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = pd.Series(gain, index=df.index).ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = pd.Series(loss, index=df.index).ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    df[name] = 100 - (100 / (1 + rs))
    return df


def stochastic(
    df: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
    smooth: int = 3,
    name_k: str | None = None,
    name_d: str | None = None,
) -> pd.DataFrame:
    """Append Stochastic Oscillator %K and %D to DataFrame.

    %K = smoothed( (close - low_min) / (high_max - low_min) * 100 )
    %D = SMA of %K over d_period
    """
    if df is None or df.empty:
        return df
    name_k = name_k or f"stoch_k_{k_period}"
    name_d = name_d or f"stoch_d_{d_period}"
    low_min = df["low"].rolling(window=k_period, min_periods=k_period).min()
    high_max = df["high"].rolling(window=k_period, min_periods=k_period).max()
    k_raw = 100 * (df["close"] - low_min) / (high_max - low_min + 1e-12)
    k = k_raw.rolling(window=smooth, min_periods=1).mean()
    d = k.rolling(window=d_period, min_periods=1).mean()
    df[name_k] = k
    df[name_d] = d
    return df


def fibonacci_retracement(high: float, low: float) -> dict:
    """Calculate Fibonacci retracement levels.

    Args:
        high: The high price point.
        low: The low price point.

    Returns:
        A dictionary of Fibonacci retracement levels.
    """
    levels = {
        "0.0": high,
        "0.236": high - (high - low) * 0.236,
        "0.382": high - (high - low) * 0.382,
        "0.5": high - (high - low) * 0.5,
        "0.618": high - (high - low) * 0.618,
        "0.786": high - (high - low) * 0.786,
        "1.0": low,
    }
    return levels


def is_impulse_candle(candle: pd.Series, atr_value: float, atr_multiplier: float) -> bool:
    """Determine if a candle is an impulse candle.

    An impulse candle has a body size greater than or equal to atr_multiplier * ATR.
    """
    body_size = abs(candle["open"] - candle["close"])
    return body_size >= (atr_multiplier * atr_value)


def rsi_divergence(df: pd.DataFrame, rsi_period: int) -> str:
    if df is None or df.empty or len(df) < rsi_period + 3:
        return "none"
    name = f"rsi_{rsi_period}"
    if name not in df.columns:
        rsi(df, rsi_period, name=name)
    sub = df.iloc[-10:]
    price_high_idx = sub["high"].idxmax()
    price_low_idx = sub["low"].idxmin()
    last_idx = sub.index[-1]
    try:
        ph1 = sub.loc[price_high_idx, "high"]
        rh1 = sub.loc[price_high_idx, name]
        ph2 = sub.loc[last_idx, "high"]
        rh2 = sub.loc[last_idx, name]
        if ph2 > ph1 and rh2 < rh1:
            return "bearish"
    except Exception:
        pass
    try:
        pl1 = sub.loc[price_low_idx, "low"]
        rl1 = sub.loc[price_low_idx, name]
        pl2 = sub.loc[last_idx, "low"]
        rl2 = sub.loc[last_idx, name]
        if pl2 < pl1 and rl2 > rl1:
            return "bullish"
    except Exception:
        pass
    return "none"