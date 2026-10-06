import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta

class DataFetcher:
    """
    Handles fetching historical price data from MetaTrader 5.

    IMPORTANT: MT5's copy_rates_from_pos(..., start=0) returns the bar that is
    STILL FORMING as the last row. Every strategy in this repo reads .iloc[-1],
    so without the fix below they make decisions on a candle that can still
    change - a live-only look-ahead bias that no backtest ever reproduces, and a
    reliable source of "works in backtest, loses live" behaviour.

    `closed_only=True` (the default) drops the forming bar. Strategies that
    explicitly want to see the live bar can ask for it.
    """

    # bar duration in seconds for the timeframes this bot uses
    _TF_SECONDS = {
        mt5.TIMEFRAME_M1: 60,
        mt5.TIMEFRAME_M5: 300,
        mt5.TIMEFRAME_M15: 900,
        mt5.TIMEFRAME_M30: 1800,
        mt5.TIMEFRAME_H1: 3600,
        mt5.TIMEFRAME_H4: 14400,
        mt5.TIMEFRAME_D1: 86400,
    }

    def __init__(self, closed_only: bool = True):
        self.closed_only = closed_only

    def get_historical_data(self, symbol: str, timeframe: int, count: int) -> pd.DataFrame:
        # ask for one extra bar so we can still return `count` closed bars
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count + (1 if self.closed_only else 0))
        if rates is None or len(rates) == 0:
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)

        if self.closed_only:
            df = self._drop_forming_bar(df, timeframe)
        return df

    def _drop_forming_bar(self, df: pd.DataFrame, timeframe: int) -> pd.DataFrame:
        """Remove the last row unless its bar period has fully elapsed."""
        if df.empty:
            return df
        bar_seconds = self._TF_SECONDS.get(timeframe, 300)
        tick = mt5.symbol_info_tick("XAUUSD")
        try:
            # broker clock = server time of the newest tick we can see
            broker_now = datetime.fromtimestamp(tick.time) if tick else datetime.now()
        except Exception:
            broker_now = datetime.now()

        last_open = df.index[-1]
        if isinstance(last_open, pd.Timestamp):
            last_open = last_open.to_pydatetime()
        if (broker_now - last_open).total_seconds() < bar_seconds:
            return df.iloc[:-1]
        return df
