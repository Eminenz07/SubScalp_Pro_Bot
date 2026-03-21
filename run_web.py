"""
run_web.py — Start the SubScalp WealthBot web dashboard.

Usage:
    python run_web.py                  # default port 5000
    python run_web.py --port 8080      # custom port
    python run_web.py --host 0.0.0.0   # expose on network (needed for Railway/Render)
"""
import argparse
import os
from dotenv import load_dotenv

load_dotenv()

from web.app import create_app, socketio


def main():
    parser = argparse.ArgumentParser(description="SubScalp WealthBot Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 5000)))
    parser.add_argument("--debug", action="store_true", default=False)
    args = parser.parse_args()

    app = create_app()

    print(f"""
  ╔══════════════════════════════════════╗
  ║   SubScalp WealthBot — Dashboard     ║
  ║   http://{args.host}:{args.port}             ║
  ╚══════════════════════════════════════╝
    """)

    socketio.run(
        app,
        host=args.host,
        port=args.port,
        debug=args.debug,
        use_reloader=False,   # Disable reloader — conflicts with bot thread
        allow_unsafe_werkzeug=True,
    )


if __name__ == "__main__":
    main()
