"""
Do market-map levels actually carry information?

Every test compares a map-derived level against a distance-matched control level
observed in the same session, because "price reacted at the level" is meaningless
without knowing how often price reacts at *any* level that far away.

Tests
-----
A  POC magnet        - is the prior session's POC reached more often than a
                       control level the same distance away on the other side?
B  Value-area edges  - after the first touch of prior VAH/VAL, does price move
                       >=0.5 ATR (either way) more often than at control levels
                       0.25 and 0.5 ATR away from the same edge?
C  Liquidity pools   - are clustered swing highs swept more often than
                       distance-matched control levels, and after a sweep does
                       price reverse (stop run) or continue (breakout)?
D  HVN vs LVN        - do bars travel faster through low-volume nodes, holding
                       distance-from-POC constant?
E  Round numbers     - are $10 multiples reached more often than controls?

Run: python research/map_validation.py [n_sessions]
Out: research/out/map_validation.csv, research/out/map_validation.txt
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.market_map import volume_profile, cluster_levels, swing_points  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RNG = np.random.default_rng(7)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval -> (p, lo, hi)."""
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, centre - half), min(1.0, centre + half)


class DayIndex:
    """
    O(1) per-session slicing.

    Filtering `df[df.index.date == day]` inside a session loop re-scans the whole
    frame on every iteration -- on 480k bars that is billions of comparisons and
    the run never finishes. Precompute the slice boundaries once instead.
    """

    def __init__(self, df: pd.DataFrame):
        self.df = df
        codes = df.index.to_numpy().astype("datetime64[D]")
        self.days, start = np.unique(codes, return_index=True)
        self.start = start
        self.end = np.append(start[1:], len(df))
        self.high = df["high"].to_numpy(float)
        self.low = df["low"].to_numpy(float)
        self.close = df["close"].to_numpy(float)
        self.rng_bar = self.high - self.low
        self.atr = np.array([
            self.rng_bar[s:e].mean() if e > s else np.nan
            for s, e in zip(self.start, self.end)
        ])

    def __len__(self) -> int:
        return len(self.days)

    def frame(self, i: int) -> pd.DataFrame:
        return self.df.iloc[self.start[i]:self.end[i]]

    def hlc(self, i: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        s, e = self.start[i], self.end[i]
        return self.high[s:e], self.low[s:e], self.close[s:e]


def session_stats(di: DayIndex) -> pd.DataFrame:
    """Per-session POC / VAH / VAL / range from each session's own profile."""
    rows = []
    for i in range(len(di)):
        sub = di.frame(i)
        if len(sub) < 20:
            continue
        try:
            prof = volume_profile(sub, bins=50)
        except ValueError:
            continue
        if not (sub["low"].min() <= prof.poc <= sub["high"].max()):
            continue
        rows.append({"poc": prof.poc, "vah": prof.vah, "val": prof.val,
                     "high": float(sub["high"].max()), "low": float(sub["low"].min()),
                     "close": float(sub["close"].iloc[-1]), "bars": len(sub),
                     "volume": prof.total_volume})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# Shared machinery
#
# Two designs are used, because the naive "did price reach the level?" test is
# degenerate: with a level 1 ATR away and an 8-hour window, EVERYTHING is
# reached and level and control both score 1.000.
#
#  * RACE  - from the entry bar, is the level (distance d) reached before an
#            equal move d in the opposite direction? Distances are symmetric, so
#            under a random walk the two outcomes are 50/50 and any edge shows
#            up as a deviation. The mirrored level is raced in the same session,
#            which absorbs drift.
#  * EVENT STUDY - after the first touch of a level, the signed forward return
#            over k bars, in ATR units, oriented so positive = continuation
#            through the level and negative = rejection.
# --------------------------------------------------------------------------
def _race(high: np.ndarray, low: np.ndarray, e: int, up_at: float, down_at: float,
          horizon: int) -> str:
    """Which barrier is hit first after bar e: 'up', 'down', 'tie' or 'none'."""
    h = high[e + 1:e + 1 + horizon]
    l = low[e + 1:e + 1 + horizon]
    u = np.flatnonzero(h >= up_at)
    d = np.flatnonzero(l <= down_at)
    if u.size == 0 and d.size == 0:
        return "none"
    iu = int(u[0]) if u.size else 10**9
    idn = int(d[0]) if d.size else 10**9
    if iu == idn:
        return "tie"
    return "up" if iu < idn else "down"


def test_poc_magnet(di: DayIndex, stats: pd.DataFrame, horizon: int = 64,
                    min_dist_atr: float = 0.5) -> dict:
    """
    From bars where the prior session's POC sits >= 0.5 ATR away, race "reach the
    POC" against "move the same distance further away", and race the mirrored
    level in the same session as the control. Races do not overlap.
    """
    counts = {"poc": 0, "mirror": 0, "tie": 0, "none": 0, "n": 0,
              # subset where BOTH barriers sit inside the prior session's range:
              # there the range boundary cannot explain the result, so this is
              # the clean test of whether the POC itself attracts price.
              "in_n": 0, "in_poc": 0,
              # era split: an effect that only lives in the 2004-2015 gold market
              # is not something you can trade today
              "era": {}}

    def _era(di, i) -> str:
        y = pd.Timestamp(di.days[i]).year
        return "2004-2015" if y < 2016 else "2016-2025"

    def _one_race(h, l, c, e, poc, d, horizon, prior_lo, prior_hi, era):
        up_at, down_at = c[e] + d, c[e] - d
        r = _race(h, l, e, up_at, down_at, horizon)
        poc_dir = "up" if poc >= c[e] else "down"
        mirror_dir = "down" if poc_dir == "up" else "up"
        if r == "tie":
            counts["tie"] += 1
        elif r == "none":
            counts["none"] += 1
        else:
            counts["n"] += 1
            counts["poc"] += (r == poc_dir)
            counts["mirror"] += (r == mirror_dir)
            ec = counts["era"].setdefault(era, [0, 0])
            ec[0] += 1; ec[1] += (r == poc_dir)
            both_in = (prior_lo <= up_at <= prior_hi and prior_lo <= down_at <= prior_hi)
            if both_in:
                counts["in_n"] += 1
                counts["in_poc"] += (r == poc_dir)

    for i in range(1, min(len(stats), len(di))):
        h, l, c = di.hlc(i)
        if len(h) < horizon + 2 or not np.isfinite(di.atr[i]) or di.atr[i] <= 0:
            continue
        atr = di.atr[i]
        poc = float(stats["poc"].iloc[i - 1])
        dist = np.abs(c - poc) / atr
        cand = np.flatnonzero(dist >= min_dist_atr)
        if cand.size == 0:
            continue
        # walk forward taking NON-OVERLAPPING races: after one resolves (or its
        # window expires) look for the next bar that clears the distance filter
        e = int(cand[0])
        while e + horizon < len(h):
            d = abs(c[e] - poc)
            _one_race(h, l, c, e, poc, d, horizon,
                      float(stats["low"].iloc[i - 1]), float(stats["high"].iloc[i - 1]),
                      _era(di, i))
            e = e + horizon
            nxt = np.flatnonzero(cand > e)
            if nxt.size == 0:
                break
            e = int(cand[nxt[0]])
        continue
    n = counts["n"]
    detail = f"races with >= {min_dist_atr} ATR of clearance, {horizon} bars to " \
             f"resolve; {counts['tie']} ties and {counts['none']} unresolved excluded"
    if counts["in_n"]:
        detail += (f". RANGE-BOUNDARY CONTROL: when both barriers sit inside the "
                   f"prior session range the POC is hit first "
                   f"{counts['in_poc'] / counts['in_n']:.1%} of the time "
                   f"(n={counts['in_n']})")
    if counts["era"]:
        detail += " | by era: " + ", ".join(
            f"{k} {v[1] / v[0]:.1%} (n={v[0]})"
            for k, v in sorted(counts["era"].items()))
    p1, l1, h1 = wilson(counts["poc"], n)
    p2, l2, h2 = wilson(counts["mirror"], n)
    return {"test": "A. POC reached before an equal move away", "n": n,
            "p_level": p1, "p_level_lo": l1, "p_level_hi": h1,
            "p_control": p2, "p_ctl_lo": l2, "p_ctl_hi": h2, "delta": p1 - p2,
            "detail": detail}


def test_value_area(di: DayIndex, stats: pd.DataFrame, horizon: int = 16) -> dict:
    """Signed forward return after the first touch of a prior-session VA edge."""
    lvl_ret, ctl_ret = [], []
    for i in range(1, min(len(stats), len(di))):
        h, l, c = di.hlc(i)
        if len(h) < horizon + 2 or not np.isfinite(di.atr[i]) or di.atr[i] <= 0:
            continue
        atr = di.atr[i]
        for kind in ("vah", "val"):
            lvl = float(stats[kind].iloc[i - 1])
            lvl_ret += _event_returns(h, l, c, lvl, atr, horizon)
            for off in (0.5, -0.5):
                ctl_ret += _event_returns(h, l, c, lvl + off * atr, atr, horizon)
    return _summarise("B. VA edge: forward return after first touch", lvl_ret, ctl_ret,
                      "positive = price continued through the edge, negative = it "
                      "rejected; control = edges +/-0.5 ATR")


def _event_returns(h, l, c, level: float, atr: float, horizon: int) -> list[float]:
    """Signed return after the first touch, +ve = continuation through the level."""
    t = np.flatnonzero((h >= level) & (l <= level))
    if t.size == 0:
        return []
    e = int(t[0])
    if e + horizon >= len(h) or e < 1:
        return []
    approached_from_below = c[e] < level
    fwd = (c[e + horizon] - c[e]) / atr
    return [fwd if approached_from_below else -fwd]


def test_pools(di: DayIndex, lookback: int = 30, horizon: int = 16) -> dict:
    """Same event study, but the levels are clustered swing highs (pools)."""
    pool_ret, ctl_ret = [], []
    n_sessions = 0
    for i in range(lookback, len(di)):
        h, l, c = di.hlc(i)
        if len(h) < horizon + 2 or not np.isfinite(di.atr[i]) or di.atr[i] <= 0:
            continue
        atr = di.atr[i]
        hist = di.df.iloc[di.start[i - lookback]:di.start[i]]
        if len(hist) < 200:
            continue
        hi_idx, _ = swing_points(hist, 3, 3)
        if hi_idx.size < 2:
            continue
        pools = cluster_levels(hist["high"].to_numpy(float)[hi_idx], 0.15 * atr)
        if not pools:
            continue
        n_sessions += 1
        dists = []
        for p in pools:
            lvl = float(p["price"])
            r = _event_returns(h, l, c, lvl, atr, horizon)
            if r:
                pool_ret += r
                dists.append(abs(lvl - float(c[0])) / atr)
        for d in (RNG.choice(dists, size=min(len(dists), 10), replace=False)
                  if dists else []):
            for sign in (1, -1):
                ctl_ret += _event_returns(h, l, c,
                                          float(c[0]) + sign * float(d) * atr, atr, horizon)
    out = _summarise("C. Swing-high pools: forward return after first touch",
                     pool_ret, ctl_ret,
                     f"positive = continuation (breakout), negative = rejection "
                     f"(stop run); control = distance-matched random levels "
                     f"({n_sessions} sessions)")
    return out


def _summarise(name: str, lvl: list[float], ctl: list[float], detail: str) -> dict:
    if not lvl:
        return {"test": name, "n": 0, "detail": "no events"}
    a = np.asarray(lvl, dtype=float); b = np.asarray(ctl, dtype=float)
    p1, l1, h1 = wilson(int((a > 0).sum()), len(a))
    if len(b):
        p2, l2, h2 = wilson(int((b > 0).sum()), len(b))
    else:
        p2 = l2 = h2 = float("nan")
    t = a.mean() / (a.std(ddof=1) / np.sqrt(len(a))) if len(a) > 2 else float("nan")
    return {"test": name, "n": len(a),
            "p_level": float(a.mean()), "p_level_lo": float(a.mean() - 1.96 * a.std(ddof=1) / max(1, np.sqrt(len(a)))),
            "p_level_hi": float(a.mean() + 1.96 * a.std(ddof=1) / max(1, np.sqrt(len(a)))),
            "p_control": float(b.mean()) if len(b) else float("nan"),
            "p_ctl_lo": float(b.mean() - 1.96 * b.std(ddof=1) / max(1, np.sqrt(len(b)))) if len(b) > 2 else float("nan"),
            "p_ctl_hi": float(b.mean() + 1.96 * b.std(ddof=1) / max(1, np.sqrt(len(b)))) if len(b) > 2 else float("nan"),
            "delta": float(a.mean() - b.mean()) if len(b) else float("nan"),
            "detail": f"{detail}; P(continuation) = {p1:.3f} [{l1:.3f},{h1:.3f}], "
                      f"t = {t:+.2f} on the mean"}


def test_nodes(di: DayIndex, stats: pd.DataFrame) -> dict:
    """Do bars travel faster through low-volume nodes? Distance-banded control."""
    rngs, vols, dists = [], [], []
    n_used = 0
    for i in range(1, min(len(stats), len(di))):
        h, l, _ = di.hlc(i)
        if len(h) < 20:
            continue
        row = stats.iloc[i - 1]
        poc, hi, lo = float(row.poc), float(row.high), float(row.low)
        if hi <= lo:
            continue
        mid = (h + l) / 2.0
        inside = (mid >= lo) & (mid <= hi)
        if inside.sum() < 10:
            continue
        try:
            prof = volume_profile(di.frame(i - 1), bins=50)
        except ValueError:
            continue
        idx = np.clip(np.searchsorted(prof.centres, mid), 0, len(prof.centres) - 1)
        prev_atr = di.atr[i - 1] if np.isfinite(di.atr[i - 1]) and di.atr[i - 1] > 0 else np.nan
        if not np.isfinite(prev_atr):
            continue
        if n_used < 500:
            rngs.append((h - l)[inside] / prev_atr); vols.append(prof.volume[idx][inside])
            dists.append(np.abs(mid - poc)[inside] / (hi - lo))
            n_used += 1
    if not rngs:
        return {"test": "D. HVN vs LVN speed", "n": 0}
    allr = pd.DataFrame({"range": np.concatenate(rngs),
                         "vol_at": np.concatenate(vols),
                         "dist": np.concatenate(dists)})
    allr["vol_tercile"] = pd.qcut(allr["vol_at"], 3, labels=["LVN", "mid", "HVN"])
    allr["dist_band"] = pd.qcut(allr["dist"], 5, labels=False, duplicates="drop")
    piv = allr.groupby(["dist_band", "vol_tercile"], observed=True)["range"].mean().unstack()
    diffs, weights = [], []
    for band, row in piv.iterrows():
        if pd.notna(row.get("LVN")) and pd.notna(row.get("HVN")):
            diffs.append(row["LVN"] - row["HVN"])
            weights.append(int(((allr.dist_band == band) &
                                (allr.vol_tercile == "LVN")).sum()))
    matched = float(np.average(diffs, weights=weights)) if diffs else float("nan")
    a = allr.loc[allr.vol_tercile == "LVN", "range"].to_numpy()
    b = allr.loc[allr.vol_tercile == "HVN", "range"].to_numpy()
    se = float(np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)))
    return {"test": "D. bar range: LVN minus HVN (distance-banded, ATR-normalised)",
            "n": len(allr),
            "p_level": matched, "p_level_lo": matched - 1.96 * se,
            "p_level_hi": matched + 1.96 * se,
            "p_control": float(a.mean() - b.mean()),
            "p_ctl_lo": float("nan"), "p_ctl_hi": float("nan"),
            "delta": matched,
            "detail": f"LVN bars average {a.mean():.3f}x the previous session's mean "
                      f"bar range vs {b.mean():.3f}x in HVN; positive = faster travel "
                      f"through low-volume nodes"}


def test_round_numbers(di: DayIndex, stats: pd.DataFrame, horizon: int = 64,
                       min_dist_atr: float = 0.5) -> dict:
    """Race to the nearest $10 level vs an equal move away (no mirror needed: the
    control is the other barrier of the same race)."""
    lvl_first = away_first = ties = none = n = 0
    for i in range(1, min(len(stats), len(di))):
        h, l, c = di.hlc(i)
        if len(h) < horizon + 2 or not np.isfinite(di.atr[i]) or di.atr[i] <= 0:
            continue
        atr = di.atr[i]
        e = 0
        while e + horizon < len(h):
            lvl = float(np.round(c[e] / 10.0) * 10.0)
            d = abs(c[e] - lvl)
            if d / atr < min_dist_atr:
                e += 1
                continue
            up_at, down_at = c[e] + d, c[e] - d
            r = _race(h, l, e, up_at, down_at, horizon)
            lvl_dir = "up" if lvl >= c[e] else "down"
            if r == "tie":
                ties += 1
            elif r == "none":
                none += 1
            else:
                n += 1
                hit_lvl = (r == lvl_dir)
                lvl_first += hit_lvl
                away_first += (not hit_lvl)
            e += horizon
    p1, l1, h1 = wilson(lvl_first, n)
    p2, l2, h2 = wilson(away_first, n)
    return {"test": "E. Round $10 level reached before an equal move away", "n": n,
            "p_level": p1, "p_level_lo": l1, "p_level_hi": h1,
            "p_control": p2, "p_ctl_lo": l2, "p_ctl_hi": h2, "delta": p1 - p2,
            "detail": f"measured from the session open with >= {min_dist_atr} ATR "
                      f"of clearance; {ties} ties, {none} unresolved excluded"}


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    path = os.path.join(DATA, "XAUUSD_M15_2004_2025.parquet")
    df = pd.read_parquet(path)[["open", "high", "low", "close", "volume"]].dropna()
    if limit:
        keep = sorted(set(df.index.date))[-limit:]
        df = df[pd.Index(df.index.date).isin(keep)]
    di = DayIndex(df)
    print(f"M15 bars: {len(df):,}  {df.index[0].date()} -> {df.index[-1].date()}  "
          f"sessions: {len(di):,}")
    t0 = time.time()
    stats = session_stats(di)
    print(f"session profiles: {len(stats):,} in {time.time()-t0:.1f}s")

    results = []
    for name, fn in (("A POC magnet", lambda: test_poc_magnet(di, stats)),
                     ("B VA edges", lambda: test_value_area(di, stats)),
                     ("C pools", lambda: test_pools(di)),
                     ("D HVN/LVN", lambda: test_nodes(di, stats)),
                     ("E round numbers", lambda: test_round_numbers(di, stats))):
        t = time.time()
        try:
            results.append(fn())
        except Exception as exc:                              # noqa: BLE001
            results.append({"test": name, "n": 0, "detail": f"ERROR {type(exc).__name__}: {exc}"})
        print(f"  {name:16s} {time.time()-t:6.1f}s")

    res = pd.DataFrame(results)
    res.to_csv(os.path.join(OUT, "map_validation.csv"), index=False)

    lines = ["Market-map level validation - XAUUSD M15, 21.3 years",
             "=" * 78,
             "Each test compares a map level against a distance-matched control",
             "level observed in the same session, so 'price reacted' is judged",
             "against how often price reacts at ANY level that far away.",
             ""]
    for r in results:
        lines.append(f"{r['test']}")
        n = r.get("n") or 0
        if not n:
            lines.append(f"   no usable sample. {r.get('detail','')}\n"); continue
        lines.append(f"   n = {n:,}")
        if np.isfinite(r.get("p_level_lo", float("nan"))):
            lines.append(f"   map level : {r['p_level']:.4f} "
                         f"[{r['p_level_lo']:.4f}, {r['p_level_hi']:.4f}]")
            lines.append(f"   control   : {r['p_control']:.4f} "
                         f"[{r['p_ctl_lo']:.4f}, {r['p_ctl_hi']:.4f}]")
            lo = r["p_level_lo"] - r["p_ctl_hi"]; hi = r["p_level_hi"] - r["p_ctl_lo"]
            if not np.isfinite(lo) or not np.isfinite(hi):
                # no usable control CI: judge the level's own interval against zero
                verdict = ("differs from zero" if (r["p_level_lo"] > 0 or
                                                   r["p_level_hi"] < 0)
                           else "not distinguishable from zero")
                lines.append(f"   difference: {r['delta']:+.4f}   -> {verdict}")
            else:
                verdict = "SIGNIFICANT" if (lo > 0 or hi < 0) else "not distinguishable"
                lines.append(f"   difference: {r['delta']:+.4f}   95% CI "
                             f"[{lo:+.4f}, {hi:+.4f}]  -> {verdict}")
        else:
            lines.append(f"   map  : {r['p_level']:+.4f}")
            lines.append(f"   ctrl : {r['p_control']:+.4f}")
        if r.get("detail"):
            lines.append(f"   {r['detail']}")
        lines.append("")
    txt = "\n".join(lines)
    with open(os.path.join(OUT, "map_validation.txt"), "w") as fh:
        fh.write(txt)
    print("\n" + txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
