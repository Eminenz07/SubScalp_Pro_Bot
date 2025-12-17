from __future__ import annotations
from typing import Any, Dict, Optional
from dataclasses import dataclass
import uuid
import os
import pandas as pd
from datetime import datetime, timezone

try:
    import ccxt  # type: ignore
    CCXT_AVAILABLE = True
except ImportError:
    ccxt = None  # type: ignore
    CCXT_AVAILABLE = False

from . import BaseConnector
from utils.logger import error_logger, trade_logger


@dataclass
class _PaperPosition:
    order_id: str
    symbol: str
    side: str  # "buy" or "sell"
    size: float
    sl: float
    tp: float
    entry_price: Optional[float] = None


class BinanceConnector(BaseConnector):
    """Binance connector with paper-mode fallback.

    Supports live trading/data if credentials and live flags are set in config["binance"].
    """

    def __init__(self, config: Dict[str, Any], **kwargs: Any) -> None:
        self.config = config
        self.kwargs = kwargs
        self.connected: bool = False
        self.paper_mode: bool = True
        self._paper_positions: Dict[str, _PaperPosition] = {}
        self._exchange: Optional[Any] = None

        binance_cfg = config.get("binance") or {}
        api_key_env = binance_cfg.get("api_key_env")
        api_secret_env = binance_cfg.get("api_secret_env")
        self._api_key: Optional[str] = binance_cfg.get("api_key") or (os.getenv(api_key_env) if api_key_env else None)
        self._api_secret: Optional[str] = binance_cfg.get("api_secret") or (os.getenv(api_secret_env) if api_secret_env else None)
        self._live_data: bool = bool(binance_cfg.get("live_data", False) and self._api_key and self._api_secret and CCXT_AVAILABLE)
        self._live_trading: bool = bool(binance_cfg.get("live_trading", False) and self._api_key and self._api_secret and CCXT_AVAILABLE)
        self._equity_fallback: float = float(config.get("equity", 0.0))

    def connect(self) -> bool:
        try:
            if self._live_data or self._live_trading:
                if not CCXT_AVAILABLE:
                    raise RuntimeError("ccxt not available for live Binance operations")
                self._exchange = ccxt.binance({
                    "apiKey": self._api_key,
                    "secret": self._api_secret,
                    "enableRateLimit": True,
                })
                # Test connection by fetching balance or markets
                self._exchange.load_markets()
                self.paper_mode = False
                trade_logger.info("Binance live connection established.")
            else:
                trade_logger.info("Binance running in paper mode.")
            self.connected = True
            return True
        except Exception as e:
            error_logger.error(f"Binance connect error: {e}")
            self.paper_mode = True
            self.connected = True  # Allow paper mode
            return True

    def get_historical_data(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        if not self.connected:
            self.connect()
        if self._live_data and self._exchange:
            try:
                ohlcv = self._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                return df.astype({"open": float, "high": float, "low": float, "close": float, "volume": float}).dropna()
            except Exception as e:
                error_logger.error(f"Binance fetch_ohlcv error: {e}")
        # Paper mode or fallback: empty dataframe
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"]).astype(
            {"timestamp": "datetime64[ns]", "open": float, "high": float, "low": float, "close": float, "volume": float}
        )

    def place_order(self, symbol: str, side: str, size: float, sl: float, tp: float) -> str:
        if not self.connected:
            self.connect()
        side = side.lower()
        if self._live_trading and self._exchange:
            try:
                order_type = "market"
                params = {}
                if sl > 0:
                    params["stopLossPrice"] = sl
                if tp > 0:
                    params["takeProfitPrice"] = tp
                order = self._exchange.create_order(symbol, order_type, side, size, params=params)
                return str(order["id"])
            except Exception as e:
                error_logger.error(f"Binance create_order error: {e}")
        # Paper mode
        order_id = str(uuid.uuid4())
        self._paper_positions[order_id] = _PaperPosition(order_id=order_id, symbol=symbol, side=side, size=size, sl=sl, tp=tp)
        return order_id

    def close_order(self, order_id: str) -> bool:
        if not self.connected:
            self.connect()
        if self._live_trading and self._exchange:
            try:
                # For simplicity, assume closing by id; may need position info
                # This is placeholder; actual implementation depends on order type (spot/futures)
                self._exchange.cancel_order(order_id)
                return True
            except Exception as e:
                error_logger.error(f"Binance cancel_order error: {e}")
                return False
        # Paper mode
        if order_id in self._paper_positions:
            del self._paper_positions[order_id]
            return True
        return False

    def get_account_info(self) -> Dict[str, Any]:
        if not self.connected:
            self.connect()
        if self._live_data and self._exchange:
            try:
                balance = self._exchange.fetch_balance()
                equity = balance["total"].get("USDT", 0.0)  # Assume USDT base
                return {"equity": float(equity)}
            except Exception as e:
                error_logger.error(f"Binance fetch_balance error: {e}")
        return {"equity": self._equity_fallback}