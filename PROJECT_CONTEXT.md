# SubScalp WealthBot — Comprehensive Project Context

> **Version:** March 2026  
> **Primary Broker:** MetaTrader 5 (Deriv-Demo)  
> **Language:** Python 3.12+  
> **Status:** Active development, running in MT5 paper/demo mode

---

## 1. Project Overview

**SubScalp WealthBot** is an automated algorithmic trading bot designed for scalping and short-term momentum trades across forex pairs, synthetic indices, and crypto. It connects to multiple brokers (MT5, Deriv, Binance, Oanda), fetches OHLCV data, evaluates market conditions through a multi-engine strategy framework, sizes trades based on risk parameters, and manages open positions with break-even and trailing stop logic.

### Goals
- **Automated execution:** Poll markets on a configurable interval (default 30s), generate signals, place/manage orders without human intervention.
- **Multi-engine architecture:** Run independent trading "engines" (Engine A: momentum continuation, Engine B: mean-reversion on exhaustion) that coordinate to avoid conflicting trades.
- **Robust risk management:** Cap daily trades, daily loss, per-symbol exposure, and cooldown periods after losses.
- **Real-time notifications:** Telegram for trade events, Email for critical risk alerts and daily summaries.
- **Multi-broker support:** MT5 as the primary connector, with Deriv/Binance/Oanda connectors available.

---

## 2. File Structure

### Root Files

| File | Purpose |
|---|---|
| `main.py` | Entry point. Strategy selection menu, builds the "trade stack" (all dependencies), runs the infinite polling loop. |
| `backtest.py` | Backtesting engine for running strategies against historical data. Exports results to CSV. |
| `requirements.txt` | Python dependency list. |
| `.env` | Environment variables: MT5 login, Telegram bot token, email SMTP creds. |
| `.gitignore` | Standard ignores for `.env`, `__pycache__`, logs, `.venv`. |
| `README.md` | Project readme. |
| `test_impulsive_strategy.py` | Unit tests for the Impulsive Crossover strategy. |
| `test_mt5_connection.py` | MT5 connection smoke test. |
| `test_notifications.py` | Notification system tests. |
| `main_test_random.py` | Test harness for the Random strategy. |
| `temp_get_symbols.py` | Utility script to list available symbols from a broker. |
| `backtest_results_ema.csv` | Saved backtest output. |

### `config/`

| File | Purpose |
|---|---|
| `config.json` | **Master config.** Broker selection, risk parameters, symbol lists per broker, strategy settings, notification settings. |
| `strategies.json` | Parameters for the EMA Hybrid strategy (EMA periods, ATR, RSI, Stochastic, multi-timeframes). |
| `ema_stochastic_config.json` | Dedicated config for the EMA+Stochastic strategy. |
| `config_test_random.json` | Config for the Random strategy test harness. |

### `core/` — Trading Engine

| File | Purpose |
|---|---|
| `indicators.py` | Technical indicator library: EMA, SMA, ATR, RSI, ADX, Stochastic, Fibonacci retracement, impulse candle detection, RSI divergence, ATR expansion check. |
| `strategy_lsmc.py` | **Engine A** — Liquidity Sweep Momentum Continuation. The primary strategy for trending markets. Coordinates with Engine B. |
| `strategy_rsi_fibonacci.py` | **Engine B** — RSI + Fibonacci retracement. Only fires when Engine A detects trend exhaustion and explicitly allows it. |
| `strategy_impulsive_crossover.py` | **Impulsive Crossover** — Standalone dual-timeframe strategy (H1 trend + M15 entry) with RSI crossover signals, regime lockout system, and trailing stop logic. |
| `strategy_ema_hybrid.py` | EMA Trend + ATR + RSI + Stochastic hybrid. Uses multi-timeframe alignment. |
| `strategy_ema_stochastic.py` | EMA + Stochastic Oscillator multi-timeframe strategy with overbought/oversold entries. |
| `strategy_random.py` | Random signal generator for testing infrastructure. |
| `trade_manager.py` | **Central orchestrator.** Handles signal processing, position sizing, order placement (single or partial-TP), position monitoring, break-even adjustments, and trade result recording. |
| `risk_manager.py` | Enforces risk limits: max trades/day, daily loss cap, per-symbol caps, engine-specific limits, cooldown timers after losses. |
| `break_even_manager.py` | Adjusts stop-loss to break-even or advanced BE levels when price moves in favor by configurable R-multiples. |
| `survival_rules.py` | Global kill-switch system: blocks trading during volatility spikes, drawdown events, consecutive losses, or low winrate periods. |
| `engine_analytics.py` | Per-engine (A/B) trade recording, daily stats, exhaustion event tracking, daily performance reports. Writes JSONL files to `analytics/`. |
| `exhaustion_event.py` | Persistent exhaustion event objects. Ensures Engine B can only fire once per exhaustion event. Events expire after 60 minutes. |
| `structure.py` | Market structure analysis: regime classification (trending/ranging/volatility), swing detection, BOS/CHoCH detection, pivot points, impulse leg counting, trend exhaustion detection, equal highs/lows, inducement zones. |
| `liquidity_sweep.py` | Detects liquidity sweeps (spike beyond recent highs/lows or equal level touches). |
| `multi_timeframe_analysis.py` | Higher-timeframe trend bias (via EMA slope) and choppiness detection. |
| `regime_classifier.py` | Centralized regime classifier: returns `TRENDING`, `RANGE`, `TRANSITION`, or `VOLATILITY_SPIKE` based on EMA slope ratio and ATR. |

### `connectors/` — Broker Connections

| File | Purpose |
|---|---|
| `__init__.py` | `BaseConnector` ABC (connect, get_historical_data, place_order, close_order, get_account_info). Factory `get_connector()` maps broker name → connector class. |
| `mt5_connector.py` | **Primary connector.** Full MT5 integration with paper-mode fallback. Handles login, OHLCV fetch, order placement with margin/volume validation, SL/TP distance enforcement, position monitoring, and order modification. |
| `deriv_connector.py` | Deriv API connector (WebSocket-based, partially deprecated). |
| `binance_connector.py` | Binance connector via CCXT. |
| `oanda_connector.py` | OANDA REST API connector. |

### `notifications/` — Alert System

| File | Purpose |
|---|---|
| `enums.py` | `EventType` and `Severity` enums (BOT_START/STOP/CRASH, TRADE_OPEN/CLOSE, risk events, daily summary, heartbeat). |
| `notifier.py` | Central dispatcher. Routes events to Telegram and/or Email based on severity/type. Uses ThreadPoolExecutor for async dispatch. Includes heartbeat timer. |
| `telegram_client.py` | Sends plain-text messages via Telegram Bot API with retry logic and rate-limit handling. |
| `email_client.py` | SMTP email client (Gmail STARTTLS) with error handling. |
| `templates.py` | Message formatting: Telegram (emoji-prefixed plain text), Email (subject + body with severity labels). |
| `state_manager.py` | Thread-safe notification throttling. Configurable cooldowns per event type to prevent notification spam. |

### `utils/` — Utilities

| File | Purpose |
|---|---|
| `data_handler.py` | `DataHandler`: wraps connector's `get_historical_data`, cleans/normalizes OHLCV DataFrames. Also `verify_mt5_connection()` and `retry_on_exception` decorator. |
| `logger.py` | Rotating file loggers (`trades.log`, `errors.log`) with console output. Logs stored in `logs/` directory. |
| `visualizer.py` | Placeholder for future charting/visualization. |

### `analytics/` — Output Directory
Empty directory. `EngineAnalytics` writes daily JSONL files here at runtime (`trades_YYYY-MM-DD.jsonl`, `exhaustion_YYYY-MM-DD.jsonl`, `false_positives_YYYY-MM-DD.jsonl`).

---

## 3. Core Logic — Trading Strategies

### 3.1 Strategy Selection (5 available)

At startup, the user selects one of:

| # | Name | Class | Description |
|---|---|---|---|
| 1 | `EMA_HYBRID` | `StrategyEMAHybrid` | EMA crossover + RSI + Stochastic with multi-timeframe alignment |
| 2 | `RANDOM` | `StrategyRandom` | Random signals for testing |
| 3 | `EMA_STOCHASTIC` | `StrategyEMAStochastic` | Multi-TF EMA + Stochastic overbought/oversold |
| 4 | `LSMC` | `StrategyLSMC` | **Dual-engine system** (Engine A + Engine B). The most sophisticated strategy. |
| 5 | `IMPULSIVE_CROSSOVER` | `StrategyImpulsiveCrossover` | H1/M15 dual-timeframe with RSI 50-cross entries and regime lockout |

### 3.2 Engine A — LSMC (Liquidity Sweep Momentum Continuation)

**Purpose:** Trade momentum continuations after liquidity sweeps in trending markets.

**Entry Conditions (Long):**
1. Higher timeframe (M15) EMA-50 trend bias is **bullish**
2. Market is **not choppy** (EMA change above threshold)
3. Market structure is **not broken** (no whipsaw beyond both extremes)
4. Structure label is **not "mixed"** (must be HH/HL or LL/LH)
5. No CHoCH (Change of Character) detected
6. **Liquidity sweep detected** (price spiked below recent lows)
7. Current candle is an **impulse candle** (body ≥ 1.5× ATR)
8. Trend is **not exhausted** (checked via multiple factors)
9. Regime is **TRENDING** (RegimeClassifier)

**SL/TP:** SL = 1× ATR, TP = 1.5× SL (configurable 1.5–2.0 RR)

**Exhaustion → Engine B Handoff:**
When Engine A detects trend exhaustion (≥2 of: EMA stretch, impulse count ≥3, trend duration exceeded, momentum decay), it returns `ALLOW_ENGINE_B_EVALUATION` instead of taking a trade.

### 3.3 Engine B — RSI + Fibonacci (Conditional)

**Purpose:** Mean-reversion trades at Fibonacci levels during trend exhaustion. **Only runs when explicitly allowed by Engine A.**

**Hard Gates (all must pass):**
- Market state must be `ALLOW_ENGINE_B_EVALUATION`
- Must have a valid `exhaustion_event_id`
- Event must not be "consumed" (Engine B can only fire **once per exhaustion event**)
- Symbol must NOT be BOOM or CRASH
- Regime must be `TRENDING`, bias not neutral, structure not mixed, no CHoCH
- Impulse leg direction must match bias

**Entry Conditions (Long):**
1. Bias is **bullish**, candle is **not an impulse**
2. **Bullish RSI divergence** detected
3. **Confluence present:** candlestick rejection pattern, structural pivot hold, or liquidity sweep confirmation
4. Price is in the **Fibonacci 0.5–0.618 zone** of the last impulse leg

**SL/TP:** SL = 0.8× ATR (tighter), TP = 1.75× SL (lower RR)

### 3.4 Impulsive Crossover Strategy

**Timeframes:** H1 (trend) + M15 (execution)

**H1 Trend Determination:**
- EMA-89 > SMA-200 → Bullish
- EMA-89 < SMA-200 → Bearish

**Execution Filters (all must pass):**
1. **Session filter:** London open (08:00) to NY close (21:00) UTC
2. **ADX > 25** (choppy market rejection)
3. **SMA-200 slope > 0.005%** (flat market rejection)

**Entry (Long):**
- H1 trend = bullish
- M15: EMA-89 > SMA-200 (aligned)
- M15: RSI crossed **above 50** on current candle

**SL/TP:** SL = 1.5× ATR, TP = SL × 1.5 (TP2 at 3.0×)

**Regime Lockout System:**
- Tracks consecutive losses. After N losses (default 3), enters `REGIME_LOCKED` state
- Unlocks only when H1 EMA-89 slope **sign flips** and stays stable for N candles (default 3)
- Tracks lockout metrics (total lockouts, duration, signals blocked)

**Trailing Stop:**
- Activates at 1.75R profit
- Weak regime: trail at 1.2× ATR
- Strong regime: trail at 1.6× ATR

### 3.5 EMA Hybrid Strategy

**Indicators:** EMA-21/50, ATR-14, RSI-14, Stochastic (14/3/3)

**Entry (Long):** Fast EMA > Slow EMA AND RSI > 50 AND Stochastic %K crosses above %D

**SL/TP:** SL = 1.5× ATR, TP = 2.0× SL

**Multi-timeframe:** Supports alignment across M15 + H1 (all timeframes must agree on signal direction).

### 3.6 EMA + Stochastic Strategy

**Timeframes:** M5 (signal), M30 (trend)

**Trend:** M30 EMA-50 vs EMA-200

**Entry (Long):** Stochastic dips below oversold (20), crosses back above, close > EMA-10

**SL/TP:** Configurable ATR multipliers

---

## 4. Supported Trading Pairs

### Deriv / MT5 Symbols
| Category | Symbols |
|---|---|
| Forex | `frxEURUSD`, `frxGBPUSD`, `frxUSDJPY`, `frxUSDCHF`, `frxAUDUSD` |
| Volatility Indices | `R_100`, `R_75`, `R_50`, `R_25`, `R_10` |
| Crash/Boom | `CRASH1000`, `BOOM1000`, `CRASH500`, `BOOM500` |
| Jump Index | `JD100` |
| Step Index | `stpRNG` |
| Commodities | `frxXAUUSD` (Gold) |
| Crypto | `cryBTCUSD` |

### Binance Symbols
`BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, `ADAUSDT`, `XRPUSDT`

### OANDA Symbols
`EUR_USD`, `GBP_USD`, `USD_JPY`, `AUD_USD`, `USD_CHF`, `USD_CAD`, `XAU_USD`

### Pair-Specific Rules
- **BOOM/CRASH symbols:** Engine B (RSI-Fibonacci) is **hard-blocked** on these.
- **Engine B risk:** 20% less risk allocation than Engine A on all symbols.
- **Engine B spread limit:** Max 2.0 pips (vs 5.0 for Engine A).

---

## 5. Risk Management

### Lot Sizing Formula
```
size = (Equity × risk_per_trade) / (tick_value × (sl_distance / point))
```
- `risk_per_trade`: 2% of equity (configurable)
- Engine B trades use 80% of the normal risk amount (20% reduction)

### Daily Limits (from `config.json`)
| Parameter | Value |
|---|---|
| `risk_per_trade` | 0.02 (2%) |
| `max_trades_per_day` | 10 |
| `daily_loss_limit` | 0.10 (10%) |
| `max_trades_per_symbol_per_day` | 2 |
| `cooldown_candles_after_loss` | 5 candles |

### Engine B Specific Limits (from `RiskConfig`)
| Parameter | Value |
|---|---|
| `max_engine_b_trades_per_day` | 2 |
| `max_engine_b_per_symbol_per_day` | 1 |
| `engine_b_cooldown_candles_after_loss` | 10 candles |

### Survival Rules (Global Kill-Switches)
The `SurvivalRules` module blocks all trading when:
- **VOLATILITY_LOCK:** ATR > 1.8× average range, or M15 regime is "volatility_expanded"
- **DRAWDOWN_PROTECTION:** Daily loss exceeds daily_loss_limit
- **CONSECUTIVE_LOSS_PROTECTION:** ≥3 consecutive stop-losses
- **LOW_WINRATE_PROTECTION:** Winrate < 30% over last 20 trades

### Break-Even Logic
- **Standard BE:** SL moves to entry + spread when profit ≥ 1.0R
- **Engine B BE:** Earlier trigger at 0.8R
- **Deriv Advanced BE:** SL moves to entry + (0.8R × risk_per_unit) when profit ≥ 0.8R

### Pre-Trade Filters (TradeManager)
1. **Spread filter:** Blocks if spread > 5 pips (Engine A) or > 2 pips (Engine B)
2. **Volatility filter:** Blocks if ATR > 25 pips (Engine A) or > 15 pips (Engine B)
3. **Margin check:** Validates free margin; reduces volume iteratively if insufficient
4. **Volume validation:** Rounds to broker's `volume_step`, clamps to `volume_min`/`volume_max`

---

## 6. Execution Flow

### Startup Sequence
```
1. main() prompts user to select strategy (1-5)
2. build_trade_stack(strategy_name) runs:
   a. Load config.json
   b. Determine broker (default: "mt5")
   c. Instantiate connector → connector.connect()
   d. Instantiate Notifier (Telegram + Email)
   e. Resolve symbol list (API or config)
   f. Instantiate DataHandler (wraps connector)
   g. Instantiate EngineAnalytics
   h. Instantiate selected Strategy
   i. Instantiate RiskManager with RiskConfig
   j. Instantiate BreakEvenManager
   k. Instantiate SurvivalRules
   l. Instantiate TradeManager (receives all above)
3. Send BOT_START notification
4. Enter infinite loop
```

### Per-Cycle (every 30s)
```
FOR each symbol in symbol list:
  1. aligned_row(symbol, base_tf, stack):
     a. Fetch OHLCV data for signal TF and trend TF
     b. [LSMC only] Run survival rules regime check
     c. [LSMC only] Check spread vs ATR gating
     d. Strategy.evaluate_market() or Strategy.generate_signals()
     e. [LSMC] If ALLOW_ENGINE_B → instantiate StrategyRSIFibonacci → generate_signals()
     f. Return last row as dict (or None if no signal)

  2. process_symbol(symbol, base_tf, stack):
     a. If aligned_row returns a valid row with signal ≠ 0:
        → TradeManager.process_signal(symbol, row)
     b. process_signal():
        - Parse signal, price, sl_distance, tp_distance, engine
        - If invalidate flag: close existing position
        - If signal > 0 (buy): close any short → open long
        - If signal < 0 (sell): close any long → open short
     c. open_position():
        - RiskManager.can_trade() check
        - Spread filter, volatility filter
        - Apply slippage to entry price
        - Compute position size from risk formula
        - Calculate SL/TP price levels
        - [Engine B] Split into partial-TP orders if configured
        - Connector.place_order()
        - Register with RiskManager
        - Send TRADE_OPEN notification
     d. If Engine B trade opened → mark exhaustion event consumed

  3. TradeManager.monitor_positions():
     a. Check broker for closed positions (SL/TP hit externally)
     b. For open positions: check break-even adjustment
     c. Record trade results in RiskManager + EngineAnalytics
     d. Clean up closed positions from local tracking

  4. Notifier.check_heartbeat() (every 12 hours)

  5. time.sleep(poll_interval)  # 30 seconds
```

### Shutdown
- `KeyboardInterrupt`: logs stop, sends BOT_STOP notification
- Unhandled exception: logs error, sends BOT_CRASH (CRITICAL severity)
- `notifier.shutdown()` and `logging.shutdown()` in `finally` block

---

## 7. GUI Breakdown

**There is no GUI.** The bot runs as a CLI application:
- Strategy selection via numbered menu at startup
- All output goes to console (via loggers) and log files
- Trade notifications via Telegram and Email

---

## 8. Data Flow

```
┌─────────────────────────────────────────────────────────┐
│                        main.py                           │
│  (polling loop: for each symbol, every 30s)              │
├──────────────┬───────────────────────────────────────────┤
│              │                                           │
│     DataHandler.fetch_ohlcv()                            │
│         │                                                │
│         ▼                                                │
│  Connector.get_historical_data()                         │
│  (MT5 → copy_rates_from_pos)                             │
│         │                                                │
│         ▼                                                │
│  OHLCV DataFrame (timestamp, O, H, L, C, V)             │
│         │                                                │
│   ┌─────┴──────┐                                         │
│   │            │                                         │
│   ▼            ▼                                         │
│ Signal TF   Trend TF                                     │
│ (M5/M15)    (M15/H1)                                     │
│   │            │                                         │
│   └──────┬─────┘                                         │
│          ▼                                               │
│  Strategy.generate_signals(df_signal, df_trend)          │
│  (computes indicators, applies entry rules)              │
│          │                                               │
│          ▼                                               │
│  Signal Row: {signal, close, sl_distance, tp_distance}   │
│          │                                               │
│          ▼                                               │
│  TradeManager.process_signal(symbol, row)                │
│          │                                               │
│    ┌─────┴──────┐                                        │
│    │            │                                        │
│    ▼            ▼                                        │
│ RiskManager  BreakEvenManager                            │
│ (can_trade?) (adjust SL?)                                │
│    │            │                                        │
│    └─────┬──────┘                                        │
│          ▼                                               │
│  Connector.place_order() / modify_order()                │
│  (MT5 order_send / paper mode)                           │
│          │                                               │
│    ┌─────┴─────────┐                                     │
│    ▼               ▼                                     │
│ Notifier      EngineAnalytics                            │
│ (Telegram     (JSONL files                               │
│  + Email)      in analytics/)                            │
└─────────────────────────────────────────────────────────┘
```

---

## 9. Dependencies

| Library | Version | Purpose |
|---|---|---|
| `pandas` | ≥2.2.0 | DataFrame operations for OHLCV data and indicator computation |
| `numpy` | ≥1.26.0 | Numerical operations in indicators |
| `MetaTrader5` | ≥5.0.37 | MT5 terminal API (Windows only) |
| `ccxt` | ≥4.3.70 | Binance connector (CCXT unified API) |
| `oandapyV20` | ≥0.7.2 | OANDA REST API connector |
| `requests` | ≥2.31.0 | Telegram Bot API HTTP calls |
| `python-dotenv` | ≥1.0.1 | Load `.env` file for credentials |
| `matplotlib` | ≥3.8.0 | Backtesting visualization (optional) |
| `python-dateutil` | ≥2.9.0 | Date/time utilities |
| `pytest` | ≥7.4.0 | Unit testing framework |
| `tqdm` | ≥4.66.5 | Progress bars for backtesting |

---

## 10. Current Limitations & Known Issues

### Code Issues
1. **`strategy_lsmc.py` has dead/broken code:** Lines 92–139 contain a duplicate `generate_signals` body inside the `mark_engine_b_consumed` method — orphaned code that would error if called. The `mark_engine_b_consumed` at line 289 references `self.exhaustion_states` but this attribute is never defined (the class uses `self.event_manager` instead).

2. **`structure.py` line 263 syntax error:** `reasons = [...] if cond else []` — `cond` is undefined. This would crash at runtime when `detect_trend_exhaustion` is called.

3. **`main.py` duplicate keys** in `strategy_options` dict (keys "2" and "3" are defined twice) and a duplicate `break` statement on line 341.

4. **`mt5_connector.py` line 429:** Duplicate `return` statement in `get_account_info()`.

5. **`break_even_manager.py` line 12:** Uses `Optional[str]` without importing `Optional` from typing.

6. **No `List` import** in `mt5_connector.py` line 433 (`get_open_positions` return type uses `List` but it's not imported).

### Architectural Limitations
7. **No persistent state:** All position tracking is in-memory. If the bot restarts, it loses awareness of open positions (though MT5 manages them broker-side).

8. **Paper mode always active on import failure:** If `MetaTrader5` package isn't installed (Linux/macOS), the connector silently falls back to paper mode with empty OHLCV data — the bot runs but does nothing.

9. **No GUI/dashboard:** All monitoring is via log files and Telegram notifications.

10. **Single-threaded polling:** Symbols are processed sequentially. With 18 symbols, each cycle could take several seconds for data fetching.

11. **Hardcoded slippage default:** `_get_atr_for_symbol()` in TradeManager returns a hardcoded `0.0005` instead of computing actual ATR.

12. **`RegimeClassifier` is instantiated in `strategy_lsmc.py generate_signals`** via `self.regime_classifier.classify()` but `regime_classifier` is never initialized as an instance attribute.

13. **Notification templates.py** has `"KX"` instead of a proper emoji for positive profit icon on line 40.

---

## 11. Recent Changes & Additions

Based on the codebase state:

1. **Impulsive Crossover Strategy (V2)** — Recently added as strategy #5. Features a novel regime lockout system based on consecutive losses and H1 EMA slope sign-flip recovery. Includes trailing stop with weak/strong regime multipliers. This is currently the actively developed strategy.

2. **Exhaustion Event System** — Added `exhaustion_event.py` with persistent `ExhaustionEvent` and `ExhaustionEventManager` classes to ensure Engine B can only trade once per exhaustion event with 60-minute expiry.

3. **Engine Analytics** — Added `engine_analytics.py` for separate Engine A/B performance tracking, exhaustion event logging, and daily report generation. Outputs JSONL files.

4. **Notification System Overhaul** — Full notification pipeline with `Notifier`, `TelegramClient`, `EmailClient`, `NotificationStateManager`, `MessageTemplates`, and `EventType`/`Severity` enums. Includes throttling, heartbeat, and async dispatch via ThreadPoolExecutor.

5. **MT5 Connector Hardening** — Added margin validation, volume step/min/max enforcement, SL/TP distance validation, `modify_order()` for break-even, `get_open_positions()` for monitoring, `close_all_positions()`, and `get_position_info()`.

6. **Break-Even Manager** — Added engine-specific R-levels (Engine B triggers earlier at 0.8R vs 1.0R) and Deriv-specific advanced break-even.

7. **Survival Rules** — Added as a global kill-switch layer with volatility lock, drawdown protection, consecutive loss pausing, and low winrate detection.

8. **Broker set to MT5** — Config changed from Deriv to MT5 as the primary broker, with Deriv connector deprecated but preserved.

---

## 12. Configuration Quick Reference

### Key `config.json` Parameters
```json
{
  "broker": "mt5",
  "risk_per_trade": 0.02,
  "max_trades_per_day": 10,
  "daily_loss_limit": 0.10,
  "timeframe": "M5",
  "poll_interval": 30,
  "equity": 10000,
  "htf_trend_timeframe": "M15",
  "max_trades_per_symbol_per_day": 2,
  "cooldown_candles_after_loss": 5,
  "winrate_pause_threshold": 0.3,
  "winrate_lookback_trades": 20,
  "consecutive_sl_pause_count": 3
}
```

### Environment Variables (`.env`)
```
MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
EMAIL_USERNAME, EMAIL_PASSWORD, EMAIL_TO
DERIV_APP_ID, DERIV_API_TOKEN
```

---

*This document was auto-generated from full codebase analysis on March 21, 2026. It reflects the state of all source files at that time.*
