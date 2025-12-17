import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

logger = logging.getLogger(__name__)

class EmailClient:
    def __init__(self, config: dict):
        import os
        self.config = config.get("notification_settings", {})
        
        # Load from Env or Config
        self.username = os.getenv("EMAIL_USERNAME") or config.get("email_username")
        self.password = os.getenv("EMAIL_PASSWORD") or config.get("email_password")
        self.sender_email = self.username
        
        # SMTP Settings
        self.smtp_server = config.get("email_smtp_server", "smtp.gmail.com")
        self.smtp_port = int(config.get("email_smtp_port", 587))
        
        self.enabled = self.config.get("email_enabled", True)
        if not self.username or not self.password:
            self.enabled = False

    def send_email(self, to_email: str, subject: str, body: str, is_html: bool = False) -> bool:
        """
        Sends an email via SMTP.
        """
        if not self.enabled:
            return True

        if not self.username or not self.password or not to_email:
            logger.warning("Email credentials or recipient missing, cannot send.")
            return False

        msg = MIMEMultipart()
        msg['From'] = self.sender_email
        msg['To'] = to_email
        msg['Subject'] = subject

        type_subtype = 'html' if is_html else 'plain'
        msg.attach(MIMEText(body, type_subtype))

        try:
            # Using context manager for connection security
            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)
            logger.info(f"Email sent successfully to {to_email}")
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP Authentication failed. Check your username/password/app-password.")
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
        
        return False
