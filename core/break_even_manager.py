from __future__ import annotations
from typing import Optional

class BreakEvenManager:
    """Manages the break-even mechanism for trades."""

    def __init__(self, config: dict):
        self.config = config
        self.breakeven_settings = config["strategy_settings"]["breakeven"]
        self.r_level = self.breakeven_settings["r_level"]
        self.deriv_advanced_r_level = self.breakeven_settings["deriv_advanced_r_level"]

    def adjust_stop_loss(self, trade_type: str, entry_price: float, current_price: float, initial_stop_loss: float, initial_take_profit: float, spread: float, is_deriv: bool = False, engine: Optional[str] = None) -> float:
        """Adjusts the stop loss to break-even or advanced break-even level.

        Args:
            trade_type: "buy" or "sell".
            entry_price: The price at which the trade was entered.
            current_price: The current market price.
            initial_stop_loss: The initial stop loss price.
            initial_take_profit: The initial take profit price.
            spread: The current spread for the symbol.
            is_deriv: True if the broker is Deriv, enabling advanced break-even.

        Returns:
            The new stop loss price, or the initial stop loss if no adjustment is needed.
        """
        risk_per_unit = abs(entry_price - initial_stop_loss)
        if risk_per_unit == 0:
            return initial_stop_loss

        # Calculate current profit in R-multiples
        if trade_type == "buy":
            profit_in_r = (current_price - entry_price) / risk_per_unit
        else: # sell
            profit_in_r = (entry_price - current_price) / risk_per_unit

        new_stop_loss = initial_stop_loss

        # Check for +1R break-even
        be_r_level = 0.8 if engine == "B" else self.r_level
        if profit_in_r >= be_r_level:
            if trade_type == "buy":
                be_level = entry_price + spread
                if initial_stop_loss < be_level: # Only move SL if it improves
                    new_stop_loss = be_level
            else: # sell
                be_level = entry_price - spread
                if initial_stop_loss > be_level: # Only move SL if it improves
                    new_stop_loss = be_level

        # Check for advanced break-even for Deriv
        adv_r_level = 0.6 if engine == "B" else self.deriv_advanced_r_level
        if is_deriv and profit_in_r >= adv_r_level:
            if trade_type == "buy":
                advanced_be_level = entry_price + (self.deriv_advanced_r_level * risk_per_unit)
                if new_stop_loss < advanced_be_level: # Only move SL if it improves
                    new_stop_loss = advanced_be_level
            else: # sell
                advanced_be_level = entry_price - (self.deriv_advanced_r_level * risk_per_unit)
                if new_stop_loss > advanced_be_level: # Only move SL if it improves
                    new_stop_loss = advanced_be_level

        return new_stop_loss