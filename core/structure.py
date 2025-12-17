from __future__ import annotations
import pandas as pd
from .indicators import ema, atr, is_impulse_candle


def regime_analysis(df_m5: pd.DataFrame, df_m15: pd.DataFrame) -> str:
    if df_m15 is None or df_m15.empty or len(df_m15) < 60:
        return "unknown"
    ema(df_m15, 50, name="ema_50")
    slope = float(df_m15["ema_50"].iloc[-1] - df_m15["ema_50"].iloc[-5])
    rng = float((df_m15["high"].iloc[-5:] - df_m15["low"].iloc[-5:]).mean())
    if rng <= 0:
        return "unknown"
    slope_ratio = abs(slope) / rng
    if slope_ratio > 0.5:
        return "trending"
    # Volatility expanded check on M5
    if df_m5 is not None and not df_m5.empty:
        atr(df_m5, 14, name="atr_14")
        avg_range = float((df_m5["high"] - df_m5["low"]).rolling(50).mean().iloc[-1])
        if avg_range > 0 and float(df_m5["atr_14"].iloc[-1]) > 1.8 * avg_range:
            return "volatility_expanded"
    return "ranging"


def find_swings(df: pd.DataFrame, lookback: int = 20) -> dict:
    sub = df.iloc[-lookback:]
    idx_high = sub["high"].idxmax()
    idx_low = sub["low"].idxmin()
    return {
        "swing_high_price": float(sub.loc[idx_high, "high"]),
        "swing_high_index": idx_high,
        "swing_low_price": float(sub.loc[idx_low, "low"]),
        "swing_low_index": idx_low,
    }


def label_structure(df: pd.DataFrame, lookback: int = 60) -> str:
    sub = df.iloc[-lookback:]
    highs = sub["high"].rolling(5).max()
    lows = sub["low"].rolling(5).min()
    last_high = float(highs.iloc[-1])
    prev_high = float(highs.iloc[-5])
    last_low = float(lows.iloc[-1])
    prev_low = float(lows.iloc[-5])
    if last_high > prev_high and last_low > prev_low:
        return "HH_HL"
    if last_high < prev_high and last_low < prev_low:
        return "LL_LH"
    return "mixed"


def detect_equal_levels(df: pd.DataFrame, tolerance_ratio: float = 0.0005, lookback: int = 40) -> dict:
    sub = df.iloc[-lookback:]
    avg_range = float((sub["high"] - sub["low"]).mean())
    tol = avg_range * tolerance_ratio if avg_range > 0 else 0.0
    highs = sub["high"].round(5)
    lows = sub["low"].round(5)
    eq_highs = any(abs(float(h) - float(highs.iloc[-1])) <= tol for h in highs.iloc[:-1])
    eq_lows = any(abs(float(l) - float(lows.iloc[-1])) <= tol for l in lows.iloc[:-1])
    return {"equal_highs": eq_highs, "equal_lows": eq_lows}


def mark_inducement_zones(df: pd.DataFrame, lookback: int = 60) -> dict:
    sub = df.iloc[-lookback:]
    pullback_high = float(sub["high"].iloc[-5:].max())
    pullback_low = float(sub["low"].iloc[-5:].min())
    return {"inducement_high": pullback_high, "inducement_low": pullback_low}


def get_last_impulse_leg(df: pd.DataFrame, direction: str, atr_period: int = 14, multiplier: float = 1.5) -> dict:
    """Get the last valid impulse leg with start and end points."""
    atr(df, atr_period, name=f"atr_{atr_period}")
    
    # Find all impulse legs
    impulses = []
    last_impulse = False
    
    for i in range(len(df)):
        row = df.iloc[i]
        is_imp = is_impulse_candle(row, float(df[f"atr_{atr_period}"].iloc[i]), multiplier)
        
        if direction == "bullish":
            dir_ok = row["close"] >= row["open"]
        else:
            dir_ok = row["close"] <= row["open"]
        
        if is_imp and dir_ok and not last_impulse:
            # Start of new impulse leg
            impulses.append({
                "start_index": i,
                "start_price": float(row["open"]),
                "end_index": i,
                "end_price": float(row["close"])
            })
            last_impulse = True
        elif is_imp and dir_ok and last_impulse and impulses:
            # Continue current impulse leg
            impulses[-1]["end_index"] = i
            impulses[-1]["end_price"] = float(row["close"])
        elif not is_imp:
            last_impulse = False
    
    if not impulses:
        return {"start_price": None, "end_price": None, "start_index": None, "end_index": None}
    
    # Return the last impulse leg
    last_leg = impulses[-1]
    return {
        "start_price": last_leg["start_price"],
        "end_price": last_leg["end_price"],
        "start_index": last_leg["start_index"],
        "end_index": last_leg["end_index"]
    }


def count_impulse_legs(df: pd.DataFrame, direction: str, atr_period: int = 14, multiplier: float = 1.5) -> int:
    atr(df, atr_period, name=f"atr_{atr_period}")
    legs = 0
    last_impulse = False
    for i in range(len(df) - 10, len(df)):
        row = df.iloc[i]
        is_imp = is_impulse_candle(row, float(df[f"atr_{atr_period}"].iloc[i]), multiplier)
        if direction == "bullish":
            dir_ok = row["close"] >= row["open"]
        else:
            dir_ok = row["close"] <= row["open"]
        if is_imp and dir_ok and not last_impulse:
            legs += 1
            last_impulse = True
        elif not is_imp:
            last_impulse = False
    return legs


def detect_bos_choch(df: pd.DataFrame, bias: str, lookback: int = 60) -> dict:
    sub = df.iloc[-lookback:]
    swings = find_swings(sub, lookback=min(lookback, len(sub)))
    last_close = float(sub["close"].iloc[-1])
    bos = False
    choch = False
    if bias == "bullish":
        bos = last_close > swings["swing_high_price"]
        choch = last_close < swings["swing_low_price"] and bos is False
    elif bias == "bearish":
        bos = last_close < swings["swing_low_price"]
        choch = last_close > swings["swing_high_price"] and bos is False
    return {"bos": bos, "choch": choch, **swings}


def is_structurally_broken(df_m5: pd.DataFrame, df_m15: pd.DataFrame) -> bool:
    if df_m5 is None or df_m5.empty or df_m15 is None or df_m15.empty:
        return True
    swings = find_swings(df_m5, lookback=40)
    recent_range = swings["swing_high_price"] - swings["swing_low_price"]
    if recent_range <= 0:
        return True
    # Broken if price whipsaws beyond both extremes within very few candles
    sub = df_m5.iloc[-15:]
    broke_high = sub["high"].max() > swings["swing_high_price"]
    broke_low = sub["low"].min() < swings["swing_low_price"]
    return broke_high and broke_low


def pivot_points(df: pd.DataFrame, left: int = 2, right: int = 2, lookback: int = 120) -> dict:
    sub = df.iloc[-lookback:]
    idx = list(sub.index)
    highs = sub["high"].values
    lows = sub["low"].values
    pivot_highs = []
    pivot_lows = []
    for i in range(left, len(sub) - right):
        wh = highs[i - left : i + right + 1]
        wl = lows[i - left : i + right + 1]
        if highs[i] == max(wh):
            pivot_highs.append((idx[i], float(highs[i])))
        if lows[i] == min(wl):
            pivot_lows.append((idx[i], float(lows[i])))
    last_ph_index = pivot_highs[-1][0] if pivot_highs else None
    last_ph_price = pivot_highs[-1][1] if pivot_highs else None
    last_pl_index = pivot_lows[-1][0] if pivot_lows else None
    last_pl_price = pivot_lows[-1][1] if pivot_lows else None
    return {
        "pivot_highs": pivot_highs,
        "pivot_lows": pivot_lows,
        "last_pivot_high_index": last_ph_index,
        "last_pivot_high_price": last_ph_price,
        "last_pivot_low_index": last_pl_index,
        "last_pivot_low_price": last_pl_price,
    }


def detect_bos_choch_pivots(df: pd.DataFrame, bias: str, lookback: int = 120, left: int = 2, right: int = 2) -> dict:
    piv = pivot_points(df, left=left, right=right, lookback=lookback)
    last_close = float(df["close"].iloc[-1])
    ph = piv.get("last_pivot_high_price")
    pl = piv.get("last_pivot_low_price")
    bos = False
    choch = False
    if bias == "bullish":
        bos = ph is not None and last_close > ph
        choch = pl is not None and last_close < pl and not bos
    elif bias == "bearish":
        bos = pl is not None and last_close < pl
        choch = ph is not None and last_close > ph and not bos
    return {
        "bos_pivot": bos,
        "choch_pivot": choch,
        "last_pivot_high_price": ph,
        "last_pivot_low_price": pl,
    }

def detect_trend_exhaustion(df: pd.DataFrame, bias: str, ema_period: int = 200, atr_period: int = 14, k: float = 2.0, max_legs: int = 3, max_trend_candles: int = 50, pullback_threshold: float = 0.5, impulse_multiplier: float = 1.5) -> dict:
    """Detect if the trend is exhausted based on multiple factors."""
    if df.empty or len(df) < max(ema_period, atr_period) + 10:
        return False

    ema(df, ema_period, name=f"ema_{ema_period}")
    atr(df, atr_period, name=f"atr_{atr_period}")

    last = df.iloc[-1]
    ema_val = float(last[f"ema_{ema_period}"])
    atr_val = float(last[f"atr_{atr_period}"])
    close = float(last["close"])

    # EMA distance
    ema_distance = abs(close - ema_val) > k * atr_val

    # Number of impulse legs
    legs = count_impulse_legs(df, bias if bias in ["bullish", "bearish"] else "bullish", atr_period, impulse_multiplier)
    legs_exceeded = legs >= max_legs

    # Time in trend: candles since last meaningful pullback
    trend_candles = 0
    for i in range(len(df)-1, 0, -1):
        candle = df.iloc[i]
        body = abs(candle["close"] - candle["open"])
        dir_match = (bias == "bullish" and candle["close"] < candle["open"]) or (bias == "bearish" and candle["close"] > candle["open"])
        if dir_match and body > pullback_threshold * atr_val:
            break
        trend_candles += 1
    time_exceeded = trend_candles >= max_trend_candles

    # Momentum decay: check if recent impulse sizes are declining
    impulse_sizes = []
    last_impulse = False
    for i in range(len(df)-1, max(0, len(df)-max_trend_candles*2), -1):
        row = df.iloc[i]
        is_imp = is_impulse_candle(row, float(df[f"atr_{atr_period}"].iloc[i]), impulse_multiplier)
        dir_ok = (bias == "bullish" and row["close"] >= row["open"]) or (bias == "bearish" and row["close"] <= row["open"])
        if is_imp and dir_ok:
            size = abs(row["close"] - row["open"])
            impulse_sizes.append(size)
            last_impulse = True
        elif last_impulse:
            last_impulse = False
    impulse_sizes = impulse_sizes[-3:]  # last 3
    declining = len(impulse_sizes) == 3 and impulse_sizes[2] > impulse_sizes[1] > impulse_sizes[0]

    # Exhausted if any two conditions are true
    conditions = [ema_distance, legs_exceeded, time_exceeded, declining]
    conditions = [ema_distance, legs_exceeded, time_exceeded, declining]
    reasons = ["ema_stretch", "impulse_count", "trend_duration", "momentum_decay"] if cond else []
    exhausted = sum(conditions) >= 2  # Require at least two factors for exhaustion
    return {"exhausted": exhausted, "reasons": [name for cond, name in zip(conditions, ["ema_stretch", "impulse_count", "trend_duration", "momentum_decay"]) if cond]}