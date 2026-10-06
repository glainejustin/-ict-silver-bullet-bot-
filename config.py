import MetaTrader5 as mt5
import pytz
import os
from dotenv import load_dotenv

# Load credentials from .env file (never commit real tokens!)
load_dotenv()

# --- Symbols & Magic Number ---
# Mixed symbol naming (Gold is standard, Forex has "c" suffix)
#
# WHY ONLY XAUUSD BY DEFAULT
# --------------------------
# Every symbol in the old list ran the same intraday ICT families (sweep-fade,
# breakout-continuation, trend-pullback). On 1.16M M1 bars of real XAUUSD data
# (2023-2026) each of those families tested NEGATIVE before costs and around
# -0.27R after costs; the exact numbers are in research/out/ and XAUUSD_EDGE_REPORT.md.
# Only the gold trend system (GoldTrendStrategy) tested positive out-of-sample,
# and it is only validated on XAUUSD. Trading the other pairs with unvalidated
# strategies is how the account was being drained, so they are disabled until
# each one is individually researched the same way.
SYMBOLS = ["XAUUSD"]
MAGIC_NUMBER = 786786

CORRELATION_GROUPS = [
    ["XAUUSD", "GBPJPY"],      # Correlated via general risk/USD strength
    ["EURUSD", "AUDUSD"],      # Positively correlated USD-base pairs
    ["USDJPY", "XAUUSD"]       # Counter-correlated safe havens
]

# --- Strategy Mapping ---
# GoldTrendStrategy is the only strategy in this repo with a positive
# out-of-sample expectancy on real XAUUSD data (see XAUUSD_EDGE_REPORT.md).
#
# The legacy intraday strategies are kept in the repo for reference/backtesting
# but are NOT enabled by default: each one tested between -0.15R and -0.40R per
# trade over 27k-49k trades, i.e. they lose faster the more often they trade.
# To re-enable one, add its name back to the list below AND re-run
# research/family_search.py to confirm it has an edge on your own data first.
LEGACY_STRATEGIES_ENABLED = False

SYMBOL_STRATEGY_MAP = {
    "XAUUSD": ["GoldTrendStrategy"],
}
if LEGACY_STRATEGIES_ENABLED:
    SYMBOL_STRATEGY_MAP.update({
        "XAUUSD": ["GoldTrendStrategy", "RajaBanksStrategy", "PurePriceActionStrategy",
                   "SilverBulletStrategy"],
        "GBPJPY": ["RajaBanksStrategy", "PurePriceActionStrategy", "SilverBulletStrategy"],
        "EURUSD": ["PurePriceActionStrategy", "SilverBulletStrategy"],
        "AUDUSD": ["PurePriceActionStrategy", "SilverBulletStrategy"],
        "USDJPY": ["PurePriceActionStrategy", "SilverBulletStrategy"],
    })

SYMBOL_PIP_SIZE = {
    "XAUUSD": 0.1,    # Gold pips
    "GBPJPY": 0.01,
    "EURUSD": 0.0001,
    "AUDUSD": 0.0001,
    "USDJPY": 0.01
}

# --- FUNDED CHALLENGE SETTINGS ($5k Account) ---
# Validated default: 0.75% risk per trade matches research/validate_live.py, which
# produced 9.0% CAGR / -5.4% max drawdown over 2023-2026. The 21-year walk-forward
# (research/long_history.py) at 0.5% risk produced 1.4% CAGR / -3.8% worst drawdown
# -- treat THAT as the honest expectation and this period as a good market.
RISK_PERCENT = 0.75             # Risk per trade (% of balance)
MAX_TOTAL_OPEN_RISK_PERCENT = 2.0 # Max risk across all open trades (one position at a time)
DYNAMIC_RISK_SCALING = True     # Scale risk down as we approach profit target
MAX_DAILY_TRADES = 2            # Safety cap: the validated system averages ~1.3 trades/MONTH
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
# Daily profit target. 0 = DISABLED, which is correct for a trend system: closing
# a position because the day went well chops exactly the trends that pay for the
# losers. The daily LOSS limit below is the one that protects you. Set this back
# to 1.5-3.0 only if you are running a high-frequency mean-reversion system.
DAILY_GOAL_PERCENT = 0.0
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


# ============================================================================
#  GOLD TREND STRATEGY  (strategies/gold_trend.py)
# ----------------------------------------------------------------------------
#  Donchian breakout on H4 with an ATR trailing stop, long-only.
#  Evidence (see XAUUSD_EDGE_REPORT.md and research/out/):
#    * 21-year walk-forward, params picked on prior 4y only:
#      +27.1% total, 12/17 positive years, worst year -4.1%, worst DD -3.8% @0.5% risk
#    * live-code replay 2023-2026 @0.75% risk: +33.9%, CAGR 9.0%, max DD -5.4%,
#      52 trades, profit factor 2.97
#    * the same rules trading long AND short roughly halved the return
#  This is a low-frequency system: ~1.3 trades a month. Do not expect it to pass
#  an 8%-in-30-days challenge - see research/challenge_sim.py for why that is a
#  lottery (3-15% pass odds even with a genuine edge).
# ============================================================================
GOLD_TREND_ENABLED = True
GOLD_TREND_TIMEFRAME = "H4"      # "H4" (validated) or "H1"
GOLD_TREND_LOOKBACK = 55         # Donchian window in bars (walk-forward chose 55)
GOLD_TREND_ATR_PERIOD = 14       # ATR period, matches the research harness
GOLD_TREND_STOP_ATR = 2.0        # Initial stop = 2.0 x ATR(H4) from entry
GOLD_TREND_TRAIL_ATR = 4.0       # Chandelier trail = 4.0 x ATR(H4) from the extreme
GOLD_TREND_REGIME_FILTER = True  # Only buy above the long moving average
GOLD_TREND_REGIME_SMA = 200      # MA length (clamped to available history)
GOLD_TREND_ALLOW_SHORTS = False  # Shorts roughly halved the 21-year return
GOLD_TREND_REQUIRE_NEW_BAR = True # One signal per closed bar, no re-firing

# --- Cost awareness (why most retail gold bots lose) ---
# A 25-point gold spread costs $0.25 round trip. If your stop is 1R = $5 then
# friction alone eats 5% of every trade before you are right about anything.
# These two guards refuse trades whose cost-to-risk ratio is hopeless.
MIN_STOP_DISTANCE_POINTS = {
    "XAUUSD": 400,   # $4.00 - refuses any setup with a tighter stop than this
    "GBPJPY": 40,
    "EURUSD": 25,
    "AUDUSD": 25,
    "USDJPY": 30,
}
MAX_COST_RATIO_OF_R = 0.12       # Block any trade where (spread+commission) > 12% of 1R

# --- Per-strategy position management ---
# The validated gold system is managed with a slow H4 chandelier trail and takes
# NO partial profits and NO breakeven stop - both of those were tested and they cut
# the right tail that pays for the losers. Legacy intraday strategies keep the old
# behaviour. Keys are strategy name prefixes.
STRATEGY_MANAGEMENT = {
    "GoldTrend": {
        "trail_atr_mult": GOLD_TREND_TRAIL_ATR,
        "trail_atr_timeframe": GOLD_TREND_TIMEFRAME,
        "partial_tp_rr": 0.0,     # disabled for this strategy
        "breakeven_rr": 0.0,      # disabled for this strategy
        "trail_after_r": 0.0,     # start trailing immediately
    },
}
DEFAULT_MANAGEMENT = {
    "trail_atr_mult": 2.5,
    "trail_atr_timeframe": "M5",
    "partial_tp_rr": PARTIAL_TP_RR,
    "breakeven_rr": BREAKEVEN_RR,
    "trail_after_r": 1.0,
}
