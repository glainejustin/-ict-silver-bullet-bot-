"""
One source of truth for the shipping trend system's parameters.

WHY THIS FILE EXISTS
--------------------
The research harness and the live strategy are separate code paths. They drifted
before: the live module (strategies/gold_trend.py) reads GOLD_TREND_ATR_PERIOD = 14
from config.py, while TrendSim's default was ATR(20), so the numbers published in
the research report described a slightly different system than the one that trades.
The difference turned out to be immaterial (CAGR 1.7% vs 2.1%), but "the backtest
and the bot are not the same system" is exactly the class of mistake this repo has
already been bitten by -- see the stub_config drift bug in XAUUSD_EDGE_REPORT.md.

Anything in research/ that intends to describe the SHIPPING system must take its
parameters from here, and research/check_config_parity.py asserts that this module
still agrees with config.py.
"""
from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CONFIG_PATH = os.path.join(ROOT, "config.py")

DEFAULTS = {
    "GOLD_TREND_TIMEFRAME": "H4",
    "GOLD_TREND_LOOKBACK": 55,
    "GOLD_TREND_ATR_PERIOD": 14,
    "GOLD_TREND_STOP_ATR": 2.0,
    "GOLD_TREND_TRAIL_ATR": 4.0,
    "GOLD_TREND_ALLOW_SHORTS": False,
}


def read_config_values() -> dict:
    """
    Parse config.py's AST instead of importing it.

    config.py does `import MetaTrader5 as mt5` at module level, which does not
    exist off Windows, so the research harness has to read the literals -- the
    same technique research/check_config_parity.py uses.
    """
    out = dict(DEFAULTS)
    try:
        tree = ast.parse(open(CONFIG_PATH, encoding="utf-8").read())
    except OSError:
        return out
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name) and t.id in DEFAULTS:
                try:
                    out[t.id] = ast.literal_eval(node.value)
                except Exception:                                  # noqa: BLE001
                    pass
    return out


def trend_kwargs() -> dict:
    """
    Keyword arguments for research.gold_edge.TrendSim.run() that reproduce the
    shipping strategy exactly. Read from config.py, not hard-coded.
    """
    v = read_config_values()
    return {
        "entry_tf": str(v["GOLD_TREND_TIMEFRAME"]),
        "donchian": int(v["GOLD_TREND_LOOKBACK"]),
        "atr_period": int(v["GOLD_TREND_ATR_PERIOD"]),
        "stop_atr": float(v["GOLD_TREND_STOP_ATR"]),
        "trail_atr": float(v["GOLD_TREND_TRAIL_ATR"]),
        "long_only": not bool(v["GOLD_TREND_ALLOW_SHORTS"]),
    }


def description() -> str:
    k = trend_kwargs()
    return (f"{k['entry_tf']} Donchian{k['donchian']} / {k['stop_atr']}xATR({k['atr_period']}) "
            f"stop / {k['trail_atr']}xATR trail / "
            f"{'long-only' if k['long_only'] else 'long+short'}")
