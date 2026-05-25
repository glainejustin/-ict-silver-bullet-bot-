import MetaTrader5 as mt5
from datetime import datetime, timedelta
import pytz
import logging

logger = logging.getLogger("TimeUtils")

_broker_offset = None

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
    _broker_offset = round((broker_time - utc_now).total_seconds() / 3600)
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
