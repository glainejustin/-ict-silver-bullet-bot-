import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
from strategies.base import Strategy
from core.price_action import PriceAction
import config
import logging
import pytz

logger = logging.getLogger("SilverBullet")

class SilverBulletStrategy(Strategy):
    def __init__(self, name, symbol):
        super().__init__(name, symbol)
        self.ny_tz = pytz.timezone('America/New_York')

    def is_silver_bullet_hour(self, current_time):
        """
        Silver Bullet Windows (NY Time):
        - AM: 10:00 - 11:00 AM
        - PM: 02:00 - 03:00 PM
        - London: 03:00 - 04:00 AM
        """
        from core.time_utils import broker_to_ny
        ny_now = broker_to_ny(current_time)
        hour = ny_now.hour
        
        return hour in [3, 10, 14]

    def generate_signal(self, data_ltf, data_htf, data_struct, current_time):
        if not self.is_silver_bullet_hour(current_time):
            return {'signal': 'HOLD', 'reason': "Outside Silver Bullet Window"}

        if data_ltf is None or len(data_ltf) < 20:
            return {'signal': 'HOLD', 'reason': "Insufficient LTF Data"}

        # HTF Structural Bias (Institutional Order Flow)
        if data_htf is None or len(data_htf) < 40:
            return {'signal': 'HOLD', 'reason': "Insufficient HTF Data (need 40 bars)"}
            
        h1_bias = PriceAction.get_structural_bias(data_htf, window=10)

        # 1. Detect Liquidity Sweep (Look for spikes above/below recent range)
        range_data = data_ltf.iloc[-20:-1]
        session_high = range_data['high'].max()
        session_low = range_data['low'].min()
        
        last_candle = data_ltf.iloc[-1]
        
        sweep_bullish = last_candle['low'] < session_low and last_candle['close'] > session_low
        sweep_bearish = last_candle['high'] > session_high and last_candle['close'] < session_high

        # 2. Detect Market Structure Shift (MSS)
        mss = PriceAction.detect_mss(data_ltf, window=5)
        
        # 3. Find FVGs
        fvgs = PriceAction.detect_fvg(data_ltf.tail(10))
        
        # --- Entry Logic ---
        atr = PriceAction.calculate_atr(data_ltf, period=14)
        import numpy as np
        if np.isnan(atr):
            atr = last_candle['close'] * 0.001
            
        # Long: H1 Bullish + (Sweep or MSS) + Bullish FVG + Displacement
        if h1_bias == 'BULLISH' and (sweep_bullish or mss == 'BULLISH'):
            for fvg in fvgs:
                if fvg['type'] == 'BULLISH':
                    # Validate displacement on the FVG candle
                    if PriceAction.detect_displacement(data_ltf, fvg['index'] + 1):
                        sl = session_low - (atr * 1.0)
                        tp = last_candle['close'] + (abs(last_candle['close'] - sl) * 2.5) # High RR for institutional moves
                        
                        return {
                            'signal': 'BUY', 'sl': sl, 'tp': tp,
                            'reason': f"Silver Bullet: H1 {h1_bias} + Displacement FVG",
                            'confidence': 1.0, 'strategy': self.name
                        }

        # Short: H1 Bearish + (Sweep or MSS) + Bearish FVG + Displacement
        if h1_bias == 'BEARISH' and (sweep_bearish or mss == 'BEARISH'):
            for fvg in fvgs:
                if fvg['type'] == 'BEARISH':
                    if PriceAction.detect_displacement(data_ltf, fvg['index'] + 1):
                        sl = session_high + (atr * 1.0)
                        tp = last_candle['close'] - (abs(last_candle['close'] - sl) * 2.5)
                        
                        return {
                            'signal': 'SELL', 'sl': sl, 'tp': tp,
                            'reason': f"Silver Bullet: H1 {h1_bias} + Displacement FVG",
                            'confidence': 1.0, 'strategy': self.name
                        }

        return {'signal': 'HOLD', 'reason': "Waiting for Sweep & FVG Setup"}
