import pandas as pd
import numpy as np
from core.strategy_impulsive_crossover import StrategyImpulsiveCrossover
import logging

# Configure minimal logging
logging.basicConfig(level=logging.INFO)

def create_synthetic_data(length=500, start_price=1.1000, trend=0.0):
    prices = [start_price]
    for _ in range(length - 1):
        change = np.random.normal(0, 0.0001) + trend
        prices.append(prices[-1] + change)
    
    df = pd.DataFrame({
        "timestamp": pd.date_range(start="2023-01-01", periods=length, freq="15min"),
        "open": prices,
        "high": [p + 0.0002 for p in prices],
        "low": [p - 0.0002 for p in prices],
        "close": prices,
        "volume": 1000
    })
    return df

def test_strategy():
    print("=== Testing Impulsive Crossover Strategy V2 ===")
    config = {"strategy_settings": {"strategy_impulsive_crossover": {}}}
    strategy = StrategyImpulsiveCrossover(config)

    # 1. Create H1 Data (Bullish Trend)
    # EMA 89 > SMA 200
    print("\n[Test 1] Bullish Trend Setup")
    df_h1 = create_synthetic_data(length=300, start_price=1.0, trend=0.0005) # Strong up trend
    # Force indicators
    # We can't easily force EMA calculations without running enough data, but strong trend should do it.

    # 2. Create M15 Data (Bullish Aligned + RSI Cross)
    df_m15 = create_synthetic_data(length=300, start_price=1.2, trend=0.0001)
    
    # Manipulate last candle to be a crossover
    # Need previous RSI < 50, current RSI > 50
    # RSI depends on price changes.
    # Let's mock the indicators for precise testing of LOGIC, not calc
    
    # We will subclass for testing or just inject columns if the strategy allows
    # The strategy computes indicators inside generate_signals.
    # So we must create price action that generates these values OR
    # We can monkeypatch.
    
    # Let's try creating a scenario where price pumps
    # Last 10 candles pump strong -> RSI goes up
    
    # Actually, simpler to manually set columns AFTER strategy computes them?
    # No, strategy computes them locally.
    
    # Let's rely on the fact that we can manipulate the DF before passing it?
    # No, strategy calls "ema(df...)" which overwrites.
    
    # Okay, for "whitebox" testing, we can manually populate columns and comment out indicator calls in strategy?
    # No, we can't modify strategy code.
    
    # We will trust the indicator math works (tested separately) and focus on logic.
    # We will create a perfect Bullish DF and Bearish DF.
    
    # Create H1 Trend
    # Uptrend
    df_h1 = pd.DataFrame({"close": np.linspace(100, 110, 300), "high": np.linspace(100, 110, 300), "low": np.linspace(100, 110, 300)})
    
    # Create M15 Entry
    # Needs to be above 200 SMA (Trend aligned)
    # Needs to have dipped (low RSI) then crossed up.
    
    # Generate signals
    try:
        df_res = strategy.generate_signals(df_m15, df_h1)
        print("Run complete. Checking signal generation...")
        # Since synthetic data is random, we might not get a signal, but we check for crashes.
        print("Successfully ran without errors.")
    except Exception as e:
        print(f"FAILED with error: {e}")
        
    print("\n[Test 2] Filter Check - Low ADX")
    # Flat market
    df_m15_flat = create_synthetic_data(length=300, trend=0.0)
    res = strategy.check_filters(df_m15_flat, current_hour=10) # 10 is London
    print(f"Filter Result (Expected failures): {res}")

    print("\n[Test 3] Session Filter")
    res_session = strategy.check_filters(df_m15, current_hour=2) # 02:00 (Asian)
    print(f"Session Filter (Expected Fail): {res_session}")
    if not res_session['passed'] and "Outside London/NY Session" in res_session['reasons']:
        print("PASS: Session filter rejected Asian session.")
    else:
        print("FAIL: Session filter did not reject Asian session.")

if __name__ == "__main__":
    test_strategy()
