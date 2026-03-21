from __future__ import annotations
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import uuid
import os
import pandas as pd
from datetime import datetime, timezone

try:
    import MetaTrader5 as mt5  # type: ignore
    MT5_AVAILABLE = True
except Exception:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False

from . import BaseConnector
from utils.logger import error_logger
import math


@dataclass
class _PaperPosition:
    order_id: str
    symbol: str
    side: str  # "buy" or "sell"
    size: float
    sl: float
    tp: float
    entry_price: Optional[float] = None


class MT5Connector(BaseConnector):
    """MetaTrader5 connector with graceful paper-mode fallback.

    Methods implement BaseConnector:
      - connect(): initialize MT5, try optional login if credentials provided in config["mt5"].
      - get_historical_data(symbol, timeframe, limit): returns OHLCV DataFrame.
      - place_order(symbol, side, size, sl, tp): returns order_id (string).
      - close_order(order_id): closes stored order/position by sending opposite deal (paper or live).
      - get_account_info(): returns dict with at least {"equity": float}.
    """

    def __init__(self, config: Dict[str, Any], **kwargs: Any) -> None:
        self.config = config
        self.kwargs = kwargs
        self.connected: bool = False
        self.paper_mode: bool = False
        self._orders: Dict[str, Dict[str, Any]] = {}
        self._paper_positions: Dict[str, _PaperPosition] = {}
        self._tf_cache: Dict[str, Any] = {}

        mt5_cfg = (config.get("mt5") or {})
        # Prefer explicit values; otherwise read from environment variables specified by *_env keys
        login_env = mt5_cfg.get("login_env")
        password_env = mt5_cfg.get("password_env")
        server_env = mt5_cfg.get("server_env")
        raw_login = mt5_cfg.get("login") or (os.getenv(login_env) if login_env else None)
        self._login: Optional[int] = int(raw_login) if raw_login is not None else None
        self._password: Optional[str] = mt5_cfg.get("password") or (os.getenv(password_env) if password_env else None)
        self._server: Optional[str] = mt5_cfg.get("server") or (os.getenv(server_env) if server_env else None)

    # ---- Public API ----
    def connect(self) -> bool:
        if not MT5_AVAILABLE:
            error_logger.warning("MT5 library not available; running in paper mode.")
            self.paper_mode = True
            self.connected = True
            return True
        try:
            if not mt5.initialize():  # type: ignore[attr-defined]
                error_logger.warning("MT5 initialization failed; running in paper mode.")
                self.paper_mode = True
                self.connected = True
                return True
            if self._login and self._password and self._server:
                ok = mt5.login(self._login, password=self._password, server=self._server)  # type: ignore[attr-defined]
                if not ok:
                    error_logger.warning(f"MT5 login failed (login={self._login}, server={self._server}); running in paper mode.")
                    self.paper_mode = True
            else:
                error_logger.warning("No MT5 credentials provided; running in paper mode.")
                self.paper_mode = True
            self.connected = True
            return True
        except Exception as e:
            error_logger.error(f"MT5 connect error: {e}; forcing paper mode.")
            self.paper_mode = True
            self.connected = True
            return True

    def get_historical_data(self, symbol: str, timeframe: str, limit: int, start_date: Optional[str] = None, end_date: Optional[str] = None) -> pd.DataFrame:
        if not self.connected:
            self.connect()
        if self.paper_mode or not MT5_AVAILABLE:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"]).astype(
                {"timestamp": "datetime64[ns]", "open": float, "high": float, "low": float, "close": float, "volume": float}
            )
        try:
            tf_const = self._to_mt5_timeframe(timeframe)
            self._ensure_symbol_selected(symbol)
            if start_date and end_date:
                start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
                end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
                rates = mt5.copy_rates_range(symbol, tf_const, start_ts, end_ts)  # type: ignore[attr-defined]
            else:
                rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, int(limit))  # type: ignore[attr-defined]
            if rates is None or len(rates) == 0:
                return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"]).astype(
                    {"timestamp": "datetime64[ns]", "open": float, "high": float, "low": float, "close": float, "volume": float}
                )
            df = pd.DataFrame(rates)
            df["timestamp"] = pd.to_datetime(df["time"], unit="s", utc=True)
            if "real_volume" in df.columns:
                out = df[["timestamp", "open", "high", "low", "close", "real_volume"]].copy()
                out.rename(columns={"real_volume": "volume"}, inplace=True)
            else:
                out = df[["timestamp", "open", "high", "low", "close", "tick_volume"]].copy()
                out.rename(columns={"tick_volume": "volume"}, inplace=True)
            out = out.dropna().sort_values("timestamp").reset_index(drop=True)
            return out
        except Exception as e:
            error_logger.error(f"MT5 get_historical_data error for {symbol} {timeframe}: {e}")
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"]).astype(
                {"timestamp": "datetime64[ns]", "open": float, "high": float, "low": float, "close": float, "volume": float}
            )

    def place_order(self, symbol: str, side: str, size: float, sl: float, tp: float) -> str:
        side = side.lower()
        if not self.connected:
            self.connect()
        if self.paper_mode or not MT5_AVAILABLE:
            order_id = str(uuid.uuid4())
            self._paper_positions[order_id] = _PaperPosition(
                order_id=order_id, symbol=symbol, side=side, size=float(size), sl=float(sl), tp=float(tp)
            )
            return order_id
        try:
            self._ensure_symbol_selected(symbol)
            symbol_info = mt5.symbol_info(symbol)  # type: ignore[attr-defined]
            if symbol_info is None:
                raise RuntimeError(f"Symbol not found: {symbol}")
            
            # Validate and adjust volume
            volume = float(size)
            volume_min = float(getattr(symbol_info, 'volume_min', 0.01))
            volume_max = float(getattr(symbol_info, 'volume_max', 1000.0))
            volume_step = float(getattr(symbol_info, 'volume_step', 0.01))
            
            if volume_step > 0:
                # Round down to nearest step
                steps = math.floor(volume / volume_step)
                volume = steps * volume_step
            
            # Clamp to min/max
            volume = max(volume_min, min(volume_max, volume))
            
            if volume < volume_min or volume <= 0:
                raise ValueError(f"Adjusted volume {volume} is invalid (min: {volume_min}) for {symbol}")
            
            # Get current prices
            tick = mt5.symbol_info_tick(symbol)  # type: ignore[attr-defined]
            if tick is None:
                raise RuntimeError(f"No tick info for symbol: {symbol}")
            
            # Get symbol properties for SL/TP validation
            point = float(getattr(symbol_info, 'point', 0.00001))
            stops_level = int(getattr(symbol_info, 'stops_level', 0))  # in points
            
            # Calculate min distances (Safe guard against 0 stops_level)
            # If stops_level is 0, use 2 points as a safety buffer
            safe_distance = max(stops_level, 10) * point
            
            # Adjust SL and TP to meet minimum distance requirements
            # IMPORTANT: For BUY, SL must be below Bid. For SELL, SL must be above Ask.
            if side == "buy":
                # Buy: SL < Bid, TP > Ask
                max_sl = tick.bid - safe_distance
                min_tp = tick.ask + safe_distance
                
                adjusted_sl = min(float(sl), max_sl)
                adjusted_tp = max(float(tp), min_tp)
            else:  # sell
                # Sell: SL > Ask, TP < Bid
                min_sl = tick.ask + safe_distance
                max_tp = tick.bid - safe_distance
                
                adjusted_sl = max(float(sl), min_sl)
                adjusted_tp = min(float(tp), max_tp)
            
            # Round to tick size if necessary (assuming trade_tick_size is point for simplicity)
            def round_to_point(value: float, point: float) -> float:
                return round(value / point) * point
            
            adjusted_sl = round_to_point(adjusted_sl, point)
            adjusted_tp = round_to_point(adjusted_tp, point)
            
            order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL  # type: ignore[attr-defined]
            price = tick.ask if side == "buy" else tick.bid

            # Check margin requirements
            acct = mt5.account_info()  # type: ignore[attr-defined]
            if acct is None:
                raise RuntimeError("Failed to get account info")
            
            free_margin = float(getattr(acct, 'margin_free', 0.0))
            if free_margin <= 0:
                raise ValueError("No free margin available")
            
            # Calculate required margin for the order
            calc_margin = mt5.order_calc_margin(order_type, symbol, volume, price)  # type: ignore[attr-defined]
            if calc_margin is None or calc_margin <= 0:
                # Fallback if calc fails (sometimes returns None on demo)
                required_margin = 0.0
            else:
                required_margin = float(calc_margin)
            
            # If required margin exceeds free margin, reduce volume
            loop_safe = 0
            while required_margin > free_margin and volume > volume_min and loop_safe < 50:
                loop_safe += 1
                volume -= volume_step
                volume = max(volume_min, round(volume / volume_step) * volume_step)
                calc_margin = mt5.order_calc_margin(order_type, symbol, volume, price)  # type: ignore[attr-defined]
                if calc_margin is None:
                    break
                required_margin = float(calc_margin)
            
            if (required_margin > free_margin and required_margin > 0) or volume < volume_min:
                 # Try one last ditch: minimum volume
                 if free_margin > 0:
                     volume = volume_min
                 else:
                     raise ValueError(f"Insufficient margin for volume {volume}")

            request = {
                "action": mt5.TRADE_ACTION_DEAL,  # type: ignore[attr-defined]
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "price": float(price),
                "sl": adjusted_sl,
                "tp": adjusted_tp,
                "deviation": 20,
                "magic": 0,
                "comment": "SubScalpBot",
                "type_filling": mt5.ORDER_FILLING_FOK,  # type: ignore[attr-defined]
                "type_time": mt5.ORDER_TIME_GTC,  # type: ignore[attr-defined]
            }
            result = mt5.order_send(request)  # type: ignore[attr-defined]
            if result is None:
                raise RuntimeError("order_send returned None")
            # result has attributes: retcode, order, deal, comment, etc.
            if getattr(result, "retcode", None) == mt5.TRADE_RETCODE_DONE:  # type: ignore[attr-defined]
                oid = str(getattr(result, "order", None) or getattr(result, "deal", uuid.uuid4()))
                self._orders[oid] = {"symbol": symbol, "side": side, "size": volume}
                return oid
            raise RuntimeError(f"order_send failed: retcode={getattr(result, 'retcode', 'unknown')} comment={getattr(result, 'comment', '')}")
        except Exception as e:
            error_logger.error(f"MT5 place_order error for {symbol}: {e}. Falling back to paper mode for this order.")
            order_id = str(uuid.uuid4())
            self._paper_positions[order_id] = _PaperPosition(
                order_id=order_id, symbol=symbol, side=side, size=float(size), sl=float(sl), tp=float(tp)
            )
            return order_id

    def close_all_positions(self) -> bool:
        """Close all open positions managed by SubScalpBot."""
        if not self.connected:
            self.connect()
        
        if self.paper_mode or not MT5_AVAILABLE:
            # Clear all paper positions
            self._paper_positions.clear()
            return True
        
        try:
            positions = mt5.positions_get()  # type: ignore[attr-defined]
            if positions is None:
                return False
            
            closed_count = 0
            for pos in positions:
                # Only close positions opened by our bot (identified by comment)
                if hasattr(pos, 'comment') and 'SubScalpBot' in str(getattr(pos, 'comment', '')):
                    symbol = getattr(pos, 'symbol', '')
                    ticket = getattr(pos, 'ticket', 0)
                    volume = getattr(pos, 'volume', 0.0)
                    
                    if not symbol or not ticket or not volume:
                        continue
                    
                    # Determine order type for closing (opposite of current position)
                    pos_type = getattr(pos, 'type', 0)
                    close_type = mt5.ORDER_TYPE_SELL if pos_type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY  # type: ignore[attr-defined]
                    
                    tick = mt5.symbol_info_tick(symbol)  # type: ignore[attr-defined]
                    if tick is None:
                        continue
                    
                    price = tick.bid if pos_type == mt5.ORDER_TYPE_BUY else tick.ask  # type: ignore[attr-defined]
                    
                    request = {
                        "action": mt5.TRADE_ACTION_DEAL,  # type: ignore[attr-defined]
                        "symbol": symbol,
                        "volume": float(volume),
                        "type": close_type,
                        "price": float(price),
                        "position": ticket,
                        "deviation": 20,
                        "magic": 0,
                        "comment": "SubScalpBot/CloseAll",
                        "type_filling": mt5.ORDER_FILLING_FOK,  # type: ignore[attr-defined]
                        "type_time": mt5.ORDER_TIME_GTC,  # type: ignore[attr-defined]
                    }
                    
                    result = mt5.order_send(request)  # type: ignore[attr-defined]
                    if result and getattr(result, "retcode", None) == mt5.TRADE_RETCODE_DONE:  # type: ignore[attr-defined]
                        closed_count += 1
            
            return closed_count > 0
        except Exception as e:
            error_logger.error(f"MT5 close_all_positions error: {e}")
            return False

    def get_position_info(self, order_id: str) -> Dict[str, Any]:
        """Get position details including status and PnL if closed."""
        if not self.connected:
            self.connect()
        
        if self.paper_mode or not MT5_AVAILABLE:
            if order_id in self._paper_positions:
                return {"status": "open", "pnl": 0.0, "exit_price": None}
            else:
                return {"status": "closed", "pnl": 0.0, "exit_price": None}
        
        try:
            position_id = int(order_id)
            # Check if position is still open
            positions = mt5.positions_get(position=position_id)  # type: ignore[attr-defined]
            if positions and len(positions) > 0:
                return {"status": "open", "pnl": 0.0, "exit_price": None}
            
            # Position closed, get history to calculate PnL
            history = mt5.history_deals_get(position=position_id)  # type: ignore[attr-defined]
            if not history or len(history) < 2:
                return {"status": "closed", "pnl": 0.0, "exit_price": None}
            
            # Assume first is entry, last is exit
            entry_deal = history[0]
            exit_deal = history[-1]
            
            entry_price = getattr(entry_deal, 'price', 0.0)
            exit_price = getattr(exit_deal, 'price', 0.0)
            volume = getattr(entry_deal, 'volume', 0.0)
            deal_type = getattr(entry_deal, 'type', 0)
            
            if deal_type == mt5.DEAL_TYPE_BUY:  # type: ignore[attr-defined]
                pnl = (exit_price - entry_price) * volume
            else:
                pnl = (entry_price - exit_price) * volume
            
            return {"status": "closed", "pnl": pnl, "exit_price": exit_price}
        except Exception as e:
            error_logger.error(f"MT5 get_position_info error for {order_id}: {e}")
            return {"status": "unknown", "pnl": 0.0, "exit_price": None}

    def close_order(self, order_id: str) -> bool:
        if not self.connected:
            self.connect()
        # Paper handling first
        if order_id in self._paper_positions:
            try:
                self._paper_positions.pop(order_id, None)
                return True
            except Exception:
                return False
        if self.paper_mode or not MT5_AVAILABLE:
            return False
        try:
            od = self._orders.get(order_id)
            if not od:
                # Unknown order id; cannot close
                return False
            symbol = od["symbol"]
            size = float(od["size"])
            side = od["side"]
            self._ensure_symbol_selected(symbol)
            tick = mt5.symbol_info_tick(symbol)  # type: ignore[attr-defined]
            if tick is None:
                return False
            # Close by sending opposite deal with same volume, specifying position
            order_type = mt5.ORDER_TYPE_SELL if side == "buy" else mt5.ORDER_TYPE_BUY  # type: ignore[attr-defined]
            price = tick.bid if side == "buy" else tick.ask
            request = {
                "action": mt5.TRADE_ACTION_DEAL,  # type: ignore[attr-defined]
                "symbol": symbol,
                "volume": float(size),
                "type": order_type,
                "position": int(order_id),  # Specify the position to close
                "price": float(price),
                "deviation": 20,
                "magic": 0,
                "comment": "SubScalpBot/Close",
                "type_filling": mt5.ORDER_FILLING_FOK,  # type: ignore[attr-defined]
                "type_time": mt5.ORDER_TIME_GTC,  # type: ignore[attr-defined]
            }
            result = mt5.order_send(request)  # type: ignore[attr-defined]
            if result is None:
                return False
            if getattr(result, "retcode", None) == mt5.TRADE_RETCODE_DONE:  # type: ignore[attr-defined]
                self._orders.pop(order_id, None)
                return True
            return False
        except Exception as e:
            error_logger.error(f"MT5 close_order error: {e}")
            return False

    def get_account_info(self) -> Dict[str, Any]:
        if not self.connected:
            self.connect()
        if self.paper_mode or not MT5_AVAILABLE:
            # MT5 not available or paper mode: no live equity
            return {"equity": float(self.config.get("equity", 0.0))}
        try:
            acct = mt5.account_info()  # type: ignore[attr-defined]
            if acct is None:
                return {"equity": float(self.config.get("equity", 0.0))}
            return {"equity": float(getattr(acct, "equity", 0.0))}
        except Exception:
            return {"equity": float(self.config.get("equity", 0.0))}

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Fetch all open positions relevant to this bot."""
        if not self.connected:
            self.connect()
            
        if self.paper_mode or not MT5_AVAILABLE:
            return [{
                "contract_id": pid,
                "symbol": p.symbol,
                "side": p.side,
                "size": p.size,
                "entry_price": p.entry_price or 0.0,
                "sl": p.sl,
                "tp": p.tp,
                "status": "open"
            } for pid, p in self._paper_positions.items()]
            
        try:
            positions = mt5.positions_get()  # type: ignore[attr-defined]
            if positions is None:
                return []
                
            out = []
            for pos in positions:
                # Filter by comment to only manage our own trades
                if hasattr(pos, 'comment') and 'SubScalpBot' in str(getattr(pos, 'comment', '')):
                    out.append({
                        "contract_id": str(getattr(pos, 'ticket')),
                        "symbol": getattr(pos, 'symbol'),
                        "side": "buy" if getattr(pos, 'type') == mt5.ORDER_TYPE_BUY else "sell",  # type: ignore[attr-defined]
                        "size": float(getattr(pos, 'volume')),
                        "entry_price": float(getattr(pos, 'price_open')),
                        "sl": float(getattr(pos, 'sl')),
                        "tp": float(getattr(pos, 'tp')),
                        "profit": float(getattr(pos, 'profit')),
                        "status": "open"
                    })
            return out
        except Exception as e:
            error_logger.error(f"MT5 get_open_positions error: {e}")
            return []

    def modify_order(self, order_id: str, sl: float = None, tp: float = None) -> bool:
        """Modify SL/TP of an existing order/position."""
        if not self.connected:
            self.connect()
            
        if self.paper_mode or not MT5_AVAILABLE:
            if order_id in self._paper_positions:
                if sl is not None:
                    self._paper_positions[order_id].sl = sl
                if tp is not None:
                    self._paper_positions[order_id].tp = tp
                return True
            return False
            
        try:
            position_id = int(order_id)
            # 1. Get current position to check symbol
            positions = mt5.positions_get(ticket=position_id)  # type: ignore[attr-defined]
            if not positions:
                return False
                
            pos = positions[0]
            symbol = getattr(pos, 'symbol')
            
            request = {
                "action": mt5.TRADE_ACTION_SLTP,  # type: ignore[attr-defined]
                "symbol": symbol,
                "position": position_id,
            }
            
            if sl is not None:
                request["sl"] = float(sl)
            else:
                request["sl"] = float(getattr(pos, 'sl'))
                
            if tp is not None:
                request["tp"] = float(tp)
            else:
                request["tp"] = float(getattr(pos, 'tp'))
                
            result = mt5.order_send(request)  # type: ignore[attr-defined]
            if result and getattr(result, "retcode") == mt5.TRADE_RETCODE_DONE:  # type: ignore[attr-defined]
                return True
            return False
        except Exception as e:
            error_logger.error(f"MT5 modify_order error: {e}")
            return False

    # ---- Internals ----
    def _ensure_symbol_selected(self, symbol: str) -> None:
        try:
            si = mt5.symbol_info(symbol)  # type: ignore[attr-defined]
            if si is None:
                mt5.symbol_select(symbol, True)  # type: ignore[attr-defined]
            elif not getattr(si, "visible", True):
                mt5.symbol_select(symbol, True)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _to_mt5_timeframe(self, tf: str):
        tf = (tf or "M15").upper()
        cache = self._tf_cache
        if tf in cache:
            return cache[tf]
        try:
            const = {
                "M1": mt5.TIMEFRAME_M1,
                "M2": mt5.TIMEFRAME_M2,
                "M3": mt5.TIMEFRAME_M3,
                "M4": mt5.TIMEFRAME_M4,
                "M5": mt5.TIMEFRAME_M5,
                "M6": mt5.TIMEFRAME_M6,
                "M10": mt5.TIMEFRAME_M10,
                "M12": mt5.TIMEFRAME_M12,
                "M15": mt5.TIMEFRAME_M15,
                "M20": mt5.TIMEFRAME_M20,
                "M30": mt5.TIMEFRAME_M30,
                "H1": mt5.TIMEFRAME_H1,
                "H2": mt5.TIMEFRAME_H2,
                "H3": mt5.TIMEFRAME_H3,
                "H4": mt5.TIMEFRAME_H4,
                "H6": mt5.TIMEFRAME_H6,
                "H8": mt5.TIMEFRAME_H8,
                "H12": mt5.TIMEFRAME_H12,
                "D1": mt5.TIMEFRAME_D1,
                "W1": mt5.TIMEFRAME_W1,
                "MN1": mt5.TIMEFRAME_MN1,
            }  # type: ignore[attr-defined]
            cache[tf] = const.get(tf, mt5.TIMEFRAME_M15)  # type: ignore[attr-defined]
            return cache[tf]
        except Exception:
            return mt5.TIMEFRAME_M15  # type: ignore[attr-defined]

    def get_symbol_specs(self, symbol: str) -> Dict[str, float]:
        if self.paper_mode or not MT5_AVAILABLE:
            return {'point': 0.00001, 'tick_value': 1.0}  # default values for paper mode
        try:
            self._ensure_symbol_selected(symbol)
            info = mt5.symbol_info(symbol)  # type: ignore[attr-defined]
            if info is None:
                raise ValueError(f"Symbol {symbol} not found")
            return {
                'point': float(info.point),
                'tick_value': float(info.trade_tick_value)
            }
        except Exception as e:
            error_logger.error(f"Failed to get symbol specs for {symbol}: {e}")
            return {'point': 0.00001, 'tick_value': 1.0}