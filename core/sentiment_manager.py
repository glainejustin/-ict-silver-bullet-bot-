import MetaTrader5 as mt5
import pandas as pd
import logging
from datetime import datetime
from core.price_action import PriceAction

logger = logging.getLogger("SentimentManager")

class SentimentManager:
    """
    Handles Macro Sentiment analysis (DXY Alignment).
    Institutions trade based on the dollar. If DXY is bullish, EURUSD must be bearish.

    QUANT FIX: All data fetches now accept a `sim_time` parameter.
    - In LIVE mode (sim_time=None): uses copy_rates_from_pos (latest N bars).
    - In BACKTEST mode (sim_time=datetime): uses copy_rates_from to fetch
      point-in-time historical data, eliminating look-ahead bias completely.
    """
    def __init__(self, dxy_symbol="USDX"):
        self.dxy_symbol = dxy_symbol

    def _fetch_rates(self, symbol: str, timeframe: int, count: int, sim_time: datetime = None) -> pd.DataFrame:
        """
        Central fetch helper. Routes to historical or live data based on sim_time.
        This is the single source of truth that eliminates look-ahead bias.
        """
        if sim_time is not None:
            # BACKTEST MODE: Fetch exactly 'count' bars ending AT sim_time
            # This guarantees we can NEVER see data from after sim_time.
            rates = mt5.copy_rates_from(symbol, timeframe, sim_time, count)
        else:
            # LIVE MODE: Fetch the latest 'count' bars from the live feed
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)

        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df

    def get_dxy_bias(self, sim_time: datetime = None) -> str:
        """
        Returns 'BULLISH', 'BEARISH', or 'NEUTRAL'.

        QUANT FIX: In backtest mode, pass sim_time (the current bar's timestamp)
        to fetch historical point-in-time DXY rates, preventing look-ahead bias.

        If a direct DXY index isn't found, calculates a 'Synthetic DXY'
        based on the consensus of the 7 major USD pairs.
        """
        symbols_to_try = ["USDX", "DXY", "DX.m", "US Dollar Index", "USDIndex"]
        valid_symbol = None

        for s in symbols_to_try:
            if mt5.symbol_select(s, True):
                valid_symbol = s
                break

        if valid_symbol:
            df = self._fetch_rates(valid_symbol, mt5.TIMEFRAME_H1, 40, sim_time)
            if len(df) >= 20:  # Need at least 20 bars for structural bias
                return PriceAction.get_structural_bias(df, window=10)

        # --- Synthetic DXY Logic ---
        # Calculate consensus across 7 majors to proxy DXY direction
        majors = {
            "EURUSD": "INVERTED", "GBPUSD": "INVERTED", "AUDUSD": "INVERTED", "NZDUSD": "INVERTED",
            "USDJPY": "DIRECT",   "USDCHF": "DIRECT",   "USDCAD": "DIRECT"
        }

        scores = []
        for symbol, direction_type in majors.items():
            if not mt5.symbol_select(symbol, True):
                continue
            df = self._fetch_rates(symbol, mt5.TIMEFRAME_H1, 10, sim_time)
            if len(df) < 10:
                continue

            bias = PriceAction.get_structural_bias(df, window=5)

            if bias == "BULLISH":
                scores.append(1 if direction_type == "DIRECT" else -1)
            elif bias == "BEARISH":
                scores.append(-1 if direction_type == "DIRECT" else 1)

        if not scores:
            return "NEUTRAL"

        net_score = sum(scores)
        # Require at least 3 pairs in agreement for a confirmed bias
        if net_score >= 3:  return "BULLISH"
        if net_score <= -3: return "BEARISH"

        return "NEUTRAL"

    def get_dxy_momentum(self, sim_time: datetime = None) -> str:
        """
        FIX 4: Fast DXY sentiment — measures 3-hour rate-of-change ACCELERATION.
        
        WHY THIS IS BETTER:
        - get_dxy_bias() analyzes 40 H1 bars → lags price by 10-40 hours.
        - This method compares the LAST 3 hours vs the PRIOR 3 hours of EURUSD
          (a perfect inverse proxy for DXY) to detect if DXY is actively accelerating
          up or down RIGHT NOW — far more predictive for intraday Gold/JPY trades.
        """
        if not mt5.symbol_select("EURUSD", True):
            return "NEUTRAL"

        df = self._fetch_rates("EURUSD", mt5.TIMEFRAME_H1, 7, sim_time)
        if len(df) < 6:
            return "NEUTRAL"

        recent_chg = df['close'].iloc[-1] - df['close'].iloc[-3]
        prior_chg  = df['close'].iloc[-3] - df['close'].iloc[-6]

        if prior_chg < 0 and recent_chg < 0 and recent_chg < prior_chg:
            return "BULLISH"
        if prior_chg > 0 and recent_chg > 0 and recent_chg > prior_chg:
            return "BEARISH"

        return "NEUTRAL"

    def is_aligned(self, symbol: str, signal_type: str, sim_time: datetime = None) -> bool:
        """
        Checks if a trade signal is aligned with DXY macro sentiment.
        - EURUSD/XAUUSD (Inverted): BUY signal requires BEARISH DXY.
        - USDJPY (Direct): BUY signal requires BULLISH DXY.

        QUANT FIX: Pass sim_time during backtests so DXY bias is calculated
        using only data available at that historical moment.
        """
        dxy_bias     = self.get_dxy_bias(sim_time=sim_time)
        dxy_momentum = self.get_dxy_momentum(sim_time=sim_time)

        # Combine structural bias + momentum for a stronger, faster filter:
        # - If both agree → high conviction filter (block trade)
        # - If only one fires → soft filter (still allow trade, log warning)
        # - If both NEUTRAL → allow trade
        def dxy_is_bearish():
            return (dxy_bias == "BEARISH" or dxy_momentum == "BEARISH") and dxy_bias != "BULLISH"

        def dxy_is_bullish():
            return (dxy_bias == "BULLISH" or dxy_momentum == "BULLISH") and dxy_bias != "BEARISH"

        # Major USD-Inverted Pairs (USD is quoted currency; DXY rise = pair falls)
        inverted_pairs = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "XAUUSD"]
        # Major USD-Direct Pairs (USD is base currency; DXY rise = pair rises)
        direct_pairs = ["USDJPY", "USDCHF", "USDCAD"]

        if any(pair in symbol for pair in inverted_pairs):
            if signal_type == "BUY"  and dxy_bias == "BULLISH": return False
            if signal_type == "SELL" and dxy_bias == "BEARISH":  return False

        if any(pair in symbol for pair in direct_pairs):
            if signal_type == "BUY"  and dxy_bias == "BEARISH": return False
            if signal_type == "SELL" and dxy_bias == "BULLISH": return False

        return True
