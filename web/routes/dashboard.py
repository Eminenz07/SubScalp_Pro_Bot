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
