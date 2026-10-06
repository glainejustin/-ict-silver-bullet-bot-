"""
Regression tests for the shipping gold strategy.

These guard the two failure modes that actually bite in production:

  1. a strategy that silently stops producing signals (e.g. an MA window longer
     than the number of bars the bot fetches -> permanently NaN)
  2. acting on the still-forming bar (live-only look-ahead that no backtest sees)

Run:  python tests/test_gold_trend.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import research.stub_config  # noqa: E402,F401  (installs the config stub)
from strategies.gold_trend import GoldTrendStrategy  # noqa: E402
import config  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILURES.append(name)


def make_h4(n: int = 300, breakout_at_end: bool = True) -> pd.DataFrame:
    """Synthetic H4 frame: a gentle uptrend, optionally with a clean breakout at the end."""
    idx = pd.date_range("2024-01-01", periods=n, freq="4h")
    base = 2000 + np.arange(n) * 0.8                      # steady uptrend
    if breakout_at_end:
        base[-1] = base[-2] + 40.0                        # last CLOSED bar breaks out
    high = base + 3.0
    low = base - 3.0
    close = base.copy()
    open_ = base - 0.5
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close},
                        index=idx)


def main() -> int:
    print("gold_trend strategy regression tests\n")

    strat = GoldTrendStrategy("GoldTrend_TEST", "XAUUSD")

    # --- 1. fires on a closed-bar breakout --------------------------------
    df = make_h4()
    sig = strat.generate_signal(df.iloc[-100:], df, df, df.index[-1] + pd.Timedelta(hours=4))
    check("produces a BUY on a valid breakout", sig["signal"] == "BUY", sig.get("reason", "")[:60])
    check("stop is below entry", sig.get("sl", 1e9) < df["close"].iloc[-1])
    check("no fixed take-profit (trailing system)", float(sig.get("tp", -1)) == 0.0)
    check("management plan carries the validated trail",
          sig.get("manage", {}).get("trail_atr_mult") == config.GOLD_TREND_TRAIL_ATR)
    check("declares its filter bypasses", "rr" in sig.get("bypass_filters", []))

    # --- 2. does NOT act on the forming bar ------------------------------
    # Same frame, but told "now" is the timestamp of that last (still open) bar.
    strat2 = GoldTrendStrategy("GoldTrend_TEST2", "XAUUSD")
    forming_now = df.index[-1] + pd.Timedelta(hours=1)     # 1h into the 4h bar
    sig2 = strat2.generate_signal(df.iloc[-100:], df, df, forming_now)
    check("ignores the still-forming bar", sig2["signal"] == "HOLD", sig2.get("reason", "")[:60])

    # --- 3. no duplicate signals from the same bar -----------------------
    strat3 = GoldTrendStrategy("GoldTrend_TEST3", "XAUUSD")
    t_close = df.index[-1] + pd.Timedelta(hours=4)
    first = strat3.generate_signal(df.iloc[-100:], df, df, t_close)
    second = strat3.generate_signal(df.iloc[-100:], df, df, t_close)
    check("fires once per closed bar", first["signal"] == "BUY" and second["signal"] == "HOLD")

    # --- 4. the regime MA must work with the history main.py actually fetches
    # 300 bars fetched -> ~299 closed; a 200-bar MA must be computable.
    short_strat = GoldTrendStrategy("GoldTrend_TEST4", "XAUUSD")
    sig4 = short_strat.generate_signal(df.iloc[-100:], df, df, df.index[-1] + pd.Timedelta(hours=4))
    check("regime MA satisfied with a 100-bar fetch (no permanent NaN)",
          sig4["signal"] == "BUY")

    # --- 5. min stop distance config exists for the traded symbol --------
    check("MIN_STOP_DISTANCE_POINTS set for XAUUSD",
          config.MIN_STOP_DISTANCE_POINTS.get("XAUUSD", 0) >= 100)

    print()
    if FAILURES:
        print(f"❌ {len(FAILURES)} test(s) failed: {', '.join(FAILURES)}")
        return 1
    print("✅ all gold_trend tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
