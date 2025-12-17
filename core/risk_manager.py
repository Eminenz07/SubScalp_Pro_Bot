from __future__ import annotations
from dataclasses import dataclass
import datetime as dt
from typing import Optional
from notifications.notifier import Notifier
from notifications.enums import EventType, Severity


@dataclass
class RiskConfig:
    risk_per_trade: float = 0.01
    max_trades_per_day: int = 5
    daily_loss_limit: float = 0.05
    max_trades_per_symbol_per_day: int = 2
    cooldown_candles_after_loss: int = 5
    max_engine_b_trades_per_day: int = 2
    max_engine_b_per_symbol_per_day: int = 1
    engine_b_cooldown_candles_after_loss: int = 10


class RiskManager:
    def __init__(self, config: RiskConfig, notifier: Notifier | None = None):
        self.config = config
        self.notifier = notifier
        self.daily_trade_count = 0
        self.current_daily_loss = 0.0
        self._current_day: dt.date | None = None
        self.symbol_trade_counts: dict[str, int] = {}
        self.cooldowns: dict[str, dt.datetime] = {}
        self.engine_daily_counts: dict[str, int] = {}
        self.symbol_engine_counts: dict[tuple[str,str], int] = {}
        # Notification flags to prevent spam
        self._max_trades_notified = False
        self._daily_loss_notified = False

    def _maybe_reset_day(self) -> None:
        today = dt.date.today()
        if self._current_day != today:
            self._current_day = today
            self.daily_trade_count = 0
            self.current_daily_loss = 0.0
            self.engine_daily_counts.clear()
            self.symbol_engine_counts.clear()
            self._max_trades_notified = False
            self._daily_loss_notified = False

    def can_trade(self, equity: float, symbol: str | None = None, engine: Optional[str] = None) -> bool:
        self._maybe_reset_day()
        if self.daily_trade_count >= self.config.max_trades_per_day:
            if self.notifier and not self._max_trades_notified:
                self.notifier.notify(
                    EventType.MAX_TRADES_REACHED, 
                    Severity.WARNING, 
                    {"message": f"Daily max trades limit ({self.config.max_trades_per_day}) reached. Trading paused."}
                )
                self._max_trades_notified = True
            return False
        if engine == "B":
            if self.engine_daily_counts.get("B", 0) >= self.config.max_engine_b_trades_per_day:
                return False
            if symbol and self.symbol_engine_counts.get((symbol, "B"), 0) >= self.config.max_engine_b_per_symbol_per_day:
                return False
        if equity > 0:
            loss_fraction = (-self.current_daily_loss) / equity if self.current_daily_loss < 0 else 0.0
            if loss_fraction >= self.config.daily_loss_limit:
                if self.notifier and not self._daily_loss_notified:
                    self.notifier.notify(
                        EventType.DAILY_LOSS_LIMIT_HIT,
                        Severity.CRITICAL,
                        {
                            "message": f"Daily loss limit ({self.config.daily_loss_limit:.1%}) hit. Loss: {loss_fraction:.1%}",
                            "current_loss": self.current_daily_loss,
                            "equity": equity
                        }
                    )
                    self._daily_loss_notified = True
                return False
        if symbol:
            if self.symbol_trade_counts.get(symbol, 0) >= self.config.max_trades_per_symbol_per_day:
                return False
            cd = self.cooldowns.get(symbol)
            if cd and dt.datetime.now() < cd:
                return False
        return True

    def register_open_trade(self, symbol: str, engine: Optional[str] = None) -> None:
        self._maybe_reset_day()
        self.symbol_trade_counts[symbol] = self.symbol_trade_counts.get(symbol, 0) + 1
        self.daily_trade_count += 1
        if engine:
            self.engine_daily_counts[engine] = self.engine_daily_counts.get(engine, 0) + 1
            if symbol:
                key = (symbol, engine)
                self.symbol_engine_counts[key] = self.symbol_engine_counts.get(key, 0) + 1

    def register_trade_result(self, symbol: str, pnl: float, candle_time: dt.datetime | None = None, timeframe_minutes: int = 5, engine: Optional[str] = None) -> None:
        self._maybe_reset_day()
        self.current_daily_loss += float(pnl)

        if pnl < 0:
            base_time = candle_time or dt.datetime.now()
            cooldown_candles = self.config.engine_b_cooldown_candles_after_loss if engine == "B" else self.config.cooldown_candles_after_loss
            cooldown_minutes = timeframe_minutes * max(1, int(cooldown_candles))
            self.cooldowns[symbol] = base_time + dt.timedelta(minutes=cooldown_minutes)