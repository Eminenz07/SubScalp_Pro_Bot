from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

TRADES_LOG_PATH = LOG_DIR / "trades.log"
ERRORS_LOG_PATH = LOG_DIR / "errors.log"


def _create_logger(name: str, log_path: Path, level: int = logging.INFO) -> logging.Logger:
    """Create a rotating file logger.

    Args:
        name: Logger name.
        log_path: Path to log file.
        level: Logging level.

    Returns:
        Configured Logger instance.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Also output to console for monitoring
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(level)
    logger.addHandler(console)

    return logger


trade_logger = _create_logger("trades", TRADES_LOG_PATH)
error_logger = _create_logger("errors", ERRORS_LOG_PATH, level=logging.ERROR)