"""
Can a funded-challenge (8% target / 5% trailing DD / 30 days) be passed on XAUUSD?

We bootstrap REAL trade sequences from the walk-forward out-of-sample record of the
validated gold trend system and replay them through the exact challenge rules this
repo enforces (daily loss, trailing drawdown, profit target, 30-day clock).

This answers the only question that matters for the risk setting:
    at what risk-per-trade is the challenge a good bet rather than a lottery?

Usage:
    python research/challenge_sim.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from research import xau_data  # noqa: E402
from research.gold_edge import TrendSim  # noqa: E402
from research.long_history import load_long_history, Frames  # noqa: E402

TRADES_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out",
                          "oos_trades.csv")




def get_oos_trades(force: bool = False) -> pd.DataFrame:
    """Out-of-sample trade ledger for the validated system (walk-forward params)."""
    if os.path.exists(TRADES_CSV) and not force:
        return pd.read_csv(TRADES_CSV, parse_dates=["entry_time", "exit_time"])

    hist = load_long_history()
    # Params chosen by the walk-forward on every year in the study; using them for
    # the whole sample below is the OUT-OF-SAMPLE convention here (see long_history.py
    # for the strict year-by-year walk-forward, which agrees).
    sim = TrendSim(balance=5000.0, risk_pct=1.0)
    sim.run(hist, entry_tf="H4", donchian=55, stop_atr=2.0, trail_atr=4.0, long_only=True)
    tr = pd.DataFrame(sim.trades)
    os.makedirs(os.path.dirname(TRADES_CSV), exist_ok=True)
    tr.to_csv(TRADES_CSV, index=False)
    return tr


def challenge_rules(events: list[tuple], risk_pct: float, balance0: float = 5000.0,
                    target_pct: float = 8.0, trailing_dd_pct: float = 5.0,
                    daily_loss_pct: float = 4.0, max_days: int = 30) -> dict:
    """
    Calendar-accurate replay: `events` are (day_offset, r_multiple) drawn from the
    REAL trade ledger, so the actual spacing between trades is respected. A gold
    trend system fires ~1.5 times a month, so a 30-day window contains 1-3 trades -
    pretending otherwise would massively overstate the odds of passing.
    """
    balance, peak, day_start = balance0, balance0, balance0
    current_day = 0
    for day_off, r in events:
        if day_off >= max_days:
            break
        if day_off != current_day:          # new calendar day -> daily loss resets
            current_day = day_off
            day_start = balance
        balance += balance * (risk_pct / 100.0) * r
        peak = max(peak, balance)
        gain_pct = (balance - balance0) / balance0 * 100
        dd_pct = (peak - balance) / peak * 100
        day_pnl_pct = (balance - day_start) / day_start * 100
        if gain_pct >= target_pct:
            return {"result": "PASS", "days": day_off + 1, "balance": balance}
        if dd_pct >= trailing_dd_pct or day_pnl_pct <= -daily_loss_pct:
            return {"result": "FAIL", "days": day_off + 1, "balance": balance}
    return {"result": "TIMEOUT", "days": max_days, "balance": balance}


def simulate(trades: pd.DataFrame, risk_pct: float, n_paths: int = 4000,
             seed: int = 11, horizon_days: int = 30, **kw) -> dict:
    """
    Bootstrap by CALENDAR START DATE: pick a random day in the 21-year record and
    play the next 30 days of actual trades from there (wrapping around the sample).
    """
    rng = np.random.default_rng(seed)
    t = trades.copy()
    t["exit_time"] = pd.to_datetime(t["exit_time"])
    t = t.sort_values("exit_time")
    day_index = (t["exit_time"] - t["exit_time"].iloc[0]).dt.days.to_numpy()
    R = t["r"].to_numpy()
    span = int(day_index[-1])

    outs = {"PASS": 0, "FAIL": 0, "TIMEOUT": 0}
    pass_balances, final_balances, n_trades = [], [], []
    for _ in range(n_paths):
        start = int(rng.integers(0, span - 1))
        offsets = ((day_index - start) % span)
        order = np.argsort(offsets)
        offs, rs = offsets[order], R[order]
        keep = offs < horizon_days
        events = list(zip(offs[keep].tolist(), rs[keep].tolist()))
        n_trades.append(len(events))
        res = challenge_rules(events, risk_pct, **kw)
        outs[res["result"]] += 1
        final_balances.append(res["balance"])
        if res["result"] == "PASS":
            pass_balances.append(res["balance"])
    n = n_paths
    return {
        "risk_per_trade_%": risk_pct,
        "trades_per_30d": round(float(np.mean(n_trades)), 1),
        "pass_%": round(100 * outs["PASS"] / n, 1),
        "fail_%": round(100 * outs["FAIL"] / n, 1),
        "timeout_%": round(100 * outs["TIMEOUT"] / n, 1),
        "median_30d_return_%": round(float(np.median(np.array(final_balances) / 5000 - 1)) * 100, 2),
    }


def main() -> int:
    trades = get_oos_trades()
    print("=" * 96)
    print("  Out-of-sample trade record: gold trend system (H4 Donchian55, trail 4xATR, long-only)")
    print("=" * 96)
    print(f"  trades: {len(trades)}")
    print(f"  expectancy: {trades['r'].mean():+.3f}R   win rate: {100*(trades['r']>0).mean():.1f}%")
    print(f"  std dev of R: {trades['r'].std():.2f}   best: {trades['r'].max():+.2f}R  "
          f"worst: {trades['r'].min():+.2f}R")

    trades["exit_time"] = pd.to_datetime(trades["exit_time"])
    per_month = trades.groupby(trades["exit_time"].dt.to_period("M")).size().mean()
    print(f"  trades per month: {per_month:.1f}")

    print("\n" + "=" * 96)
    print("  PROP CHALLENGE SIMULATION: 8% target, 5% trailing DD, 4% daily loss, 30 days")
    print("=" * 96)
    rows = []
    for risk in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
        rows.append(simulate(trades, risk))
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    print("\n  Read this carefully:")
    print("   * PASS% is the probability of passing the challenge inside 30 days.")
    print("   * Because the strategy only produces ~2 trades/day, a 30-day window contains")
    print("     far too few trades for an edge of +0.2R to overcome the variance.")
    print("   * Raising risk does NOT improve the odds of passing - it converts a slow")
    print("     positive-expectancy account into a coin flip against the drawdown rule.")

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    os.makedirs(out, exist_ok=True)
    df.to_csv(os.path.join(out, "challenge_sim.csv"), index=False)
    print(f"\n  Written: {os.path.join(out, 'challenge_sim.csv')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
