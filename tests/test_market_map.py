"""
Regression tests for core/market_map.py.

These check the properties that, if broken, produce a map that still *looks*
plausible on screen while being wrong -- which is worse than a crash.

Run: python tests/test_market_map.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.market_map import (  # noqa: E402
    volume_profile, profile_heatmap, liquidity_pools, swing_points,
    cluster_levels, session_extremes, round_numbers,
    record_depth_snapshot, load_depth_history, depth_heatmap,
)

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILED.append(name)


def synthetic(n: int = 400, seed: int = 3) -> pd.DataFrame:
    """Two-session frame with a known high-volume shelf at 2000."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="15min")
    px = 2000 + np.cumsum(rng.normal(0, 1.0, n))
    # pull half the bars back to the shelf so it is unambiguously the POC
    px[::2] = 2000 + rng.normal(0, 0.2, len(px[::2]))
    high = px + np.abs(rng.normal(0, 0.5, n))
    low = px - np.abs(rng.normal(0, 0.5, n))
    return pd.DataFrame({"open": px, "high": high, "low": low, "close": px,
                         "volume": np.abs(rng.normal(100, 20, n))}, index=idx)


def main() -> int:
    print("market_map tests\n")
    df = synthetic()

    prof = volume_profile(df, bins=60)
    check("POC sits inside the price range",
          df.low.min() <= prof.poc <= df.high.max(), f"poc={prof.poc:.2f}")
    va = prof.volume[(prof.centres >= prof.val) & (prof.centres <= prof.vah)].sum()
    cov = va / prof.total_volume
    check("value area covers ~70% of volume", 0.65 <= cov <= 0.80, f"{cov:.1%}")
    check("total volume is conserved",
          np.isclose(prof.volume.sum(), df.volume.sum(), rtol=1e-6))
    check("POC is near the planted shelf", abs(prof.poc - 2000) < 3.0, f"{prof.poc:.2f}")
    check("HVN/LVN are populated", len(prof.hvn) > 0 and len(prof.lvn) > 0,
          f"{len(prof.hvn)} HVN, {len(prof.lvn)} LVN")

    # zero-volume feed must fall back to a tick-count proxy, not produce empty output
    novol = df.assign(volume=0.0)
    prof2 = volume_profile(novol, bins=60)
    check("zero-volume feed still yields a profile", prof2.total_volume > 0,
          f"total={prof2.total_volume:.0f}")

    # --- heatmap alignment: the bug that made every session pile into one row
    hm = profile_heatmap(df, freq="D", bins=40)
    n_sessions = int(pd.Index(df.index.date).nunique())
    check("heatmap has one column per session", hm.matrix.shape[1] == n_sessions,
          f"{hm.matrix.shape} for {n_sessions} sessions")
    col_tot = hm.matrix.sum(axis=0)
    check("each column equals its session's volume",
          np.allclose(col_tot, hm.stats["volume"].to_numpy(), rtol=1e-6))
    check("per-session POC inside its own session range",
          all(s.low <= s.poc <= s.high for _, s in hm.stats.iterrows()))
    # every session must use the SAME price grid, i.e. volume lands in the middle
    # of the grid rather than at row 0
    check("session volume is not stacked at the bottom of the grid",
          int(np.argmax(hm.matrix.sum(axis=1))) > 3,
          f"peak row {int(np.argmax(hm.matrix.sum(axis=1)))} of {hm.matrix.shape[0]}")

    # --- swings and clustering
    hi, lo = swing_points(df, 3, 3)
    check("swings are found", len(hi) > 5 and len(lo) > 5, f"{len(hi)}H {len(lo)}L")
    check("swings avoid the warm-up edges",
          (len(hi) == 0 or hi.min() >= 3) and (len(hi) == 0 or hi.max() <= len(df) - 4))
    cl = cluster_levels([100.0, 100.05, 100.1, 120.0, 120.04], tol=0.2)
    check("clustering merges nearby prices", len(cl) == 2, str([c["touches"] for c in cl]))
    check("clusters are price-sorted", cl[0]["price"] < cl[1]["price"])

    pools = liquidity_pools(df, atr=1.5)
    check("buyside pools are above price, sellside below",
          (len(pools.buyside) == 0 or (pools.buyside.price > pools.price).all()) and
          (len(pools.sellside) == 0 or (pools.sellside.price < pools.price).all()))
    if len(pools.sellside):
        check("pool strength is normalised 0-1",
              float(pools.sellside.strength.max()) <= 1.0 + 1e-9)

    ex = session_extremes(df)
    check("session extremes are ordered",
          ex.get("prior_day_low", 0) < ex.get("prior_day_high", 1), str(ex.get("prior_day_high")))
    check("round numbers bracket the price",
          min(round_numbers(2005.0, step=10)) <= 2005.0 <= max(round_numbers(2005.0, step=10)))

    # --- depth (DOM) path, exercised against a stub terminal ---------------
    # The live functions take `mt5` as an argument precisely so they can be
    # tested without a terminal. A CFD broker that publishes no depth returns
    # None, so both branches are covered here.
    class _Entry:
        def __init__(self, t, price, volume):
            self.type, self.price, self.volume, self.volume_real = t, price, volume, volume

    class _StubMT5:
        def __init__(self, book):
            self._book = book

        def market_book_get(self, symbol):
            return self._book

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        log = os.path.join(td, "depth.jsonl")
        empty = record_depth_snapshot(_StubMT5(None), "XAUUSD", log)
        check("no depth published -> returns None", empty is None)
        book = [_Entry(1, 2000.00 - i * 0.25, 5 + i) for i in range(6)]
        book += [_Entry(2, 2000.25 + i * 0.25, 4 + i) for i in range(6)]
        snap = record_depth_snapshot(_StubMT5(book), "XAUUSD", log)
        check("depth snapshot recorded", snap is not None and len(snap["levels"]) == 12)
        hist = load_depth_history(log)
        check("depth log reloads as a long frame",
              len(hist) == 12 and set(hist.side) == {"bid", "ask"})
        bids, asks = depth_heatmap(log, resample="1s")
        check("depth pivots into bid/ask heatmaps",
              not bids.empty and not asks.empty, f"{bids.shape} / {asks.shape}")
        check("bid prices sit below ask prices",
              float(bids.index.max()) < float(asks.index.min()))

    print()
    if FAILED:
        print(f"❌ {len(FAILED)} test(s) failed: {', '.join(FAILED)}")
        return 1
    print("✅ all market_map tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
