import MetaTrader5 as mt5
import logging
import time

logger = logging.getLogger("SymbolInfoCache")

class SymbolInfoCache:
    """
    Caches mt5.symbol_info and mt5.symbol_info_tick results to reduce API overhead.
    Intended to be initialized once per bot cycle.
    """
    def __init__(self):
        self._info_cache = {}
        self._tick_cache = {}
        self._rates_cache = {}
        self._tick_timestamps = {}  # Track tick arrival times for TPS calculation

    def get_info(self, symbol):
        if symbol not in self._info_cache:
            info = mt5.symbol_info(symbol)
            if info:
                self._info_cache[symbol] = info
            else:
                return None
        return self._info_cache[symbol]

    def get_tick(self, symbol):
        old_tick = self._tick_cache.get(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            self._tick_cache[symbol] = tick
            now = time.time()
            if symbol not in self._tick_timestamps:
                self._tick_timestamps[symbol] = []
            self._tick_timestamps[symbol].append(now)
            # Keep last 100 timestamps
            if len(self._tick_timestamps[symbol]) > 100:
                self._tick_timestamps[symbol] = self._tick_timestamps[symbol][-100:]
            return tick
        return old_tick  # Fall back to cached if fetch fails

    def get_tps(self, symbol) -> float:
        """
        Returns ticks-per-second for the given symbol.
        Used by risk_manager.py for Execution Tax scaling.
        """
        timestamps = self._tick_timestamps.get(symbol, [])
        if len(timestamps) < 2:
            return 0.0
        # TPS = (num_ticks - 1) / (latest - earliest) over the window
        window = timestamps[-1] - timestamps[0]
        if window <= 0:
            return 0.0
        return (len(timestamps) - 1) / window

    def get_data(self, symbol, timeframe, count=100):
        """
        Returns historical rates as a pandas DataFrame.
        Used by main.py for SFP rejection guard.
        (Separate cache namespace from get_rates to avoid collisions.)
        """
        import pandas as pd
        cache_key = f"data_{symbol}_{timeframe}_{count}"
        if cache_key not in self._rates_cache:
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
            if rates is not None and len(rates) > 0:
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s')
                df.set_index('time', inplace=True)
                self._rates_cache[cache_key] = df
            else:
                return None
        return self._rates_cache[cache_key]

    def get_rates(self, symbol, timeframe, count):
        """
        Caches and returns historical rates as a pandas DataFrame.
        """
        import pandas as pd
        cache_key = f"{symbol}_{timeframe}_{count}"
        if cache_key not in self._rates_cache:
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
            if rates is not None and len(rates) > 0:
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s')
                df.set_index('time', inplace=True)
                self._rates_cache[cache_key] = df
            else:
                return None
        return self._rates_cache[cache_key]
