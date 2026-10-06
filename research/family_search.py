"""
Fast family search: which XAUUSD entry rules have real, cost-surviving edge?

This module evaluates many candidate entry families on the same footing:
  * identical stop model (ATR-based, so R is comparable across families)
  * identical cost model (spread + slippage + commission)
  * identical M1-precision path resolution, pessimistic on ambiguity
  * identical statistics (expectancy in R, win-rate, profit factor, n)

It also evaluates a NULL MODEL (random entries at random times) so that every
strategy's result can be judged against the "you have no edge" benchmark for this
exact instrument, cost level and stop size. A strategy that returns -0.10R when
random entries return -0.09R has no edge, it is just paying the spread twice.

Usage:
    python research/family_search.py            # full search, all families
    python research/family_search.py quick      # smaller subset
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

DEFAULT_TARGETS = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)


# ----------------------------------------------------------------- feature set ---
@dataclass
class Features:
    m5: pd.DataFrame
    m1_time: np.ndarray
    m1_high: np.ndarray
    m1_low: np.ndarray
    m1_close: np.ndarray
    m5_start_m1: np.ndarray      # M1 index where each M5 bar begins
    atr: np.ndarray
    atr_pct: np.ndarray          # percentile rank of ATR within a 60-day window
    ema20: np.ndarray
    ema50: np.ndarray
    sma200: np.ndarray
    h1_bias: np.ndarray          # +1/-1 closed-H1 trend vs SMA50
    h4_bias: np.ndarray
    swing_high: np.ndarray
    swing_low: np.ndarray
    pdh: np.ndarray              # prior day high (NY calendar day)
    pdl: np.ndarray
    rng: np.ndarray
    body: np.ndarray
    ny_hour: np.ndarray
    weekday: np.ndarray
    unix_min: np.ndarray         # minutes since epoch, for aligned joins


def build_features(bs: xau_data.BarSet, swing_lookback: int = 20, atr_period: int = 14) -> Features:
    m5, m1 = bs["M5"], bs["M1"]
    high, low, close = m5["high"].to_numpy(float), m5["low"].to_numpy(float), m5["close"].to_numpy(float)
    open_ = m5["open"].to_numpy(float)
    prev_close = np.concatenate([[np.nan], close[:-1]])
    tr = np.nanmax(np.vstack([high - low, np.abs(high - prev_close), np.abs(low - prev_close)]), axis=0)
    atr = pd.Series(tr).rolling(atr_period).mean().to_numpy()

    # rolling ATR percentile (regime filter) - causal, 60 trading days ~ 17k M5 bars
    atr_pct = pd.Series(atr).rolling(17280, min_periods=1000).rank(pct=True).to_numpy()

    ema20 = pd.Series(close).ewm(span=20, adjust=False).mean().to_numpy()
    ema50 = pd.Series(close).ewm(span=50, adjust=False).mean().to_numpy()
    sma200 = pd.Series(close).rolling(200).mean().to_numpy()

    swing_high = pd.Series(high).rolling(swing_lookback).max().shift(1).to_numpy()
    swing_low = pd.Series(low).rolling(swing_lookback).min().shift(1).to_numpy()

    # prior-day high/low on the NY calendar day (what a trader actually marks up)
    ny_day = m5["ny"].dt.date
    day_high = m5.groupby(ny_day)["high"].transform("max")
    day_low = m5.groupby(ny_day)["low"].transform("min")
    pdh = pd.Series(day_high.to_numpy()).groupby(ny_day.to_numpy()).last().shift(1)
    pdl = pd.Series(day_low.to_numpy()).groupby(ny_day.to_numpy()).last().shift(1)
    pdh_map = pdh.reindex(ny_day.to_numpy()).to_numpy()
    pdl_map = pdl.reindex(ny_day.to_numpy()).to_numpy()

    # higher timeframe bias, joined as-of (only closed HTF bars)
    def htf_bias(tf: str, window: int) -> np.ndarray:
        htf = bs[tf]
        sma = htf["close"].rolling(window).mean()
        bias = np.where(htf["close"].to_numpy(float) > sma.to_numpy(), 1, -1)
        s = pd.Series(bias, index=htf.index).shift(1)  # only bars closed before now
        return s.reindex(m5.index, method="ffill").to_numpy()

    h1_bias = htf_bias("H1", 50)
    h4_bias = htf_bias("H4", 50)

    m1_time = m1.index.values
    m5_start = np.searchsorted(m1_time, m5.index.values, side="left")

    return Features(
        m5=m5, m1_time=m1_time,
        m1_high=m1["high"].to_numpy(float), m1_low=m1["low"].to_numpy(float),
        m1_close=m1["close"].to_numpy(float), m5_start_m1=m5_start,
        atr=atr, atr_pct=atr_pct, ema20=ema20, ema50=ema50, sma200=sma200,
        h1_bias=h1_bias, h4_bias=h4_bias, swing_high=swing_high, swing_low=swing_low,
        pdh=pdh_map, pdl=pdl_map,
        rng=high - low, body=np.abs(close - open_),
        ny_hour=m5["ny_hour"].to_numpy(float), weekday=m5["weekday"].to_numpy(int),
        unix_min=(m5.index.values.astype("datetime64[m]").astype(np.int64)),
    )


# ------------------------------------------------------- vectorised path evaluator ---
@dataclass
class Costs:
    spread_points: float = 25.0
    slippage_points: float = 2.0
    commission_per_lot: float = 7.0

    def fee_price(self) -> float:
        return (self.spread_points + 2 * self.slippage_points) * POINT

    def fee_in_r(self, risk: np.ndarray) -> np.ndarray:
        return (self.fee_price() + self.commission_per_lot / CONTRACT) / risk


def evaluate(
    f: Features,
    bar_idx: np.ndarray,
    direction: np.ndarray,
    sl_atr: float = 1.5,
    targets: tuple[float, ...] = DEFAULT_TARGETS,
    max_bars: int = 240,
    cost: Costs | None = None,
    fill_mode: str = "market",
    limit_offset_atr: float = 0.0,
    fill_deadline: int = 24,
    chunk: int = 20000,
) -> pd.DataFrame:
    """
    Evaluate a batch of entries on the M1 path.

    bar_idx   : M5 bar index where the signal is confirmed (on its close)
    direction : +1 long / -1 short
    sl_atr    : stop distance in ATR units (1R). Also the entry buffer for limits.
    fill_mode : 'market' (next bar open +/- spread) or 'limit' (retrace by
                limit_offset_atr * ATR, must fill within `fill_deadline` M5 bars)
    """
    cost = cost or Costs()
    atr = f.atr
    n5 = len(f.m5)
    open5 = f.m5["open"].to_numpy(float)

    bar_idx = np.asarray(bar_idx)
    direction = np.asarray(direction)
    ok = (bar_idx >= 30) & (bar_idx < n5 - 2) & np.isfinite(atr[bar_idx]) & (atr[bar_idx] > 0)
    bar_idx, direction = bar_idx[ok], direction[ok]
    if len(bar_idx) == 0:
        return pd.DataFrame()

    recs = []
    for start in range(0, len(bar_idx), chunk):
        bi = bar_idx[start:start + chunk]
        di = direction[start:start + chunk]
        a = atr[bi]

        if fill_mode == "market":
            fill_bar = bi + 1
            entry = open5[fill_bar] + di * cost.spread_points * POINT
            start_m1 = f.m5_start_m1[fill_bar]
            risk = sl_atr * a
            deadline = None
        else:
            # limit at a retrace of limit_offset_atr * ATR from the signal close
            entry = f.m5["close"].to_numpy(float)[bi] - di * limit_offset_atr * a
            risk = sl_atr * a
            start_m1 = f.m5_start_m1[bi + 1]
            deadline = fill_deadline

        sl = entry - di * risk
        stop_frac = np.full(len(bi), deadline if deadline else 10**9)

        # build padded forward windows from M1 (pad with NaN)
        m1_hi = np.full((len(bi), max_bars), np.nan)
        m1_lo = np.full((len(bi), max_bars), np.nan)
        m1_cl = np.full((len(bi), max_bars), np.nan)
        for j, s in enumerate(start_m1):
            e = min(s + max_bars, len(f.m1_high))
            L = e - s
            if L <= 0:
                continue
            m1_hi[j, :L] = f.m1_high[s:e]
            m1_lo[j, :L] = f.m1_low[s:e]
            m1_cl[j, :L] = f.m1_close[s:e]

        filled = np.isfinite(m1_hi).any(axis=1)
        if fill_mode != "market":
            # long fills when price trades down to entry; short when it trades up
            touch = (m1_lo <= entry[:, None]) if di[0] > 0 else (m1_hi >= entry[:, None])
            touch = np.where(di[:, None] > 0, m1_lo <= entry[:, None], m1_hi >= entry[:, None])
            first_touch = np.where(touch.any(axis=1), touch.argmax(axis=1), 10**9)
            filled = first_touch < stop_frac
            # truncate windows to start at the fill
            idx = np.arange(max_bars)[None, :]
            valid = (idx >= first_touch[:, None]) & filled[:, None]
            m1_hi = np.where(valid, m1_hi, np.nan)
            m1_lo = np.where(valid, m1_lo, np.nan)
            m1_cl = np.where(valid, m1_cl, np.nan)
            # the fill bar itself: price touched the entry, no further excursion known
            m1_hi = np.where(idx == first_touch[:, None], entry[:, None], m1_hi)
            m1_lo = np.where(idx == first_touch[:, None], entry[:, None], m1_lo)

        # stop / target resolution (stop wins ties - pessimistic)
        stop_hit = (m1_lo <= sl[:, None]) if di[0] > 0 else (m1_hi >= sl[:, None])
        stop_hit = np.where(di[:, None] > 0, m1_lo <= sl[:, None], m1_hi >= sl[:, None])
        stop_idx = np.where(stop_hit.any(axis=1), stop_hit.argmax(axis=1), 10**9)

        # MFE / MAE
        fav = np.where(di[:, None] > 0, m1_hi - entry[:, None], entry[:, None] - m1_lo) / risk[:, None]
        adv = np.where(di[:, None] > 0, entry[:, None] - m1_lo, m1_hi - entry[:, None]) / risk[:, None]
        fav = np.where(np.isfinite(m1_hi), fav, -np.inf)
        adv = np.where(np.isfinite(m1_hi), adv, -np.inf)
        mfe = np.nanmax(np.where(np.isfinite(fav), fav, np.nan), axis=1)
        mae = np.nanmax(np.where(np.isfinite(adv), adv, np.nan), axis=1)

        base = {
            "bar_idx": bi, "direction": di, "entry": entry, "risk": risk,
            "atr": a, "mfe_r": mfe, "mae_r": mae, "filled": filled,
        }
        for r in targets:
            tgt = entry + di * risk * r
            tgt_hit = np.where(di[:, None] > 0, m1_hi >= tgt[:, None], m1_lo <= tgt[:, None])
            tgt_idx = np.where(tgt_hit.any(axis=1), tgt_hit.argmax(axis=1), 10**9)
            won = tgt_idx < stop_idx
            last_close = np.nanmax(np.where(np.isfinite(m1_cl), np.arange(max_bars)[None, :], -1), axis=1)
            open_r = np.take_along_axis(m1_cl, last_close[:, None], axis=1).ravel()
            open_r = di * (open_r - entry) / risk
            r_real = np.where(won, r, np.where(stop_idx < 10**9, -1.0, open_r))
            base[f"r{r}"] = r_real - cost.fee_in_r(risk)
            base[f"won{r}"] = won
        recs.append(pd.DataFrame(base))

    df = pd.concat(recs, ignore_index=True)
    df["time"] = f.m5.index[df["bar_idx"].to_numpy()]
    df["utc"] = f.m5["utc"].to_numpy()[df["bar_idx"].to_numpy()]
    df["ny_hour"] = f.ny_hour[df["bar_idx"].to_numpy()]
    df["direction_s"] = np.where(df["direction"] > 0, "LONG", "SHORT")
    return df


def stats(df: pd.DataFrame, targets=DEFAULT_TARGETS) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = df[df["filled"]]
    if df.empty:
        return pd.DataFrame()
    rows = []
    for r in targets:
        col = f"r{r}"
        if col not in df:
            continue
        s = df[col].dropna()
        if s.empty:
            continue
        wins, losses = s[s > 0], s[s <= 0]
        pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
        rows.append({
            "target": f"{r}R", "n": len(s), "win%": round(100 * len(wins) / len(s), 1),
            "exp_R": round(s.mean(), 4), "PF": round(pf, 3),
            "total_R": round(s.sum(), 1),
        })
    return pd.DataFrame(rows)


def quick_stat(df: pd.DataFrame, target: float = 1.0) -> str:
    if df.empty or not df["filled"].any():
        return "n=0"
    s = df.loc[df["filled"], f"r{target}"].dropna()
    if s.empty:
        return "n=0"
    return f"n={len(s):<6} win%={100*(s>0).mean():5.1f}  exp={s.mean():+.3f}R  tot={s.sum():+8.1f}R"


# ------------------------------------------------------------------- families ---
def fam_random(f: Features, n: int, seed: int = 7, targets=DEFAULT_TARGETS) -> pd.DataFrame:
    """NULL MODEL: entries at random times, random direction, same stop model."""
    rng = np.random.default_rng(seed)
    idx = rng.choice(np.arange(60, len(f.m5) - 300), size=n, replace=False)
    direction = rng.choice([-1, 1], size=n)
    return evaluate(f, idx, direction, 1.0, targets=targets)


def fam_sweep_fade(f: Features, hours=None, only_disp=False, htf=None) -> pd.DataFrame:
    low, high, close = f.m5["low"].to_numpy(float), f.m5["high"].to_numpy(float), f.m5["close"].to_numpy(float)
    disp = (f.rng > 1.5 * f.atr) & (f.body / np.where(f.rng > 0, f.rng, np.nan) > 0.6)
    long_m = (low < f.swing_low) & (close > f.swing_low)
    short_m = (high > f.swing_high) & (close < f.swing_high)
    if only_disp:
        long_m &= disp
        short_m &= disp
    if hours:
        win = (f.ny_hour >= hours[0]) & (f.ny_hour < hours[1])
        long_m &= win
        short_m &= win
    if htf is not None:
        long_m &= f.h1_bias == 1
        short_m &= f.h1_bias == -1
    idx = np.nonzero(long_m | short_m)[0]
    d = np.where(long_m[idx], 1, -1)
    return evaluate(f, idx, d)


def fam_break_follow(f: Features, hours=None, only_disp=True, htf=None) -> pd.DataFrame:
    """Continuation: bar closes beyond the prior swing in the direction of travel."""
    high, low, close = f.m5["high"].to_numpy(float), f.m5["low"].to_numpy(float), f.m5["close"].to_numpy(float)
    disp = (f.rng > 1.5 * f.atr) & (f.body / np.where(f.rng > 0, f.rng, np.nan) > 0.6)
    long_m = close > f.swing_high
    short_m = close < f.swing_low
    if only_disp:
        long_m &= disp
        short_m &= disp
    if hours:
        win = (f.ny_hour >= hours[0]) & (f.ny_hour < hours[1])
        long_m &= win
        short_m &= win
    if htf is not None:
        long_m &= f.h1_bias == 1
        short_m &= f.h1_bias == -1
    idx = np.nonzero(long_m | short_m)[0]
    d = np.where(long_m[idx], 1, -1)
    return evaluate(f, idx, d)


def fam_trend_pullback(f: Features, hours=None, require_ema_cross=True) -> pd.DataFrame:
    """With-trend pullback: HTF uptrend + M5 dips below EMA20 then closes back above."""
    close = f.m5["close"].to_numpy(float)
    prev_close = np.concatenate([[np.nan], close[:-1]])
    crossed_up = (prev_close <= f.ema20) & (close > f.ema20)
    crossed_dn = (prev_close >= f.ema20) & (close < f.ema20)
    long_m = crossed_up & (f.h1_bias == 1)
    short_m = crossed_dn & (f.h1_bias == -1)
    if hours:
        win = (f.ny_hour >= hours[0]) & (f.ny_hour < hours[1])
        long_m &= win
        short_m &= win
    idx = np.nonzero(long_m | short_m)[0]
    d = np.where(long_m[idx], 1, -1)
    return evaluate(f, idx, d)


def fam_pdh_pdl(f: Features, mode="break", hours=None) -> pd.DataFrame:
    high, low, close = f.m5["high"].to_numpy(float), f.m5["low"].to_numpy(float), f.m5["close"].to_numpy(float)
    above = close > f.pdh
    below = close < f.pdl
    if mode == "break":
        long_m = above & ~np.concatenate([[False], above[:-1]])
        short_m = below & ~np.concatenate([[False], below[:-1]])
    else:  # fade back inside
        long_m = (low < f.pdl) & (close > f.pdl)
        short_m = (high > f.pdh) & (close < f.pdh)
    if hours:
        win = (f.ny_hour >= hours[0]) & (f.ny_hour < hours[1])
        long_m &= win
        short_m &= win
    idx = np.nonzero(long_m | short_m)[0]
    d = np.where(long_m[idx], 1, -1)
    return evaluate(f, idx, d)


def fam_orb(f: Features, open_hour=8.0, range_minutes=60, stop_buffer=0) -> pd.DataFrame:
    """Opening-range breakout: break of the first hour's high/low after the NY open."""
    h = f.ny_hour
    mins = (h * 60).astype(int)
    oh = int(open_hour * 60)
    in_range = (mins >= oh) & (mins < oh + range_minutes)
    day = f.m5["ny"].dt.date.to_numpy()
    rng_hi = pd.Series(np.where(in_range, f.m5["high"].to_numpy(float), np.nan)).groupby(day).transform("max")
    rng_lo = pd.Series(np.where(in_range, f.m5["low"].to_numpy(float), np.nan)).groupby(day).transform("min")
    hi, lo = rng_hi.to_numpy(), rng_lo.to_numpy()
    close = f.m5["close"].to_numpy(float)
    after = mins >= oh + range_minutes
    long_m = after & (close > hi)
    short_m = after & (close < lo)
    long_m &= ~pd.Series(long_m).groupby(day).cumsum().gt(1).to_numpy()  # first break only
    short_m &= ~pd.Series(short_m).groupby(day).cumsum().gt(1).to_numpy()
    idx = np.nonzero(long_m | short_m)[0]
    d = np.where(long_m[idx], 1, -1)
    return evaluate(f, idx, d)


def fam_momentum(f: Features, k=3, hours=None) -> pd.DataFrame:
    close = f.m5["close"].to_numpy(float)
    open_ = f.m5["open"].to_numpy(float)
    up = close > open_
    dn = close < open_
    upk = pd.Series(up).rolling(k).sum().to_numpy() == k
    dnk = pd.Series(dn).rolling(k).sum().to_numpy() == k
    long_m = upk & ~np.concatenate([[False] * k, upk[:-k]])
    short_m = dnk & ~np.concatenate([[False] * k, dnk[:-k]])
    if hours:
        win = (f.ny_hour >= hours[0]) & (f.ny_hour < hours[1])
        long_m &= win
        short_m &= win
    idx = np.nonzero(long_m | short_m)[0]
    d = np.where(long_m[idx], 1, -1)
    return evaluate(f, idx, d)


# ----------------------------------------------------------------------- main ---
def main() -> int:
    quick = len(sys.argv) > 1 and sys.argv[1] == "quick"
    bs = xau_data.build()
    print("Building features ...")
    f = build_features(bs)
    cost = Costs()
    T = (1.0, 2.0) if quick else DEFAULT_TARGETS
    print(f"Costs: {cost.spread_points}pt spread + ${cost.commission_per_lot}/lot RT + "
          f"{cost.slippage_points}pt slippage/side\n")

    families: list[tuple[str, callable]] = [
        ("NULL: random entries (no edge benchmark)", lambda: fam_random(f, 20000, targets=T)),
        ("Sweep fade (bot's core logic)", lambda: fam_sweep_fade(f)),
        ("Sweep fade + displacement", lambda: fam_sweep_fade(f, only_disp=True)),
        ("Sweep fade + H1 trend filter", lambda: fam_sweep_fade(f, htf=True)),
        ("Sweep fade NY 08-11", lambda: fam_sweep_fade(f, hours=(8, 11))),
        ("BREAK continuation (close beyond swing)", lambda: fam_break_follow(f, only_disp=False)),
        ("BREAK continuation + displacement", lambda: fam_break_follow(f, only_disp=True)),
        ("BREAK continuation + H1 trend", lambda: fam_break_follow(f, htf=True, only_disp=False)),
        ("BREAK continuation NY 08-11", lambda: fam_break_follow(f, hours=(8, 11), only_disp=False)),
        ("BREAK continuation NY 02-05 (London)", lambda: fam_break_follow(f, hours=(2, 5), only_disp=False)),
        ("Trend pullback (HTF + EMA20 reclaim)", lambda: fam_trend_pullback(f)),
        ("Trend pullback NY 08-11", lambda: fam_trend_pullback(f, hours=(8, 11))),
        ("Prior-day H/L breakout", lambda: fam_pdh_pdl(f, "break")),
        ("Prior-day H/L sweep fade", lambda: fam_pdh_pdl(f, "fade")),
        ("Opening range breakout NY 08:00", lambda: fam_orb(f, 8.0)),
        ("Opening range breakout London 03:00", lambda: fam_orb(f, 3.0)),
        ("Momentum 3-bar continuation", lambda: fam_momentum(f, 3)),
        ("Momentum 3-bar NY 08-11", lambda: fam_momentum(f, 3, hours=(8, 11))),
    ]

    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"), exist_ok=True)
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "family_search.txt")
    lines = []
    for name, fn in families:
        df = fn()
        print("=" * 96)
        print(f"  {name}")
        print("=" * 96)
        s = stats(df, T)
        print(s.to_string(index=False) if not s.empty else "  no trades")
        # gross vs net at 1R, to expose how much is cost vs genuine edge
        if not df.empty and df["filled"].any():
            fee = df.loc[df["filled"], "risk"].pipe(lambda r: cost.fee_in_r(r.to_numpy()))
            net = df.loc[df["filled"], "r1.0"]
            print(f"  net 1R expectancy {net.mean():+.3f}R | gross {net.add(fee).mean():+.3f}R | "
                  f"cost drag {fee.mean():.3f}R")
            yearly = net.groupby(df.loc[df["filled"], "utc"].dt.year).mean().round(3)
            print(f"  yearly net 1R expectancy: {yearly.to_dict()}")
        print()
        lines.append(f"### {name}\n{s.to_string(index=False)}\n")
        df.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out",
                               f"fam_{name.split()[0].strip(':').lower()}_{abs(hash(name)) % 10000}.csv"),
                  index=False)
    with open(out_path, "w") as fh:
        fh.write("\n".join(lines))
    print(f"Written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
