import time
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

class TelegramClient:
    def __init__(self, config: dict):
        self.config = config.get("notification_settings", {})
        
        # Load from Env or Config
        import os
        self.token = os.getenv("TELEGRAM_BOT_TOKEN") or config.get("telegram_token")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID") or config.get("telegram_chat_id")
        self.enabled = self.config.get("telegram_enabled", True)
        
        if not self.token or not self.chat_id:
            logger.warning("Telegram credentials missing or incomplete in .env/config.")
            self.enabled = False

        self.base_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        self.session = requests.Session()

    def send_message(self, text: str) -> bool:
        """
        Sends a plain text message to Telegram with retry logic.
        Hardened: No Markdown/ParseMode to prevent 400 errors.
        """
        if not self.enabled:
            return True

        if not self.token or not self.chat_id:
            logger.warning("Telegram disabled or invalid credentials.")
            return False

        payload = {
            "chat_id": self.chat_id,
            "text": text
        }

        retries = 3
        for attempt in range(retries):
            try:
                response = self.session.post(self.base_url, json=payload, timeout=10)
                response.raise_for_status()
                logger.info(f"Telegram sent successfully: {text[:20]}...")
                return True
            except requests.exceptions.HTTPError as e:
                if response.status_code == 429:
                    # Rate limit hit
                    retry_after = int(response.headers.get("Retry-After", 5))
                    logger.warning(f"Telegram rate limit hit. Waiting {retry_after}s.")
                    time.sleep(retry_after)
                else:
                    logger.error(f"Telegram send failed (Attempt {attempt+1}/{retries}): {e}")
            except Exception as e:
                logger.error(f"Telegram connection error (Attempt {attempt+1}/{retries}): {e}")
            
            time.sleep(2)  # Backoff
        
        return False
