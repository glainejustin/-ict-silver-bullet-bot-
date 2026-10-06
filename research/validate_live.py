"""
End-to-end validation of the LIVE strategy module.

This does NOT re-implement the strategy. It imports `strategies/gold_trend.py`
exactly as main.py would, feeds it the same frames in the same shape, and applies
the same risk sizing, cost model and trailing management the live bot uses.

Purpose: prove the code that ships behaves the way the research says it does.
Backtests that re-implement a strategy instead of testing it are how live results
end up different from research results.

Usage:
    python research/validate_live.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Import the shipping module under a stubbed config so no MT5 / .env is required.
import types  # noqa: E402
import research.stub_config as stub  # noqa: E402, F401  (registers config stub)

from strategies.gold_trend import GoldTrendStrategy  # noqa: E402
import config  # noqa: E402

from research import xau_data  # noqa: E402

POINT = 0.01
CONTRACT = 100.0


def load(path: str, tf: str) -> pd.DataFrame:
    df = pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(path)
    return df


class LiveReplay:
    """Replays the live decision path: scan on M5, fill at market, trail on ATR."""

    def __init__(self, bs, strategy: GoldTrendStrategy, balance: float = 5000.0,
                 spread_points: float = 25.0, slippage_points: float = 2.0,
                 commission_per_lot: float = 7.0, leverage: int = 100,
                 scan_tf: str = "M5", policy=None):
        self.bs = bs
        self.m5, self.m1 = bs["M5"], bs["M1"]
        self.h1, self.h4 = bs["H1"], bs["H4"]
        self.strategy = strategy
        self.balance0 = balance
        self.balance = balance
        self.spread = spread_points * POINT
        self.slip = slippage_points * POINT
        self.comm = commission_per_lot
        self.leverage = leverage
        self.scan_tf = scan_tf
        self.policy = policy or {}
        self.trades: list[dict] = []
        self.equity: list[tuple] = []
        # fast M1 window lookup per scan bar
        self.m1_time = self.m1.index.values
        self.m1_high = self.m1["high"].to_numpy(float)
        self.m1_low = self.m1["low"].to_numpy(float)
        self.m1_close = self.m1["close"].to_numpy(float)
        # O(1) frame slicing: precompute each timeframe's timestamp array so the
        # replay never does a boolean mask over the full frame per scan bar.
        self.idx = {tf: df.index.values for tf, df in bs.frames.items()}
        # causal ATR per timeframe (identical to a live rolling(14) ATR lookup)
        self.atr_series = {}
        for tf, df in bs.frames.items():
            h, l, c = df["high"], df["low"], df["close"]
            pc = c.shift(1)
            tr = pd.concat([(h - l).abs(), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
            self.atr_series[tf] = tr.rolling(14).mean().to_numpy(float)
        # the strategy can only change its mind when a new bar of ITS timeframe starts
        self.strat_tf_idx = self.idx[self.strategy.timeframe]
        self.scan_bar_of_strat_bar = np.searchsorted(
            self.idx[self.scan_tf], self.strat_tf_idx, side="right") - 1

    # ---------------------------------------------------------------- sizing ---
    def _lots(self, entry: float, stop: float) -> float:
        risk_cash = self.balance * float(config.RISK_PERCENT) / 100.0
        dist = abs(entry - stop)
        if dist <= 0:
            return 0.0
        lots = risk_cash / (dist * CONTRACT)
        lots = np.floor(lots / 0.01) * 0.01
        if lots < 0.01:
            # risk_manager blocks trades whose minimum lot overshoots risk by >50%
            if (0.01 * dist * CONTRACT) / self.balance * 100 > config.RISK_PERCENT * 1.5:
                return 0.0
            lots = 0.01
        max_lots = (self.balance * self.leverage) / (entry * CONTRACT)
        return float(min(lots, np.floor(max_lots / 0.01) * 0.01))

    # -------------------------------------------------------------------- run ---
    def run(self, start_idx: int = 250) -> dict:
        scan = self.bs[self.scan_tf]
        scan_start_m1 = np.searchsorted(self.m1_time, scan.index.values, side="left")
        self.scan_to_m1 = scan_start_m1

        pos = None
        self._last_strat_bar = None
        for i in range(start_idx, len(scan) - 2):
            t = scan.index[i]

            # ---------------- manage open position on the M1 path ----------------
            if pos is not None:
                s, e = scan_start_m1[i], scan_start_m1[i + 1]
                closed = False
                for j in range(s, e):
                    hi, lo = self.m1_high[j], self.m1_low[j]
                    if pos["dir"] > 0:
                        if lo <= pos["stop"]:
                            self._close(pos, pos["stop"] - self.spread / 2 - self.slip, self.m1.index[j])
                            closed = True
                            break
                        pos["ext"] = max(pos["ext"], hi)
                    else:
                        if hi >= pos["stop"]:
                            self._close(pos, pos["stop"] + self.spread / 2 + self.slip, self.m1.index[j])
                            closed = True
                            break
                        pos["ext"] = min(pos["ext"], lo)
                if closed:
                    pos = None
                else:
                    # trail with the ATR of the management timeframe (live TradeManager policy)
                    atr = self._atr(pos["trail_tf"], i)
                    if np.isfinite(atr) and atr > 0:
                        if pos["dir"] > 0:
                            pos["stop"] = max(pos["stop"], pos["ext"] - pos["trail_mult"] * atr)
                        else:
                            pos["stop"] = min(pos["stop"], pos["ext"] + pos["trail_mult"] * atr)

            self.equity.append((t, self.balance + self._open_pnl(pos, i)))

            if pos is not None:
                continue

            # ---------------- scan exactly like main.py ----------------
            # main.py re-scans every M5 bar, but this strategy's inputs (closed H4
            # bars) only change when a new H4 bar opens, so we only need to call it
            # then. This is equivalent, not an approximation.
            new_bar = (self._last_strat_bar != self._strat_bar_at(i))
            self._last_strat_bar = self._strat_bar_at(i)
            if not new_bar:
                continue
            ltf = self.bs[self.scan_tf].iloc[max(0, i - 99): i + 1]
            htf = self._tail("H1", i, 300)
            struct = self._tail("H4", i, 300)
            sig = self.strategy.generate_signal(ltf, htf, struct, t)
            if sig["signal"] != "BUY":
                continue

            entry = self.m5["open"].iloc[i + 1] if i + 1 < len(self.m5) else None
            if entry is None:
                continue
            entry = float(entry) + self.spread / 2 + self.slip
            stop = float(sig["sl"])
            if stop >= entry:
                continue
            lots = self._lots(entry, stop)
            if lots <= 0:
                continue
            mg = sig.get("manage", {})
            min_stop = getattr(config, "MIN_STOP_DISTANCE_POINTS", {"XAUUSD": 200}).get("XAUUSD", 0)
            if abs(entry - stop) < min_stop * POINT:
                continue
            pos = {
                "dir": 1, "entry": entry, "stop": stop, "lots": lots,
                "ext": entry, "entry_time": self.m5.index[i + 1],
                "trail_mult": mg.get("trail_atr_mult", 4.0),
                "trail_tf": mg.get("trail_atr_timeframe", "H4"),
                "risk": abs(entry - stop),
            }
        if pos is not None:
            self._close(pos, float(self.m1_close[-1]), self.m1.index[-1])
        return self.metrics()

    def _strat_bar_at(self, i: int):
        """Index of the strategy timeframe bar currently in progress."""
        return int(np.searchsorted(self.strat_tf_idx, self.idx[self.scan_tf][i], side="right")) - 1

    def _tail(self, tf: str, i: int, n: int) -> pd.DataFrame:
        """Bars of `tf` whose start time is <= the scan bar's start time."""
        arr = self.idx[tf]
        t = self.idx[self.scan_tf][i]
        end = int(np.searchsorted(arr, t, side="right"))
        return self.bs[tf].iloc[max(0, end - n): end]

    def _atr(self, tf: str, i: int) -> float:
        """ATR of the last bar of `tf` that starts at or before scan bar i."""
        pos = int(np.searchsorted(self.idx[tf], self.idx[self.scan_tf][i], side="right")) - 1
        if pos < 0:
            return float("nan")
        return float(self.atr_series[tf][pos])

    def _open_pnl(self, pos, i) -> float:
        """
        Mark-to-market of the open position.

        NB: the M1 position of every scan bar is precomputed (self.scan_to_m1).
        Calling np.searchsorted(m1_index, Timestamp) inside this per-bar helper
        cost 5.6ms per call here -- 380s over a two-year replay -- because numpy
        re-converts the datetime64 index on every call. Precomputing is O(1).
        """
        if pos is None:
            return 0.0
        j = int(self.scan_to_m1[i])
        j = min(max(j, 0), len(self.m1_close) - 1)
        px = float(self.m1_close[j])
        return (px - pos["entry"]) * pos["dir"] * CONTRACT * pos["lots"]

    def _close(self, pos, price, ts) -> None:
        pnl = (price - pos["entry"]) * pos["dir"] * CONTRACT * pos["lots"] - self.comm * pos["lots"]
        self.balance += pnl
        self.trades.append({"entry_time": pos["entry_time"], "exit_time": ts, "lots": pos["lots"],
                            "entry": pos["entry"], "exit": price, "pnl": pnl,
                            "r": pnl / (pos["risk"] * CONTRACT * pos["lots"]),
                            "balance": self.balance, "stop": pos["stop"]})

    def metrics(self) -> dict:
        t = pd.DataFrame(self.trades)
        if t.empty:
            return {"trades": 0}
        eq = pd.Series([e for _, e in self.equity])
        dd = (eq / eq.cummax() - 1).min() * 100
        wins, losses = t[t["pnl"] > 0], t[t["pnl"] <= 0]
        years = (self.bs[self.scan_tf].index[-1] - self.bs[self.scan_tf].index[0]).days / 365.25
        return {
            "trades": len(t),
            "final_balance": round(self.balance, 2),
            "return_%": round((self.balance / self.balance0 - 1) * 100, 2),
            "CAGR_%": round(((self.balance / self.balance0) ** (1 / years) - 1) * 100, 2),
            "max_dd_%": round(float(dd), 2),
            "win_%": round(100 * len(wins) / len(t), 1),
            "PF": round(wins["pnl"].sum() / abs(losses["pnl"].sum()), 2) if len(losses) else np.inf,
            "expectancy_R": round(t["r"].mean(), 3),
            "trades_per_month": round(len(t) / (years * 12), 2),
        }


def main() -> int:
    bs = xau_data.build()
    print("=" * 96)
    print("  LIVE MODULE VALIDATION - strategies/gold_trend.py replayed through the bot's own pipeline")
    print("=" * 96)
    print(f"  data: {bs['M1'].index[0].date()} -> {bs['M1'].index[-1].date()} (M1, broker clock)")
    print(f"  config: lookback={config.GOLD_TREND_LOOKBACK} stop={config.GOLD_TREND_STOP_ATR}xATR "
          f"trail={config.GOLD_TREND_TRAIL_ATR}xATR risk={config.RISK_PERCENT}%/trade "
          f"min_stop={config.MIN_STOP_DISTANCE_POINTS.get('XAUUSD')}pts")

    strat = GoldTrendStrategy("GoldTrend_XAUUSD", "XAUUSD", timeframe=config.GOLD_TREND_TIMEFRAME)
    replay = LiveReplay(bs, strat, balance=5000.0)
    m = replay.run()
    print("\n  RESULT (live code path, realistic gold costs):")
    for k, v in m.items():
        print(f"    {k:<18} {v}")

    tr = pd.DataFrame(replay.trades)
    if not tr.empty:
        tr["year"] = pd.to_datetime(tr["exit_time"]).dt.year
        print("\n  per-year:")
        for y, g in tr.groupby("year"):
            w = g[g["pnl"] > 0]
            print(f"    {y}: {len(g):>3} trades  P/L ${g['pnl'].sum():>8.2f}  "
                  f"win% {100*len(w)/len(g):>5.1f}  avg {g['r'].mean():+.2f}R")

    out = os.path.join(ROOT, "research", "out")
    os.makedirs(out, exist_ok=True)
    tr.to_csv(os.path.join(out, "live_validation_trades.csv"), index=False)
    print(f"\n  trade log -> {os.path.join(out, 'live_validation_trades.csv')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
