"""
Two last edge classes for XAUUSD, tested properly.

1. INTRADAY DRIFT / SEASONALITY
   Gold's return is not uniform across the 24h clock. We measure the mean return
   per NY-clock hour per year, with t-statistics, and separate the drift component
   that any long-biased system would harvest from genuine time-of-day structure.

2. TREND FOLLOWING WITH TRAILING STOPS
   Fixed-barrier tests (1R/2R/3R targets) systematically UNDERSTATE trend systems:
   they cap the right tail, which is exactly where trend-following earns its money.
   Here we simulate a Donchian breakout with an ATR trailing stop, full equity
   compounding, realistic costs, and prop-firm style risk metrics.

Usage:
    python research/gold_edge.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from research import xau_data  # noqa: E402

POINT = 0.01
CONTRACT = 100.0


# --------------------------------------------------------------------- part 1 ---
def intraday_drift(bs: xau_data.BarSet) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Mean M5 return (in $) by NY hour, per year, with t-stats."""
    m5 = bs["M5"].copy()
    m5["ret"] = m5["close"].diff()
    m5["year"] = m5["ny"].dt.year
    m5["hour"] = m5["ny_hour"].astype(int)

    pivot = m5.pivot_table(index="hour", columns="year", values="ret", aggfunc="mean")
    tstat = m5.groupby(["year", "hour"])["ret"].agg(["mean", "std", "count"])
    tstat["t"] = tstat["mean"] / (tstat["std"] / np.sqrt(tstat["count"]))
    t_pivot = tstat.reset_index().pivot(index="hour", columns="year", values="t")
    return pivot.round(3), t_pivot.round(2)


# --------------------------------------------------------------------- part 2 ---
class TrendSim:
    """
    Donchian breakout with ATR trailing stop, fully compounded.

    Risk model: risk_per_trade % of equity per trade, sized so that a stop-out
    loses exactly that. Position sizes are capped by leverage.
    """

    def __init__(
        self,
        balance: float = 5000.0,
        risk_pct: float = 0.5,
        spread_points: float = 25.0,
        commission_per_lot: float = 7.0,
        slippage_points: float = 2.0,
        leverage: int = 100,
        point: float = POINT,
        contract: float = CONTRACT,
        lot_step: float = 0.01,
        min_lot: float = 0.0,
    ):
        self.balance0 = balance
        self.balance = balance
        self.risk_pct = risk_pct
        # point/contract are overridable so the same simulator can model FX:
        # gold is 0.01 / 100, a 5-digit FX pair is 0.0001 / 100000. Defaults are
        # the gold values, so every existing research result is unchanged.
        self.point = point
        self.contract = contract
        # Position-size granularity. Gold brokers quote 0.01 lots, which is far
        # too coarse for JPY pairs on a small account: an ideal 0.0248-lot
        # USDJPY position floors to 0.00 and the trade silently disappears.
        # min_lot lets the model take the broker minimum instead of skipping.
        self.lot_step = lot_step
        self.min_lot = min_lot
        self.spread = spread_points * point
        self.slip = slippage_points * point
        self.comm = commission_per_lot
        self.leverage = leverage
        self.trades: list[dict] = []
        self.equity_curve: list[tuple] = []

    # ---------------------------------------------------------------- helpers ---
    def _size(self, entry: float, stop: float) -> float:
        risk_cash = self.balance * self.risk_pct / 100.0
        risk_price = abs(entry - stop)
        if risk_price <= 0:
            return 0.0
        lots = risk_cash / (risk_price * self.contract)
        max_lots = (self.balance * self.leverage) / (entry * self.contract)
        lots = min(lots, max_lots)
        lots = np.floor(lots / self.lot_step) * self.lot_step
        if lots < self.min_lot:
            lots = self.min_lot
        return round(lots, 6)

    def run(self, bs: xau_data.BarSet, entry_tf: str = "H1", donchian: int = 55,
            atr_period: int = 20, trail_atr: float = 3.0, stop_atr: float = 2.0,
            long_only: bool = False, allow_short: bool = True, max_hold_days: int = 0,
            breakeven_at_r: float = 0.0) -> dict:
        """
        Entry  : close breaks the prior `donchian`-bar high (long) or low (short)
        Initial: stop_atr x ATR
        Trail  : chandelier stop, trail_atr x ATR from the extreme
        """
        d = bs[entry_tf]
        m1 = bs["M1"]
        high = d["high"].to_numpy(float)
        low = d["low"].to_numpy(float)
        close = d["close"].to_numpy(float)
        open_ = d["open"].to_numpy(float)
        prev = np.concatenate([[np.nan], close[:-1]])
        tr = np.nanmax(np.vstack([high - low, np.abs(high - prev), np.abs(low - prev)]), axis=0)
        atr = pd.Series(tr, index=d.index).rolling(atr_period).mean().to_numpy()
        hh = pd.Series(high, index=d.index).rolling(donchian).max().shift(1).to_numpy()
        ll = pd.Series(low, index=d.index).rolling(donchian).min().shift(1).to_numpy()

        # fast M1 lookup so intrabar stop checks use the right window
        m1_time = m1.index.values
        m1_high, m1_low = m1["high"].to_numpy(float), m1["low"].to_numpy(float)
        starts = np.searchsorted(m1_time, d.index.values, side="left")

        pos = None
        n = len(d)
        for i in range(max(donchian, atr_period) + 2, n - 1):
            if not np.isfinite(atr[i]) or atr[i] <= 0:
                continue
            # ---------------- manage an open position on the M1 path ----------------
            if pos is not None:
                s = starts[i]
                e = min(starts[i + 1], len(m1_high))
                if e > s:
                    seg_hi, seg_lo = m1_high[s:e], m1_low[s:e]
                    for hi_p, lo_p in zip(seg_hi, seg_lo):
                        # pessimistic: stop first within the minute
                        if pos["dir"] > 0 and lo_p <= pos["stop"]:
                            self._close(pos, pos["stop"] - self.spread / 2 - self.slip, d.index[i])
                            pos = None
                            break
                        if pos["dir"] < 0 and hi_p >= pos["stop"]:
                            self._close(pos, pos["stop"] + self.spread / 2 + self.slip, d.index[i])
                            pos = None
                            break
                        pos["ext"] = max(pos["ext"], hi_p) if pos["dir"] > 0 else min(pos["ext"], lo_p)
                    if pos is not None:
                        # ratchet the trailing stop
                        if pos["dir"] > 0:
                            pos["stop"] = max(pos["stop"], pos["ext"] - trail_atr * atr[i])
                        else:
                            pos["stop"] = min(pos["stop"], pos["ext"] + trail_atr * atr[i])
                        if breakeven_at_r > 0:
                            r_now = (pos["ext"] - pos["entry"]) * pos["dir"] / pos["risk"]
                            if r_now >= breakeven_at_r:
                                pos["stop"] = max(pos["stop"], pos["entry"]) if pos["dir"] > 0 \
                                    else min(pos["stop"], pos["entry"])

            if pos is None:
                go_long = close[i] > hh[i]
                go_short = (close[i] < ll[i]) and allow_short and not long_only
                if go_long or go_short:
                    direction = 1 if go_long else -1
                    entry = open_[i + 1] + direction * (self.spread / 2 + self.slip)
                    stop = entry - direction * stop_atr * atr[i]
                    lots = self._size(entry, stop)
                    if lots <= 0:
                        continue
                    pos = {
                        "dir": direction, "entry": entry, "stop": stop, "lots": lots,
                        "risk": abs(entry - stop), "ext": entry,
                        "entry_time": d.index[i + 1], "i": i + 1,
                    }
        # final liquidation
        if pos is not None:
            self._close(pos, close[-1], d.index[-1])
        return self.metrics(bs)

    # ------------------------------------------------------------------ ledger ---
    def _close(self, pos: dict, exit_price: float, ts) -> None:
        gross = (exit_price - pos["entry"]) * pos["dir"] * self.contract * pos["lots"]
        comm = self.comm * pos["lots"]
        pnl = gross - comm
        self.balance += pnl
        self.trades.append({
            "entry_time": pos["entry_time"], "exit_time": ts, "dir": pos["dir"],
            "lots": pos["lots"], "entry": pos["entry"], "exit": exit_price,
            "pnl": pnl, "r": pnl / (pos["risk"] * self.contract * pos["lots"]),
            "balance": self.balance,
        })

    def metrics(self, bs: xau_data.BarSet) -> dict:
        t = pd.DataFrame(self.trades)
        if t.empty:
            return {"trades": 0}
        eq = t.set_index("exit_time")["balance"]
        roll_max = eq.cummax()
        dd = (eq / roll_max - 1) * 100
        wins, losses = t[t["pnl"] > 0], t[t["pnl"] <= 0]
        span_years = (bs["M1"].index[-1] - bs["M1"].index[0]).days / 365.25
        cagr = ((self.balance / self.balance0) ** (1 / span_years) - 1) * 100
        return {
            "trades": len(t),
            "final_balance": round(self.balance, 2),
            "return_pct": round((self.balance / self.balance0 - 1) * 100, 1),
            "CAGR_pct": round(cagr, 1),
            "max_dd_pct": round(dd.min(), 2),
            "win_rate": round(100 * len(wins) / len(t), 1),
            "profit_factor": round(wins["pnl"].sum() / abs(losses["pnl"].sum()), 2)
            if len(losses) else np.inf,
            "expectancy_R": round(t["r"].mean(), 3),
            "avg_win_R": round(wins["r"].mean(), 2) if len(wins) else 0,
            "avg_loss_R": round(losses["r"].mean(), 2) if len(losses) else 0,
            "longest_dd_days": int((dd.index.to_series().diff().dt.days.fillna(0)
                                    [dd < -5]).sum()) if len(dd) else 0,
            "trades_per_month": round(len(t) / (span_years * 12), 1),
        }


def buy_hold(bs: xau_data.BarSet, balance: float = 5000.0, lots: float = 1.0) -> dict:
    """Reference: hold 1 lot of gold for the whole sample."""
    d = bs["H1"]
    entry, exit_ = d["open"].iloc[0], d["close"].iloc[-1]
    pnl = (exit_ - entry) * CONTRACT * lots
    eq = balance + pnl
    return {"trades": 1, "final_balance": round(eq, 2),
            "return_pct": round(pnl / balance * 100, 1),
            "note": f"1.0 lot from {entry:.0f} to {exit_:.0f}"}


def main() -> int:
    bs = xau_data.build()
    year_lo, year_hi = bs["M1"].index[0].year, bs["M1"].index[-1].year
    print(f"XAUUSD {bs['M1'].index[0]} -> {bs['M1'].index[-1]}  "
          f"({len(bs['M1']):,} M1 bars)\n")

    print("=" * 90)
    print("  PART 1: mean M5 return ($) by NY hour and year")
    print("=" * 90)
    pivot, tstats = intraday_drift(bs)
    print(pivot.to_string())
    print("\n  t-statistics (|t| > 2 = statistically meaningful):")
    print(tstats.to_string())

    print("\n" + "=" * 90)
    print("  PART 2: Donchian trend following with ATR trailing stop")
    print("=" * 90)
    results = []
    configs = [
        ("H1 Donchian55 trail3 long+short", dict(entry_tf="H1", donchian=55, trail_atr=3.0)),
        ("H1 Donchian55 trail3 long-only", dict(entry_tf="H1", donchian=55, trail_atr=3.0, long_only=True)),
        ("H1 Donchian100 trail3 long+short", dict(entry_tf="H1", donchian=100, trail_atr=3.0)),
        ("H4 Donchian20 trail3 long+short", dict(entry_tf="H4", donchian=20, trail_atr=3.0)),
        ("H4 Donchian20 trail3 long-only", dict(entry_tf="H4", donchian=20, trail_atr=3.0, long_only=True)),
        ("H4 Donchian55 trail4 long+short", dict(entry_tf="H4", donchian=55, trail_atr=4.0)),
        ("H4 Donchian55 trail2 BE1 long+short", dict(entry_tf="H4", donchian=55, trail_atr=2.0, breakeven_at_r=1.0)),
    ]
    for name, kw in configs:
        sim = TrendSim(balance=5000.0, risk_pct=0.5)
        m = sim.run(bs, **kw)
        results.append({"config": name, **m})
        print(f"\n  {name}")
        print("   ", m)

    bh = buy_hold(bs)
    print(f"\n  BUY & HOLD reference: {bh}")

    out = pd.DataFrame(results)
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"), exist_ok=True)
    out.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "gold_edge.csv"),
               index=False)
    pivot.to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "intraday_drift.csv"))
    print(f"\nWritten to research/out/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
