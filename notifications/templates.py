from datetime import datetime, timezone
from typing import Dict, Any
from notifications.enums import EventType, Severity

class MessageTemplates:
    @staticmethod
    def get_timestamp() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    @staticmethod
    def format_telegram(event: EventType, severity: Severity, payload: Dict[str, Any]) -> str:
        """Formats a message for Telegram (Plain Text)."""
        icon = MessageTemplates._get_icon(event, severity)
        title = event.value.replace("_", " ")
        timestamp = MessageTemplates.get_timestamp()
        
        message_lines = [f"{icon} {title}"]
        message_lines.append(f"{timestamp}")
        message_lines.append("")

        if event == EventType.BOT_HEARTBEAT:
             message_lines.extend([
                f"Uptime: {payload.get('uptime', 'N/A')}",
                f"Status: {payload.get('message', 'N/A')}",
            ])
        elif event == EventType.TRADE_OPEN:
            message_lines.extend([
                f"Symbol: {payload.get('symbol', 'N/A')}",
                f"Action: {payload.get('order_type', 'N/A')}",
                f"Lots: {payload.get('volume', 'N/A')}",
                f"Price: {payload.get('price', 'N/A')}",
                f"SL: {payload.get('sl', 'N/A')} | TP: {payload.get('tp', 'N/A')}",
                f"Strategy: {payload.get('strategy', 'N/A')}"
            ])
        elif event == EventType.TRADE_CLOSE:
            profit = payload.get('profit', 0.0)
            profit_icon = "📈" if profit >= 0 else "🔻"
            message_lines.extend([
                f"Symbol: {payload.get('symbol', 'N/A')}",
                f"Action: {payload.get('order_type', 'N/A')}",
                f"Close Price: {payload.get('price', 'N/A')}",
                f"P/L: {profit_icon} {profit:.2f}",
                f"Duration: {payload.get('duration', 'N/A')}",
                f"Strategy: {payload.get('strategy', 'N/A')}"
            ])
        elif event == EventType.DAILY_SUMMARY:
             message_lines.extend([
                f"Total Trades: {payload.get('total_trades', 0)}",
                f"Win Rate: {payload.get('win_rate', 0.0):.1f}%",
                f"Net P/L: {payload.get('net_pl', 0.0):.2f}",
                f"Best Engine: {payload.get('best_engine', 'N/A')}",
                f"Worst Pair: {payload.get('worst_pair', 'N/A')}"
            ])
        else:
            # Generic Payload Dump
            msg = payload.get("message")
            if msg:
                message_lines.append(f"{msg}")
            
            for k, v in payload.items():
                if k != "message":
                    message_lines.append(f"{k}: {v}")

        return "\n".join(message_lines)

    @staticmethod
    def format_email_subject(event: EventType, severity: Severity) -> str:
        """Formats the email subject line."""
        imp = "[URGENT]" if severity == Severity.CRITICAL else ""
        title = event.value.replace("_", " ")
        return f"{imp} SubScalpBot Notification: {title}"

    @staticmethod
    def format_email_body(event: EventType, severity: Severity, payload: Dict[str, Any]) -> str:
        """Formats the email body (Text/HTML hybrid style for now, keeping it simple text)."""
        # User requested Clean HTML or plaintext. Let's stick to clean text/pseudo-table for robustness first.
        # Or simple HTML if needed. Let's do a clean text format that renders well.
        timestamp = MessageTemplates.get_timestamp()
        title = event.value.replace("_", " ")
        
        lines = [
            f"SubScalp WealthBot Notification",
            f"Event: {title}",
            f"Severity: {severity.name}",
            f"Time: {timestamp}",
            "-" * 30,
            ""
        ]

        if event == EventType.DAILY_SUMMARY:
             lines.extend([
                f"Total Trades: {payload.get('total_trades', 0)}",
                f"Win Rate: {payload.get('win_rate', 0.0):.1f}%",
                f"Net P/L: {payload.get('net_pl', 0.0):.2f}",
                f"Best Engine: {payload.get('best_engine', 'N/A')}",
                f"Worst Pair: {payload.get('worst_pair', 'N/A')}"
            ])
        else:
            msg = payload.get("message")
            if msg:
                lines.append(f"Message: {msg}")
                lines.append("")
            
            for k, v in payload.items():
                if k != "message":
                    lines.append(f"{k}: {v}")
        
        lines.append("")
        lines.append("-" * 30)
        lines.append("Automated message from SubScalp WealthBot.")
        return "\n".join(lines)

    @staticmethod
    def _get_icon(event: EventType, severity: Severity) -> str:
        if severity == Severity.CRITICAL:
            return "🚨"
        if severity == Severity.WARNING:
            return "⚠️"
        
        icons = {
            EventType.BOT_START: "🟢",
            EventType.BOT_STOP: "🛑",
            EventType.TRADE_OPEN: "⚡",
            EventType.TRADE_CLOSE: "💰",
            EventType.DAILY_SUMMARY: "📊",
            EventType.DAILY_LOSS_LIMIT_HIT: "📉",
            EventType.MAX_TRADES_REACHED: "✋",
        }
        return icons.get(event, "ℹ️")
