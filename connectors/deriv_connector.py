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


# ── Symbol category helpers ───────────────────────────────────────────────────
# Deriv uses different contract types depending on the instrument.
#
#   MULTIPLIERS  (MULTUP / MULTDOWN)
#       → frxEURUSD, frxGBPUSD, frxXAUUSD, frxUSDJPY etc.
#       → cryBTCUSD
#       → Supports SL / TP natively via limit_order
#
#   RISE/FALL    (CALL / PUT)
#       → R_100, R_75, R_50, R_25, R_10  (Volatility indices)
#       → CRASH1000, CRASH500, BOOM1000, BOOM500
#       → JD100, stpRNG
#       → Duration-based; SL/TP not supported — managed externally
#
# ─────────────────────────────────────────────────────────────────────────────

_MULTIPLIER_PREFIXES = ("frx", "cry", "CRASH", "BOOM", "JD", "stp")

_RISE_FALL_SYMBOLS = {
    "R_100", "R_75", "R_50", "R_25", "R_10"
}


def _is_multiplier_symbol(symbol: str) -> bool:
    """Returns True if the symbol should use MULTUP/MULTDOWN contracts."""
    return symbol.startswith(_MULTIPLIER_PREFIXES)


def _is_rise_fall_symbol(symbol: str) -> bool:
    """Returns True if the symbol should use CALL/PUT (Rise/Fall) contracts."""
    return symbol in _RISE_FALL_SYMBOLS


@dataclass
class _PaperPosition:
    order_id: str
    symbol: str
    side: str       # "buy" or "sell"
    size: float
    sl: float
    tp: float
    entry_price: Optional[float] = None


class DerivConnector(BaseConnector):
    """
    Deriv WebSocket connector — primary broker for SubScalp on Railway.

    Contract routing:
      - frx* / cry* symbols  → MULTUP / MULTDOWN (multipliers, supports SL/TP)
      - Synthetic indices     → CALL / PUT (rise/fall, duration-based)

    Set in config.json under "deriv":
      "live_data": true       → fetch real OHLCV candles from Deriv API
      "live_trading": true    → place real orders on your Deriv account

    Credentials via .env:
      DERIV_APP_ID=xxxxx
      DERIV_API_TOKEN=xxxxx
    """

    def __init__(self, config: Dict[str, Any], **kwargs: Any) -> None:
        self.config   = config
        self.kwargs   = kwargs
        self.connected: bool = False

        self._paper_positions: Dict[str, _PaperPosition] = {}
        self._orders:          Dict[str, Dict[str, Any]] = {}
        self._live_orders:     Dict[str, Dict[str, Any]] = {}

        deriv_cfg = config.get("deriv") or {}

        # ── Credentials ──────────────────────────────────────────────────────
        app_id_env    = deriv_cfg.get("app_id_env")
        api_token_env = deriv_cfg.get("api_token_env")
        self._app_id: Optional[str] = (
            deriv_cfg.get("app_id")
            or (os.getenv(app_id_env) if app_id_env else None)
            or os.getenv("DERIV_APP_ID")
        )
        self._api_token: Optional[str] = (
            deriv_cfg.get("api_token")
            or (os.getenv(api_token_env) if api_token_env else None)
            or os.getenv("DERIV_API_TOKEN")
        )

        # ── Feature flags — read from config, fallback to env ─────────────
        # Config sets these; Railway env vars can override to True
        _env_live = os.getenv("DERIV_LIVE", "").lower() in ("1", "true", "yes")
        self._live_data: bool = bool(
            (deriv_cfg.get("live_data", False) or _env_live)
            and self._app_id and self._api_token
        )
        self._live_trading: bool = bool(
            (deriv_cfg.get("live_trading", False) or _env_live)
            and self._app_id and self._api_token
        )

        # ── Other settings ────────────────────────────────────────────────
        self._multiplier:      int   = int(deriv_cfg.get("multiplier", 10))
        self._equity_fallback: float = float(config.get("equity", 10000.0))

        # ── Duration for Rise/Fall contracts (minutes) ────────────────────
        self._rf_duration: int = int(deriv_cfg.get("rf_duration_minutes", 5))

        self._ws:           Optional[websocket.WebSocket] = None
        self._ping_thread:  Optional[threading.Thread]    = None
        self._running:      bool = False

    # ── BaseConnector API ─────────────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            self.connected = True
            self._running  = True

            self._ping_thread = threading.Thread(
                target=self._ping_loop, daemon=True, name="deriv-ping"
            )
            self._ping_thread.start()

            if self._app_id and self._api_token:
                trade_logger.info(
                    f"Deriv credentials found. "
                    f"live_data={self._live_data}, live_trading={self._live_trading}"
                )
                try:
                    socket.getaddrinfo("ws.derivws.com", 443)
                    self._ws = self._ws_authorized_connection()
                    trade_logger.info("Deriv WebSocket connection established.")
                except Exception as e:
                    error_logger.warning(
                        f"Cannot connect to Deriv API: {e}. Falling back to paper mode."
                    )
                    self._live_data    = False
                    self._live_trading = False
            else:
                trade_logger.warning(
                    "DerivConnector: no credentials found. "
                    "Set DERIV_APP_ID and DERIV_API_TOKEN in .env to enable live trading."
                )
            return True
        except Exception as e:
            error_logger.error(f"Deriv connect error: {e}")
            self.connected = False
            return False

    def get_historical_data(
        self, symbol: str, timeframe: str, limit: int = 100,
        start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> pd.DataFrame:
        empty_df = pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        ).astype({
            "timestamp": "datetime64[ns]",
            "open": float, "high": float,
            "low": float,  "close": float, "volume": float,
        })

        if not self._live_data:
            trade_logger.debug(
                f"live_data=False — generating synthetic data for {symbol} {timeframe}"
            )
            return self._generate_synthetic_ohlcv(symbol, timeframe, limit)

        try:
            if not self.connected:
                self.connect()
            df = self._get_live_candles(symbol, timeframe, limit)
            if df is not None and not df.empty:
                return df
            trade_logger.warning(
                f"No live candles for {symbol} {timeframe} — using synthetic fallback."
            )
            return self._generate_synthetic_ohlcv(symbol, timeframe, limit)
        except socket.gaierror as e:
            error_logger.warning(f"Network error for {symbol}: {e} — using synthetic.")
            return self._generate_synthetic_ohlcv(symbol, timeframe, limit)
        except Exception as e:
            error_logger.error(f"get_historical_data error for {symbol}: {e}")
            return self._generate_synthetic_ohlcv(symbol, timeframe, limit)

    def place_order(
        self, symbol: str, side: str, size: float, sl: float, tp: float
    ) -> str:
        if not self.connected:
            self.connect()

        side = side.lower()  # normalise to "buy" / "sell"
        # Round size to 2 decimal places and enforce Deriv minimum stake of 0.35 USD
        size = round(float(size), 2)
        if size < 0.35:
            size = 0.35

        trade_logger.debug(
            f"place_order: symbol={symbol} side={side} size={size} sl={sl} tp={tp}"
        )

        if self._live_trading:
            for attempt in range(2):
                try:
                    order_id = self._place_live_order(symbol, side, size, sl, tp)
                    return order_id
                except Exception as e:
                    error_logger.error(
                        f"Live place_order attempt {attempt + 1} failed: {e}"
                    )
                    self._ws = None
                    if attempt == 1:
                        error_logger.error(
                            "Live order failed. Restricting fallback to paper mode to avoid active positions."
                        )
                        return ""
        else:
            # ── Paper mode ───────────────────────────────────────────
            order_id = str(uuid.uuid4())
            self._paper_positions[order_id] = _PaperPosition(
                order_id=order_id,
                symbol=symbol,
                side=side,
                size=float(size),
                sl=float(sl),
                tp=float(tp),
            )
            trade_logger.info(f"[PAPER] Order placed: {order_id} | {symbol} {side} {size}")
            return order_id

    def close_order(self, order_id: str) -> bool:
        if not self.connected:
            self.connect()

        order_id_str = str(order_id)

        if order_id_str in self._live_orders:
            for attempt in range(2):
                try:
                    ws = self._get_ws()
                    # The Deriv 'sell' endpoint requires a 'price' parameter. 0.0 effectively means market sell.
                    ws.send(json.dumps({"sell": int(order_id), "price": 0.0}))
                    resp = json.loads(ws.recv())
                    if "error" in resp:
                        raise RuntimeError(str(resp["error"]))
                    self._live_orders.pop(order_id_str, None)
                    trade_logger.info(f"[LIVE] Closed order {order_id_str}")
                    return True
                except Exception as e:
                    error_logger.error(f"close_order attempt {attempt + 1} failed: {e}")
                    self._ws = None
                    if attempt == 1:
                        return False

        # Paper position
        if order_id_str in self._paper_positions:
            self._paper_positions.pop(order_id_str, None)
            trade_logger.info(f"[PAPER] Closed position {order_id_str}")
            return True

        error_logger.warning(f"close_order: order {order_id_str} not found")
        return False

    def get_account_info(self) -> Dict[str, Any]:
        try:
            if self._app_id and self._api_token and self._live_data:
                bal = self._get_live_balance()
                if bal is not None:
                    return {"equity": float(bal)}
        except Exception as e:
            error_logger.warning(f"get_account_info live fetch failed: {e}")
        return {"equity": float(self._equity_fallback)}

    # ── Symbol specs (required by TradeManager for position sizing) ───────────

    # Lookup table: {symbol_or_prefix: (point, tick_value)}
    _SYMBOL_SPECS: Dict[str, Dict[str, float]] = {
        # Forex — 5-digit pairs
        "frxEURUSD": {"point": 0.00001, "tick_value": 1.0},
        "frxGBPUSD": {"point": 0.00001, "tick_value": 1.0},
        "frxAUDUSD": {"point": 0.00001, "tick_value": 1.0},
        "frxUSDCHF": {"point": 0.00001, "tick_value": 1.0},
        # Forex — 3-digit (JPY) pairs
        "frxUSDJPY": {"point": 0.001, "tick_value": 1.0},
        "frxEURJPY": {"point": 0.001, "tick_value": 1.0},
        "frxGBPJPY": {"point": 0.001, "tick_value": 1.0},
        # Metals & crypto
        "frxXAUUSD": {"point": 0.01, "tick_value": 1.0},
        "frxXAGUSD": {"point": 0.001, "tick_value": 1.0},
        "cryBTCUSD": {"point": 0.01, "tick_value": 1.0},
        "cryETHUSD": {"point": 0.01, "tick_value": 1.0},
        # Volatility indices
        "R_100":  {"point": 0.01, "tick_value": 1.0},
        "R_75":   {"point": 0.01, "tick_value": 1.0},
        "R_50":   {"point": 0.01, "tick_value": 1.0},
        "R_25":   {"point": 0.0001, "tick_value": 1.0},
        "R_10":   {"point": 0.001, "tick_value": 1.0},
        # Crash / Boom
        "CRASH1000": {"point": 0.01, "tick_value": 1.0},
        "CRASH500":  {"point": 0.01, "tick_value": 1.0},
        "BOOM1000":  {"point": 0.01, "tick_value": 1.0},
        "BOOM500":   {"point": 0.01, "tick_value": 1.0},
        # Jump / Step
        "JD100":  {"point": 0.01, "tick_value": 1.0},
        "stpRNG": {"point": 0.01, "tick_value": 1.0},
    }

    def get_symbol_specs(self, symbol: str) -> Dict[str, float]:
        """Return point size and tick value for a Deriv symbol.

        Used by TradeManager._compute_size() for position sizing.
        Falls back to sensible defaults for unknown symbols.
        """
        if symbol in self._SYMBOL_SPECS:
            return dict(self._SYMBOL_SPECS[symbol])

        # Prefix-based fallback
        if symbol.startswith("frx"):
            if "JPY" in symbol:
                return {"point": 0.001, "tick_value": 1.0}
            return {"point": 0.00001, "tick_value": 1.0}
        if symbol.startswith("cry"):
            return {"point": 0.01, "tick_value": 1.0}

        # Default for synthetics / unknown
        return {"point": 0.01, "tick_value": 1.0}

    # ── Live order placement (contract-type aware) ────────────────────────────

    def _place_live_order(
        self, symbol: str, side: str, size: float, sl: float, tp: float
    ) -> str:
        ws = self._get_ws()

        if _is_multiplier_symbol(symbol):
            return self._place_multiplier_order(ws, symbol, side, size, sl, tp)
        elif _is_rise_fall_symbol(symbol):
            return self._place_rise_fall_order(ws, symbol, side, size)
        else:
            # Unknown symbol — attempt multiplier, fall back to rise/fall
            trade_logger.warning(
                f"Unknown symbol category for {symbol} — attempting multiplier contract."
            )
            return self._place_multiplier_order(ws, symbol, side, size, sl, tp)

    def _place_multiplier_order(
        self,
        ws,
        symbol: str,
        side: str,
        size: float,
        sl: float,
        tp: float,
    ) -> str:
        """
        Place a MULTUP/MULTDOWN contract.
        These support native SL and TP via limit_order.
        Suitable for: frxEURUSD, frxGBPUSD, frxXAUUSD, cryBTCUSD etc.
        """
        contract_type = "MULTUP" if side == "buy" else "MULTDOWN"

        proposal_req: Dict[str, Any] = {
            "proposal":       1,
            "amount":         float(size),
            "basis":          "stake",
            "contract_type":  contract_type,
            "currency":       "USD",
            "symbol":         symbol,
            "multiplier":     self._multiplier,
        }

        # Attach SL / TP if valid
        limit_order: Dict[str, float] = {}
        if sl and math.isfinite(float(sl)) and float(sl) > 0:
            limit_order["stop_loss"] = float(sl)
        if tp and math.isfinite(float(tp)) and float(tp) > 0:
            limit_order["take_profit"] = float(tp)
        if limit_order:
            proposal_req["limit_order"] = limit_order

        trade_logger.debug(f"Multiplier proposal: {json.dumps(proposal_req)}")

        ws.send(json.dumps(proposal_req))
        resp = json.loads(ws.recv())

        if "error" in resp:
            raise RuntimeError(f"Proposal error: {resp['error']}")

        proposal_id = resp.get("proposal", {}).get("id")
        if not proposal_id:
            raise RuntimeError(f"No proposal_id in response: {resp}")

        # Execute
        ws.send(json.dumps({"buy": proposal_id, "price": float(size)}))
        buy_resp = json.loads(ws.recv())

        if "error" in buy_resp:
            raise RuntimeError(f"Buy error: {buy_resp['error']}")

        contract_id = buy_resp.get("buy", {}).get("contract_id")
        if not contract_id:
            raise RuntimeError(f"No contract_id in buy response: {buy_resp}")

        self._live_orders[str(contract_id)] = {
            "symbol": symbol, "side": side, "size": size,
            "sl": sl, "tp": tp, "type": "multiplier",
        }

        trade_logger.info(
            f"[LIVE MULT] {contract_type} {symbol} size={size} "
            f"mult={self._multiplier}x | contract_id={contract_id}"
        )
        return str(contract_id)

    def _place_rise_fall_order(
        self, ws, symbol: str, side: str, size: float
    ) -> str:
        """
        Place a CALL/PUT (Rise/Fall) contract.
        SL/TP not supported natively — trade_manager handles exit externally.
        Suitable for: R_100, R_50, CRASH1000, BOOM1000 etc.
        """
        contract_type = "CALL" if side == "buy" else "PUT"

        proposal_req: Dict[str, Any] = {
            "proposal":      1,
            "amount":        float(size),
            "basis":         "stake",
            "contract_type": contract_type,
            "currency":      "USD",
            "symbol":        symbol,
            "duration":      self._rf_duration,
            "duration_unit": "m",
        }

        trade_logger.debug(f"Rise/Fall proposal: {json.dumps(proposal_req)}")

        ws.send(json.dumps(proposal_req))
        resp = json.loads(ws.recv())

        if "error" in resp:
            raise RuntimeError(f"Proposal error: {resp['error']}")

        proposal_id = resp.get("proposal", {}).get("id")
        if not proposal_id:
            raise RuntimeError(f"No proposal_id: {resp}")

        ws.send(json.dumps({"buy": proposal_id, "price": float(size)}))
        buy_resp = json.loads(ws.recv())

        if "error" in buy_resp:
            raise RuntimeError(f"Buy error: {buy_resp['error']}")

        contract_id = buy_resp.get("buy", {}).get("contract_id")
        if not contract_id:
            raise RuntimeError(f"No contract_id: {buy_resp}")

        self._live_orders[str(contract_id)] = {
            "symbol": symbol, "side": side, "size": size,
            "sl": None, "tp": None, "type": "rise_fall",
        }

        trade_logger.info(
            f"[LIVE RF] {contract_type} {symbol} size={size} "
            f"duration={self._rf_duration}m | contract_id={contract_id}"
        )
        return str(contract_id)

    # ── WebSocket helpers ─────────────────────────────────────────────────────

    def _ws_authorized_connection(self) -> websocket.WebSocket:
        if not (self._app_id and self._api_token):
            raise RuntimeError("Deriv credentials not configured")

        url = f"wss://ws.derivws.com/websockets/v3?app_id={self._app_id}"
        ws  = None

        for attempt in range(3):
            try:
                ws = create_connection(url, timeout=30)
                break
            except TimeoutError:
                error_logger.warning(f"WS connect timeout (attempt {attempt + 1})")
                if attempt < 2:
                    time.sleep(5)
            except socket.gaierror as e:
                raise ConnectionError(
                    f"Cannot reach Deriv API — check internet: {e}"
                ) from e

        if ws is None:
            raise RuntimeError("Failed to establish Deriv WebSocket after 3 attempts")

        ws.send(json.dumps({"authorize": self._api_token}))
        auth_resp = json.loads(ws.recv())

        if "error" in auth_resp:
            ws.close()
            raise RuntimeError(f"Deriv auth failed: {auth_resp['error']}")

        trade_logger.info("Deriv API authorization successful.")
        return ws

    def _get_ws(self) -> websocket.WebSocket:
        if self._ws is None or not self._ws.connected:
            self._ws = self._ws_authorized_connection()
        try:
            self._ws.ping()
        except Exception:
            trade_logger.warning("Deriv WS ping failed — reconnecting.")
            self._ws = self._ws_authorized_connection()
        return self._ws

    def _ws_send(self, request: dict) -> dict:
        for attempt in range(2):
            try:
                ws = self._get_ws()
                ws.send(json.dumps(request))
                response = json.loads(ws.recv())
                return response
            except Exception as e:
                error_logger.warning(f"_ws_send attempt {attempt + 1} failed: {e}")
                self._ws = None
                if attempt == 1:
                    raise
        return {}

    def _ping_loop(self):
        while self._running:
            time.sleep(30)
            try:
                if self._ws and self._ws.connected:
                    self._ws.ping()
            except Exception as e:
                trade_logger.warning(f"Ping failed: {e}")

    # ── Data helpers ──────────────────────────────────────────────────────────

    def _tf_to_deriv_granularity(self, tf: str) -> int:
        mapping = {
            "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
            "H1": 3600, "H4": 14400, "D1": 86400,
        }
        return mapping.get((tf or "M1").upper(), 60)

    def _tf_to_pandas_freq(self, tf: str) -> str:
        mapping = {
            "M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min",
            "H1": "1h", "H4": "4h", "D1": "1D",
        }
        return mapping.get((tf or "M1").upper(), "1min")

    def _get_live_candles(
        self, symbol: str, timeframe: str, limit: int
    ) -> Optional[pd.DataFrame]:
        gran = self._tf_to_deriv_granularity(timeframe)
        resp = self._ws_send({
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": int(limit),
            "end": "latest",
            "style": "candles",
            "granularity": int(gran),
        })
        if "error" in resp:
            error_logger.warning(
                f"Candles error for {symbol} {timeframe}: {resp['error']}"
            )
            return None
        candles = resp.get("candles") or []
        if not candles:
            return None

        df = pd.DataFrame(candles)
        df.rename(columns={"epoch": "timestamp"}, inplace=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        if "volume" not in df.columns:
            df["volume"] = 0.0
        return (
            df[["timestamp", "open", "high", "low", "close", "volume"]]
            .astype({"open": float, "high": float, "low": float,
                     "close": float, "volume": float})
            .dropna()
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

    def _get_live_balance(self) -> Optional[float]:
        resp = self._ws_send({"balance": 1, "subscribe": 0})
        if "error" in resp:
            return None
        bal = resp.get("balance", {}).get("balance")
        return float(bal) if bal is not None else None

    def _generate_synthetic_ohlcv(
        self, symbol: str, timeframe: str, limit: int
    ) -> pd.DataFrame:
        seed = abs(hash(symbol)) % (2 ** 32)
        rng  = np.random.default_rng(seed)
        freq = self._tf_to_pandas_freq(timeframe)
        end  = pd.Timestamp.utcnow().tz_localize(None)
        idx  = pd.date_range(end=end, periods=int(max(5, limit)), freq=freq)

        steps   = rng.normal(0.0, 0.5, len(idx))
        vol_mod = 1.0 + 0.5 * np.sin(np.linspace(0, 4 * math.pi, len(idx)))
        price   = 100 + np.cumsum(steps * vol_mod)

        opens  = np.empty_like(price)
        highs  = np.empty_like(price)
        lows   = np.empty_like(price)
        closes = np.empty_like(price)
        vols   = np.empty_like(price)

        for i in range(len(idx)):
            o = price[i] if i == 0 else closes[i - 1]
            c = price[i]
            opens[i]  = o
            closes[i] = c
            highs[i]  = max(o, c) + abs(rng.normal(0, 0.2))
            lows[i]   = min(o, c) - abs(rng.normal(0, 0.2))
            vols[i]   = abs(rng.normal(1000, 300))

        return pd.DataFrame({
            "timestamp": pd.to_datetime(idx, utc=True),
            "open":   opens.astype(float),
            "high":   highs.astype(float),
            "low":    lows.astype(float),
            "close":  closes.astype(float),
            "volume": vols.astype(float),
        }).dropna().sort_values("timestamp").reset_index(drop=True)

    # ── Utility ───────────────────────────────────────────────────────────────

    def get_active_symbols(self) -> List[str]:
        if not self._live_data:
            return []
        try:
            socket.getaddrinfo("ws.derivws.com", 443)
        except socket.gaierror:
            return []
        resp = self._ws_send({"active_symbols": "brief", "product_type": "basic"})
        if "error" in resp:
            return []
        return [
            s["symbol"] for s in resp.get("active_symbols", [])
            if s.get("exchange_is_open") and not s.get("is_trading_suspended")
        ]

    def get_contract_details(self, contract_id: int) -> Dict[str, Any]:
        try:
            resp = self._ws_send({
                "proposal_open_contract": 1,
                "contract_id": contract_id,
            })
            return resp.get("proposal_open_contract", {})
        except Exception as e:
            error_logger.error(f"get_contract_details error: {e}")
            return {}

    def check_environment(self) -> Dict[str, Any]:
        result = {
            "app_id":              bool(self._app_id),
            "api_token":           bool(self._api_token),
            "live_data_enabled":   self._live_data,
            "live_trading_enabled": self._live_trading,
            "connection":          False,
            "auth":                False,
        }
        try:
            socket.getaddrinfo("ws.derivws.com", 443)
            result["connection"] = True
            if self._app_id and self._api_token:
                self._get_ws()
                result["auth"] = True
        except Exception as e:
            error_logger.error(f"check_environment failed: {e}")
        return result
