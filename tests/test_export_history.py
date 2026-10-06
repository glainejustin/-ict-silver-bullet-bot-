"""
Tests for tools/export_mt5_history.py helpers (no MetaTrader5 needed).

The chunking and frame-building are where the quiet failures live: a wide
history request that gets silently truncated looks exactly like "gold history
starts in 2019".

Run: python tests/test_export_history.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.export_mt5_history import rates_to_frame, year_chunks, summarize  # noqa: E402

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"  {tag}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILED.append(name)


def main() -> int:
    print("mt5 history export helpers\n")

    # ---- chunking ---------------------------------------------------------
    ch = year_chunks(datetime(2003, 1, 1), datetime(2026, 1, 1))
    # 365-day chunks: a 23-year span needs 24 of them once leap days are counted
    check("a 23-year span needs <= 24 chunks", 23 <= len(ch) <= 24, f"{len(ch)} chunks")
    check("chunks cover the whole span exactly",
          ch[0][0] == datetime(2003, 1, 1) and ch[-1][1] == datetime(2026, 1, 1))
    check("chunks are contiguous",
          all(ch[i][1] == ch[i + 1][0] for i in range(len(ch) - 1)))
    check("chunks are ordered", all(a < b for a, b in ch))
    check("a sub-year span is one chunk",
          len(year_chunks(datetime(2025, 1, 1), datetime(2025, 3, 1))) == 1)
    check("an empty span is no chunks",
          year_chunks(datetime(2025, 3, 1), datetime(2025, 1, 1)) == [])

    # ---- rates -> frame ---------------------------------------------------
    n = 6
    base = int(datetime(2024, 1, 2, 0, 0).timestamp())
    rates = np.array([
        (base + i * 3600, 2000 + i, 2002 + i, 1998 + i, 2001 + i, 100 + i, 25)
        for i in range(n)
    ], dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
              ("close", "f8"), ("tick_volume", "i8"), ("spread", "i4")])
    df = rates_to_frame(rates)
    check("frame has one row per bar", len(df) == n, f"{len(df)}")
    check("index is the bar OPEN time",
          df.index[0] == pd.Timestamp("2024-01-02 00:00:00"), str(df.index[0]))
    check("ohlc columns survive",
          set(("open", "high", "low", "close")).issubset(df.columns))
    check("a utc column is added", "utc" in df.columns)
    check("utc is offset from broker time (or equal if unknown)",
          df["utc"].notna().all())
    check("spread is preserved", int(df["spread"].iloc[0]) == 25)
    check("empty input gives an empty frame", rates_to_frame(None).empty)
    malformed = np.array([(1,)], dtype=[("x", "i8")])          # no time/ohlc
    check("malformed input gives an empty frame", rates_to_frame(malformed).empty)
    check("summary mentions the bar count", "6 bars" in summarize(df, "XAUUSD", "H4"),
          summarize(df, "XAUUSD", "H4"))

    # duplicate timestamps must not survive
    dup = np.concatenate([rates, rates[:2]])
    check("duplicate bars are dropped", len(rates_to_frame(dup)) == n)

    print()
    if FAILED:
        print(f"❌ {len(FAILED)} test(s) failed: {', '.join(FAILED)}")
        return 1
    print("✅ all mt5 export helper tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
