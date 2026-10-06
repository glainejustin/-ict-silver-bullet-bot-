"""
Does market-map context improve the SHIPPING trend system's P&L?

research/map_validation.py tested whether map levels predict price. This tests
the question that actually matters: if you use map context to filter the
validated H4 Donchian system, does expectancy improve -- or is any apparent
improvement just the ordinary variance you get from splitting 582 trades in two?

Method
------
1. Run the shipping configuration (H4 Donchian55, 2xATR stop, 4xATR trail,
   long-only) over 21.3 years and collect every trade.
2. For each trade, compute map features from data STRICTLY BEFORE the entry:
     vol_pct        volume-at-price percentile of the entry price in the prior
                    20 sessions (0 = thin/LVN, 1 = heavy/HVN)
     pool_atr       distance to the nearest clustered swing high ABOVE entry,
                    in ATR units (overhead liquidity)
     va_position    entry vs the prior week's value area: above / inside / below
     poc_atr        distance from the prior session's POC, in ATR
     round_atr      distance to the nearest $10 multiple, in ATR
3. Split trades by each feature and measure expectancy, with a PERMUTATION NULL:
   shuffle the feature labels 2,000 times and record how large a difference
   appears by chance alone. A feature is only interesting if its observed
   difference beats 95-99% of the shuffled ones.

Without that permutation step, "the good half of my trades averaged +0.5R and
the bad half -0.2R" sounds like an edge. With 582 trades it usually isn't.

Usage: python research/map_filter_test.py [n_perm]
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from research import long_history as lh                      # noqa: E402
from research import shipping_config                         # noqa: E402
from research.gold_edge import CONTRACT, TrendSim            # noqa: E402
from core.market_map import volume_profile, swing_points, cluster_levels  # noqa: E402

OUT = os.path.join(HERE, "out")
# parameters straight from config.py, so this measures the SHIPPING system
SHIPPING = shipping_config.trend_kwargs()
LOOKBACK_BARS = 2000        # ~20 trading sessions of M15
MIN_BARS = 600
RNG = np.random.default_rng(11)


# --------------------------------------------------------------------------
# map features, computed backwards from each entry
# --------------------------------------------------------------------------
def _prior_window(m15: pd.DataFrame, ts: pd.Timestamp, bars: int = LOOKBACK_BARS
                  ) -> pd.DataFrame:
    """
    The `bars` M15 bars immediately before ts.

    Counted in BARS, not calendar days: this dataset has real holes (2025 is
    missing ~80 days), and a calendar window silently returns nothing inside a
    gap, which is how half the trades ended up unusable in the first version.
    """
    pos = m15.index.searchsorted(ts, side="left")
    if pos <= 0:
        return m15.iloc[0:0]
    return m15.iloc[max(0, pos - bars):pos]


def features_for_trade(m15: pd.DataFrame, ts: pd.Timestamp, entry: float,
                       atr: float) -> dict:
    hist = _prior_window(m15, ts)
    out = {"vol_pct": np.nan, "pool_atr": np.nan, "poc_atr": np.nan,
           "va_position": "unknown", "round_atr": np.nan}
    if len(hist) < MIN_BARS or not np.isfinite(atr) or atr <= 0:
        return out

    # --- volume-at-price percentile at the entry price
    try:
        prof = volume_profile(hist, bins=60)
    except ValueError:
        return out
    centres = prof.centres
    i = int(np.clip(np.searchsorted(centres, entry), 0, len(centres) - 1))
    out["vol_pct"] = float((prof.volume < prof.volume[i]).mean())

    # --- nearest clustered swing high above the entry
    hi_idx, _ = swing_points(hist, 3, 3)
    if hi_idx.size >= 2:
        pools = cluster_levels(hist["high"].to_numpy(float)[hi_idx], 0.15 * atr)
        above = [p["price"] for p in pools if p["price"] > entry]
        if above:
            out["pool_atr"] = float((min(above) - entry) / atr)

    # --- prior session POC and prior week value area
    days = sorted({d for d in hist.index.date})
    if days:
        last_day = hist[hist.index.date == days[-1]]
        if len(last_day) >= 20:
            try:
                p = volume_profile(last_day, bins=50)
                out["poc_atr"] = float(abs(entry - p.poc) / atr)
                if len(days) >= 6:
                    week = hist[hist.index.date >= days[-6]]
                    try:
                        pw = volume_profile(week, bins=50)
                        if entry > pw.vah:
                            out["va_position"] = "above_value"
                        elif entry < pw.val:
                            out["va_position"] = "below_value"
                        else:
                            out["va_position"] = "inside_value"
                    except ValueError:
                        pass
            except ValueError:
                pass

    # --- distance to the nearest $10 level
    lvl = round(entry / 10.0) * 10.0
    out["round_atr"] = float(abs(entry - lvl) / atr)
    return out


def collect_trades(hist) -> tuple[pd.DataFrame, dict]:
    sim = TrendSim(balance=5000.0, risk_pct=0.5)
    metrics = sim.run(hist, **SHIPPING)
    print(f"  shipping = {shipping_config.description()}")
    trades = pd.DataFrame(sim.trades)
    if trades.empty:
        return trades, metrics

    m15 = hist["M15"]
    h4 = hist["H4"]
    # ATR on the signal bar (the bar whose close triggered the entry)
    high, low, close = (h4[c].to_numpy(float) for c in ("high", "low", "close"))
    prev = np.concatenate([[np.nan], close[:-1]])
    tr = np.nanmax(np.vstack([high - low, np.abs(high - prev), np.abs(low - prev)]), axis=0)
    atr_series = pd.Series(tr, index=h4.index).rolling(SHIPPING["atr_period"]).mean()

    rows = []
    for t in trades.itertuples():
        ts = pd.Timestamp(t.entry_time)
        # signal bar = the H4 bar that closed immediately before entry
        pos = h4.index.searchsorted(ts, side="left") - 1
        atr = float(atr_series.iloc[pos]) if 0 <= pos < len(atr_series) else np.nan
        f = features_for_trade(m15, ts, float(t.entry), atr)
        rows.append({"entry_time": ts, "entry": t.entry, "exit_time": t.exit_time,
                     "r": t.r, "pnl": t.pnl, "atr": atr, **f})
    return pd.DataFrame(rows), metrics


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------
def split_stats(df: pd.DataFrame, mask: np.ndarray, n_perm: int) -> dict:
    """
    Expectancy of the selected subset vs the rest, with a permutation p-value.

    The p-value answers: how often does a random subset of the same SIZE produce
    a difference at least this large? That is the only honest bar for a
    subset-selection result.
    """
    a = df.loc[mask, "r"].to_numpy()
    b = df.loc[~mask, "r"].to_numpy()
    if len(a) < 10 or len(b) < 10:
        return {"n": len(a), "diff": np.nan, "p_perm": np.nan,
                "exp_in": a.mean() if len(a) else np.nan,
                "exp_out": b.mean() if len(b) else np.nan}
    observed = a.mean() - b.mean()
    r_all = df["r"].to_numpy()
    n_a = len(a)
    hits = 0
    for _ in range(n_perm):
        idx = RNG.permutation(len(r_all))[:n_a]
        m = np.zeros(len(r_all), dtype=bool)
        m[idx] = True
        d = r_all[m].mean() - r_all[~m].mean()
        if abs(d) >= abs(observed):
            hits += 1
    return {"n": n_a, "n_out": len(b), "exp_in": float(a.mean()),
            "exp_out": float(b.mean()), "diff": float(observed),
            "p_perm": (hits + 1) / (n_perm + 1),
            "se": float(np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)))}


def net_effect(df: pd.DataFrame, mask: np.ndarray, label: str) -> dict:
    """What the filter does to the account, not just to expectancy."""
    kept = df.loc[mask]
    if len(kept) < 10:
        return {"filter": label, "kept": len(kept)}
    # compounding only the kept trades (0.5% risk, $5k start)
    eq = 5000.0
    curve = [eq]
    for r in kept["r"]:
        eq *= (1 + 0.005 * r)
        curve.append(eq)
    curve = np.array(curve)
    dd = float((curve / np.maximum.accumulate(curve) - 1).min() * 100)
    return {"filter": label, "kept": len(kept),
            "kept_%": round(100 * len(kept) / len(df), 1),
            "expectancy_R": round(float(kept["r"].mean()), 3),
            "total_return_%": round((eq / 5000.0 - 1) * 100, 1),
            "max_dd_%": round(dd, 2)}


def main() -> int:
    n_perm = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    os.makedirs(OUT, exist_ok=True)
    print("loading 21-year history ...")
    hist = lh.load_long_history()
    print(f"  M15 bars {len(hist['M15']):,}")

    print("running the shipping system to collect trades ...")
    trades, metrics = collect_trades(hist)
    print(f"  trades: {len(trades)}   expectancy {metrics.get('expectancy_R')}R   "
          f"PF {metrics.get('profit_factor')}   maxDD {metrics.get('max_dd_pct')}%")
    trades.to_csv(os.path.join(OUT, "map_filter_trades.csv"), index=False)

    usable = trades.dropna(subset=["vol_pct", "pool_atr"]).copy()
    print(f"  usable for feature analysis: {len(usable)} "
          f"(need 20 sessions of prior data)\n")

    results = []

    # --- feature 1: volume-at-price percentile (HVN vs LVN) ---------------
    lo_t, hi_t = usable["vol_pct"].quantile([1 / 3, 2 / 3])
    for name, mask in (("entry in LVN (bottom third of volume-at-price)",
                        (usable["vol_pct"] <= lo_t).to_numpy()),
                       ("entry in HVN (top third of volume-at-price)",
                        (usable["vol_pct"] >= hi_t).to_numpy())):
        st = split_stats(usable, mask, n_perm)
        results.append({"feature": name, **st})
        results.append({"feature": name + " [account effect]",
                        **net_effect(usable, mask, name)})

    # --- feature 2: overhead liquidity (a pool just above entry) ----------
    pool_med = usable["pool_atr"].median()
    for name, mask in (("no pool within %.2f ATR overhead" % pool_med,
                        (usable["pool_atr"] > pool_med).to_numpy()),
                       ("pool within %.2f ATR overhead" % pool_med,
                        (usable["pool_atr"] <= pool_med).to_numpy())):
        results.append({"feature": name, **split_stats(usable, mask, n_perm)})

    # --- feature 3: position vs the prior week's value area ---------------
    for cat in ("above_value", "inside_value"):
        mask = (usable["va_position"] == cat).to_numpy()
        if mask.sum() >= 10:
            results.append({"feature": f"entry {cat.replace('_', ' ')}",
                            **split_stats(usable, mask, n_perm)})

    # --- feature 4: distance from the prior session POC -------------------
    poc_med = usable["poc_atr"].median()
    results.append({"feature": f"far from prior POC (>{poc_med:.2f} ATR)",
                    **split_stats(usable, (usable["poc_atr"] > poc_med).to_numpy(), n_perm)})

    # --- feature 5: round-number proximity --------------------------------
    rnd_med = usable["round_atr"].median()
    results.append({"feature": f"near a round $10 level (<{rnd_med:.2f} ATR)",
                    **split_stats(usable, (usable["round_atr"] < rnd_med).to_numpy(), n_perm)})

    base = net_effect(usable, np.ones(len(usable), dtype=bool), "NO FILTER (all usable trades)")
    res = pd.DataFrame(results)
    res.to_csv(os.path.join(OUT, "map_filter_results.csv"), index=False)

    # ---- report
    n_tests = len([r for r in results if "p_perm" in r and np.isfinite(r.get("p_perm", np.nan))])
    lines = ["Market-map CONTEXT FILTERS applied to the shipping trend system",
             "=" * 78,
             f"Base system: H4 Donchian55 / 2xATR stop / 4xATR trail, long-only,",
             f"0.5% risk, 21.3 years. Trades: {len(trades)} "
             f"({len(usable)} with enough prior map history).",
             f"Base expectancy: {metrics.get('expectancy_R')}R   "
             f"PF {metrics.get('profit_factor')}   maxDD {metrics.get('max_dd_pct')}%",
             "",
             f"p_perm = probability that a RANDOM subset of the same size differs by",
             f"at least this much ({n_perm:,} shuffles). Bonferroni threshold for",
             f"{n_tests} tests at 5% is p < {0.05 / max(1, n_tests):.4f}.",
             "",
             f"BASELINE (no filter, same {base['kept']} usable trades): "
             f"expectancy {base['expectancy_R']}R, compounded return "
             f"{base['total_return_%']}%, maxDD {base['max_dd_%']}%",
             "-" * 78]
    for r in results:
        if r.get("filter", "").startswith("NO FILTER"):
            continue
        if "kept" in r and "expectancy_R" in r:
            lines.append(f"[account] {r['filter']}")
            lines.append(f"    keeps {r['kept']} trades ({r['kept_%']}%)  "
                         f"expectancy {r['expectancy_R']}R  "
                         f"compounded return {r['total_return_%']}%  "
                         f"maxDD {r['max_dd_%']}%")
            continue
        lines.append(f"{r['feature']}")
        if not np.isfinite(r.get("p_perm", np.nan)):
            lines.append("    not enough trades on one side\n"); continue
        lines.append(f"    n={int(r['n'])} vs {int(r['n_out'])}   "
                     f"expectancy in-selection {r['exp_in']:+.3f}R vs "
                     f"{r['exp_out']:+.3f}R elsewhere")
        lines.append(f"    difference {r['diff']:+.3f}R  (SE {r['se']:.3f})   "
                     f"p_perm = {r['p_perm']:.3f}"
                     f"{'   <-- survives shuffle test' if r['p_perm'] < 0.05 else ''}")
        lines.append("")
    txt = "\n".join(lines)
    with open(os.path.join(OUT, "map_filter_results.txt"), "w") as fh:
        fh.write(txt)
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
