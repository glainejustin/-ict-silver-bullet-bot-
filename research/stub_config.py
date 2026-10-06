"""
Config stub for research scripts.

The repo's real `config.py` imports MetaTrader5 (Windows-only), so research runs
cannot import it. This module installs a stub `config` into sys.modules with the
same values as the shipped config.py.

IMPORTANT: if you change the values in config.py, change them here too -- the
numbers below are what the research validation asserts against.
"""
from __future__ import annotations

import sys
import types


def install() -> None:
    if "config" in sys.modules and getattr(sys.modules["config"], "_is_stub", False):
        return
    m = types.ModuleType("config")
    m._is_stub = True

    # --- gold trend strategy (mirrors config.py) ---
    m.GOLD_TREND_ENABLED = True
    m.GOLD_TREND_TIMEFRAME = "H4"
    m.GOLD_TREND_LOOKBACK = 55
    m.GOLD_TREND_ATR_PERIOD = 14
    m.GOLD_TREND_STOP_ATR = 2.0
    m.GOLD_TREND_TRAIL_ATR = 4.0
    m.GOLD_TREND_REGIME_FILTER = True
    m.GOLD_TREND_ALLOW_SHORTS = False
    m.GOLD_TREND_REQUIRE_NEW_BAR = True

    # --- risk / costs ---
    m.RISK_PERCENT = 0.75
    m.SYMBOL_PIP_SIZE = {"XAUUSD": 0.1, "GBPJPY": 0.01, "EURUSD": 0.0001,
                         "AUDUSD": 0.0001, "USDJPY": 0.01}
    m.MIN_STOP_DISTANCE_POINTS = {"XAUUSD": 400, "GBPJPY": 40, "EURUSD": 25,
                                 "AUDUSD": 25, "USDJPY": 30}
    m.MAX_COST_RATIO_OF_R = 0.12
    m.MAX_DAILY_TRADES = 2
    m.VOL_MA_PERIOD = 20
    m.DAILY_GOAL_PERCENT = 0.0
    m.PARTIAL_TP_RR = 1.0
    m.BREAKEVEN_RR = 1.0
    m.GOLD_TREND_REGIME_SMA = 200
    m.STRATEGY_MANAGEMENT = {"GoldTrend": {"trail_atr_mult": 4.0, "trail_atr_timeframe": "H4",
                                           "partial_tp_rr": 0.0, "breakeven_rr": 0.0,
                                           "trail_after_r": 0.0}}
    m.DEFAULT_MANAGEMENT = {"trail_atr_mult": 2.5, "trail_atr_timeframe": "M5",
                            "partial_tp_rr": 1.0, "breakeven_rr": 1.0, "trail_after_r": 1.0}
    m.MAX_SPREAD_PIPS = {"XAUUSD": 45, "GBPJPY": 4, "EURUSD": 2, "AUDUSD": 2.5, "USDJPY": 3}
    m.NEWS_NO_TRADE_MINUTES = 30
    m.FRIDAY_CLOSE_HOUR = 20
    m.SLEEP_SECONDS = 15
    m.MAGIC_NUMBER = 786786
    m.SYMBOLS = ["XAUUSD"]

    sys.modules["config"] = m


install()
