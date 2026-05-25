import MetaTrader5 as mt5
import pytz
import os
from dotenv import load_dotenv

# Load credentials from .env file (never commit real tokens!)
load_dotenv()

# --- Symbols & Magic Number ---
# Mixed symbol naming (Gold is standard, Forex has "c" suffix)
SYMBOLS = ["XAUUSD", "GBPJPY", "EURUSD", "AUDUSD", "USDJPY"]
MAGIC_NUMBER = 786786

CORRELATION_GROUPS = [
    ["XAUUSD", "GBPJPY"],      # Correlated via general risk/USD strength
    ["EURUSD", "AUDUSD"],      # Positively correlated USD-base pairs
    ["USDJPY", "XAUUSD"]       # Counter-correlated safe havens
]

# --- Strategy Mapping ---
SYMBOL_STRATEGY_MAP = {
    "XAUUSD": ["RajaBanksStrategy", "PurePriceActionStrategy", "SilverBulletStrategy"],
    "GBPJPY": ["RajaBanksStrategy", "PurePriceActionStrategy", "SilverBulletStrategy"],
    "EURUSD": ["PurePriceActionStrategy", "SilverBulletStrategy"],
    "AUDUSD": ["PurePriceActionStrategy", "SilverBulletStrategy"],
    "USDJPY": ["PurePriceActionStrategy", "SilverBulletStrategy"]
}

SYMBOL_PIP_SIZE = {
    "XAUUSD": 0.1,    # Gold pips
    "GBPJPY": 0.01,
    "EURUSD": 0.0001,
    "AUDUSD": 0.0001,
    "USDJPY": 0.01
}

# --- FUNDED CHALLENGE SETTINGS ($5k Account) ---
RISK_PERCENT = 1.0              # Risk 1.0% per trade (Required for 30-day time limits)
MAX_TOTAL_OPEN_RISK_PERCENT = 3.0 # Max risk across all open trades
DYNAMIC_RISK_SCALING = True     # Scale risk down as we approach profit target
MAX_DAILY_TRADES = 6            # Allow more attempts per day
DAILY_PROFIT_TARGET_PERCENT = 3.0  # Lock in 3% daily gains to compound quickly
OVERALL_PROFIT_TARGET_PERCENT = 8.0 # $400 overall target
MAX_DAILY_LOSS_PERCENT = 4.0        # $200 daily limit (extra safety buffer)
MAX_TOTAL_LOSS_PERCENT = 8.0        # $400 total limit
MAX_TRAILING_DRAWDOWN_PERCENT = 5.0 # Stop if equity drops 5% from peak
WEEKLY_LOSS_LIMIT_PERCENT = 3.0     # Cool down for 24h if 3% lost in a week
MIN_TRADING_DAYS = 3
MINIMUM_RR_THRESHOLD = 1.25     # Lowered from 2.0. Accepts high-win-rate 1:1.25 setups to massively increase trade frequency.
SLEEP_SECONDS = 15
DATA_STALE_THRESHOLD = 30           # Halt if price is >30s old

# Spread Guard (Points/Pips) - Block if spread > X
MAX_SPREAD_PIPS = {
    "XAUUSD": 45,  # 45 points ($0.45)
    "GBPJPY": 4,
    "EURUSD": 2,
    "AUDUSD": 2.5,
    "USDJPY": 3
}

# --- Advanced Risk ---
# Note: MAX_TOTAL_OPEN_RISK_PERCENT (above) is the primary cap across all open trades.
SMART_RISK_SCALING = True       # Reduce risk as target nears
SPREAD_MA_PERIOD = 20           # Samples for dynamic spread MA
SPREAD_MA_MULTIPLIER = 1.5      # Block if spread > 1.5x average

# Dynamic Spread Guard
DYNAMIC_SPREAD_THRESHOLD = 1.5   # Don't trade if current spread > 1.5x average

# Volatility Adjusted Sizing
ATR_VOLATILITY_ADJUSTMENT = True # Reduce risk during high volatility
VOLATILITY_EMA_PERIOD = 20       # Period to calculate average volatility
VOLATILITY_THRESHOLD = 1.5       # Reduce risk if Current Vol > 1.5x Average

# Safety Settings
DAILY_GOAL_PERCENT = 1.5        # $75 goal (lock profit for day)
FRIDAY_CLOSE_HOUR = 20          # Close all at 8 PM Friday
COAST_MODE_THRESHOLD = 7.0      # At 7% profit, reduce risk to "coast" to 8% target
COAST_MODE_RISK = 0.1           # 0.1% risk in Coast Mode
RISK_DEESCALATION_START = 4.0   # Start reducing risk after 4% profit

# --- London Breakout Parameters ---
LONDON_MIN_RR = 2.0            
LONDON_ENTRY_BUFFER = 5
LONDON_MIN_RANGE = 40
LONDON_MAX_RANGE = 2000

# --- Raja Banks Parameters ---
RAJA_RR = 2.0                  
RAJA_WINDOW = 20
RAJA_SESSION_START = "08:00"    # London Start
RAJA_SESSION_END = "16:30"      # NY Close

# --- Silver Bullet Parameters ---
SILVER_BULLET_RR = 2.0
SILVER_BULLET_WINDOW = 20
SILVER_BULLET_ENTRY_TYPE = "LIMIT" # Use LIMIT for precise entries in FVG

# --- News & Session Buffer ---
NEWS_NO_TRADE_MINUTES = 30      # Skip trades 30m before/after major news
SESSION_ONLY_TRADING = True     # Only trade during defined session windows

# --- Volume Filter ---
VOL_MA_PERIOD = 20              # Period for volume moving average in base strategy

# --- SIGNAL ASSISTANT MODE ---
AUTO_EXECUTE = True             # Set to False to require manual confirmation in Telegram
# Telegram Bot (create via @BotFather, get chat_id via @userinfobot)
# NEVER hardcode real tokens here — use .env file (see .env.example)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Alert Behaviour
ALERT_TIMEOUT_SECONDS = 60      # Seconds to wait for user confirmation before skipping
ALERT_SOUND_FREQ = 1000         # Beep frequency (Hz)
ALERT_SOUND_DURATION = 500      # Beep duration (ms)

# Position Management (risk management assistance — Funded Elite compliant)
AUTO_MANAGE_POSITIONS = True    # Auto trailing stop / breakeven / partial TP
PARTIAL_TP_RR = 1.0             # Take partial profit at 1:1 RR
BREAKEVEN_RR = 1.0              # Move SL to breakeven at 1:1 RR
PARTIAL_TP_PCT = 0.5            # Close 50% of position

# --- Pure Price Action Parameters ---
PURE_PA_RR = 2.0

# --- Timezone ---
NY_TIMEZONE = pytz.timezone('America/New_York')
LONDON_TIMEZONE = pytz.timezone('Europe/London')
