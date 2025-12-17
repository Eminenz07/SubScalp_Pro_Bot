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


class OandaConnector(BaseConnector):
    """Oanda connector with paper-mode fallback.

    Supports live trading/data if token, account_id, and live flags are set in config["oanda"].
    """

    def __init__(self, config: Dict[str, Any], **kwargs: Any) -> None:
        self.config = config
        self.kwargs = kwargs
        self.connected: bool = False
        self.paper_mode: bool = True
        self._paper_positions: Dict[str, _PaperPosition] = {}
        self._exchange: Optional[Any] = None

        oanda_cfg = config.get("oanda") or {}
        access_token_env = oanda_cfg.get("access_token_env")
        account_id_env = oanda_cfg.get("account_id_env")
        self._token: Optional[str] = oanda_cfg.get("access_token") or (os.getenv(access_token_env) if access_token_env else None)
        self._account_id: Optional[str] = oanda_cfg.get("account_id") or (os.getenv(account_id_env) if account_id_env else None)
        self._practice: bool = bool(oanda_cfg.get("practice", True))  # Default to practice account
        self._live_data: bool = bool(oanda_cfg.get("live_data", False) and self._token and self._account_id and CCXT_AVAILABLE)
        self._live_trading: bool = bool(oanda_cfg.get("live_trading", False) and self._token and self._account_id and CCXT_AVAILABLE)
        self._equity_fallback: float = float(config.get("equity", 0.0))

    def connect(self) -> bool:
        try:
            if self._live_data or self._live_trading:
                if not CCXT_AVAILABLE:
                    raise RuntimeError("ccxt not available for live Oanda operations")
                hostname = 'fxpractice.oanda.com' if self._practice else 'fxtrade.oanda.com'
                self._exchange = ccxt.oanda({
                    'token': self._token,
                    'hostname': hostname,
                })
                self._exchange.v20_account_id = self._account_id
                # Test connection
                self._exchange.load_markets()
                self.paper_mode = False
                trade_logger.info(f"Oanda {'practice' if self._practice else 'live'} connection established.")
            else:
                trade_logger.info("Oanda running in paper mode.")
            self.connected = True
            return True
        except Exception as e:
            error_logger.error(f"Oanda connect error: {e}")
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
                error_logger.error(f"Oanda fetch_ohlcv error: {e}")
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
                if sl > 0 or tp > 0:
                    params["stopLossOnFill"] = {"price": sl} if sl > 0 else None
                    params["takeProfitOnFill"] = {"price": tp} if tp > 0 else None
                order = self._exchange.create_order(symbol, order_type, side, size, params=params)
                return str(order["id"])
            except Exception as e:
                error_logger.error(f"Oanda create_order error: {e}")
        # Paper mode
        order_id = str(uuid.uuid4())
        self._paper_positions[order_id] = _PaperPosition(order_id=order_id, symbol=symbol, side=side, size=size, sl=sl, tp=tp)
        return order_id

    def close_order(self, order_id: str) -> bool:
        if not self.connected:
            self.connect()
        if self._live_trading and self._exchange:
            try:
                self._exchange.cancel_order(order_id, params={"account_id": self._account_id})
                return True
            except Exception as e:
                error_logger.error(f"Oanda cancel_order error: {e}")
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
                account = self._exchange.fetch_balance(params={"account_id": self._account_id})
                equity = account["info"].get("NAV", 0.0)  # Oanda uses NAV for equity
                return {"equity": float(equity)}
            except Exception as e:
                error_logger.error(f"Oanda fetch_balance error: {e}")
        return {"equity": self._equity_fallback}