import time
import logging
import os
from dotenv import load_dotenv
from notifications.notifier import Notifier
from notifications.enums import EventType, Severity

# Setup basics
logging.basicConfig(level=logging.INFO)
load_dotenv()

def test_manual_verification():
    print(">>> Starting Manual Notification Verification")

    # Mock Config
    config = {
        "notification_settings": {
            "telegram_enabled": True,
            "email_enabled": True
        }
    }
    
    # Check Env Vars
    print(f"Telegram Token Present: {bool(os.getenv('TELEGRAM_BOT_TOKEN'))}")
    print(f"Telegram Chat ID Present: {bool(os.getenv('TELEGRAM_CHAT_ID'))}")
    print(f"Email User Present: {bool(os.getenv('EMAIL_USERNAME'))}")

    notifier = Notifier(config)

    # 1. Test Info (Should affect Telegram only by default logic if not summary)
    print("\n[1] Sending BOT_START - Expect Telegram Message")
    notifier.notify(EventType.BOT_START, Severity.INFO, {
        "message": "Test Message: Bot Started",
        "strategy": "TEST_MODE"
    })

    print("\n[1b] Sending BOT_START AGAIN (Immediate) - Expect THROTTLED (No Message)")
    notifier.notify(EventType.BOT_START, Severity.INFO, {
        "message": "Test Message: Bot Started Duplicate",
        "strategy": "TEST_MODE"
    })
    
    # 2. Test Trade Open (Telegram Only, No Throttling)
    print("\n[2] Sending TRADE_OPEN - Expect Telegram (No Throttling)")
    notifier.notify(EventType.TRADE_OPEN, Severity.INFO, {
        "symbol": "frxEURUSD",
        "order_type": "buy",
        "volume": 0.1,
        "price": 1.0500,
        "sl": 1.0450,
        "tp": 1.0600,
        "strategy": "TEST",
        "message": "Test Trade Open"
    })

    # Test Heartbeat
    print("\n[H] Checking Heartbeat - Expect Message")
    notifier.check_heartbeat()
    
    # Check Heartbeat Again
    print("\n[H2] Checking Heartbeat Again - Expect THROTTLED")
    notifier.check_heartbeat()

    # 3. Test Critical (Expect Email + Telegram)
    print("\n[3] Sending CRITICAL (BOT_CRASH) - Expect Email + Telegram")
    notifier.notify(EventType.BOT_CRASH, Severity.CRITICAL, {
        "message": "Test Fatal Error: Something went wrong!"
    })

    # 4. Test Summary (Expect Email Only)
    print("\n[4] Sending DAILY_SUMMARY - Expect Email Only")
    notifier.notify(EventType.DAILY_SUMMARY, Severity.INFO, {
        "total_trades": 5,
        "win_rate": 60.0,
        "net_pl": 120.50,
        "best_engine": "A",
        "worst_pair": "frxGBPUSD"
    })

    print("\n>>> Dispatch calls made. Waiting 5s for threads to complete...")
    time.sleep(5)
    print(">>> Done.")

if __name__ == "__main__":
    test_manual_verification()
