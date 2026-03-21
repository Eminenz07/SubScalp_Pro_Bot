import threading
import time
from flask_socketio import SocketIO, emit
from database.queries import TradeQueries, LogQueries, ConfigQueries


def register_events(socketio: SocketIO):

    @socketio.on("connect")
    def on_connect():
        """Push full state snapshot the moment a client connects."""
        _push_snapshot()

    @socketio.on("request_snapshot")
    def on_snapshot():
        _push_snapshot()

    def _push_snapshot():
        emit("snapshot", {
            "stats":       TradeQueries.get_daily_stats(),
            "open_trades": TradeQueries.get_open_trades(),
            "equity":      TradeQueries.get_equity_curve(),
            "bot_state":   ConfigQueries.get_bot_state(),
            "logs":        LogQueries.get_recent_logs(30),
        })

    # ── Background broadcaster ──────────────────────────────────────────
    # Runs in a daemon thread. Every 5 seconds it pushes:
    #   - Updated open positions (live P&L will come from MT5 connector)
    #   - Any new log lines
    #   - Bot state (running/stopped, strategy)
    # Every 30 seconds it also pushes fresh stats and equity.

    _last_log_id = {"value": 0}

    def _broadcast_loop():
        tick = 0
        while True:
            time.sleep(5)
            tick += 1
            try:
                # Always push open trades and new logs
                open_trades = TradeQueries.get_open_trades()
                new_logs    = _get_new_logs()
                bot_state   = ConfigQueries.get_bot_state()

                socketio.emit("live_update", {
                    "open_trades": open_trades,
                    "new_logs":    new_logs,
                    "bot_state":   bot_state,
                })

                # Every 6 ticks (30s) also push stats + equity refresh
                if tick % 6 == 0:
                    socketio.emit("stats_update", {
                        "stats":  TradeQueries.get_daily_stats(),
                        "equity": TradeQueries.get_equity_curve(),
                        "daily_pnl": TradeQueries.get_daily_pnl(),
                    })

            except Exception:
                pass  # Never crash the broadcast thread

    def _get_new_logs() -> list[dict]:
        """Only return logs newer than the last seen ID to avoid re-sending."""
        conn_logs = LogQueries.get_recent_logs(limit=100)
        if not conn_logs:
            return []
        new = [l for l in conn_logs if l["id"] > _last_log_id["value"]]
        if new:
            _last_log_id["value"] = max(l["id"] for l in new)
        return new

    broadcaster = threading.Thread(target=_broadcast_loop, daemon=True, name="ws-broadcaster")
    broadcaster.start()
