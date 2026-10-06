import MetaTrader5 as mt5
from datetime import datetime, timedelta
import pytz
import logging

logger = logging.getLogger("TimeUtils")

_broker_offset = None

# MetaTrader servers for the brokers this bot targets (FundedNext/FundingPips/
# IC Markets etc.) run on EET/EEST: GMT+2 in winter, GMT+3 in summer, matching
# Europe/Athens DST rules. Used as a sanity anchor for the tick-derived offset.
BROKER_TZ = pytz.timezone("Europe/Athens")
NY_TZ = pytz.timezone("America/New_York")
LONDON_TZ = pytz.timezone("Europe/London")


def session_time(dt: datetime, tz=None) -> datetime:
    """
    Convert a timestamp to the session timezone a strategy reasons about.

    THIS FUNCTION EXISTS TO FIX A SILENT, EXPENSIVE BUG.
    There are two completely different clocks flowing into the strategies:

      * LIVE: main.py passes get_mt5_time_utc() -> a TRUE UTC, tz-aware datetime.
      * BACKTEST: backtest_combined.py passes MT5 bar timestamps -> BROKER time
        (GMT+2/+3), tz-naive.

    The old strategies did `pytz.UTC.localize(dt)` on anything naive, i.e. they
    treated broker time as UTC, which is a 2-3 hour error. Every session window
    (Silver Bullet 10:00-11:00 NY, London 08:00, Raja Banks 08:00-16:30) then
    fired at the wrong time of day, and backtests "confirmed" setups that live
    trading would never have taken. That mismatch is a big part of why live
    results did not match the reports.

    Accepts either clock and always returns the requested timezone.
    """
    tz = tz or NY_TZ
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(tz)
    # naive == broker/server clock (MT5 bar or tick time)
    return BROKER_TZ.localize(dt).astimezone(tz)


def broker_naive_to_utc(dt: datetime) -> datetime:
    """Broker-local naive datetime -> true UTC (tz-aware)."""
    if dt.tzinfo is None:
        return BROKER_TZ.localize(dt).astimezone(pytz.UTC)
    return dt.astimezone(pytz.UTC)

def get_broker_offset():
    """
    Detects the broker's GMT offset by comparing the latest tick time with UTC.
    """
    global _broker_offset
    if _broker_offset is not None:
        return _broker_offset

    if not mt5.initialize():
        return 0

    tick = mt5.symbol_info_tick("EURUSD")
    if not tick:
        # Fallback to current local time vs UTC if MT5 is closed/no ticks
        logger.warning("Could not get EURUSD tick for offset detection. Using 0.")
        return 0

    # MT5 'time' is seconds since 1970-01-01 in BROKER time
    broker_time = datetime.fromtimestamp(tick.time, pytz.UTC).replace(tzinfo=None)
    utc_now = datetime.now(pytz.UTC).replace(tzinfo=None)
    
    # Calculate offset in hours
    guess = round((broker_time - utc_now).total_seconds() / 3600)

    # Sanity anchor: brokers run EET/EEST, so the true offset is +2 or +3.
    # A stale ticket (weekend, terminal just opened, feed lag) can make the tick
    # difference wildly wrong; a wrong offset silently shifts the daily reset and
    # the Friday close-out, which are exactly the rules that blow funded accounts.
    anchor = BROKER_TZ.localize(utc_now.replace(tzinfo=None)).utcoffset().total_seconds() / 3600
    if abs(guess - anchor) > 3:
        logger.warning(f"Tick-derived broker offset {guess:+}h looks wrong "
                       f"(expected ~{anchor:+.0f}h). Using the EET anchor.")
        guess = int(anchor)
    _broker_offset = int(guess)
    logger.info(f"Detected Broker GMT Offset: {_broker_offset:+} hours")
    return _broker_offset

def broker_to_ny(broker_dt):
    """
    Converts a broker datetime object to New York time.
    """
    offset = get_broker_offset()
    
    # 1. Remove any existing tzinfo (treat as raw broker time)
    raw_dt = broker_dt.replace(tzinfo=None)
    
    # 2. Adjust to UTC
    utc_dt = raw_dt - timedelta(hours=offset)
    utc_dt = pytz.UTC.localize(utc_dt)
    
    # 3. Convert to NY
    ny_tz = pytz.timezone('America/New_York')
    return utc_dt.astimezone(ny_tz)

def get_mt5_time_utc():
    import config
    if not mt5.initialize(): return datetime.now(pytz.UTC)
    tick = None
    for sym in config.SYMBOLS:
        tick = mt5.symbol_info_tick(sym)
        if tick: break
        
    if not tick: return datetime.now(pytz.UTC)
    
    broker_time = datetime.fromtimestamp(tick.time, pytz.UTC).replace(tzinfo=None)
    offset = get_broker_offset()
    utc_dt = broker_time - timedelta(hours=offset)
    return pytz.UTC.localize(utc_dt)
