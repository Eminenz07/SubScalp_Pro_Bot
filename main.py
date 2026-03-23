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
from core.strategy_ema_hybrid import StrategyEMAHybrid
from core.strategy_random import StrategyRandom
from core.strategy_ema_stochastic import StrategyEMAStochastic
from core.strategy_lsmc import StrategyLSMC
from core.strategy_rsi_fibonacci import StrategyRSIFibonacci
from core.strategy_impulsive_crossover import StrategyImpulsiveCrossover
from core.risk_manager import RiskConfig, RiskManager
from core.break_even_manager import BreakEvenManager
from core.survival_rules import SurvivalRules
from core.indicators import atr
from core.trade_manager import TradeManager
from core.engine_analytics import EngineAnalytics
from notifications.notifier import Notifier
from notifications.enums import EventType, Severity
import logging


def load_json(path: Path | str) -> Dict[str, Any]:
    p = Path(path)
    content = p.read_text(encoding="utf-8")
    # Remove comments before parsing
    content = re.sub(r'//.*', '', content)
    return json.loads(content)


def build_trade_stack(strategy_name: str) -> Dict[str, Any]:
    base_dir = Path(__file__).resolve().parent
    cfg_path = base_dir / "config" / "config.json"
    strategies_path = base_dir / "config" / "strategies.json"

    cfg = load_json(cfg_path)

    # Resolve symbols for selected broker
    broker_name = str(cfg.get("broker", "deriv")).lower()
    broker_cfg = cfg.get(broker_name) or {}
    
    # Connector
    connector = get_connector(broker_name, cfg, {})
    connector.connect()

    # Notification System
    notifier = Notifier(cfg)

    # Validate MT5 connection status and warn if in paper mode
    try:
        from utils.data_handler import verify_mt5_connection
        if broker_name == "mt5" and not verify_mt5_connection(connector):
            error_logger.error("MT5 connection not established; running in paper mode.")
    except Exception:
        pass
    
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
    
    # Analytics
    analytics = EngineAnalytics(cfg)
    
    # Strategy selection
    if strategy_name == "EMA_HYBRID":
        strategy = StrategyEMAHybrid(strategies_path)
        config_path = strategies_path
    elif strategy_name == "RANDOM":
        strategy = StrategyRandom(strategies_path)
        config_path = base_dir / "config" / "config_test_random.json"
    elif strategy_name == "EMA_STOCHASTIC":
        config_path = base_dir / "config" / "ema_stochastic_config.json"
        strategy = StrategyEMAStochastic(config_path)
    elif strategy_name == "LSMC":
        config_path = cfg_path
        strategy = StrategyLSMC(cfg, analytics)
    elif strategy_name == "IMPULSIVE_CROSSOVER":
        config_path = cfg_path
        strategy = StrategyImpulsiveCrossover(cfg)
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    
    # Risk
    risk_cfg = RiskConfig(
        risk_per_trade=float(cfg.get("risk_per_trade", 0.01)),
        max_trades_per_day=int(cfg.get("max_trades_per_day", 5)),
        daily_loss_limit=float(cfg.get("daily_loss_limit", 0.05)),
    )
    risk = RiskManager(risk_cfg, notifier)
    breakeven_manager = BreakEvenManager(cfg)
    survival_rules = SurvivalRules(cfg)

    # Orchestrator
    manager = TradeManager(cfg, connector, risk, breakeven_manager, analytics, notifier)

    return {
        "config": cfg,
        "connector": connector,
        "data": data,
        "strategy": strategy,
        "risk": risk,
        "manager": manager,
        "survival": survival_rules,
        "analytics": analytics,
        "notifier": notifier,
        "config_path": config_path  # Add if needed
    }


def aligned_row(symbol: str, base_tf: str, stack: Dict[str, Any]) -> Dict[str, Any] | None:
    data: DataHandler = stack["data"]
    strategy = stack["strategy"]
    strategy_name = type(strategy).__name__

    if strategy_name == "StrategyEMAStochastic":
        # Special handling for EMA Stochastic MTF
        signal_tf = "M5"
        trend_tf = "M30"
        
        df_signal = data.fetch_ohlcv(symbol, signal_tf, limit=500)
        if df_signal is None or df_signal.empty:
            return None
            
        df_trend = data.fetch_ohlcv(symbol, trend_tf, limit=500)
        if df_trend is None or df_trend.empty:
            return None
            
        trend = strategy.check_trend(df_trend)
        sig_df = strategy.generate_signals(df_signal, trend)
        
        if sig_df is None or sig_df.empty:
            return None
            
        return sig_df.iloc[-1].to_dict()
    elif strategy_name == "StrategyRandom":
        df = data.fetch_ohlcv(symbol, base_tf, limit=100)
        if df is None or df.empty:
            trade_logger.info(f"No data for {symbol} {base_tf}; skipping.")
            return None
        sig_df = strategy.generate_signals(df)
        if sig_df is None or sig_df.empty:
            trade_logger.info(f"No signals for {symbol} {base_tf}; skipping.")
            return None
        last_row = sig_df.iloc[-1].to_dict()
        if last_row.get("signal", 0) == 0:
            return None
        trade_logger.info(f"Random signal generated for {symbol}: {'BUY' if last_row['signal'] > 0 else 'SELL'}")
        return last_row
    elif strategy_name == "StrategyLSMC":
        signal_tf = base_tf
        htf = str(stack["config"].get("htf_trend_timeframe", "M15"))

        df_signal = data.fetch_ohlcv(symbol, signal_tf, limit=500)
        if df_signal is None or df_signal.empty:
            return None

        df_trend = data.fetch_ohlcv(symbol, htf, limit=500)
        if df_trend is None or df_trend.empty:
            return None

        atr(df_signal, 14, name="atr_14")
        atr_val = float(df_signal["atr_14"].iloc[-1] or 0.0)
        if atr_val <= 0:
            return None

        regime_state = survival.get_regime_state(df_signal, df_trend, atr_val)
        if regime_state != "NORMAL":
            return None

        decision, ctx = strategy.evaluate_market(df_signal, df_trend, symbol)

        # Spread/slippage gating
        try:
            specs = stack["connector"].get_symbol_specs(symbol)
            get_spread = getattr(stack["connector"], "get_current_spread", None)
            spread_val = float(get_spread(symbol)) if callable(get_spread) else 0.0
            if atr_val > 0 and spread_val > (0.2 * atr_val):
                return None
        except Exception:
            pass

        if decision == "ALLOW_ENGINE_A_TRADE":
            sig_df_a = strategy.generate_signals(df_signal, df_trend)
            if sig_df_a is None or sig_df_a.empty:
                return None
            last_a = sig_df_a.iloc[-1].to_dict()
            if int(last_a.get("signal", 0) or 0) == 0:
                return None
            return last_a

        if decision == "ALLOW_ENGINE_B_EVALUATION":
            manager = stack.get("manager")
            if manager and symbol in manager.get_open_positions():
                return None
            rsi_fib = StrategyRSIFibonacci(stack["config"], stack["analytics"])
            sig_df_b = rsi_fib.generate_signals(df_signal, df_trend, decision, symbol, ctx)
            if sig_df_b is None or sig_df_b.empty:
                return None
            last_b = sig_df_b.iloc[-1].to_dict()
            if int(last_b.get("signal", 0) or 0) == 0:
                return None
            return last_b

        # Aggressive invalidation for Engine B on structure failure
        if decision == "BLOCK_ALL_TRADES" and ctx.get("reason") == "structure_broken":
            return {
                "signal": 0,
                "invalidate": True,
                "close_reason": "structure_failure",
                "close": float(df_signal.iloc[-1]["close"])
            }

        return None

    elif strategy_name == "StrategyImpulsiveCrossover":
        # Dual Timeframe: H1 (Trend) + M15 (Entry) - or base_tf
        signal_tf = base_tf # Should be M15
        trend_tf = "H1"
        
        df_signal = data.fetch_ohlcv(symbol, signal_tf, limit=500)
        if df_signal is None or df_signal.empty:
            return None
            
        df_trend = data.fetch_ohlcv(symbol, trend_tf, limit=500)
        if df_trend is None or df_trend.empty:
            return None
            
        sig_df = strategy.generate_signals(df_signal, df_trend)
        if sig_df is None or sig_df.empty:
            return None
            
        return sig_df.iloc[-1].to_dict()

    else:
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
            df = data.fetch_ohlcv(symbol, tf, limit=500)
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
    
        # If there are higher TFs, require alignment in the same direction
        for tf in timeframes[1:]:
            tf_row = last_rows.get(tf)
            if not tf_row:
                return None
            tf_sig = int(tf_row.get("signal", 0) or 0)
            if tf_sig == 0 or (tf_sig > 0) != (base_signal > 0):
                # Not aligned
                return None
    
        return base_row


essage = ""  # placeholder to avoid accidental print

def process_symbol(symbol: str, base_timeframe: str, stack: Dict[str, Any]) -> None:
    manager: TradeManager = stack["manager"]
    try:
        row = aligned_row(symbol, base_timeframe, stack)
        if not row:
            return
        opened = manager.process_signal(symbol, row)
        # Mark exhaustion consumed if Engine B trade was taken
        if opened and row.get("engine") == "B":
            stack["strategy"].mark_engine_b_consumed(symbol)
    except Exception as e:
        error_logger.error(f"Error processing {symbol}: {e}")


def run_bot(strategy: str, stop_event=None) -> None:
    """Entry point for the web UI.

    Args:
        strategy: Strategy name (e.g. "IMPULSIVE_CROSSOVER").
        stop_event: A threading.Event that, when set, cleanly stops the loop.
    """
    stack = build_trade_stack(strategy)
    cfg: Dict[str, Any] = stack["config"]

    symbols: List[str] = list(cfg.get("symbols", []))
    base_timeframe: str = str(cfg.get("timeframe", "M15"))
    poll_interval: float = float(cfg.get("poll_interval", 30))

    start_msg = (
        f"SubScalpBot starting with broker={cfg.get('broker')} "
        f"symbols={symbols} base_tf={base_timeframe} interval={poll_interval}s"
    )
    trade_logger.info(start_msg)
    notifier: Notifier = stack["notifier"]
    notifier.notify(EventType.BOT_START, Severity.INFO, {"message": start_msg, "strategy": strategy})
    
    from database.queries import ConfigQueries
    ConfigQueries.set_bot_running(True, strategy=strategy)

    try:
        while True:
            # Allow the web UI to request a clean stop
            if stop_event and stop_event.is_set():
                trade_logger.info("SubScalpBot stopped by web UI.")
                notifier.notify(EventType.BOT_STOP, Severity.INFO, {"message": "SubScalpBot stopped by web UI."})
                break

            for sym in symbols:
                process_symbol(sym, base_timeframe, stack)
            stack["manager"].monitor_positions()
            stack["notifier"].check_heartbeat()
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        trade_logger.info("SubScalpBot stopped by user.")
        stack["notifier"].notify(EventType.BOT_STOP, Severity.INFO, {"message": "SubScalpBot stopped by user."})
    except Exception as e:
        error_logger.error(f"Fatal error: {e}")
        stack["notifier"].notify(EventType.BOT_CRASH, Severity.CRITICAL, {"message": f"Fatal error: {e}"})
    finally:
        from database.queries import ConfigQueries
        ConfigQueries.set_bot_running(False)
        if "notifier" in stack:
            stack["notifier"].shutdown()


def main() -> None:
    strategy_options = {
        "1": "EMA_HYBRID",
        "2": "RANDOM",
        "3": "EMA_STOCHASTIC",
        "4": "LSMC",
        "5": "IMPULSIVE_CROSSOVER"
    }
    
    while True:
        print("Select strategy:")
        for num, name in strategy_options.items():
            print(f"  {num}. {name}")
        
        choice = input("Enter number (1-5): ").strip()
        strategy_name = strategy_options.get(choice)
        
        if strategy_name:
            break
        else:
            print("Invalid choice. Please enter a number between 1 and 5.")

    # Reuse run_bot with no stop_event (CLI mode)
    run_bot(strategy_name)


if __name__ == "__main__":
    main()