"""
Exhaustion Event Management Module

This module provides a persistent ExhaustionEvent class that tracks trend exhaustion events
and ensures Engine B can only trade once per exhaustion event.
"""

from __future__ import annotations
import uuid
from datetime import datetime
from typing import Dict, Any, Optional


class ExhaustionEvent:
    """
    Represents a trend exhaustion event with persistent state.
    
    This class ensures Engine B can only execute once per exhaustion event
    and provides structured data for analytics and logging.
    """
    
    def __init__(self, symbol: str, exhaustion_type: str, context: Dict[str, Any]):
        """
        Initialize a new exhaustion event.
        
        Args:
            symbol: Trading symbol (e.g., 'frxEURUSD')
            exhaustion_type: Type of exhaustion (e.g., 'ema_stretch', 'impulse_count')
            context: Additional context data from Engine A
        """
        self.exhaustion_id = str(uuid.uuid4())
        self.symbol = symbol
        self.exhaustion_type = exhaustion_type
        self.timestamp = datetime.now()
        self.context = context.copy()
        self.engine_b_consumed = False
        self.engine_b_trade_id = None
        self.is_active = True
        
    def mark_engine_b_triggered(self, trade_id: str) -> bool:
        """
        Mark that Engine B has been triggered for this exhaustion event.
        
        Args:
            trade_id: The trade ID from Engine B
            
        Returns:
            True if successfully marked, False if already consumed
        """
        if self.engine_b_consumed:
            return False
            
        self.engine_b_consumed = True
        self.engine_b_trade_id = trade_id
        return True
        
    def can_engine_b_evaluate(self) -> bool:
        """
        Check if Engine B is allowed to evaluate for this exhaustion event.
        
        Returns:
            True if Engine B can evaluate, False otherwise
        """
        return self.is_active and not self.engine_b_consumed
        
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the exhaustion event to a dictionary for serialization.
        
        Returns:
            Dictionary representation of the exhaustion event
        """
        return {
            "exhaustion_id": self.exhaustion_id,
            "symbol": self.symbol,
            "exhaustion_type": self.exhaustion_type,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
            "engine_b_consumed": self.engine_b_consumed,
            "engine_b_trade_id": self.engine_b_trade_id,
            "is_active": self.is_active
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExhaustionEvent:
        """
        Create an ExhaustionEvent from a dictionary.
        
        Args:
            data: Dictionary containing exhaustion event data
            
        Returns:
            ExhaustionEvent instance
        """
        event = cls(
            symbol=data["symbol"],
            exhaustion_type=data["exhaustion_type"],
            context=data["context"]
        )
        event.exhaustion_id = data["exhaustion_id"]
        event.timestamp = datetime.fromisoformat(data["timestamp"])
        event.engine_b_consumed = data["engine_b_consumed"]
        event.engine_b_trade_id = data["engine_b_trade_id"]
        event.is_active = data["is_active"]
        return event


class ExhaustionEventManager:
    """
    Manages exhaustion events across multiple symbols with persistence.
    
    This class ensures proper lifecycle management of exhaustion events
    and provides centralized state tracking for the dual-engine system.
    """
    
    def __init__(self, max_age_minutes: int = 60):
        """
        Initialize the exhaustion event manager.
        
        Args:
            max_age_minutes: Maximum age in minutes before an event becomes inactive
        """
        self.events: Dict[str, ExhaustionEvent] = {}  # symbol -> current event
        self.max_age_minutes = max_age_minutes
        
    def create_exhaustion_event(self, symbol: str, exhaustion_type: str, 
                               context: Dict[str, Any]) -> ExhaustionEvent:
        """
        Create a new exhaustion event for a symbol.
        
        Args:
            symbol: Trading symbol
            exhaustion_type: Type of exhaustion
            context: Context data from Engine A
            
        Returns:
            New ExhaustionEvent instance
        """
        # Deactivate any existing event for this symbol
        if symbol in self.events:
            self.events[symbol].is_active = False
            
        # Create new event
        event = ExhaustionEvent(symbol, exhaustion_type, context)
        self.events[symbol] = event
        return event
        
    def get_current_event(self, symbol: str) -> Optional[ExhaustionEvent]:
        """
        Get the current active exhaustion event for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Current ExhaustionEvent or None if no active event
        """
        if symbol not in self.events:
            return None
            
        event = self.events[symbol]
        
        # Check if event is too old
        age_minutes = (datetime.now() - event.timestamp).total_seconds() / 60
        if age_minutes > self.max_age_minutes:
            event.is_active = False
            return None
            
        return event if event.is_active else None
        
    def can_engine_b_evaluate(self, symbol: str) -> bool:
        """
        Check if Engine B can evaluate for a symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            True if Engine B can evaluate, False otherwise
        """
        event = self.get_current_event(symbol)
        return event.can_engine_b_evaluate() if event else False
        
    def mark_engine_b_triggered(self, symbol: str, trade_id: str) -> bool:
        """
        Mark that Engine B has been triggered for a symbol.
        
        Args:
            symbol: Trading symbol
            trade_id: Trade ID from Engine B
            
        Returns:
            True if successfully marked, False if no active event or already consumed
        """
        event = self.get_current_event(symbol)
        if not event:
            return False
            
        return event.mark_engine_b_triggered(trade_id)
        
    def get_all_active_events(self) -> Dict[str, ExhaustionEvent]:
        """
        Get all currently active exhaustion events.
        
        Returns:
            Dictionary of symbol -> ExhaustionEvent for active events
        """
        active_events = {}
        for symbol, event in self.events.items():
            if event.is_active:
                age_minutes = (datetime.now() - event.timestamp).total_seconds() / 60
                if age_minutes <= self.max_age_minutes:
                    active_events[symbol] = event
                else:
                    event.is_active = False
        return active_events
        
    def clear_inactive_events(self):
        """
        Clear events that are no longer active (too old or manually deactivated).
        """
        current_time = datetime.now()
        symbols_to_remove = []
        
        for symbol, event in self.events.items():
            age_minutes = (current_time - event.timestamp).total_seconds() / 60
            if age_minutes > self.max_age_minutes or not event.is_active:
                symbols_to_remove.append(symbol)
                
        for symbol in symbols_to_remove:
            del self.events[symbol]