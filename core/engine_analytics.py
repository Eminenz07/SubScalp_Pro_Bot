from __future__ import annotations
import json
import datetime as dt
from pathlib import Path
from typing import Dict, Any, Optional
import pandas as pd


class EngineAnalytics:
    """Separate logging and analytics for Engine A, Engine B, and exhaustion events."""
    
    def __init__(self, config: dict):
        self.config = config
        self.analytics_dir = Path(config.get("analytics_dir", "analytics"))
        self.analytics_dir.mkdir(exist_ok=True)
        
        # Initialize tracking dictionaries
        self.engine_a_trades = []
        self.engine_b_trades = []
        self.exhaustion_events = []
        self.false_positives = []
        
        # Daily metrics
        self.daily_engine_stats = {
            "A": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0},
            "B": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
        }
        self.current_date = dt.date.today()
    
    def _maybe_reset_daily(self):
        """Reset daily stats if it's a new day."""
        today = dt.date.today()
        if self.current_date != today:
            self.current_date = today
            self.daily_engine_stats = {
                "A": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0},
                "B": {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}
            }
    
    def record_trade(self, engine: str, symbol: str, side: str, entry_price: float, 
                    exit_price: float, pnl: float, reason: str, 
                    exhaustion_event_id: Optional[str] = None):
        """Record a trade for analytics."""
        self._maybe_reset_daily()
        
        trade_data = {
            "timestamp": dt.datetime.now().isoformat(),
            "engine": engine,
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "reason": reason,
            "exhaustion_event_id": exhaustion_event_id,
            "is_win": pnl > 0
        }
        
        if engine == "A":
            self.engine_a_trades.append(trade_data)
        elif engine == "B":
            self.engine_b_trades.append(trade_data)
        
        # Update daily stats
        self.daily_engine_stats[engine]["trades"] += 1
        self.daily_engine_stats[engine]["pnl"] += pnl
        if pnl > 0:
            self.daily_engine_stats[engine]["wins"] += 1
        else:
            self.daily_engine_stats[engine]["losses"] += 1
        
        # Log to file
        self._log_trade(trade_data)
    
    def record_exhaustion_event(self, symbol: str, exhaustion_type: str, 
                               event_id: str, context: Dict[str, Any]):
        """Record an exhaustion event for analytics."""
        event_data = {
            "timestamp": dt.datetime.now().isoformat(),
            "symbol": symbol,
            "exhaustion_type": exhaustion_type,
            "event_id": event_id,
            "context": context,
            "engine_b_triggered": False,
            "engine_b_trade_id": None
        }
        
        self.exhaustion_events.append(event_data)
        self._log_exhaustion_event(event_data)
    
    def mark_engine_b_triggered(self, event_id: str, trade_id: str):
        """Mark that Engine B was triggered for an exhaustion event."""
        for event in self.exhaustion_events:
            if event["event_id"] == event_id:
                event["engine_b_triggered"] = True
                event["engine_b_trade_id"] = trade_id
                break
    
    def record_false_positive(self, engine: str, symbol: str, reason: str,
                             context: Dict[str, Any]):
        """Record a false positive signal for analytics."""
        false_positive_data = {
            "timestamp": dt.datetime.now().isoformat(),
            "engine": engine,
            "symbol": symbol,
            "reason": reason,
            "context": context
        }
        
        self.false_positives.append(false_positive_data)
        self._log_false_positive(false_positive_data)
    
    def get_engine_performance(self, engine: str, days: int = 30) -> Dict[str, Any]:
        """Get performance metrics for a specific engine."""
        trades = self.engine_a_trades if engine == "A" else self.engine_b_trades
        
        if not trades:
            return {"winrate": 0.0, "avg_pnl": 0.0, "total_trades": 0}
        
        recent_trades = [t for t in trades 
                        if dt.datetime.fromisoformat(t["timestamp"]).date() >= 
                           (dt.date.today() - dt.timedelta(days=days))]
        
        if not recent_trades:
            return {"winrate": 0.0, "avg_pnl": 0.0, "total_trades": 0}
        
        wins = sum(1 for t in recent_trades if t["is_win"])
        total_pnl = sum(t["pnl"] for t in recent_trades)
        
        return {
            "winrate": wins / len(recent_trades) if recent_trades else 0.0,
            "avg_pnl": total_pnl / len(recent_trades) if recent_trades else 0.0,
            "total_trades": len(recent_trades),
            "wins": wins,
            "losses": len(recent_trades) - wins
        }
    
    def get_exhaustion_stats(self) -> Dict[str, Any]:
        """Get statistics about exhaustion events and Engine B performance."""
        if not self.exhaustion_events:
            return {"total_events": 0, "engine_b_triggered": 0, "trigger_rate": 0.0}
        
        total_events = len(self.exhaustion_events)
        engine_b_triggered = sum(1 for e in self.exhaustion_events if e["engine_b_triggered"])
        
        return {
            "total_events": total_events,
            "engine_b_triggered": engine_b_triggered,
            "trigger_rate": engine_b_triggered / total_events if total_events > 0 else 0.0,
            "exhaustion_types": self._count_exhaustion_types()
        }
    
    def _count_exhaustion_types(self) -> Dict[str, int]:
        """Count occurrences of each exhaustion type."""
        type_counts = {}
        for event in self.exhaustion_events:
            exhaustion_type = event["exhaustion_type"]
            type_counts[exhaustion_type] = type_counts.get(exhaustion_type, 0) + 1
        return type_counts
    
    def _log_trade(self, trade_data: Dict[str, Any]):
        """Log trade to daily file."""
        date_str = dt.date.today().isoformat()
        filename = self.analytics_dir / f"trades_{date_str}.jsonl"
        
        with open(filename, "a") as f:
            f.write(json.dumps(trade_data) + "\n")
    
    def _log_exhaustion_event(self, event_data: Dict[str, Any]):
        """Log exhaustion event to daily file."""
        date_str = dt.date.today().isoformat()
        filename = self.analytics_dir / f"exhaustion_{date_str}.jsonl"
        
        with open(filename, "a") as f:
            f.write(json.dumps(event_data) + "\n")
    
    def _log_false_positive(self, fp_data: Dict[str, Any]):
        """Log false positive to daily file."""
        date_str = dt.date.today().isoformat()
        filename = self.analytics_dir / f"false_positives_{date_str}.jsonl"
        
        with open(filename, "a") as f:
            f.write(json.dumps(fp_data) + "\n")
    
    def generate_daily_report(self) -> str:
        """Generate a daily performance report."""
        self._maybe_reset_daily()
        
        engine_a_perf = self.get_engine_performance("A", days=1)
        engine_b_perf = self.get_engine_performance("B", days=1)
        exhaustion_stats = self.get_exhaustion_stats()
        
        report = f"""
Daily Trading Report - {dt.date.today().isoformat()}

Engine A Performance:
- Trades: {engine_a_perf['total_trades']}
- Wins: {engine_a_perf['wins']}
- Losses: {engine_a_perf['losses']}
- Win Rate: {engine_a_perf['winrate']:.2%}
- Avg PnL: ${engine_a_perf['avg_pnl']:.2f}

Engine B Performance:
- Trades: {engine_b_perf['total_trades']}
- Wins: {engine_b_perf['wins']}
- Losses: {engine_b_perf['losses']}
- Win Rate: {engine_b_perf['winrate']:.2%}
- Avg PnL: ${engine_b_perf['avg_pnl']:.2f}

Exhaustion Events:
- Total Events: {exhaustion_stats['total_events']}
- Engine B Triggered: {exhaustion_stats['engine_b_triggered']}
- Trigger Rate: {exhaustion_stats['trigger_rate']:.2%}

Exhaustion Types:
"""
        for exhaustion_type, count in exhaustion_stats['exhaustion_types'].items():
            report += f"- {exhaustion_type}: {count}\n"
        
        report += "\nEngine B Performance by Exhaustion Type:\n"
        for typ, data in self.get_engine_b_performance_by_exhaustion_type().items():
            report += f"- {typ}: Trades={data['trades']}, Winrate={data['winrate']:.2%}, Avg PnL=${data['avg_pnl']:.2f}\n"
        
        return report