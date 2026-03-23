from flask import Blueprint, render_template, jsonify
from database.queries import TradeQueries, LogQueries, ConfigQueries

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    """Serve the main dashboard UI."""
    return render_template("index.html")


@dashboard_bp.route("/api/dashboard/summary")
def summary():
    """
    Returns all data needed to populate the dashboard stat cards,
    open positions, survival rule statuses, and equity curve.
    """
    stats      = TradeQueries.get_daily_stats(days=30)
    open_trades = TradeQueries.get_open_trades()
    equity     = TradeQueries.get_equity_curve(days=30)
    bot_state  = ConfigQueries.get_bot_state()
    logs       = LogQueries.get_recent_logs(limit=30)

    today_pnl  = TradeQueries.get_today_pnl()
    stats["today_pnl"] = today_pnl

    return jsonify({
        "stats":       stats,
        "open_trades": open_trades,
        "equity":      equity,
        "bot_state":   bot_state,
        "logs":        logs,
    })


@dashboard_bp.route("/api/dashboard/equity")
def equity():
    days = 30
    curve = TradeQueries.get_equity_curve(days=days)
    return jsonify(curve)


@dashboard_bp.route("/api/dashboard/logs")
def logs():
    recent = LogQueries.get_recent_logs(limit=50)
    return jsonify(recent)


@dashboard_bp.route("/api/dashboard/account")
def account():
    import json
    import re
    from pathlib import Path
    from connectors import get_connector
    
    try:
        cfg_path = Path(__file__).parent.parent.parent / "config" / "config.json"
        content = re.sub(r'//.*', '', cfg_path.read_text(encoding="utf-8"))
        cfg = json.loads(content)
        
        broker = str(cfg.get("broker", "deriv")).lower()
        connector = get_connector(broker, cfg, {})
        connector.connect()
        info = connector.get_account_info()
        
        # deriv_connector has no disconnect method so we just let it go out of scope or close websocket
        if hasattr(connector, "disconnect"):
            connector.disconnect()
        elif hasattr(connector, "ws") and hasattr(connector.ws, "close"):
            connector.ws.close()
            
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e), "equity": 0}), 500
