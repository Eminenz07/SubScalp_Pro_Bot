import pandas as pd

def detect_liquidity_sweep(df: pd.DataFrame, lookback_min: int, lookback_max: int, is_bullish: bool) -> bool:
    """Detects a liquidity sweep based on equal highs/lows, spike extremes, or range extremes.

    Args:
        df: OHLCV DataFrame.
        lookback_min: Minimum number of candles to look back for sweep detection.
        lookback_max: Maximum number of candles to look back for sweep detection.
        is_bullish: True for bullish sweep (looking for lows), False for bearish (looking for highs).

    Returns:
        True if a liquidity sweep is detected, False otherwise.
    """
    if len(df) < lookback_max:
        return False

    # Consider the most recent candle as the potential sweep candle
    current_candle = df.iloc[-1]

    # Define the lookback range for previous candles
    lookback_df = df.iloc[-(lookback_max + 1):-1] # Exclude current candle

    if is_bullish: # Looking for a sweep of lows
        # Condition 1: Spike extreme (current low breaks previous lows)
        previous_lows = lookback_df['low'].min()
        if current_candle['low'] < previous_lows:
            return True

        # Condition 2: Equal lows (current low is near previous lows)
        # This is a simplified check, can be made more robust with a tolerance
        if any(abs(current_candle['low'] - low) < (df['high'] - df['low']).mean() * 0.1 for low in lookback_df['low']):
            return True

    else: # Looking for a sweep of highs
        # Condition 1: Spike extreme (current high breaks previous highs)
        previous_highs = lookback_df['high'].max()
        if current_candle['high'] > previous_highs:
            return True

        # Condition 2: Equal highs (current high is near previous highs)
        # This is a simplified check, can be made more robust with a tolerance
        if any(abs(current_candle['high'] - high) < (df['high'] - df['low']).mean() * 0.1 for high in lookback_df['high']):
            return True

    return False