from flask import Blueprint, jsonify, request
from database.queries import TradeQueries

trades_bp = Blueprint("trades", __name__)


@trades_bp.route("/api/trades")
def get_trades():
    """
    Returns filtered trade history.
    Query params: symbol, strategy, days (default 30), limit (default 200)
    """
    symbol   = request.args.get("symbol")
    strategy = request.args.get("strategy")
    days     = int(request.args.get("days", 30))
    limit    = int(request.args.get("limit", 200))

    trades = TradeQueries.get_trades(
        symbol=symbol, strategy=strategy, days=days, limit=limit
    )
    return jsonify(trades)


@trades_bp.route("/api/trades/open")
def get_open_trades():
    return jsonify(TradeQueries.get_open_trades())


@trades_bp.route("/api/trades/stats")
def get_stats():
    days  = int(request.args.get("days", 30))
    stats = TradeQueries.get_daily_stats(days=days)
    return jsonify(stats)


@trades_bp.route("/api/trades/daily-pnl")
def daily_pnl():
    days = int(request.args.get("days", 14))
    data = TradeQueries.get_daily_pnl(days=days)
    return jsonify(data)


@trades_bp.route("/api/trades/strategy-stats")
def strategy_stats():
    data = TradeQueries.get_strategy_stats()
    return jsonify(data)
