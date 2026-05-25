import MetaTrader5 as mt5
from datetime import datetime, timedelta
import pandas as pd

if mt5.initialize():
    # Let's test copy_rates_from
    symbol = "EURUSD"
    if mt5.symbol_select(symbol, True):
        # 10 days ago
        target_date = datetime.now() - timedelta(days=10)
        print(f"Target date: {target_date}")
        rates = mt5.copy_rates_from(symbol, mt5.TIMEFRAME_H1, target_date, 5)
        if rates is not None:
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            print("Rates found:")
            print(df[['time', 'open', 'high', 'low', 'close']])
        else:
            print("No rates found.")
    mt5.shutdown()
else:
    print("MT5 initialization failed.")
