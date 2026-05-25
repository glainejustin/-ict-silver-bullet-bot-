import MetaTrader5 as mt5
from strategies.base import Strategy
from core.price_action import PriceAction
from datetime import datetime
import config
import pytz

class PurePriceActionStrategy(Strategy):
    def __init__(self, name, symbol):
        super().__init__(name, symbol)

    def generate_signal(self, data_ltf, data_htf, data_struct, current_time):
        if current_time.tzinfo is None: current_time = pytz.UTC.localize(current_time)
        t = current_time.astimezone(config.LONDON_TIMEZONE).time()
        start = datetime.strptime(config.RAJA_SESSION_START, "%H:%M").time()
        end = datetime.strptime(config.RAJA_SESSION_END, "%H:%M").time()
        if not (start <= t <= end): return {'signal': 'HOLD', 'reason': "Outside Session"}
        atr = PriceAction.calculate_atr(data_struct, period=14)
        import numpy as np
        if np.isnan(atr):
            atr = data_struct['close'].iloc[-1] * 0.001  # fallback: 0.1% of price
        levels = PriceAction.find_high_quality_levels(data_struct, lookback=100, touches=2, threshold_price=atr * 0.1)
        res, sup = levels['resistance'], levels['support']
        if res is None or sup is None: return {'signal': 'HOLD', 'reason': "No Levels"}
        last_m5 = data_ltf.iloc[-1]; pip = config.SYMBOL_PIP_SIZE.get(self.symbol, 0.0001)
        rej = PriceAction.check_wick_rejection(last_m5, threshold=0.5)
        
        if abs(last_m5['low'] - sup) <= (atr * 1.0) and rej['lower']:
            entry = sup
            sl = last_m5['low'] - (atr * 1.0)
            risk = abs(entry - sl)
            tp = entry + (risk * config.PURE_PA_RR)
            
            if PriceAction.check_clean_traffic(data_ltf, tp, 'BUY'):
                return {'signal': 'BUY_LIMIT', 'entry_price': entry, 'sl': sl, 'tp': tp, 'reason': "H4 Support Rejection", 'confidence': 1.0, 'strategy': self.name}
                
        elif abs(last_m5['high'] - res) <= (atr * 1.0) and rej['upper']:
            entry = res
            sl = last_m5['high'] + (atr * 1.0)
            risk = abs(entry - sl)
            tp = entry - (risk * config.PURE_PA_RR)
            
            if PriceAction.check_clean_traffic(data_ltf, tp, 'SELL'):
                return {'signal': 'SELL_LIMIT', 'entry_price': entry, 'sl': sl, 'tp': tp, 'reason': "H4 Resistance Rejection", 'confidence': 1.0, 'strategy': self.name}
        return {'signal': 'HOLD', 'reason': "Scanning S/R..."}
