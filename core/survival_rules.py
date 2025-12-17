from __future__ import annotations
import pandas as pd
import datetime
from .structure import regime_analysis

class SurvivalRules:
    """Implements survival rules and regime kill-switches for the trading bot."""

    def __init__(self, config: dict):
        self.config = config
        self.global_settings = config.get("global_params") or {
            "daily_loss_limit": config.get("daily_loss_limit"),
            "consecutive_sl_pause_count": config.get("consecutive_sl_pause_count"),
            "winrate_pause_threshold": config.get("winrate_pause_threshold"),
            "winrate_lookback_trades": config.get("winrate_lookback_trades"),
        }

        self.daily_loss_limit = self.global_settings["daily_loss_limit"]
        self.consecutive_sl_pause_count = self.global_settings["consecutive_sl_pause_count"]
        self.winrate_pause_threshold = self.global_settings["winrate_pause_threshold"]
        self.winrate_lookback_trades = self.global_settings["winrate_lookback_trades"]

        # Trackers
        self.current_daily_loss = 0.0
        self.consecutive_sl_count = 0
        self.trade_results = [] # Stores (profit_loss, is_win) for winrate calculation
        self.trading_paused = False
        self.pause_reason = ""

    def reset_daily_metrics(self):
        """Resets daily loss at the start of a new day."""
        self.current_daily_loss = 0.0
        self.trading_paused = False
        self.pause_reason = ""

    def record_trade_result(self, profit_loss: float):
        """Records the result of a trade for survival rule evaluation."""
        self.current_daily_loss += profit_loss
        is_win = profit_loss > 0
        self.trade_results.append(is_win)

        # Keep only the last `winrate_lookback_trades` results
        if len(self.trade_results) > self.winrate_lookback_trades:
            self.trade_results.pop(0)

        if not is_win:
            self.consecutive_sl_count += 1
        else:
            self.consecutive_sl_count = 0

    def get_regime_state(self, df_m5: pd.DataFrame, df_m15: pd.DataFrame, atr_value: float) -> str:
        """Determines the current regime state for global kill-switch."""
        # Volatility regime check
        regime = regime_analysis(df_m5, df_m15)
        if regime == "volatility_expanded":
            return "VOLATILITY_LOCK"

        # Daily Loss Limit
        if self.current_daily_loss <= -abs(self.daily_loss_limit):
            return "DRAWDOWN_PROTECTION"

        # Consecutive Stop Losses
        if self.consecutive_sl_count >= self.consecutive_sl_pause_count:
            return "CONSECUTIVE_LOSS_PROTECTION"

        # Winrate below threshold
        if len(self.trade_results) >= self.winrate_lookback_trades:
            wins = sum(1 for result in self.trade_results if result)
            winrate = wins / len(self.trade_results)
            if winrate < self.winrate_pause_threshold:
                return "LOW_WINRATE_PROTECTION"

        # ATR spike
        avg_range = df_m5['high'].diff().rolling(window=20).mean().iloc[-1]
        if not pd.isna(avg_range) and atr_value > avg_range * 2:
            return "VOLATILITY_LOCK"

        return "NORMAL"