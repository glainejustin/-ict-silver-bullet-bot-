"""
Refined edge testing: separate DIRECTIONAL SKILL from COST DRAG.

THE METHODOLOGY PROBLEM
-----------------------
A naive backtest mixes three completely different effects:
  1. directional skill      - does the signal predict where price goes?
  2. barrier geometry       - paying the spread shifts your TP further and your
                              SL closer, which costs win-rate even with zero skill
  3. explicit costs         - commission and slippage

To measure (1) alone we compare every strategy against a MATCHED NULL MODEL:
the exact same entry timestamps and stop sizes, but with RANDOM direction.
Both arms pay identical costs. Any difference is genuine directional skill.

This is the only honest way to answer "does this strategy work?" -- otherwise a
strategy can look profitable simply because it trades when volatility (and hence
stop size) is large, or lose simply because it trades too often for the spread.

Usage:
    python research/edge_test.py
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from research import xau_data  # noqa: E402

POINT = 0.01
CONTRACT = 100.0


# --------------------------------------------------------------- cost-aware R ---
@dataclass
class Costs:
    spread_points: float = 25.0
    slippage_points: float = 2.0
    commission_per_lot: float = 7.0

    def fee_price(self) -> float:
        return (self.spread_points + 2 * self.slippage_points) * POINT

    def fee_in_r(self, risk: np.ndarray) -> np.ndarray:
        return (self.fee_price() + self.commission_per_lot / CONTRACT) / risk


# ------------------------------------------------------------ path evaluation ---
class Evaluator:
    """
    Vectorised M1-path evaluator with adaptive chunking so that multi-day
    horizons on H1/H4 strategies stay inside memory.
    """

    BUDGET = 6_000_000  # elements per working array

    def __init__(self, bs: xau_data.BarSet, cost: Costs | None = None):
        self.m1 = bs["M1"]
        self.m1_high = self.m1["high"].to_numpy(float)
        self.m1_low = self.m1["low"].to_numpy(float)
        self.m1_close = self.m1["close"].to_numpy(float)
        self.m1_time = self.m1.index.values
        self.tfs = {tf: bs[tf] for tf in bs.frames}
        self.tf_start_m1 = {
            tf: np.searchsorted(self.m1_time, df.index.values, side="left")
            for tf, df in self.tfs.items()
        }
        self.cost = cost or Costs()

    # ---------------------------------------------------------------- helpers ---
    def tf_start(self, tf: str, bar_idx: np.ndarray) -> np.ndarray:
        return self.tf_start_m1[tf][bar_idx]

    def simulate(
        self,
        tf: str,
        bar_idx: np.ndarray,
        direction: np.ndarray,
        entry: np.ndarray,
        risk: np.ndarray,
        targets: tuple[float, ...] = (1.0, 2.0, 3.0),
        max_bars: int = 240,
        sl_price: np.ndarray | None = None,
        fill_from_next_bar: bool = True,
        limit_price: np.ndarray | None = None,
        fill_deadline: int = 24,
    ) -> pd.DataFrame:
        """
        Resolve trades on the M1 path.

        entry      : fill price (already spread-adjusted by the caller)
        risk       : 1R in price terms
        sl_price   : absolute stop; if None, entry - direction * risk
        limit_price: if given, the trade only exists once price trades through it
        """
        bar_idx = np.asarray(bar_idx)
        n = len(bar_idx)
        out = []

        chunk = max(1, int(self.BUDGET / max(max_bars, 1)))
        for s0 in range(0, n, chunk):
            sl_idx = slice(s0, s0 + chunk)
            bi = bar_idx[sl_idx]
            di = direction[sl_idx]
            ent = entry[sl_idx]
            rk = risk[sl_idx]
            sl = (ent - di * rk) if sl_price is None else sl_price[sl_idx]

            start_bar = bi + 1 if fill_from_next_bar else bi
            start = self.tf_start(tf, start_bar)
            m = len(bi)

            hi = np.full((m, max_bars), np.nan)
            lo = np.full((m, max_bars), np.nan)
            cl = np.full((m, max_bars), np.nan)
            for j, st in enumerate(start):
                en = min(st + max_bars, len(self.m1_high))
                L = max(en - st, 0)
                if L:
                    hi[j, :L] = self.m1_high[st:en]
                    lo[j, :L] = self.m1_low[st:en]
                    cl[j, :L] = self.m1_close[st:en]

            valid = np.isfinite(hi)
            idx = np.arange(max_bars)[None, :]

            filled = valid.any(axis=1)
            if limit_price is not None:
                lp = limit_price[sl_idx]
                touch = np.where(di[:, None] > 0, lo <= lp[:, None], hi >= lp[:, None])
                touch &= valid
                first = np.where(touch.any(axis=1), touch.argmax(axis=1), 10**9)
                filled = first < fill_deadline
                keep = (idx >= first[:, None]) & filled[:, None]
                hi = np.where(keep, hi, np.nan)
                lo = np.where(keep, lo, np.nan)
                cl = np.where(keep, cl, np.nan)
                # the fill bar itself: touch equals fill price, no extra excursion
                ent = np.where(filled, lp, ent)
                sl = ent - di * rk
                hi = np.where(idx == first[:, None], ent[:, None], hi)
                lo = np.where(idx == first[:, None], ent[:, None], lo)

            stop_hit = np.where(di[:, None] > 0, lo <= sl[:, None], hi >= sl[:, None]) & valid
            stop_idx = np.where(stop_hit.any(axis=1), stop_hit.argmax(axis=1), 10**9)

            fee_r = self.cost.fee_in_r(rk)
            rec = {"filled": filled, "risk": rk, "entry": ent, "direction": di}
            last_valid = np.where(valid, idx, -1).max(axis=1)
            end_close = np.take_along_axis(cl, last_valid[:, None], axis=1).ravel()

            for r in targets:
                tgt = ent + di * rk * r
                tgt_hit = np.where(di[:, None] > 0, hi >= tgt[:, None], lo <= tgt[:, None]) & valid
                tgt_idx = np.where(tgt_hit.any(axis=1), tgt_hit.argmax(axis=1), 10**9)
                won = tgt_idx < stop_idx
                mtm = di * (end_close - ent) / rk
                r_real = np.where(won, r, np.where(stop_idx < 10**9, -1.0, mtm))
                rec[f"r{r}"] = r_real - fee_r
                rec[f"won{r}"] = won & filled
            out.append(pd.DataFrame(rec))

        return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


# ------------------------------------------------------------------ strategies ---
class Features:
    """Causal feature set across timeframes (only closed bars)."""

    def __init__(self, bs: xau_data.BarSet, ev: Evaluator):
        self.bs, self.ev = bs, ev
        self.tf = {t: df for t, df in bs.frames.items()}

        def asof(tf: str, series: pd.Series) -> pd.Series:
            s = series.shift(1)  # only bars CLOSED before the current bar
            target = self.tf[tf].index
            return s.reindex(target)

        # --- M5 features ---
        m5 = self.tf["M5"]
        self.m5_series = {}

        def m5f(name, values):
            self.m5_series[name] = np.asarray(values, dtype=float)

        high = m5["high"].to_numpy(float)
        low = m5["low"].to_numpy(float)
        close = m5["close"].to_numpy(float)
        open_ = m5["open"].to_numpy(float)
        prev = np.concatenate([[np.nan], close[:-1]])
        tr = np.nanmax(np.vstack([high - low, np.abs(high - prev), np.abs(low - prev)]), axis=0)
        m5f("atr", pd.Series(tr).rolling(14).mean().to_numpy())
        m5f("ema20", pd.Series(close).ewm(span=20, adjust=False).mean().to_numpy())
        m5f("close", close)
        m5f("hour", m5["ny_hour"].to_numpy(float))

        # --- per-timeframe ATR + trend ---
        for tf in ("M15", "H1", "H4"):
            d = self.tf[tf]
            h, l, c = d["high"].to_numpy(float), d["low"].to_numpy(float), d["close"].to_numpy(float)
            pc = np.concatenate([[np.nan], c[:-1]])
            t = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
            d = d.copy()
            # NB: always pass the index explicitly -- assigning a Series built on a
            # RangeIndex to a DatetimeIndex frame silently produces all-NaN.
            d["atr"] = pd.Series(t, index=d.index).rolling(14).mean()
            d["sma50"] = d["close"].rolling(50).mean()
            d["sma200"] = d["close"].rolling(200).mean()
            self.tf[tf] = d

        # as-of joins onto the decision timeframe (M5)
        self.h1 = self.tf["H1"]
        self.h4 = self.tf["H4"]

    def join_tf(self, tf: str, col: str, target_index) -> np.ndarray:
        s = self.tf[tf][col].shift(1)
        return s.reindex(target_index, method="ffill").to_numpy(float)


def trend_family(bs, ev, f: Features, tf: str, entry_tf: str, trend_len: int,
                 stop_atr: float, target_r: float, hours=None, long_only=False,
                 breakout_lookback: int = 0) -> dict:
    """
    Long-horizon trend following:
      * trend filter: close above SMA(trend_len) on `tf`
      * trigger: close breaks the prior `breakout_lookback` highs/lows on entry_tf
      * stop: stop_atr x ATR(tf)  --> wide stops = tiny cost drag
    """
    d = f.tf[entry_tf]
    close = d["close"].to_numpy(float)
    atr_big = f.join_tf(tf, "atr", d.index)
    sma = f.join_tf(tf, f"sma{trend_len}", d.index) if f"sma{trend_len}" is not None else None
    if sma is None:
        sma = f.join_tf(tf, "sma50", d.index)

    if breakout_lookback:
        hh = d["high"].rolling(breakout_lookback).max().shift(1).to_numpy()
        ll = d["low"].rolling(breakout_lookback).min().shift(1).to_numpy()
        up = close > hh
        dn = close < ll
    else:
        pc = np.concatenate([[np.nan], close[:-1]])
        up = (pc <= sma) & (close > sma)
        dn = (pc >= sma) & (close < sma)
        up |= close > sma
        dn |= close < sma

    up &= close > sma
    dn &= close < sma
    if long_only:
        dn &= False
    if hours:
        h = d["ny_hour"].to_numpy(float)
        win = (h >= hours[0]) & (h < hours[1])
        up &= win
        dn &= win

    # one entry per leg: only fire on the first bar of each new streak
    def first_of_streak(mask):
        m = mask.astype(int)
        prev_m = np.concatenate([[0], m[:-1]])
        return (m == 1) & (prev_m == 0)

    up = first_of_streak(up)
    dn = first_of_streak(dn)

    idx = np.nonzero(up | dn)[0]
    di = np.where(up[idx], 1, -1)
    ok = np.isfinite(atr_big[idx]) & (atr_big[idx] > 0) & (idx < len(d) - 1)
    idx, di, atr_big = idx[ok], di[ok], atr_big[idx]
    entry = d["open"].to_numpy(float)[idx + 1] + di * ev.cost.spread_points * POINT
    risk = stop_atr * atr_big
    return {"tf": entry_tf, "bar_idx": idx, "direction": di, "entry": entry, "risk": risk}


# ------------------------------------------------------------------- analysis ---
def null_matched(ev: Evaluator, spec: dict, targets=(1.0, 2.0), seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    di = rng.choice([-1, 1], size=len(spec["bar_idx"]))
    entry = spec["entry"] - spec["direction"] * ev.cost.spread_points * POINT + di * ev.cost.spread_points * POINT
    return ev.simulate(spec["tf"], spec["bar_idx"], di, entry, spec["risk"], targets=targets)


def report(name: str, ev: Evaluator, spec: dict, targets=(1.0, 2.0, 3.0), null_seeds=5) -> pd.DataFrame:
    res = ev.simulate(spec["tf"], spec["bar_idx"], spec["direction"], spec["entry"],
                      spec["risk"], targets=targets)
    rows = []
    for r in targets:
        s = res.loc[res["filled"], f"r{r}"].dropna()
        if s.empty:
            continue
        gross = s + ev.cost.fee_in_r(res.loc[res["filled"], "risk"].to_numpy())
        nulls = []
        for seed in range(null_seeds):
            nres = null_matched(ev, spec, targets=targets, seed=seed)
            ns = nres.loc[nres["filled"], f"r{r}"].dropna()
            if not ns.empty:
                nulls.append(ns.mean())
        null_mean = float(np.mean(nulls)) if nulls else np.nan
        rows.append({
            "family": name, "target": f"{r}R", "n": len(s),
            "win%": round(100 * (s > 0).mean(), 1),
            "net_exp_R": round(s.mean(), 4),
            "gross_exp_R": round(gross.mean(), 4),
            "null_exp_R": round(null_mean, 4),
            "SKILL_R": round(s.mean() - null_mean, 4),
            "cost_drag_R": round(float(ev.cost.fee_in_r(res.loc[res["filled"]], ).mean()) if False else
                                 float(ev.cost.fee_in_r(res.loc[res["filled"], "risk"].to_numpy()).mean()), 3),
        })
    df = pd.DataFrame(rows)
    return df


def main() -> int:
    bs = xau_data.build()
    ev = Evaluator(bs, Costs())
    print(f"XAUUSD {bs['M1'].index[0].date()} -> {bs['M1'].index[-1].date()} | "
          f"{len(bs['M1']):,} M1 bars | spread {ev.cost.spread_points}pt + "
          f"${ev.cost.commission_per_lot}/lot")
    f = Features(bs, ev)

    families = []
    # --- wide stops, long horizon (cost drag should shrink dramatically) ---
    for tf, elen in (("H1", 20), ("H4", 20)):
        for stop in (2.0, 3.0):
            families.append((f"Trend {tf} breakout(20) stop={stop}ATR", dict(
                tf=tf, entry_tf=tf, trend_len=50, stop_atr=stop, target_r=3.0,
                breakout_lookback=elen)))
    families.append(("Trend H4 daily-close > SMA50 (long only)", dict(
        tf="H4", entry_tf="H4", trend_len=50, stop_atr=3.0, target_r=3.0, long_only=True)))
    families.append(("Trend H4 long+short", dict(
        tf="H4", entry_tf="H4", trend_len=50, stop_atr=3.0, target_r=3.0)))
    families.append(("Trend H1 NY-session only", dict(
        tf="H1", entry_tf="H1", trend_len=50, stop_atr=2.0, target_r=3.0, hours=(8, 17))))
    families.append(("Trend H1 London+NY", dict(
        tf="H1", entry_tf="H1", trend_len=50, stop_atr=2.0, target_r=3.0, hours=(3, 17))))

    out = []
    for name, kw in families:
        spec = trend_family(bs, ev, f, **kw)
        if len(spec["bar_idx"]) < 30:
            print(f"  {name}: only {len(spec['bar_idx'])} signals, skipping")
            continue
        df = report(name, ev, spec, targets=(1.0, 2.0, 3.0, 5.0))
        out.append(df)
        print("\n" + "=" * 100)
        print(f"  {name}   signals={len(spec['bar_idx'])}")
        print("=" * 100)
        print(df.to_string(index=False))

    if out:
        all_df = pd.concat(out, ignore_index=True)
        os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"), exist_ok=True)
        all_df.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "edge_trend.csv"),
                      index=False)
        print("\nSKILL_R = strategy expectancy minus matched null (cost-free measure of directional edge)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
