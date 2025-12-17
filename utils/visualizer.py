from __future__ import annotations
import matplotlib.pyplot as plt
import pandas as pd


def plot_signals(df: pd.DataFrame, title: str = "Signals"):
    """Plot price with buy/sell signals (expects columns: close, signal)."""
    plt.figure(figsize=(12, 6))
    plt.plot(df.index, df["close"], label="Close", color="black")
    buys = df[df["signal"] == 1]
    sells = df[df["signal"] == -1]
    plt.scatter(buys.index, buys["close"], marker="^", color="green", label="Buy")
    plt.scatter(sells.index, sells["close"], marker="v", color="red", label="Sell")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.show()