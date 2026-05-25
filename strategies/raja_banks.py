import MetaTrader5 as mt5
from strategies.base import Strategy
from core.price_action import PriceAction
from datetime import datetime
import config

class RajaBanksStrategy(Strategy):
    def __init__(self, name, symbol):
        super().__init__(name, symbol)
        self.start_t = datetime.strptime(config.RAJA_SESSION_START, "%H:%M").time()
        self.end_t = datetime.strptime(config.RAJA_SESSION_END, "%H:%M").time()

    def generate_signal(self, data_ltf, data_htf, data_struct, current_time):
        if current_time.tzinfo is None:
            import pytz
            current_time = pytz.UTC.localize(current_time)
        london_time = current_time.astimezone(config.LONDON_TIMEZONE)
        t = london_time.time()
        if not (self.start_t <= t <= self.end_t): return {'signal': 'HOLD', 'reason': "Outside Session"}
        levels = PriceAction.find_high_quality_levels(data_struct, lookback=50, touches=3)
        res, sup = levels['resistance'], levels['support']
        if res is None or sup is None: return {'signal': 'HOLD', 'reason': "No Levels"}
        sma50 = data_struct['close'].rolling(50).mean()
        bull, bear = all(data_struct['close'].tail(3) > sma50.tail(3)), all(data_struct['close'].tail(3) < sma50.tail(3))
        last_h4 = data_struct['close'].iloc[-1]
        is_bull, is_bear = last_h4 > res and bull, last_h4 < sup and bear
        if not is_bull and not is_bear: return {'signal': 'HOLD', 'reason': "No H4 Break"}
        fvgs = PriceAction.detect_fvg(data_ltf.tail(15))
        last_m5 = data_ltf.iloc[-1]
        pip = config.SYMBOL_PIP_SIZE.get(self.symbol, 0.0001)
        if is_bull and any(f['type'] == 'BULLISH' for f in fvgs):
            sl = data_ltf['low'].tail(10).min()
            if (last_m5['close'] - sl) < (10 * pip): sl = last_m5['close'] - (10 * pip)
            return {'signal': 'BUY', 'sl': sl, 'tp': last_m5['close'] + (abs(last_m5['close'] - sl) * config.RAJA_RR), 'reason': "H4 Break + M5 Sniper", 'confidence': 1.0, 'strategy': self.name}
        elif is_bear and any(f['type'] == 'BEARISH' for f in fvgs):
            sl = data_ltf['high'].tail(10).max()
            if (sl - last_m5['close']) < (10 * pip): sl = last_m5['close'] + (10 * pip)
            return {'signal': 'SELL', 'sl': sl, 'tp': last_m5['close'] - (abs(last_m5['close'] - sl) * config.RAJA_RR), 'reason': "H4 Break + M5 Sniper", 'confidence': 1.0, 'strategy': self.name}
        return {'signal': 'HOLD', 'reason': "Searching Sniper..."}
