import os
from flask import Flask
from flask_socketio import SocketIO
from flask_cors import CORS
from database.db import init_db

socketio = SocketIO(cors_allowed_origins="*", async_mode="threading")


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "subscalp-dev-secret")

    CORS(app)
    socketio.init_app(app)

    # Ensure DB and tables exist
    init_db()

    # Register route blueprints
    from web.routes.dashboard import dashboard_bp
    from web.routes.trades import trades_bp
    from web.routes.settings import settings_bp
    from web.routes.bot_control import bot_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(trades_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(bot_bp)

    # Register SocketIO events
    from web.socket_events import register_events
    register_events(socketio)

    return app
