import MetaTrader5 as mt5
import numpy as np
from strategies.base import Strategy
from datetime import time
import config
import logging

logger = logging.getLogger("LondonBreakout")

class LondonBreakoutStrategy(Strategy):
    def __init__(self, name, symbol):
        super().__init__(name, symbol)
        self.session_start = time(8, 0)
        self.session_end = time(8, 30)
        self.session_high = 0
        self.session_low = 0
        self.breakout_occurred = False

    def is_session_active(self, current_time):
        return self.session_start <= current_time.time() <= self.session_end

    def generate_signal(self, data_ltf, data_htf, data_struct, current_time):
        if len(data_ltf) < 15: return {'signal': 'HOLD', 'reason': "Insufficient Data"}
        if current_time.tzinfo is None:
            import pytz
            current_time = pytz.UTC.localize(current_time)
        london_time = current_time.astimezone(config.LONDON_TIMEZONE)
        if not self.is_session_active(london_time):
            self.session_high = 0; self.session_low = 0; self.breakout_occurred = False
            return {'signal': 'HOLD', 'reason': "Outside Session"}
        if self.session_high == 0:
            self.session_high = data_ltf['high'].tail(12).max()
            self.session_low = data_ltf['low'].tail(12).min()
            return {'signal': 'HOLD', 'reason': "Setting Range"}
        if self.breakout_occurred: return {'signal': 'HOLD', 'reason': "Trade Taken"}
        last_candle = data_ltf.iloc[-1]
        
        # If price already broke it drastically, mark as occurred
        if last_candle['close'] > self.session_high + (config.SYMBOL_PIP_SIZE.get(self.symbol, 0.0001) * 10) or \
           last_candle['close'] < self.session_low - (config.SYMBOL_PIP_SIZE.get(self.symbol, 0.0001) * 10):
            self.breakout_occurred = True
            return {'signal': 'HOLD', 'reason': "Breakout Already Occurred"}
            
        tr = np.maximum(data_ltf['high'] - data_ltf['low'], np.maximum(abs(data_ltf['high'] - data_ltf['close'].shift()), abs(data_ltf['low'] - data_ltf['close'].shift())))
        sl_dist = tr.rolling(14).mean().iloc[-1] * 1.5
        
        if np.isnan(sl_dist) or sl_dist <= 0:
            return {'signal': 'HOLD', 'reason': "Invalid Stop Distance (NaN)"}
            
        pip_size = config.SYMBOL_PIP_SIZE.get(self.symbol, 0.0001)
        buffer = pip_size * 2.0 # 2 pip buffer outside the range
        
        buy_entry = self.session_high + buffer
        sell_entry = self.session_low - buffer
        
        # We can issue a pending order based on proximity
        if abs(last_candle['close'] - self.session_high) < abs(last_candle['close'] - self.session_low):
            # Closer to high, prep BUY_STOP
            return {'signal': 'BUY_STOP', 'entry_price': buy_entry, 'sl': buy_entry - sl_dist, 'tp': buy_entry + (sl_dist * config.LONDON_MIN_RR), 'reason': "London Breakout BUY_STOP", 'confidence': 1.0, 'strategy': self.name}
        else:
            # Closer to low, prep SELL_STOP
            return {'signal': 'SELL_STOP', 'entry_price': sell_entry, 'sl': sell_entry + sl_dist, 'tp': sell_entry - (sl_dist * config.LONDON_MIN_RR), 'reason': "London Breakout SELL_STOP", 'confidence': 1.0, 'strategy': self.name}
