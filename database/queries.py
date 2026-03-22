import json
from datetime import datetime, date
from .db import get_db


class TradeQueries:

    @staticmethod
    def insert_trade(trade: dict) -> int:
        """Insert a new trade. Called by trade_manager.py after order placement."""
        trade['lots'] = round(float(trade.get('lots', 0.0)), 2)
        conn = get_db()
        with conn:
            cur = conn.execute("""
                INSERT OR IGNORE INTO trades
                    (ticket, symbol, direction, lots, entry_price, sl, tp,
                     strategy, engine, status, open_time)
                VALUES
                    (:ticket, :symbol, :direction, :lots, :entry_price, :sl, :tp,
                     :strategy, :engine, 'open', :open_time)
            """, trade)
        row_id = cur.lastrowid
        conn.close()
        return row_id

    @staticmethod
    def close_trade(ticket: str, exit_price: float, pnl: float):
        """Mark a trade as closed. Called by trade_manager.py after position close."""
        conn = get_db()
        with conn:
            conn.execute("""
                UPDATE trades
                SET exit_price = ?,
                    pnl        = ?,
                    status     = 'closed',
                    close_time = datetime('now')
                WHERE ticket = ?
            """, (exit_price, pnl, ticket))
        conn.close()

    @staticmethod
    def get_open_trades() -> list[dict]:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM trades WHERE status = 'open' ORDER BY open_time DESC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def get_trades(symbol: str = None, strategy: str = None,
                   days: int = 30, limit: int = 200) -> list[dict]:
        conn = get_db()
        filters, params = [], []
        filters.append("open_time >= datetime('now', ?)")
        params.append(f'-{days} days')
        if symbol:
            filters.append("symbol = ?")
            params.append(symbol)
        if strategy:
            filters.append("strategy = ?")
            params.append(strategy)
        where = "WHERE " + " AND ".join(filters) if filters else ""
        rows = conn.execute(
            f"SELECT * FROM trades {where} ORDER BY open_time DESC LIMIT ?",
            params + [limit]
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def get_daily_stats(days: int = 30) -> dict:
        """Returns aggregate stats for the dashboard stat cards."""
        conn = get_db()
        row = conn.execute("""
            SELECT
                COUNT(*)                                          AS total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)        AS wins,
                SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END)       AS losses,
                ROUND(SUM(pnl), 2)                               AS net_pnl,
                ROUND(AVG(CASE WHEN pnl > 0 THEN pnl END), 2)   AS avg_win,
                ROUND(AVG(CASE WHEN pnl <= 0 THEN pnl END), 2)  AS avg_loss,
                COUNT(CASE WHEN status = 'open' THEN 1 END)      AS open_positions
            FROM trades
            WHERE status = 'closed'
              AND open_time >= datetime('now', ?)
        """, (f'-{days} days',)).fetchone()
        conn.close()
        d = dict(row) if row else {}
        total = d.get('total_trades') or 0
        wins  = d.get('wins') or 0
        d['winrate'] = round(wins / total * 100, 1) if total > 0 else 0.0
        return d

    @staticmethod
    def get_daily_pnl(days: int = 14) -> list[dict]:
        """Returns day-by-day P&L for the bar chart."""
        conn = get_db()
        rows = conn.execute("""
            SELECT
                DATE(close_time)    AS day,
                ROUND(SUM(pnl), 2)  AS pnl
            FROM trades
            WHERE status = 'closed'
              AND close_time >= datetime('now', ?)
            GROUP BY DATE(close_time)
            ORDER BY day
        """, (f'-{days} days',)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def get_equity_curve(days: int = 30, starting_balance: float = 10000) -> list[dict]:
        """Returns running balance over time for the equity chart."""
        conn = get_db()
        rows = conn.execute("""
            SELECT close_time, pnl
            FROM trades
            WHERE status = 'closed'
              AND close_time >= datetime('now', ?)
            ORDER BY close_time
        """, (f'-{days} days',)).fetchall()
        conn.close()
        balance = starting_balance
        curve = [{"time": "start", "balance": balance}]
        for r in rows:
            balance += r["pnl"]
            curve.append({"time": r["close_time"], "balance": round(balance, 2)})
        return curve

    @staticmethod
    def get_today_trade_count() -> int:
        conn = get_db()
        row = conn.execute("""
            SELECT COUNT(*) AS cnt FROM trades
            WHERE DATE(open_time) = DATE('now') AND status != 'failed'
        """).fetchone()
        conn.close()
        return row["cnt"] if row else 0

    @staticmethod
    def get_strategy_stats() -> list[dict]:
        conn = get_db()
        rows = conn.execute("""
            SELECT
                strategy,
                COUNT(*)                                        AS trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)      AS wins,
                ROUND(SUM(pnl), 2)                             AS net_pnl,
                ROUND(AVG(CASE WHEN pnl > 0 THEN pnl END), 2) AS avg_win,
                ROUND(AVG(CASE WHEN pnl <=0 THEN pnl END), 2) AS avg_loss
            FROM trades
            WHERE status = 'closed'
            GROUP BY strategy
        """).fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d['winrate'] = round(d['wins'] / d['trades'] * 100, 1) if d['trades'] > 0 else 0
            result.append(d)
        return result


class LogQueries:

    @staticmethod
    def insert_log(level: str, message: str):
        conn = get_db()
        with conn:
            conn.execute(
                "INSERT INTO logs (level, message) VALUES (?, ?)",
                (level, message)
            )
        conn.close()

    @staticmethod
    def get_recent_logs(limit: int = 50) -> list[dict]:
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM logs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


class ConfigQueries:

    @staticmethod
    def get_all() -> dict:
        conn = get_db()
        rows = conn.execute("SELECT key, value FROM config").fetchall()
        conn.close()
        result = {}
        for r in rows:
            try:
                result[r["key"]] = json.loads(r["value"])
            except (json.JSONDecodeError, TypeError):
                result[r["key"]] = r["value"]
        return result

    @staticmethod
    def set(key: str, value):
        conn = get_db()
        with conn:
            conn.execute("""
                INSERT INTO config (key, value, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(key) DO UPDATE
                SET value = excluded.value, updated_at = excluded.updated_at
            """, (key, json.dumps(value)))
        conn.close()

    @staticmethod
    def set_many(data: dict):
        conn = get_db()
        with conn:
            for key, value in data.items():
                conn.execute("""
                    INSERT INTO config (key, value, updated_at)
                    VALUES (?, ?, datetime('now'))
                    ON CONFLICT(key) DO UPDATE
                    SET value = excluded.value, updated_at = excluded.updated_at
                """, (key, json.dumps(value)))
        conn.close()

    @staticmethod
    def get_bot_state() -> dict:
        conn = get_db()
        row = conn.execute("SELECT * FROM bot_state WHERE id = 1").fetchone()
        conn.close()
        return dict(row) if row else {}

    @staticmethod
    def set_bot_running(running: bool, strategy: str = None):
        conn = get_db()
        with conn:
            if running:
                conn.execute("""
                    UPDATE bot_state
                    SET running = 1, started_at = datetime('now'),
                        strategy = COALESCE(?, strategy), updated_at = datetime('now')
                    WHERE id = 1
                """, (strategy,))
            else:
                conn.execute("""
                    UPDATE bot_state
                    SET running = 0, stopped_at = datetime('now'),
                        updated_at = datetime('now')
                    WHERE id = 1
                """)
        conn.close()
