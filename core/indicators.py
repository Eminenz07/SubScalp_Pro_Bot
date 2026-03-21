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


def sma(df: pd.DataFrame, period: int, column: str = "close", name: str | None = None) -> pd.DataFrame:
    """Append Simple Moving Average to DataFrame."""
    if df is None or df.empty:
        return df
    name = name or f"sma_{period}"
    df[name] = df[column].rolling(window=period).mean()
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


def adx(df: pd.DataFrame, period: int = 14, name: str | None = None) -> pd.DataFrame:
    """Append Average Directional Index (ADX) to DataFrame.
    
    Calculates signal strength. ADX < 25 often indicates choppy/ranging markets.
    """
    if df is None or df.empty:
        return df
    
    name = name or f"adx_{period}"
    
    # Needs High, Low, Close
    high = df["high"]
    low = df["low"]
    close = df["close"]
    
    # 1. Calculate TR and +/- DM
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    
    up_move = high.diff()
    down_move = -low.diff()
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)
    
    # 2. Smooth TR and +/- DM (Wilder's Smoothing)
    # alpha = 1/period
    tr_smooth = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/period, adjust=False).mean() / tr_smooth)
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, adjust=False).mean() / tr_smooth)
    
    # 3. DX
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-12)
    
    # 4. ADX (EMA of DX)
    df[name] = dx.ewm(alpha=1/period, adjust=False).mean()
    
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


def is_atr_expanding(df: pd.DataFrame, period: int = 14, lookback: int = 20, name: str | None = None) -> bool:
    """Check if current ATR is expanding (current > mean of last N periods).
    
    This indicates increasing volatility/momentum strength.
    
    Args:
        df: OHLCV DataFrame with high, low, close.
        period: ATR calculation period (default 14).
        lookback: Number of periods to calculate mean ATR (default 20).
        name: Optional ATR column name. If None, will compute ATR.
    
    Returns:
        True if current ATR > mean of last `lookback` ATR values.
    """
    if df is None or df.empty or len(df) < period + lookback:
        return False
    
    # Compute ATR if not already present
    atr_col = name or f"atr_{period}"
    if atr_col not in df.columns:
        atr(df, period, name=atr_col)
    
    # Get current ATR and mean of last N periods
    atr_values = df[atr_col].iloc[-(lookback + 1):]  # Last N+1 values
    current_atr = float(atr_values.iloc[-1])
    atr_mean = float(atr_values.iloc[:-1].mean())  # Mean of previous N
    
    return current_atr > atr_mean