"""
Robustness test: does trend following on XAUUSD survive 21 years and a bear market?

Data: XAUUSD M15, 2004-06-11 .. 2025-09-30 (480,717 bars, MetaQuotes-style export).
That sample contains every regime that matters:
    2004-2011  secular bull (+550%)
    2011-2015  secular BEAR (-45%)
    2015-2018  range
    2018-2020  rally + covid crash
    2021-2023  rate-shock drawdown and recovery
    2023-2025  bull run to $3800+

We test long-only Donchian breakout with an ATR trailing stop, plus a
walk-forward where parameters are chosen ONLY on past data and applied to the
next year untouched.

WHY LONG-ONLY: gold has a positive long-run drift, and the short side of gold
trend systems has to fight both the drift and the spread. We still report the
long+short variant so the choice is evidence-based, not assumed.

Usage:
    python research/long_history.py
"""
from __future__ import annotations

import itertools
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from research import xau_data  # noqa: E402
from research import shipping_config  # noqa: E402
from research.gold_edge import POINT, CONTRACT, TrendSim  # noqa: E402

# The shipping system's parameters come from config.py via shipping_config, so
# this harness cannot describe a different system from the one that trades.
SHIP = shipping_config.trend_kwargs()
ATR_PERIOD = SHIP["atr_period"]

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "XAUUSD_M15_2004_2025.parquet")


class Frames:
    """Minimal frame container so TrendSim can run on the long history."""

    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.frames = frames

    def __getitem__(self, tf: str) -> pd.DataFrame:
        # TrendSim scans intrabar paths on "M1"; with the long history the finest
        # granularity available is M15, which is plenty for multi-day trend trades.
        if tf == "M1":
            return self.frames["M15"]
        return self.frames[tf]


def load_long_history() -> Frames:
    m15 = pd.read_parquet(DATA)
    m15 = m15.rename(columns=str.lower)
    m15.index.name = "time"
    # broker/server clock (EET) -> true UTC and NY, so time-of-day logic stays honest
    utc = m15.index.tz_localize(xau_data.BROKER_TZ).tz_convert("UTC").tz_localize(None)
    m15["utc"] = utc
    m15["ny"] = utc.tz_localize("UTC").tz_convert(xau_data.NY_TZ).tz_localize(None)
    m15["ny_hour"] = m15["ny"].dt.hour + m15["ny"].dt.minute / 60
    m15["weekday"] = m15["ny"].dt.weekday

    frames = {"M15": m15}
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    for tf, rule in (("H1", "1h"), ("H4", "4h"), ("D1", "1D")):
        r = m15.resample(rule, label="left", closed="left").agg(agg).dropna(subset=["open", "close"])
        r["utc"] = r.index.tz_localize(xau_data.BROKER_TZ).tz_convert("UTC").tz_localize(None)
        r["ny"] = r["utc"].dt.tz_localize("UTC").dt.tz_convert(xau_data.NY_TZ).dt.tz_localize(None)
        r["ny_hour"] = r["ny"].dt.hour + r["ny"].dt.minute / 60
        r["weekday"] = r["ny"].dt.weekday
        frames[tf] = r
    return Frames(frames)


def year_table(trades: pd.DataFrame, balance0: float = 5000.0) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    t = trades.copy()
    t["year"] = pd.to_datetime(t["exit_time"]).dt.year
    rows = []
    eq = balance0
    for y, g in t.groupby("year"):
        start_eq = eq
        eq = eq + g["pnl"].sum()
        wins, losses = g[g["pnl"] > 0], g[g["pnl"] <= 0]
        rows.append({
            "year": y, "trades": len(g),
            "return_%": round(g["pnl"].sum() / start_eq * 100, 1),
            "end_equity": round(eq, 0),
            "win_%": round(100 * len(wins) / len(g), 0),
            "PF": round(wins["pnl"].sum() / abs(losses["pnl"].sum()), 2) if len(losses) else np.inf,
            "expectancy_R": round(g["r"].mean(), 2),
        })
    return pd.DataFrame(rows)


def run(hist: Frames, **kw) -> tuple[dict, pd.DataFrame]:
    sim = TrendSim(balance=5000.0, risk_pct=0.5)
    kw.setdefault("atr_period", ATR_PERIOD)      # shipping value unless overridden
    m = sim.run(hist, **kw)
    return m, pd.DataFrame(sim.trades)


def walk_forward(hist: Frames, grid: dict, train_years: int = 4, start_year: int = 2009,
                 entry_tf: str = "H4", long_only: bool = True) -> pd.DataFrame:
    """
    Rolling walk-forward: pick the best parameter set on the trailing `train_years`
    of data, then trade the NEXT year with it, untouched. This is the only honest
    way to report an optimised system.
    """
    combos = list(itertools.product(*grid.values()))
    keys = list(grid.keys())
    years = sorted({d.year for d in hist["M1"].index})
    rows = []

    for y in years:
        if y < start_year or y > years[-1]:
            continue
        train_lo, train_hi = pd.Timestamp(f"{y - train_years}-01-01"), pd.Timestamp(f"{y - 1}-12-31 23:59")
        test_lo, test_hi = pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y}-12-31 23:59")

        best, best_score = None, -np.inf
        for combo in combos:
            params = dict(zip(keys, combo))
            sub = slice_frames(hist, train_lo, train_hi)
            m, _ = run(sub, entry_tf=entry_tf, long_only=long_only, **params)
            score = m.get("expectancy_R", -9) if m.get("trades", 0) >= 8 else -9
            if score is not None and score > best_score:
                best_score, best = score, params
        if best is None:
            continue

        test = slice_frames(hist, test_lo, test_hi)
        m, tr = run(test, entry_tf=entry_tf, long_only=long_only, **best)
        rows.append({"year": y, **best, "train_expectancy_R": round(best_score, 3),
                     "test_trades": m.get("trades", 0), "test_return_%": m.get("return_pct", 0),
                     "test_PF": m.get("profit_factor", 0), "test_maxDD_%": m.get("max_dd_pct", 0)})
    return pd.DataFrame(rows)


def slice_frames(hist: Frames, lo, hi) -> Frames:
    out = {}
    for tf, df in hist.frames.items():
        out[tf] = df.loc[(df.index >= lo) & (df.index <= hi)]
    return Frames(out)


def main() -> int:
    hist = load_long_history()
    m15 = hist["M15"]
    span_years = (m15.index[-1] - m15.index[0]).days / 365.25
    print("=" * 100)
    print(f"  XAUUSD long history: {m15.index[0].date()} -> {m15.index[-1].date()}  "
          f"({len(m15):,} M15 bars, {span_years:.1f} years)")
    print(f"  price {m15['close'].iloc[0]:.2f} -> {m15['close'].iloc[-1]:.2f}")
    print("=" * 100)

    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)

    # ---------------- 1. core systems, full sample ----------------
    print("\n### FULL-SAMPLE SYSTEM COMPARISON (0.5% risk per trade, $5,000 start)\n")
    systems = [
        ("H4 Donchian20/stop2/trail3 LONG-ONLY", dict(entry_tf="H4", donchian=20, stop_atr=2.0,
                                                      trail_atr=3.0, long_only=True)),
        ("H4 Donchian20/stop2/trail3 LONG+SHORT", dict(entry_tf="H4", donchian=20, stop_atr=2.0,
                                                       trail_atr=3.0)),
        ("H4 Donchian55/stop2/trail3 LONG-ONLY", dict(entry_tf="H4", donchian=55, stop_atr=2.0,
                                                      trail_atr=3.0, long_only=True)),
        ("H4 Donchian55/stop2/trail3 LONG+SHORT", dict(entry_tf="H4", donchian=55, stop_atr=2.0,
                                                       trail_atr=3.0)),
        ("H1 Donchian55/stop2/trail3 LONG-ONLY", dict(entry_tf="H1", donchian=55, stop_atr=2.0,
                                                      trail_atr=3.0, long_only=True)),
        ("H1 Donchian55/stop2/trail3 LONG+SHORT", dict(entry_tf="H1", donchian=55, stop_atr=2.0,
                                                       trail_atr=3.0)),
        ("D1 Donchian20/stop3/trail4 LONG-ONLY", dict(entry_tf="D1", donchian=20, stop_atr=3.0,
                                                      trail_atr=4.0, long_only=True)),
        ("D1 Donchian20/stop3/trail4 LONG+SHORT", dict(entry_tf="D1", donchian=20, stop_atr=3.0,
                                                       trail_atr=4.0)),
    ]
    summary = []
    per_year_all = {}
    for name, kw in systems:
        m, tr = run(hist, **kw)
        summary.append({"system": name, **{k: v for k, v in m.items()}})
        per_year_all[name] = year_table(tr)
        print(f"  {name:<42} CAGR {m.get('CAGR_pct', 0):>6}%  maxDD {m.get('max_dd_pct', 0):>7}%  "
              f"PF {m.get('profit_factor', 0):>5}  exp {m.get('expectancy_R', 0):>6}R  "
              f"trades {m.get('trades', 0):>4}  win% {m.get('win_rate', 0):>4}")

    summary_df = pd.DataFrame(summary)
    summary_df.to_csv(os.path.join(HERE, "out", "long_history_systems.csv"), index=False)

    # ---------------- 2. per-year detail for the headline system ----------------
    headline = "H4 Donchian20/stop2/trail3 LONG-ONLY"
    print(f"\n### PER-YEAR DETAIL: {headline}\n")
    print(per_year_all[headline].to_string(index=False))
    per_year_all[headline].to_csv(os.path.join(HERE, "out", "long_history_yearly.csv"), index=False)

    print(f"\n### PER-YEAR: the same system LONG+SHORT (why shorts hurt)\n")
    print(per_year_all["H4 Donchian20/stop2/trail3 LONG+SHORT"].to_string(index=False))

    # ---------------- 3. parameter sensitivity ----------------
    print("\n### PARAMETER SENSITIVITY (H4, long-only, full sample, CAGR%)\n")
    grid = {"donchian": [10, 20, 30, 40, 55, 80], "trail_atr": [2.0, 3.0, 4.0, 5.0]}
    sens = pd.DataFrame(index=grid["donchian"], columns=grid["trail_atr"], dtype=float)
    for d, tr_ in itertools.product(grid["donchian"], grid["trail_atr"]):
        m, _ = run(hist, entry_tf="H4", donchian=d, stop_atr=2.0, trail_atr=tr_, long_only=True)
        sens.loc[d, tr_] = m.get("CAGR_pct", np.nan)
    print(sens.to_string())
    sens.to_csv(os.path.join(HERE, "out", "long_history_sensitivity.csv"))

    # ---------------- 4. walk-forward ----------------
    print("\n### WALK-FORWARD (params chosen on prior 4y only, then traded out-of-sample)\n")
    wf_grid = {"donchian": [20, 30, 40, 55], "trail_atr": [2.0, 3.0, 4.0]}
    wf = walk_forward(hist, wf_grid, train_years=4, start_year=2009, entry_tf="H4", long_only=True)
    print(wf.to_string(index=False))
    if not wf.empty:
        oos_return = (1 + wf["test_return_%"] / 100).prod() - 1
        yrs = len(wf)
        print(f"\n  OOS aggregate: {oos_return*100:.1f}% over {yrs} years "
              f"({((1+oos_return)**(1/yrs)-1)*100:.1f}% CAGR) | "
              f"positive years {int((wf['test_return_%'] > 0).sum())}/{yrs} | "
              f"worst year {wf['test_return_%'].min():.1f}% | "
              f"worst DD {wf['test_maxDD_%'].min():.1f}%")
        wf.to_csv(os.path.join(HERE, "out", "long_history_walkforward.csv"), index=False)

        # out-of-sample equity curve
        eq, curve = 5000.0, []
        for _, r in wf.iterrows():
            eq *= (1 + r["test_return_%"] / 100)
            curve.append((int(r["year"]), round(eq, 2)))
        print("  OOS equity:", ", ".join(f"{y}:${e:,.0f}" for y, e in curve))

    print(f"\nOutputs -> {os.path.join(HERE, 'out')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
