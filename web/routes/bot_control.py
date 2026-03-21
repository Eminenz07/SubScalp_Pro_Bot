import threading
from flask import Blueprint, jsonify, request
from database.queries import ConfigQueries, LogQueries

bot_bp = Blueprint("bot", __name__)

# This will hold a reference to the running bot thread
_bot_thread: threading.Thread | None = None
_bot_stop_event = threading.Event()


def _run_bot(strategy: str, stop_event: threading.Event):
    """
    Target function for the bot thread.
    Imports and runs main.py's polling loop in a controlled way.
    stop_event is checked each cycle so the UI can cleanly stop the bot.
    """
    try:
        LogQueries.insert_log("INFO", f"[BOT] Starting with strategy: {strategy}")
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # Import the bot's run function — adjust this import to match
        # whatever your main.py exposes (e.g. run_bot(strategy, stop_event))
        from main import run_bot
        run_bot(strategy=strategy, stop_event=stop_event)

    except Exception as e:
        LogQueries.insert_log("ERROR", f"[BOT] Crashed: {str(e)}")
        ConfigQueries.set_bot_running(False)


@bot_bp.route("/api/bot/status")
def bot_status():
    state = ConfigQueries.get_bot_state()
    return jsonify(state)


@bot_bp.route("/api/bot/start", methods=["POST"])
def start_bot():
    global _bot_thread, _bot_stop_event

    state = ConfigQueries.get_bot_state()
    if state.get("running"):
        return jsonify({"ok": False, "error": "Bot is already running"}), 409

    data     = request.get_json(force=True) or {}
    strategy = data.get("strategy", state.get("strategy", "IMPULSIVE_CROSSOVER"))

    _bot_stop_event = threading.Event()
    _bot_thread = threading.Thread(
        target=_run_bot,
        args=(strategy, _bot_stop_event),
        daemon=True,
        name="subscalp-bot"
    )
    _bot_thread.start()
    ConfigQueries.set_bot_running(True, strategy=strategy)
    LogQueries.insert_log("INFO", f"[BOT] Started via web UI · Strategy: {strategy}")

    return jsonify({"ok": True, "strategy": strategy})


@bot_bp.route("/api/bot/stop", methods=["POST"])
def stop_bot():
    global _bot_thread, _bot_stop_event

    state = ConfigQueries.get_bot_state()
    if not state.get("running"):
        return jsonify({"ok": False, "error": "Bot is not running"}), 409

    if _bot_stop_event:
        _bot_stop_event.set()

    ConfigQueries.set_bot_running(False)
    LogQueries.insert_log("INFO", "[BOT] Stopped via web UI")

    return jsonify({"ok": True})
