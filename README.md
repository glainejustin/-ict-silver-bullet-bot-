<p align="center">
  <img src="https://img.shields.io/badge/status-production--ready-brightgreen" alt="Status">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/platform-MetaTrader%205-orange" alt="MT5">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
</p>

<p align="center">
  <h1 align="center">🏦 ICT Silver Bullet Bot</h1>
  <p align="center"><em>Institutional-Grade Algorithmic Trading System for Funded Challenge Accounts</em></p>
</p>

---

> ⚠️ **FINANCIAL RISK DISCLAIMER**
>
> **This software is provided for educational and research purposes only.**
>
> - **Past performance does not guarantee future results.** Backtested returns are not indicative of live trading outcomes.
> - **You trade at your own risk.** The author(s) assume no liability for any financial losses incurred through the use of this software.
> - **Foreign exchange, commodities, and cryptocurrency trading carries a high level of risk** and may not be suitable for all investors. You could lose more than your initial deposit.
> - **This bot is not a "set and forget" solution.** It requires monitoring, understanding of the underlying strategies, and manual intervention when market conditions deviate from historical norms.
> - **Demo-test thoroughly.** Run the bot on a demo account for **at least 2–4 weeks** before deploying any real capital. Verify that it behaves as expected under live market conditions.
> - **Funded challenge accounts have strict rules.** Exceeding daily loss limits, maximum drawdown, or inactivity periods can result in account termination regardless of bot performance.
> - **This is not financial advice.** Nothing in this repository constitutes a recommendation to buy or sell any financial instrument.
>
> By using this software, you acknowledge that you have read, understood, and agree to these terms.

---

## 📖 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Project Structure](#️-project-structure)
- [Quick Start](#-quick-start)
  - [Prerequisites](#prerequisites)
  - [Installation](#1-clone--install)
  - [Telegram Bot Setup](#2-telegram-bot-setup)
  - [Configuration](#3-configure-risk--symbols)
  - [MT5 Setup](#4-mt5-setup)
  - [Launch](#5-launch)
- [Backtesting](#-backtesting)
- [Telegram Commands](#-telegram-commands)
- [Configuration Reference](#️-configuration-reference)
- [Security](#-security)
- [Contributing](#-contributing)
- [License](#-license)
- [Acknowledgments](#-acknowledgments)

---

## 📖 Overview

The ICT Silver Bullet Bot is a modular algorithmic trading system built on the **MetaTrader 5 Python API**. It executes **4 institutional-grade strategies** across **5 currency pairs** using ICT/SMC (Smart Money Concepts) — institutional order flow, market structure shifts, and fair value gaps.

Designed specifically for **funded challenge accounts** (FundedNext, FTMO, etc.), the bot enforces challenge rules via a professional risk guardian: daily loss limits, profit targets, trailing drawdown, and Friday close-out.

### Supported Instruments

| Symbol | Type | Strategies |
|--------|------|------------|
| **XAUUSD** | Gold (Spot) | Silver Bullet · Raja Banks · Pure Price Action |
| **GBPJPY** | Forex (Major Cross) | Silver Bullet · Raja Banks · Pure Price Action |
| **EURUSD** | Forex (Major) | Silver Bullet · Pure Price Action |
| **AUDUSD** | Forex (Major) | Silver Bullet · Pure Price Action |
| **USDJPY** | Forex (Major) | Silver Bullet · Pure Price Action |

---

## ✨ Features

### 📊 Strategy Arsenal

| Strategy | Timeframe | Description |
|----------|-----------|-------------|
| **Silver Bullet** | M5 | ICT Silver Bullet window (10-11 AM & 2-3 PM NY). Sweep → MSS → Displacement → FVG entry with limit orders |
| **Raja Banks** | H4 + M5 | H4 structural break confirmed by M5 sniper entry. 2:1 risk-reward targeting liquidity pools |
| **Pure Price Action** | H4 + M5 | H4 support/resistance rejection with wick confirmation and clean traffic validation |
| **London Breakout** | M15 | 8:00-8:30 AM London range breakout with pending orders (available, disabled by default) |

### 🛡️ Risk Guardian (Funded Challenge Compliant)

| Rule | Default | Behavior |
|------|---------|----------|
| Daily Profit Target | 3.0% | Auto-pauses trading when hit |
| Daily Loss Limit | 4.0% | Hard stop for the day |
| Max Total Loss | 8.0% | Permanent halt (challenge blown) |
| Trailing Drawdown | 5.0% | Halts if equity drops 5% from peak |
| Weekly Loss Limit | 3.0% | 24-hour cool-down period |
| Friday Auto-Close | 8 PM NY | All positions closed for weekend safety |
| Coast Mode | ≥7% profit | Reduces risk to 0.1% near target |
| Soft Recovery | After losing day | Halves risk on next session |

### 🧠 Institutional Intelligence

- **Synthetic DXY Consensus** — Derives USD directional bias from 7 major pairs
- **Correlation Penalty** — Halves position size on overlapping USD exposure
- **Volatility-Adjusted Sizing** — Scales lots down during high-ATR regimes
- **Liquidity Cost Guard** — Blocks entries when spread exceeds 15% of ATR
- **Exhaustion Wick Detection** — Filters fading momentum from false breakouts
- **SFP Rejection Guard** — Detects institutional liquidity sweeps (stop hunts)
- **Execution Tax** — Adjusts lot size for high-velocity market conditions
- **Stale Price Heartbeat** — Halts trading if data exceeds 30-second age

---

## 🏗️ Project Structure

```
ict_silver_bullet_bot/
├── main.py                     # Entry point: main loop, guardian, Telegram
├── config.py                   # All configuration (risk, symbols, strategies)
├── backtest_combined.py        # Multi-symbol tick-level backtester
├── automate_report.py          # Auto backtest + dashboard generation
├── test_trade.py               # Manual trade execution tester
├── start_bot.bat               # Windows auto-restart launcher
├── requirements.txt            # Python dependencies
├── README.md                   # This file
├── walkthrough.md              # Detailed strategy walkthrough
├── DEPLOYMENT_CHECKLIST.md     # Pre-deployment verification checklist
├── .env.example                # Environment variable template
├── .gitignore                  # Git exclusion rules
│
├── core/                       # Core modules (13 files)
│   ├── connection.py           # MT5 connection & permission checks
│   ├── order_manager.py        # Trade execution, fills, closing
│   ├── risk_manager.py         # Lot sizing, volatility, correlation
│   ├── trade_manager.py        # Position management (trailing SL, partial TP)
│   ├── signal_aggregator.py    # Multi-strategy signal aggregation
│   ├── data_fetcher.py         # MT5 historical data fetching
│   ├── price_action.py         # ICT concepts: FVG, MSS, SFP, ATR
│   ├── sentiment_manager.py    # Synthetic DXY consensus & momentum
│   ├── news_manager.py         # High-impact news buffer (auto-fetch)
│   ├── performance_tracker.py  # Win rate, expectancy, profit factor
│   ├── alert_manager.py        # Telegram bot + console alerts
│   ├── symbol_cache.py         # Symbol info, tick, and rates caching
│   ├── time_utils.py           # Broker offset, timezone conversions
│   └── visualizer.py           # Professional dashboard generation
│
├── strategies/                 # Trading strategies (ABC pattern)
│   ├── base.py                 # Abstract base class
│   ├── silver_bullet.py        # ICT Silver Bullet (M5 FVG + displacement)
│   ├── raja_banks.py           # H4 break + M5 sniper
│   ├── london_breakout.py      # London range breakout
│   └── pure_price_action.py    # H4 S/R rejection
│
├── backtesting/                # Generated reports & charts (gitignored)
│
└── scratch/                    # Developer utilities
    ├── find_dxy.py             # DXY ticker locator
    └── test_copy_rates.py      # Rate fetching stress test
```

---

## 🚀 Quick Start

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **MetaTrader 5** | Installed and logged into a trading account (demo or live) |
| **Python** | 3.10 or higher |
| **Market Watch** | `EURUSD`, `GBPJPY`, `XAUUSD`, `AUDUSD`, `USDJPY` must be visible |
| **Telegram** | A Telegram account (for bot alerts & remote control) |

### 1. Clone & Install

```bash
git clone https://github.com/glainejustin/-ict-silver-bullet-bot-.git
cd -ict-silver-bullet-bot-

# (Recommended) Create a virtual environment
python -m venv venv
source venv/Scripts/activate   # Windows Git Bash
# or: venv\Scripts\activate    # Windows CMD

pip install -r requirements.txt
```

### 2. Telegram Bot Setup

The bot uses Telegram for real-time alerts and remote control. You'll need a bot token and your personal chat ID.

<details>
<summary><b>📘 Step-by-step Telegram setup guide</b> (click to expand)</summary>

#### Step A — Create a Bot with @BotFather

1. Open Telegram and search for **[@BotFather](https://t.me/BotFather)** — this is the official Telegram bot that creates other bots.
2. Start a chat and send the command:
   ```
   /newbot
   ```
3. Follow the prompts:
   - **Bot name:** Give it a display name (e.g., `ICT Silver Bullet Bot`)
   - **Bot username:** Must end in `bot` (e.g., `ict_silver_bullet_bot`)
4. After creation, **@BotFather will send you an API token** — it looks like:
   ```
   1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
   ```
   > 🔐 **Save this token immediately.** You will paste it into your `.env` file.

#### Step B — Get Your Chat ID

1. Open Telegram and search for **[@userinfobot](https://t.me/userinfobot)**.
2. Start a chat and send any message (or just press `/start`).
3. The bot will reply with your information, including your **Chat ID** — a number like:
   ```
   123456789
   ```
   > 📝 This is your personal Chat ID. The bot will only respond to messages from this ID, preventing unauthorized access.

#### Step C — Configure Your `.env` File

```bash
# Copy the template
cp .env.example .env
```

Now edit `.env` with a text editor:

```env
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789
```

> ⚠️ **Never commit `.env` to git.** It is already listed in `.gitignore` for your safety. Anyone with your bot token can control your bot and receive your trading alerts.

</details>

### 3. Configure Risk & Symbols

Edit `config.py` to match your funded challenge parameters:

```python
# === Core Risk Settings ===
RISK_PERCENT = 1.0                    # Risk per trade (% of balance)
MAX_DAILY_LOSS_PERCENT = 4.0          # Daily loss limit
OVERALL_PROFIT_TARGET_PERCENT = 8.0   # Challenge profit target
MAX_TOTAL_LOSS_PERCENT = 8.0          # Max total drawdown
MAX_DAILY_TRADES = 6                  # Max entries per day

# === Trading Pairs ===
SYMBOLS = ["XAUUSD", "GBPJPY", "EURUSD", "AUDUSD", "USDJPY"]
```

> 💡 **Tip for challenge accounts:** Match these values to your specific challenge rules. FTMO and FundedNext have slightly different parameters — check your dashboard.

### 4. MT5 Setup

Before launching, configure MetaTrader 5:

1. **Enable One-Click Trading**  
   `Tools → Options → Trade → ✓ One Click Trading`

2. **Enable Algo Trading**  
   Click the **Algo Trading** button in the toolbar until it turns <span style="color:green">🟢 GREEN</span>

3. **Increase Chart History**  
   `Tools → Options → Charts → Max bars in chart: 100,000+`

4. **Preload Chart Data**  
   Open **M1, M5, H1, and H4** charts for each symbol to cache historical data

### 5. Launch

```bash
python main.py
```

**Windows users:** Double-click `start_bot.bat` for auto-restart on crash.

**First launch:** You should receive a "🟢 Bot Started" message on Telegram. If you don't, check your `.env` file and verify your bot token is correct.

---

## 📊 Backtesting

The bot includes a tick-level backtester that validates exits using M1 data for accuracy.

```bash
# Run a 3-month backtest across all symbols
python backtest_combined.py 3

# Or trigger from Telegram while the bot is running
/backtest 6
```

### Backtester Features

- **M1 tick-level exit validation** — uses actual candle closes, not interpolation
- **Accurate spread, commission & slippage modeling**
- **Point-in-time sentiment analysis** — no look-ahead bias
- **Multi-symbol support** — runs all configured pairs
- Results export to `backtesting/results.json` with full trade log

---

## 📱 Telegram Commands

Once running, you control the bot entirely through Telegram:

| Command | Description |
|---------|-------------|
| `/status` | Current balance, equity, P/L, trade load, open positions |
| `/backtest X` | Run X-month backtest audit (e.g., `/backtest 3`) |
| `/setprofit X` | Set daily profit target to X% (e.g., `/setprofit 2.5`) |
| `/pause` | Pause new trade entries (positions still managed) |
| `/resume` | Resume trading |
| `/stop` | Gracefully shut down the bot |
| `/logs` | View the last 15 log lines |
| `/help` | Show all available commands |

### Daily Workflow

| Time (NY) | Action |
|-----------|--------|
| **Morning** | Check `/status` — verify no overnight limit hits |
| **London Session** | Monitor Telegram for Raja Banks / Pure PA signals |
| **10-11 AM / 2-3 PM** | Silver Bullet window — highest probability setups |
| **Friday 8 PM** | Bot auto-closes all positions. Verify no orphans. |

---

## ⚙️ Configuration Reference

<details>
<summary><b>Full configuration table</b> (click to expand)</summary>

| Setting | Default | Description |
|---------|---------|-------------|
| `SYMBOLS` | `["XAUUSD", ...]` | Trading instruments (5 pairs) |
| `RISK_PERCENT` | `1.0` | Risk per trade (% of balance) |
| `MAGIC_NUMBER` | `786786` | MT5 magic number (unique per bot instance) |
| `MAX_DAILY_TRADES` | `6` | Maximum entries per trading day |
| `DAILY_PROFIT_TARGET_PERCENT` | `3.0` | Auto-pause when daily profit hits this |
| `MAX_DAILY_LOSS_PERCENT` | `4.0` | Hard daily stop-loss |
| `MAX_TOTAL_LOSS_PERCENT` | `8.0` | Permanent halt (challenge blown) |
| `MAX_TRAILING_DRAWDOWN_PERCENT` | `5.0` | Halt if equity drops from peak |
| `MIN_TRADING_DAYS` | `3` | Minimum trading days for challenge pass |
| `AUTO_EXECUTE` | `True` | Auto-execute signals (False = Telegram confirm) |
| `AUTO_MANAGE_POSITIONS` | `True` | Auto trailing stops & partial TPs |
| `SLEEP_SECONDS` | `15` | Idle wait when disconnected from MT5 |
| `MINIMUM_RR_THRESHOLD` | `1.25` | Minimum risk-reward to take a trade |
| `FRIDAY_CLOSE_HOUR` | `20` | Hour (NY) to close all Friday positions |
| `COAST_MODE_THRESHOLD` | `7.0` | Profit % at which risk scales to coast mode |
| `NEWS_NO_TRADE_MINUTES` | `30` | Buffer around high-impact news events |

</details>

---

## 🔒 Security

This project takes credential security seriously:

| Protection | Detail |
|------------|--------|
| **`.env` gitignored** | Telegram token and chat ID never committed to version control |
| **`.env.example`** | Template provided — copy and fill in your values |
| **`bot_state.json` gitignored** | Contains real MT5 account ID and balance |
| **All logs gitignored** | `*.log` excluded from commits |
| **`__pycache__/` gitignored** | All Python bytecode excluded at every level |
| **No hardcoded secrets** | Credentials loaded via `python-dotenv` only |

> 🔐 **Before every push, verify:** `git status` should show NO `.env`, `bot_state.json`, or `*.log` files staged.

---

## 🤝 Contributing

Contributions are welcome! Please:

1. **Fork** the repository
2. **Create a feature branch** (`git checkout -b feature/amazing-feature`)
3. **Test thoroughly** — run backtests and verify no regressions
4. **Commit** with clear messages (`git commit -m "Add amazing feature"`)
5. **Push** and open a Pull Request

For major changes, please open an issue first to discuss the proposed approach.

---

## 📄 License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for the full text.

---

## 🙏 Acknowledgments

- **[ICT (Inner Circle Trader)](https://www.youtube.com/@InnerCircleTrader)** — Smart Money Concepts methodology
- **FundedNext / FTMO** — Challenge structure and risk rule inspiration
- **MetaQuotes** — MetaTrader 5 and its Python API
- **python-dotenv** — Secure credential management

---

<p align="center">
  <sub>Built with ❤️ by <a href="https://github.com/glainejustin">glainejustin</a> · Trade Smart, Trade Safe</sub>
</p>
