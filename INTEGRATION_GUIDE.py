# ─────────────────────────────────────────────────────────────
# INTEGRATION SNIPPET FOR core/trade_manager.py
#
# Add these two imports near the top of trade_manager.py:
#
#   from database.queries import TradeQueries, LogQueries
#
# Then in the two places shown below, add the DB write calls.
# Everything else in trade_manager.py stays exactly the same.
# ─────────────────────────────────────────────────────────────


# ── 1. After a trade is successfully placed ───────────────────
# Find the section in trade_manager.py where order placement
# succeeds (after connector.place_order returns a result).
# Add this block right after:

def _on_trade_opened(result, symbol, direction, lots,
                     entry_price, sl, tp, strategy, engine):
    """
    Call this right after connector.place_order() succeeds.
    `result` is whatever your MT5 connector returns (has .order / ticket).
    """
    from datetime import datetime

    TradeQueries.insert_trade({
        "ticket":      str(getattr(result, "order", result)),
        "symbol":      symbol,
        "direction":   direction,          # 'BUY' or 'SELL'
        "lots":        lots,
        "entry_price": entry_price,
        "sl":          sl,
        "tp":          tp,
        "strategy":    strategy,
        "engine":      engine,             # 'A', 'B', or None
        "open_time":   datetime.now().isoformat(timespec="seconds"),
    })

    LogQueries.insert_log(
        "TRADE",
        f"[TRADE] {direction} {symbol} {lots} lots @ {entry_price} "
        f"| SL: {sl} | TP: {tp} | Strategy: {strategy}"
    )


# ── 2. After a position is closed ────────────────────────────
# Find where trade_manager.py processes a closed position
# (after break-even, TP hit, SL hit, or manual close).
# Add this block right after:

def _on_trade_closed(ticket, exit_price, pnl, symbol):
    """
    Call this when a position is confirmed closed.
    """
    TradeQueries.close_trade(
        ticket=str(ticket),
        exit_price=exit_price,
        pnl=pnl,
    )

    outcome = "WIN" if pnl > 0 else "LOSS"
    LogQueries.insert_log(
        "TRADE",
        f"[CLOSE] {symbol} ticket={ticket} @ {exit_price} "
        f"| PnL: {pnl:+.2f} | {outcome}"
    )


# ── 3. For general bot log lines ─────────────────────────────
# Replace or supplement your existing logger calls with:
#
#   LogQueries.insert_log("INFO",  "[POLL] Scanned 18 symbols")
#   LogQueries.insert_log("WARN",  "[RISK] GBPJPY skipped — symbol cap")
#   LogQueries.insert_log("ERROR", "[BOT] MT5 connection lost")
#
# These go straight into SQLite and get pushed to the
# dashboard live log via SocketIO automatically.
