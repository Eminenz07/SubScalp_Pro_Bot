from __future__ import annotations
from typing import Dict, List, Callable, Type
import time
import pandas as pd


class DataHandler:
    """Utility to fetch and prepare OHLCV data from a connector."""

    def __init__(self, connector):
        self.connector = connector

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 500, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
        df = self.connector.get_historical_data(symbol, timeframe, limit, start_date, end_date)
        return self._clean(df)

    def fetch_multi_timeframe(self, symbol: str, timeframes: List[str], limit: int = 500) -> Dict[str, pd.DataFrame]:
        return {tf: self.fetch_ohlcv(symbol, tf, limit) for tf in timeframes}

    @staticmethod
    def _clean(df: pd.DataFrame) -> pd.DataFrame:
        """Basic cleaning and type normalization for OHLCV data."""
        if df is None or df.empty:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"]).astype(
                {"timestamp": "datetime64[ns]", "open": float, "high": float, "low": float, "close": float, "volume": float}
            )
        # Ensure correct columns
        cols = ["timestamp", "open", "high", "low", "close", "volume"]
        df = df[cols].copy()
        # Convert timestamp
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.dropna()
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df


def verify_mt5_connection(connector) -> bool:
    """Return True if MT5 is initialized and not in paper mode."""
    try:
        # Ensure connect() was called
        if hasattr(connector, "connect"):
            connector.connect()
        # Check connector has MT5 attributes
        if hasattr(connector, "paper_mode") and hasattr(connector, "connected"):
            return bool(getattr(connector, "connected", False)) and not bool(getattr(connector, "paper_mode", False))
        # Fallback: assume connected if connect succeeded
        return True
    except Exception:
        return False


def retry_on_exception(retries: int = 3, delay: float = 0.5, exceptions: tuple[Type[BaseException], ...] = (Exception,)):
    """Simple retry decorator for transient errors (e.g., MT5 connectivity hiccups)."""
    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(max(1, retries)):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_err = e
                    time.sleep(delay)
            if last_err:
                raise last_err
        return wrapper
    return decorator