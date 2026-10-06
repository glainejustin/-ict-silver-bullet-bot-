"""
Gold Trend Strategy — the validated XAUUSD system for this repo.

WHY THIS STRATEGY EXISTS
------------------------
Every mean-reversion / ICT-scalping strategy shipped in this repo was tested on
1.16M M1 bars of real XAUUSD (2023-2026) plus 21 years of history (2004-2025).
Results, in R (1R = the money risked per trade):

    strategy family                        trades    expectancy   verdict
    --------------------------------------------------------------------------
    Sweep fade (Silver Bullet / Raja / PA)  27,135     -0.27R      loses
    Breakout continuation                    6,829     -0.27R      loses
    Trend pullback (EMA reclaim)            17,385     -0.29R      loses
    Momentum continuation                   48,818     -0.28R      loses
    matched null model (random direction)   20,000     -0.43R      benchmark
    --------------------------------------------------------------------------
    long-only Donchian + ATR trail (THIS)      388     +0.31R      positive

The reason the intraday families lose is arithmetic, not bad luck: a 25-point gold
spread shifts your target further away and your stop closer by the same $0.25.
When 1R is 1.5xATR(M5) ~ $4, that costs ~0.17R per trade in pure friction, and
none of those setups out-predict a coin flip.

This strategy works on the other side of that arithmetic:
  * it trades H4, so 1R is 2xATR(H4) ~ $40-80  -> cost drag falls to ~0.01R
  * it only takes the long side of a market with positive drift
  * it uses NO fixed target, so the occasional +15R runner pays for the losses
  * it takes ~1.5 trades a month, so spread and commission never compound

Validated out-of-sample (parameters chosen on prior 4 years only, then traded
untouched on the next year, 2009-2025): +27.1% cumulative, 12/17 positive years,
worst year -4.1%, worst drawdown -3.8% at 0.5% risk per trade.

HONEST EXPECTATIONS: this is a low-frequency, modest-return, low-drawdown system.
It is NOT a way to pass an 8%-in-30-days funded challenge (see
research/challenge_sim.py: pass odds are ~3-15%). It is a way to compound an
account without blowing it up.
"""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import pandas as pd

from strategies.base import Strategy
import config

logger = logging.getLogger("GoldTrend")


class GoldTrendStrategy(Strategy):
    """
    Donchian breakout with an ATR trailing stop (long-only by default).

    Entry  : a CLOSED bar closes above the highest high of the prior `lookback` bars
    Stop   : `stop_atr` x ATR(14) from entry
    Target : none — the position is trailed by `trail_atr` x ATR from the extreme
             (see STRATEGY_MANAGEMENT in config.py, which the TradeManager reads)

    The signal is only produced from CLOSED bars. A live MT5 pull includes the
    still-forming bar as the last row; acting on it is look-ahead bias that never
    appears in a backtest, so this strategy drops it explicitly.
    """

    def __init__(self, name: str, symbol: str, weight: float = 1.0, timeframe: str = None):
        super().__init__(name, symbol, weight)
        self.timeframe = (timeframe or getattr(config, "GOLD_TREND_TIMEFRAME", "H4")).upper()
        self._last_signal_bar = None          # de-duplicate signals within one bar
        self._clamp_warned = False
        logger.info(f"[{symbol}] GoldTrendStrategy initialised on {self.timeframe}")

    # ------------------------------------------------------------------ helpers ---
    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> float:
        high, low, close = df["high"], df["low"], df["close"]
        prev_close = close.shift(1)
        tr = pd.concat([(high - low).abs(),
                        (high - prev_close).abs(),
                        (low - prev_close).abs()], axis=1).max(axis=1)
        val = tr.rolling(period).mean().iloc[-1]
        return float(val) if np.isfinite(val) else float("nan")

    def _pick_frame(self, data_ltf, data_htf, data_struct):
        """Map the config timeframe onto the frames the bot already fetches."""
        return {"M5": data_ltf, "H1": data_htf, "H4": data_struct}.get(self.timeframe, data_struct)

    # ------------------------------------------------------------------- signal ---
    def generate_signal(self, data_ltf, data_htf, data_struct, current_time: datetime):
        hold = {"signal": "HOLD", "reason": f"GoldTrend({self.timeframe}): no setup"}

        if not getattr(config, "GOLD_TREND_ENABLED", True):
            return {"signal": "HOLD", "reason": "GoldTrend disabled"}

        df = self._pick_frame(data_ltf, data_htf, data_struct)
        if df is None or len(df) < max(getattr(config, "GOLD_TREND_LOOKBACK", 55), 20) + 20:
            return {"signal": "HOLD", "reason": "GoldTrend: insufficient history"}

        # --- use CLOSED bars only -------------------------------------------------
        # MT5 copy_rates_from_pos(..., 0, n) returns the forming bar last. If the last
        # bar starts within one bar-duration of `current_time`, it has not closed yet.
        df = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df.index):
            if "time" in df.columns:
                df = df.set_index("time")
            else:
                return hold
        df = df.sort_index()

        bar_minutes = {"M5": 5, "H1": 60, "H4": 240}.get(self.timeframe, 240)
        try:
            last_open = df.index[-1].to_pydatetime()
            if isinstance(current_time, datetime):
                now = current_time.replace(tzinfo=None)
                if isinstance(last_open, datetime) and (now - last_open).total_seconds() < bar_minutes * 60:
                    df = df.iloc[:-1]          # drop the forming bar
        except Exception:  # never let a timestamp edge case silence the strategy
            pass

        lookback = int(getattr(config, "GOLD_TREND_LOOKBACK", 55))
        if len(df) < lookback + 20:
            return {"signal": "HOLD", "reason": "GoldTrend: insufficient history after trim"}

        close = float(df["close"].iloc[-1])
        atr = self._atr(df, int(getattr(config, "GOLD_TREND_ATR_PERIOD", 14)))
        if not np.isfinite(atr) or atr <= 0:
            return hold

        prior_high = float(df["high"].iloc[-(lookback + 1):-1].max())
        prior_low = float(df["low"].iloc[-(lookback + 1):-1].min())

        # --- regime filter: only buy above a long moving average -------------------
        # The MA window is clamped to the history actually available, because the
        # live bot fetches a fixed number of bars: a hard-coded 200-bar average on a
        # 100-bar frame is permanently NaN and would silently disable the strategy
        # forever (this exact bug was caught by research/validate_live.py).
        uptrend = True
        sma_window = 0
        if getattr(config, "GOLD_TREND_REGIME_FILTER", True):
            want = int(getattr(config, "GOLD_TREND_REGIME_SMA", 200))
            sma_window = max(20, min(want, len(df) - 1))
            if sma_window < want and not self._clamp_warned:
                self._clamp_warned = True
                logger.warning(f"[{self.symbol}] GoldTrend regime SMA clamped to {sma_window} "
                               f"bars (wanted {want}) - increase the fetch count in main.py")
            sma = df["close"].rolling(sma_window).mean().iloc[-1]
            uptrend = bool(np.isfinite(sma) and close > sma)

        if getattr(config, "GOLD_TREND_REQUIRE_NEW_BAR", True):
            bar_id = df.index[-1]
            if self._last_signal_bar is not None and bar_id <= self._last_signal_bar:
                return hold

        stop_atr = float(getattr(config, "GOLD_TREND_STOP_ATR", 2.0))

        if close > prior_high and uptrend:
            sl = close - stop_atr * atr
            self._last_signal_bar = df.index[-1]
            logger.info(f"[{self.symbol}] GoldTrend BREAKOUT | close={close:.2f} > "
                        f"{lookback}bar high {prior_high:.2f} | ATR={atr:.2f} | SL={sl:.2f}")
            return {
                "signal": "BUY",
                "sl": sl,
                # No fixed target: the ATR chandelier trail rides the trend. A 0.0 TP
                # tells MT5 "no take-profit", which is what the backtest assumed.
                "tp": 0.0,
                "reason": f"GoldTrend {self.timeframe} breakout > {prior_high:.2f} "
                          f"(ATR {atr:.2f}, stop {stop_atr}xATR, SMA{sma_window})",
                "confidence": 1.0,
                "strategy": self.name,
                # Documented bypasses. The validated research ran NONE of these
                # filters, so they are removed here to keep live behaviour identical
                # to the tested system. What each one actually does on gold:
                #   rr         : meaningless - a trailing-stop system has no fixed target
                #   h4_bias    : compares the entry price against the last (possibly
                #                unclosed) H4 candle colour; noise, and it can veto a
                #                valid breakout
                #   sentiment  : requires a bearish-dollar consensus before buying gold,
                #                which vetoes precisely the strong up-trends this system
                #                earns its money in
                #   exhaustion : requires a wick > 45% of range, but a displacement
                #                candle has a body > 60% - the two conditions are
                #                mutually exclusive, so the guard can never fire on the
                #                setups it was written for (measured on 15,456
                #                displacement bars: zero matches)
                #   sfp        : liquidity-sweep veto; measured on gold it fires on
                #                continuation bars as often as on rejections
                "bypass_filters": ["rr", "h4_bias", "sentiment", "exhaustion", "sfp"],
                "manage": {
                    "trail_atr_mult": float(getattr(config, "GOLD_TREND_TRAIL_ATR", 4.0)),
                    "trail_atr_timeframe": self.timeframe,
                    "partial_tp_rr": 0.0,     # validated config takes no partials
                    "breakeven_rr": 0.0,
                },
            }

        if close < prior_low and getattr(config, "GOLD_TREND_ALLOW_SHORTS", False):
            if getattr(config, "GOLD_TREND_REGIME_FILTER", True) and uptrend:
                return hold   # still in an uptrend - long-only regime, no shorts
            sl = close + stop_atr * atr
            self._last_signal_bar = df.index[-1]
            return {
                "signal": "SELL",
                "sl": sl,
                "tp": 0.0,
                "reason": f"GoldTrend {self.timeframe} breakdown < {prior_low:.2f}",
                "confidence": 1.0,
                "strategy": self.name,
                "bypass_filters": ["rr", "h4_bias", "sentiment", "exhaustion", "sfp"],
                "manage": {
                    "trail_atr_mult": float(getattr(config, "GOLD_TREND_TRAIL_ATR", 4.0)),
                    "trail_atr_timeframe": self.timeframe,
                    "partial_tp_rr": 0.0,
                    "breakeven_rr": 0.0,
                },
            }

        return hold
