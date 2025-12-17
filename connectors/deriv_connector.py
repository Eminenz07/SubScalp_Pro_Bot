from __future__ import annotations
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import uuid
import math
import os
import json
import websocket
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import socket
from datetime import datetime, timezone
from websocket import create_connection
import time
import threading

from . import BaseConnector
from utils.logger import trade_logger, error_logger
from utils import logger  # assuming error_logger is from there


@dataclass
class _PaperPosition:
    order_id: str
    symbol: str
    side: str  # "buy" or "sell"
    size: float
    sl: float
    tp: float
    entry_price: Optional[float] = None


class DerivConnector(BaseConnector):
    """Deriv connector with a robust paper-mode for synthetic indices testing.

    Public API matches BaseConnector:
      - connect() -> bool
      - get_historical_data(symbol, timeframe, limit) -> pd.DataFrame["timestamp","open","high","low","close","volume"]
      - place_order(...) -> str order_id
      - close_order(order_id) -> bool
      - get_account_info() -> Dict[str, Any] containing at least {"equity": float}

    NOTE: Live Deriv usage typically relies on the WebSocket API; this implementation
    focuses on paper-mode to enable end-to-end strategy and risk testing without
    external dependencies or credentials. Live data and balance retrieval are supported
    when credentials are provided; order execution remains paper unless explicitly enabled.
    """

    def __init__(self, config: Dict[str, Any], **kwargs: Any) -> None:
        self.config = config
        self.kwargs = kwargs
        self.connected: bool = False
        self.paper_mode: bool = True  # default to paper trading
        self._paper_positions: Dict[str, _PaperPosition] = {}
        self._orders: Dict[str, Dict[str, Any]] = {}
        self._live_orders: Dict[str, Dict[str, Any]] = {}

        deriv_cfg = (config.get("deriv") or {})
        app_id_env = deriv_cfg.get("app_id_env")
        api_token_env = deriv_cfg.get("api_token_env")
        # Prefer explicit values, otherwise read from environment using *_env keys
        self._app_id: Optional[str] = deriv_cfg.get("app_id") or (os.getenv(app_id_env) if app_id_env else None)
        self._api_token: Optional[str] = deriv_cfg.get("api_token") or (os.getenv(api_token_env) if api_token_env else None)
        # toggles
        self._live_data: bool = bool(deriv_cfg.get("live_data", False) and self._app_id and self._api_token)
        self._live_trading: bool = bool(deriv_cfg.get("live_trading", False) and self._app_id and self._api_token)
        # equity for paper-mode fallback
        self._equity_fallback: float = float(config.get("equity", 0.0))
        self._ws: Optional[websocket.WebSocket] = None
        self._ping_thread = None
        self._running = False

    # ---- BaseConnector API ----
    def connect(self) -> bool:
        try:
            self.connected = True
            self._running = True
            self._ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
            self._ping_thread.start()
            if self._app_id and self._api_token:
                trade_logger.info(f"Deriv credentials found. Live data: {self._live_data}, Live trading: {self._live_trading}")
                try:
                    socket.getaddrinfo('ws.derivws.com', 443)
                    self._ws = self._ws_authorized_connection()
                    trade_logger.info("Persistent Deriv WebSocket connection established.")
                except Exception as e:
                    error_logger.warning(f"Cannot establish persistent connection to Deriv API: {e}. Falling back to paper mode.")
                    self._live_data = False
                    self._live_trading = False
            else:
                trade_logger.info("DerivConnector running in paper mode (no credentials supplied).")
            return True
        except Exception as e:
            error_logger.error(f"Deriv connect error: {e}")
            self.connected = False
            return False

    def get_historical_data(self, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
        # Create empty dataframe for fallback
        empty_df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"]).astype(
            {"timestamp": "datetime64[ns]", "open": float, "high": float, "low": float, "close": float, "volume": float}
        )
        
        # Check if we're in offline mode
        if not self._live_data:
            trade_logger.info(f"Running in offline mode. Generating synthetic data for {symbol} {timeframe}")
            return self._generate_synthetic_ohlcv(symbol, timeframe, limit)
            
        # Try to get live data
        try:
            # Only try to connect if not already connected
            if not self.connected:
                try:
                    self.connect()
                except (ConnectionError, socket.gaierror) as e:
                    error_logger.warning(f"Network connection failed: {e}. Using synthetic data for {symbol}.")
                    return self._generate_synthetic_ohlcv(symbol, timeframe, limit)
                    
            # Try to get live candles
            try:
                df = self._get_live_candles(symbol, timeframe, limit)
                if df is not None and not df.empty:
                    return df
                else:
                    trade_logger.info(f"No live data for {symbol} {timeframe}; using synthetic data.")
                    return self._generate_synthetic_ohlcv(symbol, timeframe, limit)
            except socket.gaierror as e:
                error_logger.warning(f"Network error fetching data for {symbol}: {e}. Falling back to synthetic data.")
                return self._generate_synthetic_ohlcv(symbol, timeframe, limit)
            except Exception as e:
                error_logger.error(f"Error getting live candles for {symbol} {timeframe}: {e}")
                return self._generate_synthetic_ohlcv(symbol, timeframe, limit)
                
        except Exception as e:
            error_logger.error(f"Deriv get_historical_data error for {symbol} {timeframe}: {e}")
            return self._generate_synthetic_ohlcv(symbol, timeframe, limit)

    def place_order(self, symbol: str, side: str, size: float, sl: float, tp: float) -> str:
        if not self.connected:
            self.connect()
        side = side.lower()
        
        # Debug the input values
        trade_logger.debug(f"place_order received: symbol={symbol}, side={side}, size={size}, sl={sl} (type: {type(sl)}), tp={tp} (type: {type(tp)})")
        
        if self._live_trading:
            trade_logger.info(f"Attempting live trade placement for {symbol} {side} size={size}")
            for attempt in range(2):
                try:
                    ws = self._get_ws()
                    if 'frx' in symbol.lower():
                        contract_type = 'CALL' if side == 'buy' else 'PUT'
                        proposal_req = {
                            "proposal": 1,
                            "amount": float(size),
                            "basis": "stake",
                            "contract_type": contract_type,
                            "currency": "USD",
                            "symbol": symbol,
                            "duration": 5,
                            "duration_unit": "m",  # Changed from "d" to "m" (minutes) for better compatibility
                            "subscribe": 0,  # Explicitly set to 0 to avoid API defaulting to 1
                        }
                    else:
                        contract_type = 'CALL' if side == 'buy' else 'PUT'  # Changed from MULTIPLIERS to CALL/PUT
                        proposal_req = {
                            "proposal": 1,
                            "amount": float(size),
                            "basis": "stake",
                            "contract_type": contract_type,
                            "currency": "USD",
                            "symbol": symbol,
                            "duration": 5,
                            "duration_unit": "m",  # Changed from "d" to "m" (minutes)
                            "subscribe": 0,  # Explicitly set to 0 to avoid API defaulting to 1
                        }
                    limit_order = {}
                    if sl > 0:
                        # Ensure sl is a simple number, not an object
                        sl_value = float(sl)
                        if not math.isfinite(sl_value):
                            error_logger.warning(f"Invalid SL value: {sl}, using 0")
                            sl_value = 0.0
                        limit_order["stop_loss"] = sl_value
                    if tp > 0:
                        # Ensure tp is a simple number, not an object
                        tp_value = float(tp)
                        if not math.isfinite(tp_value):
                            error_logger.warning(f"Invalid TP value: {tp}, using 0")
                            tp_value = 0.0
                        limit_order["take_profit"] = tp_value
                    if limit_order:
                        proposal_req["limit_order"] = limit_order
                        trade_logger.debug(f"Setting limit_order: {limit_order}")
                    
                    # Debug the complete request
                    trade_logger.debug(f"Sending proposal request: {json.dumps(proposal_req, indent=2)}")
                    ws.send(json.dumps(proposal_req))
                    resp = json.loads(ws.recv())
                    if "error" in resp:
                        raise RuntimeError(str(resp["error"]))
                    proposal_id = resp.get("proposal", {}).get("id")
                    if not proposal_id:
                        raise RuntimeError("No proposal_id in response")
                    buy_req = {"buy": proposal_id, "price": float(size)}
                    ws.send(json.dumps(buy_req))
                    buy_resp = json.loads(ws.recv())
                    if "error" in buy_resp:
                        error_logger.error(f"Buy response error: {buy_resp['error']}")
                        raise RuntimeError(str(buy_resp["error"]))
                    contract_id = buy_resp.get("buy", {}).get("contract_id")
                    if not contract_id:
                        raise RuntimeError("No contract_id in buy response")
                    self._live_orders[str(contract_id)] = {"symbol": symbol, "side": side, "size": size, "sl": sl, "tp": tp}
                    return contract_id
                except Exception as e:
                    error_logger.error(f"Deriv live place_order error on attempt {attempt+1}: {str(e)}.")
                    self._ws = None
                    if attempt == 1:
                        error_logger.error("Failed after retry. Falling back to paper.")
                        break
            # Paper mode
            order_id = str(uuid.uuid4())
            self._paper_positions[order_id] = _PaperPosition(
                order_id=order_id, symbol=symbol, side=side, size=float(size), sl=float(sl), tp=float(tp)
            )
            return order_id

    def close_order(self, order_id: str) -> bool:
        if not self.connected:
            self.connect()
        # Convert order_id to string for dictionary lookup since _live_orders uses string keys
        order_id_str = str(order_id)
        if order_id_str in self._live_orders:
            for attempt in range(2):
                try:
                    ws = self._get_ws()
                    sell_req = {"sell": int(order_id)}
                    ws.send(json.dumps(sell_req))
                    resp = json.loads(ws.recv())
                    if "error" in resp:
                        raise RuntimeError(str(resp["error"]))
                    del self._live_orders[order_id_str]
                    return True
                except Exception as e:
                    error_logger.error(f"Deriv live close_order error on attempt {attempt+1}: {e}")
                    self._ws = None
                    if attempt == 1:
                        return False
            # Paper mode
            if order_id_str in self._paper_positions:
                self._paper_positions.pop(order_id_str, None)
                return True
            return False

    def get_account_info(self) -> Dict[str, Any]:
        try:
            if self._app_id and self._api_token:
                bal = self._get_live_balance()
                if bal is not None:
                    return {"equity": float(bal)}
            return {"equity": float(self._equity_fallback)}
        except Exception:
            return {"equity": 0.0}

    # ---- Helpers ----
    def _tf_to_pandas_freq(self, tf: str) -> str:
        tf = (tf or "M1").upper()
        mapping = {
            "M1": "1min",
            "M5": "5min",
            "M15": "15min",
            "M30": "30min",
            "H1": "1h",
            "H4": "4h",
            "D1": "1D",
            "W1": "7D",
        }
        return mapping.get(tf, "1min")

    def _tf_to_deriv_granularity(self, tf: str) -> int:
        tf = (tf or "M1").upper()
        mapping = {
            "M1": 60,
            "M5": 300,
            "M15": 900,
            "M30": 1800,
            "H1": 3600,
            "H4": 14400,
            "D1": 86400,
        }
        return mapping.get(tf, 60)

    def _ws_authorized_connection(self):
        if not (self._app_id and self._api_token):
            raise RuntimeError("Deriv credentials not configured")
        url = f"wss://ws.derivws.com/websockets/v3?app_id={self._app_id}"
        
        # Use a class variable to track if we've already logged the connection attempt
        if not hasattr(self, '_connection_logged'):
            trade_logger.info("Establishing authorized connection to Deriv API")
            self._connection_logged = True
        
        ws = None
        for attempt in range(3):
            try:
                ws = create_connection(url, timeout=30)
                if attempt > 0:  # Only log on retry success
                    trade_logger.info(f"Connection established on attempt {attempt+1}")
                break
            except TimeoutError:
                error_logger.warning(f"Connection timeout on attempt {attempt+1}")
                if attempt < 2:
                    time.sleep(5)
                    continue
                raise
            except socket.gaierror as e:
                error_logger.error(f"Network error: DNS resolution failed ({e}). Check your internet connection.")
                # Raise a more informative exception
                raise ConnectionError(f"Cannot connect to Deriv API: DNS resolution failed. Check your internet connection.") from e
                
        if ws is None:
            raise RuntimeError("Failed to establish WebSocket connection")
            
        # authorize
        ws.send(json.dumps({"authorize": self._api_token}))
        auth_resp = json.loads(ws.recv())
        if "error" in auth_resp:
            ws.close()
            raise RuntimeError(f"Authorize failed: {auth_resp['error']}")
        trade_logger.info("Authorization successful")
        return ws

    def _get_ws(self) -> websocket.WebSocket:
        if self._ws is None or not self._ws.connected:
            self._ws = self._ws_authorized_connection()
        try:
            self._ws.ping()
        except Exception as e:
            trade_logger.warning(f"WebSocket ping failed: {e}. Reconnecting...")
            self._ws = self._ws_authorized_connection()
        return self._ws

    def _ping_loop(self):
        while self._running:
            time.sleep(30)
            try:
                if self._ws and self._ws.connected:
                    self._ws.ping()
                    trade_logger.debug("Sent keep-alive ping")
            except Exception as e:
                trade_logger.warning(f"Keep-alive ping failed: {e}")

    def _ws_send(self, request):
        """Send a request to the Deriv API and return the response."""
        for attempt in range(2):
            try:
                ws = self._get_ws()
                ws.send(json.dumps(request))
                response = json.loads(ws.recv())
                if "error" in response:
                    error_logger.error(f"API error: {response['error']}")
                return response
            except Exception as e:
                error_logger.warning(f"WebSocket error on attempt {attempt+1}: {e}. Reconnecting...")
                self._ws = None  # Force reconnect
                if attempt == 1:
                    raise

    def _get_live_candles(self, symbol: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
        gran = self._tf_to_deriv_granularity(timeframe)
        req = {
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": int(limit),
            "end": "latest",
            "style": "candles",
            "granularity": int(gran),
        }
        resp = self._ws_send(req)
        if "error" in resp:
            err = resp["error"]
            if err.get("code") == "WrongResponse":
                error_logger.warning(f"WrongResponse for {symbol} {timeframe}: {err.get('message')}")
                return None
            else:
                raise RuntimeError(str(err))
        candles = resp.get("candles") or []
        if not candles:
            return None
        df = pd.DataFrame(candles)
        # expected keys: open, high, low, close, epoch, (volume optional)
        df.rename(columns={"epoch": "timestamp"}, inplace=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        if "volume" not in df.columns:
            df["volume"] = 0.0
        out = df[["timestamp", "open", "high", "low", "close", "volume"]].astype(
            {"open": float, "high": float, "low": float, "close": float, "volume": float}
        )
        return out.dropna().sort_values("timestamp").reset_index(drop=True)

    def _get_live_balance(self) -> Optional[float]:
        resp = self._ws_send({"balance": 1, "subscribe": 0})
        if "error" in resp:
            return None
        bal = resp.get("balance", {}).get("balance")
        if bal is None:
            return None
        return float(bal)

    def _generate_synthetic_ohlcv(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        # Deterministic seed from symbol for reproducibility
        seed = abs(hash(symbol)) % (2**32)
        rng = np.random.default_rng(seed)

        freq = self._tf_to_pandas_freq(timeframe)
        end = pd.Timestamp.utcnow().tz_localize(None)
        # Make tz-aware UTC later
        idx = pd.date_range(end=end, periods=int(max(5, limit)), freq=freq)

        # Random walk with mean-reversion and volatility modulation
        steps = rng.normal(loc=0.0, scale=0.5, size=len(idx))
        # Apply a slow-varying volatility factor
        vol_mod = 1.0 + 0.5 * np.sin(np.linspace(0, 4 * math.pi, len(idx)))
        steps = steps * vol_mod
        price = 100 + np.cumsum(steps)

        # Build OHLCV
        opens = np.empty_like(price)
        highs = np.empty_like(price)
        lows = np.empty_like(price)
        closes = np.empty_like(price)
        vols = np.empty_like(price)

        for i in range(len(idx)):
            if i == 0:
                o = price[i]
            else:
                o = closes[i - 1]
            c = price[i]
            hi = max(o, c) + abs(rng.normal(0, 0.2))
            lo = min(o, c) - abs(rng.normal(0, 0.2))
            v = abs(rng.normal(1000, 300))
            opens[i], highs[i], lows[i], closes[i], vols[i] = o, hi, lo, c, v

        df = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(idx, utc=True),
                "open": opens.astype(float),
                "high": highs.astype(float),
                "low": lows.astype(float),
                "close": closes.astype(float),
                "volume": vols.astype(float),
            }
        )
        df = df.dropna().sort_values("timestamp").reset_index(drop=True)
        return df

    def get_active_symbols(self) -> List[str]:
        """Fetch active symbols from Deriv API that are available for trading.
        
        Returns:
            List[str]: List of valid symbol codes that can be traded
        """
        if not self._live_data:
            trade_logger.info("Live data disabled; cannot fetch active symbols")
            return []
        
        try:
            # Test connection to Deriv API
            import socket
            socket.getaddrinfo('ws.derivws.com', 443)
        except socket.gaierror:
            trade_logger.warning("Cannot connect to Deriv API (network issue). Cannot fetch symbols.")
            return []
            
        trade_logger.info("Fetching active symbols from Deriv API...")
        # Request active symbols with market info
        resp = self._ws_send({"active_symbols": "brief", "product_type": "basic"})
        
        if "error" in resp:
            error_logger.error(f"Deriv API error: {resp['error']}")
            return []
            
        symbols = []
        for sym in resp.get("active_symbols", []):
            if sym.get("exchange_is_open") and not sym.get("is_trading_suspended"):
                symbols.append(sym["symbol"])
        
        trade_logger.info(f"Found {len(symbols)} active symbols: {symbols[:10]}...")
        return symbols

    def get_contract_details(self, contract_id: int) -> Dict[str, Any]:
        try:
            response = self._ws_send({"proposal_open_contract": 1, "contract_id": contract_id})
            return response.get("proposal_open_contract", {})
        except Exception as e:
            error_logger.error(f"get_contract_details error: {e}")
            return {}

    def check_environment(self) -> Dict[str, Any]:
        """Check if the environment is properly configured for live trading."""
        result = {
            "app_id": bool(self._app_id),
            "api_token": bool(self._api_token),
            "live_data_enabled": self._live_data,
            "live_trading_enabled": self._live_trading,
            "connection": False,
            "auth": False
        }
        
        try:
            # Test connection
            socket.getaddrinfo('ws.derivws.com', 443)
            result["connection"] = True
            
            # Test auth if credentials exist
            if self._app_id and self._api_token:
                try:
                    ws = self._get_ws()
                    result["auth"] = True
                except Exception as e:
                    error_logger.error(f"Auth test failed: {e}")
        except Exception as e:
            error_logger.error(f"Connection test failed: {e}")
            
        trade_logger.info(f"Environment check: {result}")
        return result
