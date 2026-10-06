"""
Portfolio breadth: does the trend system work on more than gold, and do the
trades diversify?

WHY THIS IS THE NEXT QUESTION
-----------------------------
The validated gold system earns +0.26R per trade and fires ~1.3 times a month.
That is a real edge attached to a very small number of independent bets: 338
trades in 21 years. Almost all of the variation in your yearly result comes from
*how many trades happened to work*, not from the edge -- which is why the honest
expectation is single-digit annual returns with a wide spread of outcomes.

There are only two ways to improve that: raise risk per trade (which raises
drawdown faster, see research/challenge_sim.py) or take MORE INDEPENDENT BETS.
The second is how every real trend-following fund works: the same logic across
20-100 markets, sized small in each, so that the portfolio's outcome depends on
the edge rather than on one instrument's luck.

This script tests the half of that idea I can actually verify with the data at
hand: whether the SAME trend logic is positive on other instruments, and whether
their trade returns are actually uncorrelated.

WHAT IT IS NOT
--------------
* 3.4 years (2023-2026) on 4 instruments -- a mechanism check, not a track
  record. There is not enough data here to estimate a small edge precisely, and
  the period is a strong dollar/rate regime, not a representative one.
* No swap/carry modelled. Multi-day FX positions pay or earn interest, which for
  the short-USD pairs here is not negligible over weeks. Gold's results are
  unaffected; the FX numbers should be read as "before financing".
* Costs are modelled (spread + commission) but FX spreads vary by broker far
  more than gold's does.

Usage: python research/breadth_test.py
Out:   research/out/breadth_results.csv, breadth_monthly.csv, breadth_report.txt
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from research import shipping_config                     # noqa: E402
from research.gold_edge import TrendSim                  # noqa: E402

OUT = os.path.join(HERE, "out")
DATA = os.path.join(HERE, "data")
BREADTH = os.path.join(DATA, "breadth")
RNG = np.random.default_rng(5)

# point    = price units per "point" as passed to the simulator
# contract = units per lot (FX standard lot = 100,000; gold 100oz)
# spread   = typical retail spread in points;  comm = $/lot round turn
SPECS = {
    "XAUUSD": dict(point=0.01, contract=100.0, spread=25.0, comm=7.0),
    "GBPUSD": dict(point=0.0001, contract=100_000.0, spread=1.0, comm=7.0),
    "USDJPY": dict(point=0.01, contract=100_000.0, spread=1.0, comm=7.0),
    "AUDUSD": dict(point=0.0001, contract=100_000.0, spread=1.2, comm=7.0),
    "EURUSD": dict(point=0.0001, contract=100_000.0, spread=0.9, comm=7.0),
}
# A JPY pair's P&L is denominated in JPY, so the ideal position size on a $5k
# account lands under the 0.01-lot broker minimum. Taking the minimum instead of
# skipping means those trades risk less than the nominal 0.5% -- a real
# constraint of a small account, and a caveat on the FX numbers here.
MIN_LOT = {"USDJPY": 0.01, "GBPUSD": 0.01, "AUDUSD": 0.01, "EURUSD": 0.01}


def build_frames(m15: pd.DataFrame, entry_tf: str = "H4") -> dict:
    """Resample M15 into the entry timeframe; TrendSim also wants an 'M1' key."""
    rule = {"H1": "1h", "H4": "4h", "D1": "1D"}[entry_tf]
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    htf = m15.resample(rule, label="left", closed="left").agg(agg).dropna(
        subset=["open", "close"])
    return {"M1": m15, "M15": m15, entry_tf: htf}


def load(symbol: str) -> pd.DataFrame:
    if symbol == "XAUUSD":
        path = os.path.join(DATA, "XAUUSD_M15_2004_2025.parquet")
        df = pd.read_parquet(path)
        df = df.loc["2023-01-01":]          # match the FX window
    else:
        path = os.path.join(BREADTH, f"{symbol}_M15_2023_2026.parquet")
        df = pd.read_parquet(path)
    df = df.rename(columns=str.lower)
    return df[["open", "high", "low", "close"]].dropna()


def run_symbol(symbol: str, params: dict, risk_pct: float = 0.5):
    df = load(symbol)
    spec = SPECS[symbol]
    sim = TrendSim(balance=5000.0, risk_pct=risk_pct,
                   spread_points=spec["spread"], commission_per_lot=spec["comm"],
                   slippage_points=0.0, point=spec["point"], contract=spec["contract"],
                   min_lot=MIN_LOT.get(symbol, 0.0))
    metrics = sim.run(build_frames(df, params["entry_tf"]), **params)
    trades = pd.DataFrame(sim.trades)
    return metrics, trades, df


def monthly_returns(trades: pd.DataFrame) -> pd.Series:
    """Compounded monthly return of a 0.5%-risk-per-trade stream."""
    if trades.empty:
        return pd.Series(dtype=float)
    t = trades.copy()
    t["month"] = pd.to_datetime(t["exit_time"]).dt.to_period("M")
    out = {}
    for m, g in t.groupby("month"):
        eq = 1.0
        for r in g["r"]:
            eq *= (1 + 0.005 * r)
        out[m] = eq - 1
    return pd.Series(out).sort_index()


def bootstrap_expectancy(r: np.ndarray, n: int = 10_000) -> tuple[float, float]:
    """95% CI on mean R by resampling trades."""
    if len(r) < 5:
        return float("nan"), float("nan")
    draws = RNG.choice(r, size=(n, len(r)), replace=True).mean(axis=1)
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    params = shipping_config.trend_kwargs()
    print(f"shipping config: {shipping_config.description()}")
    print(f"window: 2023-01-01 .. 2026-05-29 (gold sliced to match)\n")

    rows, all_trades, monthly = [], {}, {}
    for sym in ("XAUUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURUSD"):
        try:
            metrics, trades, df = run_symbol(sym, params)
        except FileNotFoundError:
            print(f"  {sym}: no data, skipped")
            continue
        if trades.empty:
            print(f"  {sym}: no trades")
            continue
        all_trades[sym] = trades
        monthly[sym] = monthly_returns(trades)
        r = trades["r"].to_numpy()
        lo, hi = bootstrap_expectancy(r)
        wins = trades[trades.pnl > 0]
        losses = trades[trades.pnl <= 0]
        rows.append({
            "symbol": sym, "bars": len(df), "trades": len(trades),
            "expectancy_R": round(float(r.mean()), 3),
            "ci_lo": round(lo, 3), "ci_hi": round(hi, 3),
            "win_%": round(100 * len(wins) / len(trades), 1),
            "PF": round(float(wins.pnl.sum() / abs(losses.pnl.sum())), 2) if len(losses) else np.inf,
            "trades_per_month": round(len(trades) / 41.0, 2),
        })
        print(f"  {sym:7s} {len(trades):4d} trades  exp {r.mean():+.3f}R "
              f"[{lo:+.3f}, {hi:+.3f}]  PF {rows[-1]['PF']}  "
              f"{rows[-1]['trades_per_month']}/month")

    per_symbol = pd.DataFrame(rows)
    per_symbol.to_csv(os.path.join(OUT, "breadth_results.csv"), index=False)

    # ---------------- portfolio view ----------------
    combined = pd.concat([t.assign(symbol=s) for s, t in all_trades.items()])
    combined = combined.sort_values("exit_time")
    port_r = combined["r"].to_numpy()
    lo, hi = bootstrap_expectancy(port_r)
    port_monthly = monthly_returns(combined)

    # correlation of monthly returns between instruments
    mdf = pd.DataFrame(monthly).dropna(how="all")
    mdf.to_csv(os.path.join(OUT, "breadth_monthly.csv"))
    corr = mdf.corr(min_periods=6)
    # average pairwise correlation of the non-gold instruments
    pairs = []
    syms = list(mdf.columns)
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            c = corr.loc[syms[i], syms[j]]
            if np.isfinite(c):
                pairs.append(c)
    avg_corr = float(np.mean(pairs)) if pairs else float("nan")

    # equal-risk portfolio vs gold alone: same 0.5% risk per trade, but every
    # instrument's trades taken (i.e. more bets at the same size per bet)
    def curve_stats(monthly_series: pd.Series) -> tuple[float, float]:
        if monthly_series.empty:
            return float("nan"), float("nan")
        eq = (1 + monthly_series).cumprod()
        dd = float((eq / eq.cummax() - 1).min() * 100)
        years = len(monthly_series) / 12.0
        cagr = float((eq.iloc[-1] ** (1 / years) - 1) * 100) if years > 0 else np.nan
        return cagr, dd

    gold_cagr, gold_dd = curve_stats(monthly["XAUUSD"]) if "XAUUSD" in monthly else (np.nan, np.nan)
    port_cagr, port_dd = curve_stats(port_monthly)

    # a 5000-run bootstrap of the portfolio's monthly series gives an idea of how
    # much of this is luck
    def annualised_drawdown(series: pd.Series, n: int = 2000) -> tuple[float, float]:
        if len(series) < 12:
            return float("nan"), float("nan")
        vals = series.to_numpy()
        cagrs, dds = [], []
        for _ in range(n):
            idx = RNG.integers(0, len(vals), size=12)      # one synthetic year
            eq = np.cumprod(1 + vals[idx])
            dds.append(float((eq / np.maximum.accumulate(eq) - 1).min() * 100))
            cagrs.append(float(eq[-1] - 1) * 100)
        return float(np.percentile(cagrs, 5)), float(np.percentile(dds, 5))

    p5_ret, p5_dd = annualised_drawdown(port_monthly)
    g5_ret, g5_dd = annualised_drawdown(monthly["XAUUSD"]) if "XAUUSD" in monthly else (np.nan, np.nan)

    lines = ["PORTFOLIO BREADTH TEST - same trend logic, more instruments",
             "=" * 78,
             f"Config: {shipping_config.description()}, 0.5% risk per trade",
             "Window: 2023-01-01 .. 2026-05-29 (gold sliced to match; 3.4 years)",
             "Costs: retail spread + $7/lot round turn. No swap/carry modelled.",
             "",
             "WHAT THIS SHOWS: whether the edge is a PROPERTY OF THE LOGIC or a",
             "property of gold. Small samples -- read the confidence intervals.",
             "", "-" * 78, ""]
    for _, r in per_symbol.iterrows():
        lines.append(f"{r['symbol']:7s} {r['trades']:3d} trades  expectancy "
                     f"{r['expectancy_R']:+.3f}R  (95% CI [{r['ci_lo']:+.3f}, {r['ci_hi']:+.3f}])  "
                     f"win {r['win_%']}%  PF {r['PF']}")
    lines += ["", f"Average pairwise monthly-return correlation: {avg_corr:+.2f}"
                  if np.isfinite(avg_corr) else "",
             f"Correlation matrix (monthly returns):", corr.round(2).to_string(), "",
             "-" * 78, "",
             f"PORTFOLIO (all instruments, 0.5% risk per trade):",
             f"  total trades      : {len(combined)}   expectancy {port_r.mean():+.3f}R "
             f"[{lo:+.3f}, {hi:+.3f}]",
             f"  CAGR              : {port_cagr:.1f}%   vs gold alone {gold_cagr:.1f}%",
             f"  max drawdown      : {port_dd:.1f}%   vs gold alone {gold_dd:.1f}%",
             "",
             f"  bootstrap of a random 12-month stretch (5th percentile):",
             f"  portfolio: {p5_ret:+.1f}% return, {p5_dd:.1f}% drawdown",
             f"  gold only: {g5_ret:+.1f}% return, {g5_dd:.1f}% drawdown"]
    txt = "\n".join(l for l in lines if l is not None)
    with open(os.path.join(OUT, "breadth_report.txt"), "w") as fh:
        fh.write(txt)
    print("\n" + txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
