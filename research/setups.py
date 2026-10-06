"""
Vectorised ICT setup mining for XAUUSD.

WHAT THIS DOES
--------------
Instead of guessing whether the bot's rules work, we enumerate every occurrence of
each ICT building block on M5 gold over 3.4 years (1.16M M1 bars), then measure what
price actually did next -- with 1-minute precision and realistic costs.

Outputs per setup:
  * forward MFE / MAE in R (how far it ran, how far it went against us first)
  * hit-rate of fixed R targets with structurally-placed stops
  * expectancy in R, gross and net of spread + commission + slippage

Key modelling choices (all chosen to be pessimistic, i.e. not flatter the strategy):
  * decisions use CLOSED bars only (no look-ahead, signals fire on bar close)
  * when a bar's range could both stop out and hit target, we assume the STOP
  * costs are charged on entry AND exit via spread, plus per-lot commission

Usage:
    python research/setups.py
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from research import xau_data  # noqa: E402

# ---------------------------------------------------------------- instrument ---
POINT = 0.01          # MT5 point for XAUUSD
CONTRACT = 100.0      # ounces per lot


@dataclass
class Costs:
    """Execution cost model. Defaults = typical prop-firm gold feed."""

    spread_points: float = 25.0        # 25 points = $0.25 round-trip spread paid
    slippage_points: float = 2.0       # per side, stop/limit fills
    commission_per_lot: float = 7.0    # $ round-turn per 1.00 lot

    def cost_in_r(self, sl_distance_price: float) -> float:
        """Total friction expressed as a fraction of 1R (risk per trade)."""
        if sl_distance_price <= 0:
            return np.inf
        price_cost = (self.spread_points + 2 * self.slippage_points) * POINT
        comm_cost = self.commission_per_lot / CONTRACT
        return (price_cost + comm_cost) / sl_distance_price


# ------------------------------------------------------------------- features ---
@dataclass
class M5Features:
    """Vectorised, closed-bar-only features on the M5 series."""

    df: pd.DataFrame
    ny_hour: np.ndarray
    weekday: np.ndarray
    atr: np.ndarray
    swing_high: np.ndarray
    swing_low: np.ndarray
    body_ratio: np.ndarray
    rng: np.ndarray

    @classmethod
    def build(cls, m5: pd.DataFrame, swing_lookback: int = 20, atr_period: int = 14) -> "M5Features":
        high, low, close = m5["high"].to_numpy(float), m5["low"].to_numpy(float), m5["close"].to_numpy(float)
        prev_close = np.concatenate([[np.nan], close[:-1]])
        tr = np.nanmax(np.vstack([high - low, np.abs(high - prev_close), np.abs(low - prev_close)]), axis=0)
        atr = pd.Series(tr).rolling(atr_period).mean().to_numpy()

        # swing levels of the PRIOR `swing_lookback` bars (shifted -> no look-ahead)
        sh = pd.Series(high).rolling(swing_lookback).max().shift(1).to_numpy()
        sl = pd.Series(low).rolling(swing_lookback).min().shift(1).to_numpy()

        rng = high - low
        with np.errstate(invalid="ignore", divide="ignore"):
            body = np.where(rng > 0, np.abs(close - m5["open"].to_numpy(float)) / rng, 0.0)

        return cls(
            df=m5,
            ny_hour=m5["ny_hour"].to_numpy(float),
            weekday=m5["weekday"].to_numpy(int),
            atr=atr,
            swing_high=sh,
            swing_low=sl,
            body_ratio=body,
            rng=rng,
        )


def detect_fvg(m5: pd.DataFrame) -> pd.DataFrame:
    """
    Every 3-bar fair value gap, with the bar index at which it becomes known.

    Bullish FVG: low[i] > high[i-2]  -> gap [high[i-2], low[i]]
    Bearish FVG: high[i] < low[i-2]  -> gap [high[i], low[i-2]]
    `known_at` = i (the gap is only visible once bar i has closed).
    """
    high = m5["high"].to_numpy(float)
    low = m5["low"].to_numpy(float)
    idx = np.arange(len(m5))

    bull = np.zeros(len(m5), bool)
    bear = np.zeros(len(m5), bool)
    bull[2:] = low[2:] > high[:-2]
    bear[2:] = high[2:] < low[:-2]

    rows = []
    for mask, kind, top, bottom in (
        (bull, "BULLISH", low, high),          # top=low[i], bottom=high[i-2]
        (bear, "BEARISH", low, high),          # top=low[i-2], bottom=high[i]
    ):
        for i in idx[mask]:
            if kind == "BULLISH":
                rows.append((i, kind, float(top[i]), float(bottom[i - 2])))
            else:
                rows.append((i, kind, float(top[i - 2]), float(bottom[i])))
    fvgs = pd.DataFrame(rows, columns=["known_at", "type", "top", "bottom"])
    return fvgs.sort_values("known_at").reset_index(drop=True)


# ------------------------------------------------------------------ outcomes ---
@dataclass
class Outcome:
    """Forward path statistics for one setup, measured on the M1 series."""

    filled: bool = False
    fill_time: int = -1            # M1 index of fill
    r_multiple: float = np.nan     # realised R at the fixed target / stop
    target_hit: bool = False
    mfe_r: float = 0.0
    mae_r: float = 0.0
    bars_to_mfe: int = 0
    bars_held: int = 0
    resolved: bool = False


class PathEngine:
    """
    M1-precision forward simulator.

    Pre-indexes the M1 series so that any [start, end) window can be sliced in O(1)
    and scanned with numpy in a single vectorised pass per setup.
    """

    def __init__(self, m1: pd.DataFrame):
        self.time = m1.index.to_numpy()     # datetime64[ns], broker clock
        self.utc = m1["utc"].to_numpy("datetime64[ns]")
        self.high = m1["high"].to_numpy(float)
        self.low = m1["low"].to_numpy(float)
        self.close = m1["close"].to_numpy(float)

    def window_start(self, ts) -> int:
        """First M1 index at or after the given M5 timestamp."""
        return int(np.searchsorted(self.time, np.datetime64(ts), side="left"))

    def simulate(
        self,
        start_i: int,
        direction: int,
        entry: float,
        sl: float,
        targets_r: tuple[float, ...] = (1.0, 2.0, 3.0),
        max_bars: int = 240,
        limit_entry: bool = False,
        fill_deadline_bars: int = 24,
    ) -> dict[float, Outcome]:
        """
        Run the M1 path forward.

        direction: +1 long, -1 short
        entry:     price the position is filled at. If limit_entry, price must trade
                   through this level before the trade exists.
        sl:        stop price (structural).
        Returns a dict keyed by target R multiple.
        """
        risk = abs(entry - sl)
        end = min(start_i + max_bars, len(self.time))
        if risk <= 0 or end - start_i < 2:
            return {r: Outcome() for r in targets_r}

        hi = self.high[start_i:end]
        lo = self.low[start_i:end]
        cl = self.close[start_i:end]
        n = len(hi)

        fill_i = 0
        if limit_entry:
            if direction > 0:
                touched = np.nonzero(lo <= entry)[0]
            else:
                touched = np.nonzero(hi >= entry)[0]
            if touched.size == 0 or touched[0] >= fill_deadline_bars:
                return {r: Outcome() for r in targets_r}
            fill_i = int(touched[0])
            hi, lo, cl = hi[fill_i:], lo[fill_i:], cl[fill_i:]
            n = len(hi)

        # --- stop first (pessimistic) ---
        if direction > 0:
            stop_hits = np.nonzero(lo <= sl)[0]
        else:
            stop_hits = np.nonzero(hi >= sl)[0]
        stop_i = int(stop_hits[0]) if stop_hits.size else 10**9

        out: dict[float, Outcome] = {}
        for r_mult in targets_r:
            target = entry + direction * risk * r_mult
            if direction > 0:
                tgt_hits = np.nonzero(hi >= target)[0]
                adverse = (entry - lo) / risk
                favour = (hi - entry) / risk
            else:
                tgt_hits = np.nonzero(lo <= target)[0]
                adverse = (hi - entry) / risk
                favour = (entry - lo) / risk

            tgt_i = int(tgt_hits[0]) if tgt_hits.size else 10**9
            hit = tgt_i < stop_i
            resolved = tgt_i < 10**9 or stop_i < 10**9

            if not resolved:
                r_realised = direction * (cl[-1] - entry) / risk
                bars_held = n - 1
            elif hit:
                r_realised = r_mult
                bars_held = tgt_i
            else:
                r_realised = -1.0
                bars_held = stop_i

            # excursion stats up to the resolution bar (or the horizon)
            upto = min(tgt_i, stop_i, n - 1) if resolved else n - 1
            upto = max(upto, 0)
            out[r_mult] = Outcome(
                filled=True,
                fill_time=start_i + fill_i,
                r_multiple=float(r_realised),
                target_hit=bool(hit),
                mfe_r=float(np.max(favour[: upto + 1])),
                mae_r=float(np.max(adverse[: upto + 1])),
                bars_to_mfe=int(np.argmax(favour[: upto + 1])),
                bars_held=int(bars_held),
                resolved=bool(resolved),
            )
        return out


# ------------------------------------------------------------------- pipeline ---
@dataclass
class SetupSpec:
    """A named family of setups to mine."""

    name: str
    direction_filter: int = 0          # 0 both, +1 longs only, -1 shorts only
    hours_ny: tuple[float, float] | None = None
    require_sweep: bool = False
    require_displacement: bool = False
    require_mss: bool = False
    min_atr_pct: float = 0.0           # require ATR above this percentile of history
    entry_mode: str = "market"         # 'market' | 'fvg_retrace'
    sl_mode: str = "structure"         # 'structure' | 'atr'
    sl_buffer_atr: float = 0.25
    atr_sl_mult: float = 1.0


def mine_setups(
    f: M5Features,
    spec: SetupSpec,
    pe: PathEngine,
    max_bars: int = 240,
    targets_r: tuple[float, ...] = (1.0, 1.5, 2.0, 2.5, 3.0),
    cost: Costs | None = None,
) -> pd.DataFrame:
    """
    Enumerate setups matching `spec` and return one row per trade with outcomes.

    Entry / stop construction follows the ICT reading used by the repo's strategies:
      long:  sweep of the prior swing low -> enter on reclaim, stop under the wick
      short: sweep of the prior swing high -> enter on rejection, stop above the wick
    """
    cost = cost or Costs()
    m5 = f.df
    high, low, close = m5["high"].to_numpy(float), m5["low"].to_numpy(float), m5["close"].to_numpy(float)
    open_ = m5["open"].to_numpy(float)
    n = len(m5)
    idx = np.arange(n)

    # --- candidate sweeps (closed-bar, causal) ---
    swept_low = (low < f.swing_low) & (close > f.swing_low)
    swept_high = (high > f.swing_high) & (close < f.swing_high)

    disp = (f.rng > 1.5 * f.atr) & (f.body_ratio > 0.6)

    # --- MSS: close beyond the prior swing in the sweep direction on the same bar ---
    mss_up = close > f.swing_high
    mss_dn = close < f.swing_low

    long_mask = np.zeros(n, bool)
    short_mask = np.zeros(n, bool)
    if spec.direction_filter >= 0:
        long_mask = swept_low.copy()
        if spec.require_mss:
            long_mask &= mss_up | (close > open_)
    if spec.direction_filter <= 0:
        short_mask = swept_high.copy()
        if spec.require_mss:
            short_mask &= mss_dn | (close < open_)

    if spec.require_sweep is False:
        pass  # sweeps are the base trigger in this family
    if spec.require_displacement:
        long_mask &= disp
        short_mask &= disp

    if spec.hours_ny is not None:
        lo_h, hi_h = spec.hours_ny
        in_window = (f.ny_hour >= lo_h) & (f.ny_hour < hi_h)
        long_mask &= in_window
        short_mask &= in_window

    if spec.min_atr_pct > 0:
        thr = np.nanpercentile(f.atr, spec.min_atr_pct)
        vol_ok = f.atr >= thr
        long_mask &= vol_ok
        short_mask &= vol_ok

    # FVG pre-computation for retrace entries
    fvgs = None
    if spec.entry_mode == "fvg_retrace":
        fvgs = detect_fvg(m5)

    rows = []
    for i in np.nonzero(long_mask | short_mask)[0]:
        if not np.isfinite(f.atr[i]) or f.atr[i] <= 0 or i < 30 or i >= n - 2:
            continue
        direction = 1 if long_mask[i] else -1

        # --- entry price ---
        if spec.entry_mode == "market":
            # filled at the next bar's open (signals fire on close)
            fill_bar = i + 1
            if fill_bar >= n:
                continue
            entry = float(open_[fill_bar])
            start_i = pe.window_start(m5.index[fill_bar])
            limit = False
            if direction > 0:
                entry += cost.spread_points * POINT  # pay the spread on a long
            else:
                entry -= cost.spread_points * POINT
        else:
            # limit at the nearest unmitigated FVG in the trade direction
            cand = fvgs[(fvgs["known_at"] <= i) & (fvgs["known_at"] >= i - 12)]
            cand = cand[cand["type"] == ("BULLISH" if direction > 0 else "BEARISH")]
            if cand.empty:
                continue
            g = cand.iloc[-1]
            entry = float(g["top"]) if direction > 0 else float(g["bottom"])
            # long: buy back into the gap from above; short: sell into the gap from below
            if direction > 0 and entry >= close[i]:
                continue
            if direction < 0 and entry <= close[i]:
                continue
            start_i = pe.window_start(m5.index[i + 1])
            limit = True

        # --- stop ---
        if spec.sl_mode == "structure":
            if direction > 0:
                sl = float(low[max(0, i - 2): i + 1].min()) - spec.sl_buffer_atr * f.atr[i]
            else:
                sl = float(high[max(0, i - 2): i + 1].max()) + spec.sl_buffer_atr * f.atr[i]
        else:
            sl = entry - direction * spec.atr_sl_mult * f.atr[i]

        risk = abs(entry - sl)
        if risk < 5 * POINT:      # sub-$0.05 stop = noise, unusable
            continue

        outs = pe.simulate(
            start_i, direction, entry, sl, targets_r=targets_r,
            max_bars=max_bars, limit_entry=limit,
        )
        if not outs[targets_r[0]].filled:
            continue

        fee_r = cost.cost_in_r(risk)
        rec = {
            "time": m5.index[i],
            "utc": m5["utc"].iloc[i],
            "direction": "LONG" if direction > 0 else "SHORT",
            "entry": entry,
            "sl": sl,
            "risk": risk,
            "risk_points": risk / POINT,
            "atr": f.atr[i],
            "ny_hour": f.ny_hour[i],
            "fee_r": fee_r,
        }
        for r_mult, o in outs.items():
            rec[f"r{r_mult}"] = o.r_multiple - fee_r
            rec[f"hit{r_mult}"] = o.target_hit
        first = outs[targets_r[0]]
        rec["mfe_r"] = first.mfe_r
        rec["mae_r"] = first.mae_r
        rec["bars_to_mfe"] = first.bars_to_mfe
        rec["bars_held"] = first.bars_held
        rows.append(rec)

    return pd.DataFrame(rows)


# --------------------------------------------------------------------- report ---
def summarise(trades: pd.DataFrame, targets_r: tuple[float, ...] = (1.0, 1.5, 2.0, 2.5, 3.0)) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    out = []
    for r in targets_r:
        col = f"r{r}"
        if col not in trades:
            continue
        s = trades[col].dropna()
        wins = s[s > 0]
        losses = s[s <= 0]
        pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else np.inf
        out.append({
            "target": f"{r}R",
            "n": len(s),
            "win%": round(100 * len(wins) / len(s), 1),
            "expectancy_R": round(s.mean(), 4),
            "profit_factor": round(pf, 3),
            "total_R": round(s.sum(), 1),
            "avg_mfe_R": round(trades["mfe_r"].mean(), 2),
            "avg_mae_R": round(trades["mae_r"].mean(), 2),
        })
    return pd.DataFrame(out)


def main() -> int:
    bs = xau_data.build()
    m5 = bs["M5"]
    m1 = bs["M1"]
    print(f"Data: {len(m1):,} M1 bars, {len(m5):,} M5 bars  ({m1.index[0]} -> {m1.index[-1]} broker time)")

    f = M5Features.build(m5, swing_lookback=20, atr_period=14)
    pe = PathEngine(m1)
    cost = Costs()
    print(f"Costs: {cost.spread_points}pt spread, ${cost.commission_per_lot}/lot RT, "
          f"{cost.slippage_points}pt slippage")

    specs = [
        SetupSpec("A. All sweeps (baseline family)", entry_mode="market"),
        SetupSpec("B. Sweeps in NY 08:00-11:00", hours_ny=(8, 11), entry_mode="market"),
        SetupSpec("C. Sweeps + displacement", require_displacement=True, entry_mode="market"),
        SetupSpec("D. Sweeps + disp + FVG retrace entry", require_displacement=True,
                  entry_mode="fvg_retrace"),
        SetupSpec("E. Sweeps + disp + FVG retrace + high vol", require_displacement=True,
                  entry_mode="fvg_retrace", min_atr_pct=60),
        SetupSpec("F. Sweeps + FVG retrace (no disp filter)", entry_mode="fvg_retrace"),
    ]

    results = {}
    for spec in specs:
        t = mine_setups(f, spec, pe, cost=cost)
        results[spec.name] = t
        print("\n" + "=" * 78)
        print(f"  {spec.name}   ({len(t)} trades)")
        print("=" * 78)
        if t.empty:
            print("  no trades")
            continue
        print(summarise(t).to_string(index=False))
        # split by direction and by cost
        for d in ("LONG", "SHORT"):
            sub = t[t["direction"] == d]
            if len(sub) > 20:
                s = sub["r2.0"]
                print(f"    {d:<5} n={len(sub):<5} R2 win%={100*(s>0).mean():.1f} "
                      f"exp={s.mean():+.3f}R  (gross {sub['r2.0'].add(sub['fee_r']).mean():+.3f}R)")

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out_dir, exist_ok=True)
    for name, t in results.items():
        if not t.empty:
            safe = name.split(".")[0]
            t.to_csv(os.path.join(out_dir, f"setups_{safe}.csv"), index=False)
    print(f"\nPer-setup trade logs written to {out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
