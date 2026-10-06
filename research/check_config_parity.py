"""
Guard against research/shipped-config drift.

The research harness cannot import config.py (it imports MetaTrader5, which is
Windows-only), so research/stub_config.py mirrors the values. If someone tunes
config.py without updating the stub, every research number silently describes a
different system than the one that trades.

This script parses config.py's AST for the mirrored literals and compares them.
Run it before trusting any research output:

    python research/check_config_parity.py
"""
from __future__ import annotations

import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import research.stub_config as stub  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(os.path.dirname(HERE), "config.py")

# keys the research depends on
KEYS = [
    "GOLD_TREND_ENABLED", "GOLD_TREND_TIMEFRAME", "GOLD_TREND_LOOKBACK",
    "GOLD_TREND_ATR_PERIOD", "GOLD_TREND_STOP_ATR", "GOLD_TREND_TRAIL_ATR",
    "GOLD_TREND_REGIME_FILTER", "GOLD_TREND_REGIME_SMA", "GOLD_TREND_ALLOW_SHORTS",
    "GOLD_TREND_REQUIRE_NEW_BAR", "RISK_PERCENT", "MIN_STOP_DISTANCE_POINTS",
    "MAX_COST_RATIO_OF_R", "MAX_DAILY_TRADES", "DAILY_GOAL_PERCENT",
    "SYMBOLS", "MAX_SPREAD_PIPS", "SYMBOL_PIP_SIZE", "VOL_MA_PERIOD",
    "PARTIAL_TP_RR", "BREAKEVEN_RR",
]


def parse_config_literals() -> dict:
    tree = ast.parse(open(CONFIG).read())
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in KEYS:
                try:
                    out[target.id] = ast.literal_eval(node.value)
                except Exception:
                    pass
    return out


def check_shipping_config(real: dict) -> list[tuple]:
    """
    The research harness must describe the SAME system the bot trades.

    TrendSim's ATR default was 20 while the shipping module uses config's
    GOLD_TREND_ATR_PERIOD (14), so published numbers described a slightly
    different system. research/shipping_config.py now reads config.py, and this
    asserts the values it reads are the ones that came out of the AST.
    """
    import importlib
    importlib.import_module("research.shipping_config")
    sc = sys.modules["research.shipping_config"]
    kw = sc.trend_kwargs()
    pairs = [
        ("entry_tf", kw["entry_tf"], real.get("GOLD_TREND_TIMEFRAME", "H4")),
        ("donchian", kw["donchian"], real.get("GOLD_TREND_LOOKBACK", 55)),
        ("atr_period", kw["atr_period"], real.get("GOLD_TREND_ATR_PERIOD", 14)),
        ("stop_atr", float(kw["stop_atr"]), float(real.get("GOLD_TREND_STOP_ATR", 2.0))),
        ("trail_atr", float(kw["trail_atr"]), float(real.get("GOLD_TREND_TRAIL_ATR", 4.0))),
        ("long_only", kw["long_only"], not bool(real.get("GOLD_TREND_ALLOW_SHORTS", False))),
    ]
    return [("shipping." + k, a, b) for k, a, b in pairs if a != b]


def main() -> int:
    real = parse_config_literals()
    # the stub installs itself as sys.modules["config"]; read the installed module
    import importlib
    importlib.import_module("research.stub_config")
    stub_mod = sys.modules["config"]
    mismatches = []
    for k in KEYS:
        cfg_val = real.get(k, "<missing>")
        stub_val = getattr(stub_mod, k, "<missing>")
        if cfg_val != stub_val:
            mismatches.append((k, cfg_val, stub_val))

    print(f"config.py keys found: {len(real)}/{len(KEYS)}")
    ship_mismatches = check_shipping_config(real)
    if not ship_mismatches:
        print("✅ research/shipping_config.py uses the shipped GOLD_TREND_* parameters.")
    else:
        print("❌ research/shipping_config.py does NOT match config.py:")
        for k, a, b in ship_mismatches:
            print(f"     {k}: research={a}  config.py={b}")
        mismatches = list(mismatches) + ship_mismatches

    if not mismatches:
        print("✅ config.py and research/stub_config.py agree on every mirrored value.")
        return 0

    print("❌ MISMATCH between config.py and research/stub_config.py:\n")
    print(f"  {'key':<28} {'config.py':<28} {'stub_config.py'}")
    for k, a, b in mismatches:
        print(f"  {k:<28} {str(a):<28} {b}")
    print("\nUpdate research/stub_config.py so the research describes the shipped system.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
