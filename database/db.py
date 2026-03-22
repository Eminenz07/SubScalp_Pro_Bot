import sqlite3
import os
from pathlib import Path

DB_PATH = Path(os.getenv('DB_PATH', str(Path(__file__).parent.parent / "data" / "subscalp.db")))


def get_db() -> sqlite3.Connection:
    """Return a SQLite connection with row_factory set."""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_db()
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket        TEXT UNIQUE,
                symbol        TEXT NOT NULL,
                direction     TEXT NOT NULL,
                lots          REAL NOT NULL,
                entry_price   REAL NOT NULL,
                exit_price    REAL,
                sl            REAL,
                tp            REAL,
                pnl           REAL,
                strategy      TEXT,
                engine        TEXT,
                status        TEXT DEFAULT 'open',
                open_time     TEXT NOT NULL,
                close_time    TEXT,
                created_at    TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                level      TEXT NOT NULL,
                message    TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS config (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS bot_state (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                running    INTEGER DEFAULT 0,
                strategy   TEXT DEFAULT 'IMPULSIVE_CROSSOVER',
                started_at TEXT,
                stopped_at TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            );

            INSERT OR IGNORE INTO bot_state (id, running, strategy)
            VALUES (1, 0, 'IMPULSIVE_CROSSOVER');
        """)
    conn.close()
