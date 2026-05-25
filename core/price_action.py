import pandas as pd
import numpy as np

class PriceAction:
    @staticmethod
    def detect_fvg(df: pd.DataFrame):
        """
        Detects Fair Value Gaps (FVG) in the dataframe.
        Returns a list of dictionaries with FVG details.
        """
        fvgs = []
        if len(df) < 3:
            return fvgs

        for i in range(2, len(df)):
            # Bullish FVG
            if df['low'].iloc[i] > df['high'].iloc[i-2]:
                fvgs.append({
                    'type': 'BULLISH',
                    'top': df['low'].iloc[i],
                    'bottom': df['high'].iloc[i-2],
                    'index': i-1
                })
            # Bearish FVG
            elif df['high'].iloc[i] < df['low'].iloc[i-2]:
                fvgs.append({
                    'type': 'BEARISH',
                    'top': df['low'].iloc[i-2],
                    'bottom': df['high'].iloc[i],
                    'index': i-1
                })
        return fvgs

    @staticmethod
    def detect_mss(df: pd.DataFrame, window=5):
        """
        Detects a genuine ICT Market Structure Shift (MSS).

        FIX 2: A true MSS requires 3 phases:
          Phase 1 - A prior swing high/low exists
          Phase 2 - Price BREAKS that swing level (closes beyond it)
          Phase 3 - Price PULLS BACK toward the broken level (does not just keep running)
          Result  - The pullback-and-hold confirms institutional re-entry, not just a spike

        The old code returned 'BULLISH' the moment price closed above ANY prior high,
        which fires constantly in chop and has no predictive value.
        """
        if len(df) < window * 3:
            return None

        # --- Phase 1: Identify the prior swing high and swing low ---
        # Look back 'window*2' bars before the last 'window' bars
        lookback = df.iloc[-(window * 3):-(window)]
        recent   = df.iloc[-(window):]

        prior_swing_high = lookback['high'].max()
        prior_swing_low  = lookback['low'].min()

        # --- Phase 2: Did price BREAK the swing? ---
        # A break requires a full candle CLOSE beyond the swing, not just a wick
        broke_high = any(recent['close'] > prior_swing_high)
        broke_low  = any(recent['close'] < prior_swing_low)

        if not broke_high and not broke_low:
            return None  # No structural break occurred

        # --- Phase 3: Pullback confirmation ---
        # After the break candle, did price pull back at least 20% of the break distance?
        # This filters out pure momentum breakouts (no edge) vs institutional displacement + retest
        last_close = recent['close'].iloc[-1]

        if broke_high:
            break_distance = recent['close'].max() - prior_swing_high
            pullback_threshold = recent['close'].max() - (break_distance * 0.20)
            # Price must have come back down toward the broken level (pullback)
            pulled_back = last_close <= pullback_threshold
            if pulled_back and last_close > prior_swing_high:  # Held above broken level = bullish MSS
                return 'BULLISH'

        if broke_low:
            break_distance = prior_swing_low - recent['close'].min()
            pullback_threshold = recent['close'].min() + (break_distance * 0.20)
            pulled_back = last_close >= pullback_threshold
            if pulled_back and last_close < prior_swing_low:  # Held below broken level = bearish MSS
                return 'BEARISH'

        return None  # Break occurred but no pullback confirmation yet

    @staticmethod
    def check_wick_rejection(candle, threshold=0.4):
        """
        Checks if a candle has a long rejection wick relative to its range.
        threshold: 0.4 means wick is 40% or more of total candle size.
        """
        total_range = candle['high'] - candle['low']
        if total_range == 0:
            return {'upper': False, 'lower': False}
        
        body_top = max(candle['open'], candle['close'])
        body_bottom = min(candle['open'], candle['close'])
        
        upper_wick = (candle['high'] - body_top) / total_range
        lower_wick = (body_bottom - candle['low']) / total_range
        
        return {'upper': upper_wick > threshold, 'lower': lower_wick > threshold}

    @staticmethod
    def check_clean_traffic(df: pd.DataFrame, target_price, direction, pips_range=20):
        """
        Checks if there's 'clean traffic' (no major obstacles) towards the target.
        """
        recent_data = df.tail(50) # Look back 50 candles
        
        if direction == 'BUY':
            # Check if there are many candles in the way up to target_price
            obstacles = recent_data[(recent_data['high'] > df['close'].iloc[-1]) & (recent_data['low'] < target_price)]
        else:
            obstacles = recent_data[(recent_data['low'] < df['close'].iloc[-1]) & (recent_data['high'] > target_price)]
            
        # If less than 15% of candles are obstacles, it's relatively clean
        return len(obstacles) < (len(recent_data) * 0.15)

    @staticmethod
    def is_momentum_candle(candle, min_body_pct=0.6):
        """
        Checks if the candle is a momentum candle (large body, small wicks).
        """
        total_range = candle['high'] - candle['low']
        if total_range == 0: return False
        
        body_size = abs(candle['close'] - candle['open'])
        body_pct = body_size / total_range
        
        return body_pct >= min_body_pct

    @staticmethod
    def has_confirmation_wick(candle, direction):
        """
        Raja Banks Style: Buys need a bottom wick, Sells need a top wick.
        Shows that price 'tested' the area before moving.
        """
        total_range = candle['high'] - candle['low']
        if total_range == 0: return False
        
        body_bottom = min(candle['open'], candle['close'])
        body_top = max(candle['open'], candle['close'])
        
        if direction == 'BUY':
            lower_wick_pct = (body_bottom - candle['low']) / total_range
            return lower_wick_pct > 0.05 # At least 5% wick
        else:
            upper_wick_pct = (candle['high'] - body_top) / total_range
            return upper_wick_pct > 0.05

    @staticmethod
    def find_high_quality_levels(df, lookback=100, touches=2, threshold_price=None):
        """
        Finds S/R levels by identifying price clusters where multiple candles stalled.
        """
        data = df.tail(lookback)
        current_price = df['close'].iloc[-1]

        if threshold_price is None:
            # Dynamic threshold: ~15 pips equivalent
            if current_price > 1000: # Gold (~2000+)
                threshold_price = 1.5 
            elif current_price > 50: # JPY Pairs (~150+)
                threshold_price = 0.15
            else: # Standard Forex (1.x)
                threshold_price = 0.0015

        # Use a combination of highs, lows and closes for better level detection
        price_points = np.concatenate([data['high'].values, data['low'].values])
        
        # Sort price points to find clusters
        price_points.sort()
        
        levels = []
        if len(price_points) == 0:
            return {'resistance': None, 'support': None}

        # Simple clustering: group points that are within 'threshold_price' of each other
        current_cluster = [price_points[0]]
        for i in range(1, len(price_points)):
            if (price_points[i] - price_points[i-1]) <= threshold_price:
                current_cluster.append(price_points[i])
            else:
                if len(current_cluster) >= touches:
                    levels.append(np.mean(current_cluster))
                current_cluster = [price_points[i]]
        
        # Add the last cluster if it qualifies
        if len(current_cluster) >= touches:
            levels.append(np.mean(current_cluster))

        if not levels:
            return {'resistance': None, 'support': None}

        # Sort levels and pick the ones furthest from current price as SR
        levels.sort()
        current_price = df['close'].iloc[-1]
        
        resistances = [l for l in levels if l > current_price]
        supports = [l for l in levels if l < current_price]
        
        return {
            'resistance': min(resistances) if resistances else None,
            'support': max(supports) if supports else None,
            'all_levels': levels
        }

    @staticmethod
    def is_liquidity_sweep_rejection(df: pd.DataFrame, direction: str, window=20):
        """
        Detects a Swing Failure Pattern (SFP).
        Price breaks the previous swing high/low but immediately rejects back inside.
        """
        if len(df) < window + 2: return False
        
        last_candle = df.iloc[-1]
        prev_data = df.iloc[-window-1:-1]
        
        if direction == 'BUY': # Looking for Bearish SFP (Sweep of High)
            swing_high = prev_data['high'].max()
            # If current high broke swing_high but close is below it
            if last_candle['high'] > swing_high and last_candle['close'] < swing_high:
                return True
        else: # Looking for Bullish SFP (Sweep of Low)
            swing_low = prev_data['low'].min()
            # If current low broke swing_low but close is above it
            if last_candle['low'] < swing_low and last_candle['close'] > swing_low:
                return True
        return False

    @staticmethod
    def is_exhaustion_candle(candle, direction):
        """
        Detects exhaustion wicks (Bullish signal with massive top wick).
        Retailers buy the spike, but institutions are selling the top.
        """
        wicks = PriceAction.check_wick_rejection(candle, threshold=0.45)
        if direction == 'BUY' and wicks['upper']: return True
        if direction == 'SELL' and wicks['lower']: return True
        return False

    @staticmethod
    def detect_displacement(df: pd.DataFrame, index: int, period=10):
        """
        ICT Displacement: A candle that is significantly larger than the recent average.
        Usually indicates institutional intent.
        """
        if index < period: return False
        candle = df.iloc[index]
        prev_candles = df.iloc[index-period:index]
        avg_size = (prev_candles['high'] - prev_candles['low']).mean()
        curr_size = candle['high'] - candle['low']
        
        # Displacement = Size > 1.5x average AND Body > 70% of candle
        return curr_size > (avg_size * 1.5) and abs(candle['close'] - candle['open']) / curr_size > 0.7

    @staticmethod
    def get_structural_bias(df: pd.DataFrame, window=20):
        """
        Analyzes HH/HL vs LH/LL to determine institutional bias on HTF.
        """
        if len(df) < window * 2: return 'NEUTRAL'
        
        # Simple rolling peak detection
        recent_highs = df['high'].tail(window * 2)
        recent_lows = df['low'].tail(window * 2)
        
        h1 = recent_highs.iloc[:window].max()
        h2 = recent_highs.iloc[window:].max()
        
        l1 = recent_lows.iloc[:window].min()
        l2 = recent_lows.iloc[window:].min()
        
        if h2 > h1 and l2 > l1: return 'BULLISH'
        if h2 < h1 and l2 < l1: return 'BEARISH'
        
        return 'NEUTRAL'

    @staticmethod
    def calculate_atr(df, period=14):
        """
        Calculates the Average True Range.
        """
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        return true_range.rolling(period).mean().iloc[-1]
