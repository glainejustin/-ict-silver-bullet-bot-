import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime

class DataFetcher:
    """
    Handles fetching historical price data from MetaTrader 5.
    """
    def get_historical_data(self, symbol: str, timeframe: int, count: int):
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            return None
            
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        return df
