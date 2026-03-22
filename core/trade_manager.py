from __future__ import annotations
from typing import Dict, Optional, Any, List
from datetime import datetime
import math
import random

from utils.logger import trade_logger, error_logger
from notifications.notifier import Notifier
from notifications.enums import EventType, Severity
from .risk_manager import RiskManager
from .break_even_manager import BreakEvenManager
from .engine_analytics import EngineAnalytics
from database.queries import TradeQueries, LogQueries


class TradeManager:
    """
    Coordinates signal handling, risk-based sizing, and order execution via a connector.

    The core responsibility is to:
    1. Determine the appropriate trade size using the RiskManager, potentially adjusting for 'Engine' risk.
    2. Apply pre-trade filters (Spread, Volatility).
    3. Execute trade orders (including single or partial-profit orders) via the Connector.
    4. Monitor and manage open positions (e.g., applying break-even stop-loss).
    5. Record trade results in RiskManager and EngineAnalytics.
    
    Expects each latest data row to contain keys: 'close', 'signal', 'sl_distance', 'tp_distance', and optionally 'engine'.
    """

    def __init__(self, config: Dict[str, Any], connector: Any, risk_manager: RiskManager, breakeven: BreakEvenManager | None = None, analytics: EngineAnalytics | None = None, notifier: Notifier | None = None):
        """
        Initializes the TradeManager with configuration and dependencies.

        :param config: Dictionary containing general configuration.
        :param connector: An object responsible for connecting to the broker/exchange.
        :param risk_manager: An instance of RiskManager for trade sizing and exposure limits.
        :param breakeven: An optional instance of BreakEvenManager for stop-loss adjustment.
        :param analytics: An optional instance of EngineAnalytics for performance tracking.
        :param notifier: An optional instance of Notifier for centralized notifications.
        """
        self.config = config
        self.connector = connector
        self.risk = risk_manager
        self.breakeven = breakeven
        self.analytics = analytics or EngineAnalytics(config)
        self.notifier = notifier
        # Changed to support multiple sub-positions (for partial TP) per symbol
        self.open_positions: Dict[str, List[Dict[str, Any]]] = {} 

    ## --- Internal Helper Methods ---

    def _equity(self) -> float:
        """
        Fetch current account equity from the connector. 
        Falls back to the configuration value if fetching fails.
        """
        try:
            info = self.connector.get_account_info()
            eq = float(info.get("equity"))
            if math.isfinite(eq) and eq > 0:
                return eq
        except Exception as e:
            error_logger.error(f"get_account_info error: {e}")
        # Fallback
        return float(self.config.get("equity", 0))

    def _notify_event(self, event: EventType, severity: Severity, payload: Dict[str, Any]) -> None:
        """Helper to dispatch notifications if notifier is present."""
        if self.notifier:
            self.notifier.notify(event, severity, payload)
        
        # Also log to file as before
        message = payload.get("message")
        if message:
            trade_logger.info(message)

    def _position_side(self, symbol: str) -> Optional[str]:
        """
        Returns the side ('buy' or 'sell') of an open position for a given symbol, 
        or None. Assumes all sub-positions for a symbol have the same side.
        """
        positions = self.open_positions.get(symbol)
        return positions[0].get("side") if positions else None

    def _compute_size(self, symbol: str, sl_distance: float, engine: Optional[str] = None) -> float:
        r"""
        Calculates the trade size (in lots/contracts) based on risk per trade,
        account equity, and the stop-loss distance.
        
        Formula: $size = \frac{Equity \times Risk_{Percent}} {Loss_{if\_SL\_hit}}$ 
        
        
        :param sl_distance: The distance from entry price to the Stop-Loss (in price units).
        :param engine: The trading engine ('A' or 'B') which may modify the risk percentage.
        :return: The calculated size (volume) for the trade.
        """
        equity = self._equity()
        symbol_specs = self.connector.get_symbol_specs(symbol)
        point = symbol_specs.get('point', 0.00001)
        tick_value = symbol_specs.get('tick_value', 1.0)
        
        if sl_distance <= 0 or point <= 0 or tick_value <= 0:
            return 0.0
            
        risk_amount = equity * self.risk.config.risk_per_trade
        
        # Apply engine-specific risk reduction
        if engine == "B":
            risk_amount *= 0.8  # 20% less risk for Engine B
        
        points_in_sl = sl_distance / point
        
        # Loss per lot/contract if SL is hit
        loss_if_sl_hit = tick_value * points_in_sl 
        
        # Calculate size required to risk only risk_amount
        size = risk_amount / loss_if_sl_hit
        
        return max(0.0, float(size))
    
    def _apply_slippage(self, price: float, symbol: str, engine: Optional[str] = None) -> float:
        """Apply randomized slippage based on symbol volatility and engine type."""
        try:
            symbol_specs = self.connector.get_symbol_specs(symbol)
            point = symbol_specs.get('point', 0.00001)
            atr_val = self._get_atr_for_symbol(symbol)
            
            if atr_val > 0 and point > 0:
                # Slippage range: 0.1-0.3 ATR for Engine A, 0.2-0.4 ATR for Engine B
                min_mult = 0.2 if engine == "B" else 0.1
                max_mult = 0.4 if engine == "B" else 0.3
                slippage_points = random.uniform(min_mult, max_mult) * atr_val / point
                slippage_price = slippage_points * point
                
                # Random direction (positive or negative)
                return price + (slippage_price if random.choice([True, False]) else -slippage_price)
        except Exception:
            pass
        return price
    
    def _get_atr_for_symbol(self, symbol: str) -> float:
        """Get cached ATR value for slippage and volatility filter calculation."""
        # Note: In a real system, this fetches live ATR from market data.
        return 0.0005  # 5 pips default for forex (example value)
    
    def _check_spread_filter(self, symbol: str, engine: Optional[str] = None) -> bool:
        """Check if spread is within acceptable limits for the engine."""
        try:
            spread = float(getattr(self.connector, 'get_current_spread', lambda s: 0.0)(symbol))
            symbol_specs = self.connector.get_symbol_specs(symbol)
            point = symbol_specs.get('point', 0.00001)
            
            # Convert spread to pips
            spread_pips = spread / point if point > 0 else 0
            
            # Engine B has stricter spread limits (2.0 pips vs 5.0 pips for A)
            max_spread_pips = 2.0 if engine == "B" else 5.0
            
            return spread_pips <= max_spread_pips
        except Exception:
            return True  # Allow trade if we can't check spread
    
    def _check_volatility_filter(self, symbol: str, engine: Optional[str] = None) -> bool:
        """Check if volatility (ATR in pips) is within acceptable limits for the engine."""
        try:
            atr_val = self._get_atr_for_symbol(symbol)
            symbol_specs = self.connector.get_symbol_specs(symbol)
            point = symbol_specs.get('point', 0.00001)
            
            if atr_val > 0 and point > 0:
                atr_pips = atr_val / point
                
                # Engine B has stricter volatility limits (15.0 pips vs 25.0 pips for A)
                max_atr_pips = 15.0 if engine == "B" else 25.0
                
                return atr_pips <= max_atr_pips
        except Exception:
            pass 
        return True # Allow trade if we can't check volatility

    ## --- Core Trading Methods ---

    def open_position(self, symbol: str, side: str, price: float, sl_distance: float, tp_distance: float, row: Dict[str, Any], engine: Optional[str] = None) -> Optional[str]:
        """
        Opens a new position, supporting single or split (partial TP) orders.

        :param row: The signal row, may contain partial_tp_distance and partial_fraction.
        :param engine: The trading engine initiating the trade (e.g., 'A' or 'B').
        :return: The first order/contract ID if successful, otherwise None.
        """
        # --- Pre-Trade Checks ---
        if not self.risk.can_trade(equity=self._equity(), symbol=symbol, engine=engine):
            self._notify_event(EventType.MAX_TRADES_REACHED, Severity.WARNING, {"message": f"Risk limits prevent new trade. Ignored {symbol} {side}.", "symbol": symbol})
            return None
        
        if not self._check_spread_filter(symbol, engine):
            self._notify_event(EventType.TRADING_PAUSED, Severity.INFO, {"message": f"Spread too high for {symbol}. Trade blocked.", "symbol": symbol})
            return None
        
        if not self._check_volatility_filter(symbol, engine):
            self._notify_event(EventType.TRADING_PAUSED, Severity.INFO, {"message": f"Volatility too high for {symbol}. Trade blocked.", "symbol": symbol})
            return None
        
        # Apply slippage to entry price
        price = self._apply_slippage(price, symbol, engine)
        
        # Calculate size based on risk per trade
        size = self._compute_size(symbol, sl_distance, engine)
        if size <= 0:
            self._notify_event(EventType.TRADING_PAUSED, Severity.WARNING, {"message": f"Calculated size is 0. Skipping trade for {symbol}.", "symbol": symbol})
            return None

        # Determine SL price level
        side = side.lower()
        if side == "buy":
            sl = max(0.0, price - sl_distance)
        else: # side == "sell"
            sl = price + sl_distance

        order_ids: List[Any] = []
        self.open_positions[symbol] = []

        # --- Partial Profit Logic (Engine B only example) ---
        if "partial_tp_distance" in row and row["partial_tp_distance"] > 0 and engine == "B":
            partial_fraction = row.get("partial_fraction", 0.5)
            partial_size = size * partial_fraction
            full_size = size - partial_size
            partial_tp_distance = row["partial_tp_distance"]

            # Calculate partial and full TP price levels
            if side == "buy":
                partial_tp = price + partial_tp_distance
                full_tp = price + tp_distance
            else:
                partial_tp = price - partial_tp_distance
                full_tp = price - tp_distance

            # 1. Place partial order (smaller TP)
            try:
                order1 = self.connector.place_order(symbol=symbol, side=side, size=partial_size, sl=sl, tp=partial_tp)
                if order1:
                    self.open_positions[symbol].append({
                        "contract_id": order1, "side": side, "entry_price": float(price), "size": float(partial_size),
                        "sl": float(sl), "tp": float(partial_tp), "breakeven_triggered": False,
                        "engine": engine, "partial_closed": False, "is_partial": True
                    })
                    order_ids.append(order1)
                    # ── DB: record partial trade open ──
                    try:
                        TradeQueries.insert_trade({
                            "ticket": str(order1), "symbol": symbol,
                            "direction": side.upper(), "lots": round(partial_size, 2),
                            "entry_price": price, "sl": sl, "tp": partial_tp,
                            "strategy": row.get("strategy", "UNKNOWN"), "engine": engine,
                            "open_time": datetime.now().isoformat(timespec="seconds"),
                        })
                        LogQueries.insert_log("TRADE", f"[TRADE] {side.upper()} {symbol} {partial_size} lots @ {price} | SL: {sl} | TP: {partial_tp} | Engine: {engine} (partial)")
                    except Exception as db_err:
                        error_logger.error(f"DB insert_trade error (partial): {db_err}")
            except Exception as e:
                error_logger.error(f"Partial place_order failed: {e}")

            # 2. Place full order (larger TP)
            try:
                order2 = self.connector.place_order(symbol=symbol, side=side, size=full_size, sl=sl, tp=full_tp)
                if order2:
                    self.open_positions[symbol].append({
                        "contract_id": order2, "side": side, "entry_price": float(price), "size": float(full_size),
                        "sl": float(sl), "tp": float(full_tp), "breakeven_triggered": False,
                        "engine": engine, "partial_closed": False, "is_partial": False
                    })
                    order_ids.append(order2)
                    # ── DB: record full trade open ──
                    try:
                        TradeQueries.insert_trade({
                            "ticket": str(order2), "symbol": symbol,
                            "direction": side.upper(), "lots": round(full_size, 2),
                            "entry_price": price, "sl": sl, "tp": full_tp,
                            "strategy": row.get("strategy", "UNKNOWN"), "engine": engine,
                            "open_time": datetime.now().isoformat(timespec="seconds"),
                        })
                        LogQueries.insert_log("TRADE", f"[TRADE] {side.upper()} {symbol} {full_size} lots @ {price} | SL: {sl} | TP: {full_tp} | Engine: {engine}")
                    except Exception as db_err:
                        error_logger.error(f"DB insert_trade error (full): {db_err}")
            except Exception as e:
                error_logger.error(f"Full place_order failed: {e}")

            if order_ids:
                payload = {
                    "symbol": symbol,
                    "order_type": side,
                    "volume": f"{partial_size:.4f}/{full_size:.4f}",
                    "price": price,
                    "sl": sl,
                    "tp": f"{partial_tp:.5f}/{full_tp:.5f}",
                    "strategy": engine,
                    "message": f"Opened partial {side} {symbol} (Engine {engine})"
                }
                self._notify_event(EventType.TRADE_OPEN, Severity.INFO, payload)
        
        # --- Normal Single Order Logic ---
        else:
            if side == "buy":
                tp = price + tp_distance
            else:
                tp = price - tp_distance

            try:
                order_id = self.connector.place_order(symbol=symbol, side=side, size=size, sl=sl, tp=tp)
                if order_id:
                    self.open_positions[symbol].append({
                        "contract_id": order_id, "side": side, "entry_price": float(price), "size": float(size),
                        "sl": float(sl), "tp": float(tp), "breakeven_triggered": False,
                        "engine": engine, "partial_closed": False, "is_partial": False
                    })
                    order_ids.append(order_id)
                    payload = {
                        "symbol": symbol,
                        "order_type": side,
                        "volume": size,
                        "price": price,
                        "sl": sl,
                        "tp": tp,
                        "strategy": engine,
                        "message": f"Opened {side} {symbol} (Engine {engine})"
                    }
                    self._notify_event(EventType.TRADE_OPEN, Severity.INFO, payload)
                    # ── DB: record trade open ──
                    try:
                        TradeQueries.insert_trade({
                            "ticket": str(order_id), "symbol": symbol,
                            "direction": side.upper(), "lots": round(size, 2),
                            "entry_price": price, "sl": sl, "tp": tp,
                            "strategy": row.get("strategy", "UNKNOWN"), "engine": engine,
                            "open_time": datetime.now().isoformat(timespec="seconds"),
                        })
                        LogQueries.insert_log("TRADE", f"[TRADE] {side.upper()} {symbol} {size} lots @ {price} | SL: {sl} | TP: {tp} | Engine: {engine}")
                    except Exception as db_err:
                        error_logger.error(f"DB insert_trade error: {db_err}")
            except Exception as e:
                error_logger.error(f"place_order failed: {e}")

        # --- Post-Order Registration ---
        if order_ids:
            # Register with RiskManager (using the symbol to manage aggregate risk)
            try:
                self.risk.register_open_trade(symbol, engine=engine)
            except Exception as e:
                error_logger.error(f"register_open_trade error: {e}")
                
            return order_ids[0]  # Return first order_id
        else:
            self._notify_event(EventType.WARNING, Severity.WARNING, {"message": f"Order rejected for {symbol}.", "symbol": symbol})
            # Clean up if symbol entry was created but no orders placed
            if symbol in self.open_positions and not self.open_positions[symbol]:
                del self.open_positions[symbol]
            
        return None

    def close_position(self, symbol: str, price: float, reason: str = "signal") -> bool:
        """
        Closes *all* open sub-positions for a given symbol.

        :return: True if at least one position was successfully closed, False otherwise.
        """
        positions_to_close = self.open_positions.get(symbol, [])
        if not positions_to_close:
            return False
            
        success_count = 0
        
        positions_to_keep = []
        
        # Close all constituent orders
        for pos in positions_to_close:
            try:
                ok = self.connector.close_order(pos["contract_id"])
            except Exception as e:
                error_logger.error(f"close_order failed for {pos['contract_id']}: {e}")
                ok = False

            if ok:
                success_count += 1
                
                # Calculate PnL (estimated)
                pnl = 0.0
                try:
                    if pos["side"] == "buy":
                        pnl = (float(price) - pos["entry_price"]) * pos["size"]
                    else:
                        pnl = (pos["entry_price"] - float(price)) * pos["size"]
                except Exception:
                    pnl = 0.0
                    
                payload = {
                    "symbol": symbol,
                    "order_type": pos["side"],
                    "price": price,
                    "profit": pnl,
                    "strategy": pos.get("engine"),
                    "duration": "N/A",
                    "message": f"Closed sub-position {pos['side']} {symbol} ({reason})"
                }
                self._notify_event(EventType.TRADE_CLOSE, Severity.INFO, payload)
                
                # ── DB: record trade close ──
                try:
                    TradeQueries.close_trade(ticket=str(pos["contract_id"]), exit_price=float(price), pnl=pnl)
                    outcome = "WIN" if pnl > 0 else "LOSS"
                    LogQueries.insert_log("TRADE", f"[CLOSE] {symbol} ticket={pos['contract_id']} @ {price} | PnL: {pnl:+.2f} | {outcome}")
                except Exception as db_err:
                    error_logger.error(f"DB close_trade error: {db_err}")
                
                # Register trade result with RiskManager and Analytics
                try:
                    tf = str(self.config.get("timeframe", "M5"))
                    tf_minutes = 5 if tf.upper().startswith("M5") else 15 if tf.upper().startswith("M15") else 5
                    self.risk.register_trade_result(symbol, pnl, candle_time=None, timeframe_minutes=tf_minutes, engine=pos.get("engine"))
                    
                    self.analytics.record_trade(
                        engine=pos.get("engine", "unknown"),
                        symbol=symbol, side=pos["side"], entry_price=pos["entry_price"],
                        exit_price=price, pnl=pnl, reason=reason
                    )
                except Exception as e:
                    error_logger.error(f"Analytics/Risk update error: {e}")
            else:
                # Keep tracking if the close failed
                positions_to_keep.append(pos)
        
        # Update symbol tracking
        if positions_to_keep:
            self.open_positions[symbol] = positions_to_keep
        else:
            self.open_positions.pop(symbol, None)
            
        return success_count > 0

    def process_signal(self, symbol: str, row: Dict[str, Any]) -> bool:
        """
        Processes a single latest signal row for one symbol.
        """
        if not row:
            return False

        # --- Input Validation and Parsing ---
        try:
            signal = int(row.get("signal", 0))
            price = float(row.get("close"))
            sl_distance = float(row.get("sl_distance", 0))
            tp_distance = float(row.get("tp_distance", 0))
            engine = row.get("engine")
            
            trade_logger.debug(f"Signal process for {symbol} (Engine {engine}): signal={signal}, price={price}")
            
            if not (math.isfinite(sl_distance) and math.isfinite(tp_distance)) or sl_distance <= 0 or tp_distance <= 0:
                error_logger.warning(f"Invalid or non-positive distances for {symbol}. Skipping decision.")
                return False
                
        except Exception as e:
            error_logger.error(f"Invalid row structure or data type for {symbol}: {e}")
            return False

        current = self._position_side(symbol)
        opened = False

        # --- Invalidate Signal Logic (Close on Neutral/Exit Signal) ---
        if row.get("invalidate", False):
            if current:
                self.close_position(symbol, row["close"], row.get("close_reason", "signal_invalidation"))
            return False

        # --- Trading Logic ---
        if signal > 0: # Buy/Long Signal
            if current == "buy":
                return False 
            
            if current == "sell":
                self.close_position(symbol, price, reason="reverse_to_long")
                
            opened = self.open_position(symbol, "buy", price, sl_distance, tp_distance, row, engine=engine)

        elif signal < 0: # Sell/Short Signal
            if current == "sell":
                return False
            
            if current == "buy":
                self.close_position(symbol, price, reason="reverse_to_short")
                
            opened = self.open_position(symbol, "sell", price, sl_distance, tp_distance, row, engine=engine)

        # signal == 0: Neutral signal, keep current position.
        return bool(opened)

    def get_open_positions(self) -> Dict[str, List[Dict[str, Any]]]:
        """Returns a copy of the dictionary of currently tracked open positions."""
        return dict(self.open_positions)

    def monitor_positions(self) -> None:
        """
        Monitors open positions, checking if they were closed externally (SL/TP hit)
        or if a break-even stop-loss adjustment is necessary.
        
        Handles individual sub-positions for partial TP trades.
        """
        
        # --- MT5-Style Monitoring (Assumes Broker handles SL/TP but we track local state) ---
        if hasattr(self.connector, 'get_open_positions'):
            try:
                # 1. Get current *actual* open positions from the broker (by ID is safer for multi-position strategy)
                current_positions = {p['contract_id']: p for p in self.connector.get_open_positions()}
                
                symbols_to_delete: List[str] = []

                for symbol, positions in list(self.open_positions.items()):
                    new_positions: List[Dict[str, Any]] = []
                    
                    for pos in positions:
                        contract_id = pos['contract_id']
                        
                        if contract_id not in current_positions:
                            # Position was closed externally (SL/TP hit or manual close)
                            reason = "tp_sl_hit" 
                            pnl = 0.0 # Cannot get accurate PnL from here

                            self._notify_event(EventType.TRADE_CLOSE, Severity.INFO, {
                                "symbol": symbol,
                                "order_type": pos["side"],
                                "price": "External",
                                "profit": pnl,
                                "strategy": pos.get("engine"),
                                "message": f"Closed sub-position {pos['side']} {symbol} externally ({reason})"
                            })
                            
                            # ── DB: record externally closed trade ──
                            try:
                                TradeQueries.close_trade(ticket=str(contract_id), exit_price=0.0, pnl=pnl)
                                LogQueries.insert_log("TRADE", f"[CLOSE] {symbol} ticket={contract_id} closed externally | PnL: {pnl:+.2f}")
                            except Exception as db_err:
                                error_logger.error(f"DB close_trade error (external): {db_err}")
                            
                            # Register a zero-pnl trade result to update risk limits/analytics
                            try:
                                self.risk.register_trade_result(symbol, pnl, engine=pos.get("engine")) 
                                self.analytics.record_trade(
                                    engine=pos.get("engine", "unknown"), symbol=symbol, side=pos["side"], 
                                    entry_price=pos["entry_price"], exit_price=0.0, pnl=pnl, reason=reason
                                )
                            except Exception as e:
                                error_logger.error(f"register_trade_result error: {e}")
                            
                            continue # Don't add to new_positions list
                        else:
                            # Position is still open, check for break-even adjustment
                            if self.breakeven and not pos.get('breakeven_triggered', False):
                                try:
                                    current_price = float(self.connector.get_current_price(symbol))
                                    if not math.isfinite(current_price):
                                        new_positions.append(pos)
                                        continue
                                except Exception as e:
                                    error_logger.error(f"Failed to get current price for {symbol}: {e}")
                                    new_positions.append(pos)
                                    continue

                                # --- Break-Even Logic ---
                                entry = pos['entry_price']
                                side = pos['side']
                                initial_sl = pos['sl']
                                initial_tp = pos['tp']
                                spread = float(getattr(self.connector, 'get_current_spread', lambda s: 0.0)(symbol))
                                is_deriv = str(self.config.get('broker', '')).lower() == 'deriv' 

                                new_sl = self.breakeven.adjust_stop_loss(
                                    side, float(entry), float(current_price), float(initial_sl), float(initial_tp), 
                                    float(spread), is_deriv
                                )
                                
                                # Check if new SL is better than current SL
                                sl_modified = (side == 'buy' and new_sl > pos['sl']) or \
                                              (side == 'sell' and new_sl < pos['sl'])
                                
                                if sl_modified:
                                    try:
                                        self.connector.modify_order(contract_id, sl=new_sl)
                                        pos['sl'] = new_sl
                                        pos['breakeven_triggered'] = True
                                        self._notify_event(EventType.INFO, Severity.INFO, {
                                            "message": f"Breakeven adjusted for {side} {symbol} (ID: {contract_id}), new SL={new_sl:.5f}",
                                            "symbol": symbol
                                        })
                                    except Exception as e:
                                        error_logger.error(f"Modify SL failed for {symbol}: {e}")
                            
                            # Add position back to the list of active positions
                            new_positions.append(pos)

                    # Update or remove the symbol entry
                    if new_positions:
                        self.open_positions[symbol] = new_positions
                    else:
                        symbols_to_delete.append(symbol)

                # Final cleanup of empty symbol entries
                for symbol in symbols_to_delete:
                    if symbol in self.open_positions:
                        del self.open_positions[symbol]
                        
            except Exception as e:
                error_logger.error(f"MT5 position monitoring error: {e}")
                
        # --- Legacy Deriv-style Monitoring (Kept for compatibility) ---
        else:
            for symbol, positions in list(self.open_positions.items()):
                positions_to_keep: List[Dict[str, Any]] = []
                
                for pos in positions:
                    contract_id = str(pos.get("contract_id", ""))
                    if not contract_id:
                        continue
                        
                    # Skip paper positions (which are UUIDs)
                    if not contract_id.isdigit():
                        positions_to_keep.append(pos)
                        continue
                        
                    # Get details of the contract/order
                    details = self.connector.get_contract_details(int(contract_id))
                    if not details:
                        positions_to_keep.append(pos) # Assume still open if details unavailable
                        continue
                        
                    status = details.get("status")
                    
                    if status == "open":
                        positions_to_keep.append(pos)
                        continue
                    
                    if status == "sold" or details.get("is_expired"):
                        # Position was closed by the broker
                        exit_spot = details.get("sell_spot", details.get("sell_price", details.get("current_spot", pos.get("entry_price", 0))))
                        entry_spot = details.get("buy_price", pos.get("entry_price", 0))
                        
                        try:
                            pnl = float(details.get("profit", float(exit_spot) - float(entry_spot)))
                        except:
                            pnl = 0.0
                        
                        # Estimate reason for closure 
                        tp_dist = abs(exit_spot - pos["tp"])
                        sl_dist = abs(exit_spot - pos["sl"])
                        reason = "take_profit" if tp_dist < sl_dist else "stop_loss"
                        
                        if tp_dist > 0.001 and sl_dist > 0.001:
                            reason = "unknown"
                            
                        self._notify_event(EventType.TRADE_CLOSE, Severity.INFO, {
                            "symbol": symbol,
                            "order_type": pos["side"],
                            "price": exit_spot,
                            "profit": pnl,
                            "strategy": pos.get("engine"),
                            "message": f"Closed {pos['side']} {symbol} at {exit_spot:.5f} ({reason})"
                        })
                        
                        # ── DB: record Deriv closed trade ──
                        try:
                            TradeQueries.close_trade(ticket=str(contract_id), exit_price=float(exit_spot), pnl=pnl)
                            outcome = "WIN" if pnl > 0 else "LOSS"
                            LogQueries.insert_log("TRADE", f"[CLOSE] {symbol} ticket={contract_id} @ {exit_spot} | PnL: {pnl:+.2f} | {outcome}")
                        except Exception as db_err:
                            error_logger.error(f"DB close_trade error (Deriv): {db_err}")
                        
                        # Register trade result with RiskManager and Analytics
                        try:
                            tf = str(self.config.get("timeframe", "M5"))
                            tf_minutes = 5 if tf.upper().startswith("M5") else 15 if tf.upper().startswith("M15") else 5
                            self.risk.register_trade_result(symbol, pnl, candle_time=None, timeframe_minutes=tf_minutes, engine=pos.get("engine"))
                            self.analytics.record_trade(
                                engine=pos.get("engine", "unknown"), symbol=symbol, side=pos["side"], 
                                entry_price=pos["entry_price"], exit_price=exit_spot, pnl=pnl, reason=reason
                            )
                        except Exception as e:
                            error_logger.error(f"Analytics/Risk update error: {e}")
                        
                        # Do not append to positions_to_keep (position is closed)

                # Update or remove symbol entry
                if positions_to_keep:
                    self.open_positions[symbol] = positions_to_keep
                else:
                    del self.open_positions[symbol]