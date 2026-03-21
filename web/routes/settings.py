from flask import Blueprint, jsonify, request
from database.queries import ConfigQueries

settings_bp = Blueprint("settings", __name__)

# These are the keys we allow the UI to read/write.
# Keeps the API surface explicit and safe.
ALLOWED_KEYS = {
    "risk_per_trade", "max_trades_per_day", "daily_loss_limit",
    "max_trades_per_symbol_per_day", "cooldown_candles_after_loss",
    "consecutive_sl_pause_count", "broker", "timeframe",
    "htf_trend_timeframe", "poll_interval",
    "winrate_pause_threshold", "winrate_lookback_trades", "strategy",
}


@settings_bp.route("/api/settings", methods=["GET"])
def get_settings():
    """Return all stored config values."""
    config = ConfigQueries.get_all()
    return jsonify(config)


@settings_bp.route("/api/settings", methods=["POST"])
def save_settings():
    """
    Save config values sent from the settings page.
    Only keys in ALLOWED_KEYS are accepted.
    """
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "No data provided"}), 400

    filtered = {k: v for k, v in data.items() if k in ALLOWED_KEYS}

    if not filtered:
        return jsonify({"error": "No valid config keys provided"}), 400

    ConfigQueries.set_many(filtered)
    return jsonify({"ok": True, "saved": list(filtered.keys())})
