import logging
import threading
import os
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from notifications.enums import EventType, Severity
from notifications.templates import MessageTemplates
from notifications.telegram_client import TelegramClient
from notifications.email_client import EmailClient
from notifications.state_manager import NotificationStateManager

logger = logging.getLogger(__name__)

class Notifier:
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the Notifier with configuration.
        Config should contain keys for Telegram and Email settings.
        """
        self.config = config
        
        # Telegram Setup

        self.telegram = TelegramClient(config)
        self.email = EmailClient(config)
        
        # Load email recipient
        import os
        self.email_to = os.getenv("EMAIL_TO") or config.get("email_to")
        
        # Hardening: Executor & State Manager
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="NotifyWorker")
        self.state_manager = NotificationStateManager()
        self._start_time = datetime.now()
        
    def shutdown(self):
        """Gracefully shuts down the notification executor."""
        self.executor.shutdown(wait=False)

    def check_heartbeat(self):
        """Triggers a heartbeat notification if allowed by state manager."""
        if self.state_manager.should_send(EventType.BOT_HEARTBEAT):
            # Calculate uptime
            uptime = datetime.now() - self._start_time
            # Format as "X days, HH:MM:SS"
            uptime_str = str(uptime).split('.')[0]
            
            payload = {
                "uptime": uptime_str,
                "message": "System Operational"
            }
            self.notify(EventType.BOT_HEARTBEAT, Severity.INFO, payload)

    def notify(self, event: EventType, severity: Severity, payload: Dict[str, Any]):
        """Dispatches notification asynchronously if passed throttling checks."""
        # 1. Throttling Check
        symbol = payload.get("symbol")
        if not self.state_manager.should_send(event, symbol):
            # TODO: Log throttled action?
            return

        # 2. Update State
        self.state_manager.update_state(event, symbol)

        # 3. Dispatch via Executor
        try:
            self.executor.submit(self._dispatch, event, severity, payload)
        except RuntimeError:
            pass # Executor closed

    def _dispatch(self, event: EventType, severity: Severity, payload: Dict[str, Any]):
        try:
            # Logic: 
            # - Critical -> Always Email + Telegram (if enabled)
            # - Trade Events -> Telegram Only
            # - Daily Summary -> Email Only (as per requirements)
            # - Others -> Configurable or Default Logic
            
            # Telegram
            if self._should_send_telegram(event, severity):
                msg = MessageTemplates.format_telegram(event, severity, payload)
                self.telegram.send_message(msg)

            # Email
            if self._should_send_email(event, severity):
                subject = MessageTemplates.format_email_subject(event, severity)
                body = MessageTemplates.format_email_body(event, severity, payload)
                self.email.send_email(self.email_to, subject, body)

        except Exception as e:
            logger.error(f"Error during notification dispatch: {e}")

    def _should_send_telegram(self, event: EventType, severity: Severity) -> bool:
        # User defined: "Email is for: Errors, Risk events, Daily summaries. NOT for every trade."
        # "Trade Events -> Telegram only"
        if event == EventType.DAILY_SUMMARY:
            return False # Summary events via email only per requirements
            
        return True # Default to yes for telegram for most other things

    def _should_send_email(self, event: EventType, severity: Severity) -> bool:
        if severity == Severity.CRITICAL:
            return True
        if event == EventType.DAILY_SUMMARY:
            return True
        
        # "Email is for: Errors, Risk events, Daily summaries"
        # Risk events are usually WARNING or Higher
        risk_events = {
            EventType.DAILY_LOSS_LIMIT_HIT, 
            EventType.MAX_TRADES_REACHED, 
            EventType.DRAWDOWN_WARNING,
            EventType.TRADING_PAUSED,
            EventType.TRADING_RESUMED
        }
        
        if event in risk_events:
            return True
            
        if severity == Severity.WARNING:
            return True

        return False
