# SubScalp Pro Bot 🚀

**SubScalp Pro Bot** is a high-performance, automated trading bot built for **MetaTrader 5 (MT5)**. It features a hardened, production-grade notification system, multi-strategy support, and robust risk management designed for 24/7 VPS operation.

---

## 🔥 Key Features

### 🤖 Intelligent Trading

- **Multi-Strategy Architecture**: Supports EMA Crossover, Stochastic, RSI, and LSMC (Liquidity Sweep Momentum Continuation) logic.
- **Paper Trading Mode**: Automatically falls back to paper trading if MT5 is unavailable or for testing.
- **Dynamic Risk Management**:
  - Daily Loss Limits.
  - Max Trades Per Day.
  - Drawdown Protection.

### 🛡️ Production-Hardened Notifications

A centralized, non-blocking notification system designed for stability:

- **Telegram Integration**: Real-time trade alerts (Plain Text for reliability).
- **Email Reports**: Critical error alerts and Daily Trading Summaries.
- **Smart Throttling**: Prevents spam during high-volatility events (e.g., `BOT_START` throttled to once per 10m).
- **Heartbeat Monitor**: Sends "System Operational" reports every 12 hours.
- **Concurrency**: Uses a safe `ThreadPoolExecutor` to ensure trading logic is never blocked by network calls.

### 🔌 Connectivity

- **Primary**: MetaTrader 5 (Windows).
- **Secondary Support**: Connectors for Binance, Deriv, and Oanda (extensible).

---

## 🛠️ Installation

### Prerequisites

- Windows OS (Required for local MT5 terminal).
- Python 3.10+.
- MetaTrader 5 Terminal installed and logged in.

### Setup Steps

1. **Clone the Repository**

   ```bash
   git clone https://github.com/Eminenz07/SubScalp_Pro_Bot.git
   cd SubScalp_Pro_Bot
   ```

2. **Create a Virtual Environment**

   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. **Install Dependencies**

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables**
   Create a `.env` file in the root directory:

   ```env
   # Telegram
   TELEGRAM_BOT_TOKEN=your_bot_token
   TELEGRAM_CHAT_ID=your_chat_id

   # Email (Gmail Example)
   EMAIL_USERNAME=your_email@gmail.com
   EMAIL_PASSWORD=your_app_password
   EMAIL_TO=recipient@example.com

   # MT5 Credentials (Optional - uses terminal login by default)
   MT5_LOGIN=12345678
   MT5_PASSWORD=your_password
   MT5_SERVER=Broker-Server
   ```

---

## ⚙️ Configuration

### `config/config.json`

Controls the bot's core behavior, risk settings, and active broker.

```json
{
  "project_name": "SubScalpBot",
  "active_broker": "mt5",
  "risk_settings": {
    "max_trades_per_day": 50,
    "daily_loss_limit": 0.05,
    "max_drawdown": 0.1
  }
}
```

### `config/strategies.json`

Fine-tune strategy parameters (EMA periods, RSI thresholds, etc.).

---

## 🚀 Usage

### Live Trading

Start the bot in the console. It will auto-detect the connected MT5 terminal.

```bash
python main.py
```

### Verify Notifications

Run the standalone test script to verify Telegram/Email delivery without placing trades.

```bash
python test_notifications.py
```

### Backtesting

Run historical simulations using your strategy logic.

```bash
python backtest.py
```

---

## 📂 Project Structure

```text
SubScalp_Pro_Bot/
├── config/                 # Configuration JSONs
├── connectors/             # Broker integrations (MT5, Binance, etc.)
├── core/                   # Trading logic, engines, and risk management
├── logs/                   # Execution and Trade logs
├── notifications/          # Hardened Notification Module
│   ├── notifier.py         # Threaded Dispatcher
│   ├── telegram_client.py  # Telegram API Handler
│   ├── email_client.py     # SMTP Handler
│   └── state_manager.py    # Throttling Logic
├── utils/                  # Helpers (Logger, Visualizer)
├── main.py                 # Application Entry Point
└── requirements.txt        # Python Dependencies
```

---

## ⚠️ Disclaimer

**Trading Foreign Exchange (Forex), CFDs, and Cryptocurrencies carries a high level of risk and may not be suitable for all investors.** The high degree of leverage can work against you as well as for you. Before deciding to trade, you should carefully consider your investment objectives, level of experience, and risk appetite. The authors of this software accept no liability for any losses incurred.

**Use at your own risk.**
