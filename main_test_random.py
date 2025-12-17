from __future__ import annotations
import json
import time
import re
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
load_dotenv()

from connectors import get_connector
from utils.logger import trade_logger, error_logger
from utils.data_handler import DataHandler
from core.strategy_random import StrategyRandom
from core.risk_manager import RiskConfig, RiskManager
from core.trade_manager import TradeManager


def load_json(path: Path | str) -> Dict[str, Any]:
    p = Path(path)
    content = p.read_text(encoding="utf-8")
    # Remove comments before parsing
    content = re.sub(r'//.*', '', content)
    return json.loads(content)


def build_trade_stack() -> Dict[str, Any]:
    base_dir = Path(__file__).resolve().parent
    cfg_path = base_dir / "config" / "config_test_random.json"
    strategies_path = base_dir / "config" / "strategies.json"

    cfg = load_json(cfg_path)

    # Resolve symbols for selected broker
    broker_name = str(cfg.get("broker", "deriv")).lower()
    broker_cfg = cfg.get(broker_name) or {}
    
    # Connector
    connector = get_connector(broker_name, cfg, {})
    connector.connect()
    
    # For Deriv, try to get active symbols from API if live_data is enabled
    selected_symbols: List[str] = []
    if broker_name == "deriv" and hasattr(connector, "get_active_symbols"):
        use_api = broker_cfg.get("use_api_symbols", False)
        if use_api:
            api_symbols = connector.get_active_symbols()
            if api_symbols:
                trade_logger.info(f"Loaded {len(api_symbols)} symbols from Deriv API")
                selected_symbols = api_symbols
    
    # Fall back to config if no symbols from API
    if not selected_symbols:
        selected_symbols = list(broker_cfg.get("symbols") or cfg.get("symbols", []))
        trade_logger.info(f"Using {len(selected_symbols)} symbols from config")
    
    cfg["symbols"] = selected_symbols

    # Helpers
    data = DataHandler(connector)
    
    # Use RANDOM strategy for testing
    strategy = StrategyRandom(strategies_path, signal_probability=0.5)  # 50% chance of signal
    strategy_info = strategy.get_strategy_info()
    trade_logger.info(f"Using RANDOM strategy for testing: {strategy_info}")

    # Risk - Use more aggressive settings for testing
    risk_cfg = RiskConfig(
        risk_per_trade=float(cfg.get("risk_per_trade", 0.01)),
        max_trades_per_day=int(cfg.get("max_trades_per_day", 20)),  # Increased for testing
        daily_loss_limit=float(cfg.get("daily_loss_limit", 0.10)),  # Increased for testing
    )
    risk = RiskManager(risk_cfg)

    # Orchestrator
    manager = TradeManager(cfg, connector, risk)

    return {
        "config": cfg,
        "connector": connector,
        "data": data,
        "strategy": strategy,
        "risk": risk,
        "manager": manager,
    }


def aligned_row(symbol: str, base_tf: str, stack: Dict[str, Any]) -> Dict[str, Any] | None:
    data: DataHandler = stack["data"]
    strategy: StrategyRandom = stack["strategy"]

    # Determine timeframes for MTF alignment
    timeframes: List[str] = list(strategy.params.get("multi_timeframes", []))
    if not timeframes:
        timeframes = [base_tf]
    # Ensure base timeframe is included and is first
    if base_tf not in timeframes:
        timeframes = [base_tf] + [tf for tf in timeframes if tf != base_tf]
    else:
        # Move base_tf to front if not already
        timeframes = [base_tf] + [tf for tf in timeframes if tf != base_tf]

    # Fetch and compute signals per timeframe
    last_rows: Dict[str, Dict[str, Any]] = {}
    for tf in timeframes:
        df = data.fetch_ohlcv(symbol, tf, limit=100)  # Reduced limit for testing
        if df is None or df.empty:
            trade_logger.info(f"No data for {symbol} {tf}; skipping.")
            return None
        sig_df = strategy.generate_signals(df)
        if sig_df is None or sig_df.empty:
            trade_logger.info(f"No signals for {symbol} {tf}; skipping.")
            return None
        last_rows[tf] = sig_df.iloc[-1].to_dict()

    base_row = last_rows.get(base_tf)
    if not base_row:
        return None

    base_signal = int(base_row.get("signal", 0) or 0)
    if base_signal == 0:
        return None

    # For random strategy, we don't need MTF alignment - just use the signal
    trade_logger.info(f"Random signal generated for {symbol}: {'BUY' if base_signal > 0 else 'SELL'}")
    return base_row


def process_symbol(symbol: str, base_timeframe: str, stack: Dict[str, Any]) -> None:
    manager: TradeManager = stack["manager"]
    try:
        row = aligned_row(symbol, base_timeframe, stack)
        if not row:
            return
        manager.process_signal(symbol, row)
    except Exception as e:
        error_logger.error(f"Error processing {symbol}: {e}")


def main() -> None:
    stack = build_trade_stack()
    cfg: Dict[str, Any] = stack["config"]

    symbols: List[str] = list(cfg.get("symbols", []))
    base_timeframe: str = str(cfg.get("timeframe", "M5"))  # Use M5 for faster testing
    poll_interval: float = float(cfg.get("poll_interval", 10))  # Faster polling for testing

    trade_logger.info(
        f"SubScalpBot TEST MODE with RANDOM strategy - broker={cfg.get('broker')} symbols={symbols} base_tf={base_timeframe} interval={poll_interval}s"
    )
    trade_logger.info("WARNING: This is a test mode with random signals - DO NOT use for live trading!")

    try:
        while True:
            for sym in symbols:
                process_symbol(sym, base_timeframe, stack)
            stack["manager"].monitor_positions()
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        trade_logger.info("SubScalpBot TEST MODE stopped by user.")
    except Exception as e:
        error_logger.error(f"Fatal error: {e}")


if __name__ == "__main__":
    main()