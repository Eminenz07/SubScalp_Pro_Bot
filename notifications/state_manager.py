from datetime import datetime, timedelta
import threading
from typing import Dict, Tuple, Optional
from notifications.enums import EventType

class NotificationStateManager:
    """
    Manages state for notification throttling and cooldowns.
    Thread-safe.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._last_sent: Dict[str, datetime] = {}
        
        # Cooldown configurations (in seconds)
        self.cooldowns = {
            EventType.BOT_START: 600,   # 10 mins
            EventType.BOT_STOP: 600,
            EventType.MT5_DISCONNECTED: 600,
            EventType.MT5_RECONNECTED: 0, # Always notify
            
            EventType.DAILY_LOSS_LIMIT_HIT: 900, # 15 mins
            EventType.MAX_TRADES_REACHED: 900,
            EventType.DRAWDOWN_WARNING: 900,
            
            EventType.DAILY_SUMMARY: 86400, # 24 hours (approx, logic handles daily)
            
            EventType.BOT_HEARTBEAT: 43200, # 12 hours
        }
        
    def should_send(self, event: EventType, symbol: Optional[str] = None) -> bool:
        """Determines if a notification should be sent based on cooldowns."""
        key = self._get_key(event, symbol)
        
        # Always allow Trade events (no throttling)
        if event in [EventType.TRADE_OPEN, EventType.TRADE_CLOSE]:
            return True
            
        with self._lock:
            # Special logic for MT5 Reconnect - always send if strictly a reconnect,
            # but maybe we want to allow it only if we were previously disconnected?
            # For now, simplest path: allow it, but maybe block duplicates?
            if event == EventType.MT5_RECONNECTED:
                # If we recently sent a reconnect, maybe suppress? 
                # Let's stick to simple cooldown check (0 means always unless handled elsewhere)
                pass

            last_time = self._last_sent.get(key)
            if not last_time:
                return True
                
            cooldown = self.cooldowns.get(event, 0)
            if cooldown == 0:
                return True
                
            elapsed = (datetime.now() - last_time).total_seconds()
            if elapsed < cooldown:
                return False
                
            # Special Daily Summary Logic: Check if it's the same day?
            if event == EventType.DAILY_SUMMARY:
                if last_time.date() == datetime.now().date():
                    return False
                    
            return True

    def update_state(self, event: EventType, symbol: Optional[str] = None):
        """Updates the last sent timestamp for an event."""
        key = self._get_key(event, symbol)
        with self._lock:
            self._last_sent[key] = datetime.now()
            
            # Reset logic
            if event == EventType.MT5_RECONNECTED:
                # Reset disconnection state so we can notify again if it drops
                disc_key = self._get_key(EventType.MT5_DISCONNECTED, None)
                if disc_key in self._last_sent:
                    del self._last_sent[disc_key]

    def _get_key(self, event: EventType, symbol: Optional[str]) -> str:
        if symbol:
            return f"{event.value}:{symbol}"
        return event.value
