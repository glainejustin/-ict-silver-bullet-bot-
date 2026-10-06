"""
Tests for core/trade_ledger.py and core/health_monitor.py.

These guard behaviour that only shows up in production: an R computed from the
wrong denominator, a halt that does not survive a restart, an alert that spams
every loop iteration, or a stop rule that fires on an incomplete window.

Run: python tests/test_health_monitor.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.trade_ledger import TradeLedger, compute_r, rolling_expectancy  # noqa: E402
from core.health_monitor import (  # noqa: E402
    HealthMonitor, evaluate_edge, silence_days,
)

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILED.append(name)


class StubMT5:
    """Minimal stand-in for the two history call styles."""

    DEAL_ENTRY_OUT = 1

    def __init__(self, deals_by_position):
        self._deals = deals_by_position

    def history_deals_get(self, *args, **kwargs):
        # date-range form (what reconcile uses) -> every deal
        if kwargs or len(args) == 2:
            out = []
            for group in self._deals.values():
                out.extend(group)
            return out or None
        return self._deals.get(kwargs.get("position"), [])


class DealP:
    def __init__(self, profit, commission=0.0, swap=0.0, price=0.0, entry=1,
                 time=0, position_id=0, magic=1):
        self.profit, self.commission, self.swap = profit, commission, swap
        self.price, self.entry, self.time = price, entry, time
        self.position_id, self.magic = position_id, magic


def Deal(profit, commission=0.0, swap=0.0, price=0.0, entry=1, time=0,
         position_id=0, magic=1):
    return DealP(profit, commission, swap, price, entry, time, position_id, magic)


def main() -> int:
    print("trade ledger + health monitor tests\n")

    # ---- pure maths -------------------------------------------------------
    check("R is pnl / risk", compute_r(75.0, 37.5) == 2.0)
    check("R is None without usable risk", compute_r(50.0, 0) is None)
    check("losing R is negative", compute_r(-37.5, 37.5) == -1.0)
    check("rolling expectancy needs a full window",
          rolling_expectancy([1.0] * 19, 20) is None)
    check("rolling expectancy uses the most recent window",
          rolling_expectancy([9.0, 1.0, 1.0], 2) == 1.0)

    # ---- edge rule --------------------------------------------------------
    halt, why = evaluate_edge(0.10, 20, 20, -0.30)
    check("healthy edge does not halt", not halt, why[:40])
    halt, why = evaluate_edge(-0.31, 20, 20, -0.30)
    check("edge at the stop line halts", halt, why[:50])
    halt, why = evaluate_edge(-0.45, 8, 30, -0.30)
    check("incomplete window never halts", not halt, why[:45])
    # the calibration that chose the window: 30 trades is the shipped setting, and
    # a 20-trade bad run must NOT halt it (a 20-trade window was rejected for
    # firing on 8.2% of random draws of the validated distribution)
    check("a bad 20-trade run does not halt the shipped 30-trade window",
          not evaluate_edge(-0.40, 20, 30, -0.30)[0])
    halt, _ = evaluate_edge(None, 0, 20, -0.30)
    check("no closed trades never halts", not halt)

    # ---- silence ----------------------------------------------------------
    now = datetime(2026, 10, 6, 12, 0, 0)
    check("silence_days is None with no history", silence_days(None, now) is None)
    check("silence_days counts days",
          abs(silence_days(now - timedelta(days=61), now) - 61) < 1e-6)

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "ledger.jsonl")
        state = os.path.join(td, "health.json")
        led = TradeLedger(path)

        # ---- persistence round-trip --------------------------------------
        led.record_open(101, "XAUUSD", "GoldTrend", entry=3841.2, sl=3803.7,
                        lots=0.01, risk_cash=37.5, opened=now - timedelta(days=30))
        led.record_open(102, "XAUUSD", "GoldTrend", entry=3900.0, sl=3860.0,
                        lots=0.01, risk_cash=40.0, opened=now - timedelta(days=20))
        check("two trades open", len(led.open_trades) == 2)
        reloaded = TradeLedger(path)
        check("ledger survives a restart", len(reloaded.records) == 2,
              f"{len(reloaded.records)} records")
        check("open trade has no R yet", reloaded.closed_trades == [])

        # ---- reconcile from broker history -------------------------------
        # position ids: 101 matches the ORDER ticket, 102 matches only the
        # opening DEAL ticket -- the account-type difference that would otherwise
        # leave a record open forever.
        reloaded.records[1].deal = 902
        stub = StubMT5({
            101: [Deal(-20.0, commission=-3.5, price=3803.7, entry=1, time=100, position_id=101),
                  Deal(-15.0, commission=-3.5, price=3803.7, entry=1, time=101, position_id=101)],
            902: [Deal(80.0, commission=-3.5, price=3940.0, entry=1, time=200, position_id=902)],
        })
        reloaded._save()
        n = reloaded.reconcile(stub)
        check("reconcile closes both trades", n == 2, f"closed {n}")
        first = [r for r in reloaded.records if r.ticket == 101][0]
        check("net P&L includes commission", abs(first.pnl - (-42.0)) < 1e-9,
              f"pnl={first.pnl}")
        check("R uses the risk recorded at entry", abs(first.r - (-1.12)) < 1e-9,
              f"R={first.r:.4f}")
        check("closed trades are ordered oldest-first",
              [r.ticket for r in reloaded.closed_trades] == [101, 102])
        check("reconcile is idempotent", reloaded.reconcile(stub) == 0)

        # ---- edge halt ----------------------------------------------------
        led2 = TradeLedger(os.path.join(td, "ledger2.jsonl"))
        for i in range(20):
            led2.record_open(200 + i, "XAUUSD", "GoldTrend", entry=1.0, sl=0.9,
                             lots=0.01, risk_cash=10.0,
                             opened=now - timedelta(days=100 - i))
            led2.close(200 + i, pnl_net=-5.0)          # every trade -0.5R
        mon = HealthMonitor(led2, silence_days_limit=60, edge_window=20,
                            edge_threshold_r=-0.30, state_path=state)
        check("shipped defaults use a 30-trade window",
              HealthMonitor(led2, state_path=state).edge_window == 30)
        blocked, reason = mon.should_block_entries(now)
        check("20 x -0.5R halts new entries", blocked, reason[:60])
        check("halt is persisted", HealthMonitor(led2, state_path=state).state.halted)
        reloaded_mon = HealthMonitor(led2, state_path=state)
        check("halted bot stays halted after restart",
              reloaded_mon.should_block_entries(now)[0])
        reloaded_mon.clear_halt("reviewed logs")
        fresh = HealthMonitor(led2, edge_window=20, edge_threshold_r=-0.30,
                              state_path=state)
        check("manual clear re-enables entries", not fresh.should_block_entries(now)[0])
        check("after a resume the window is empty, not inherited",
              fresh.ledger.rolling_expectancy(20) == -0.5
              and fresh.status_line().endswith("ok"),
              fresh.status_line())
        # and it must halt again once a NEW full window of bad trades closes
        for i in range(20):
            t = 900 + i
            fresh.ledger.record_open(t, "XAUUSD", "GoldTrend", entry=1.0, sl=0.9,
                                     lots=0.01, risk_cash=10.0,
                                     opened=now + timedelta(minutes=i))
            fresh.ledger.close(t, pnl_net=-4.0,
                               closed=now + timedelta(days=1, minutes=i))
        later = now + timedelta(days=2)
        check("a new bad window halts again", fresh.should_block_entries(later)[0])

        # ---- silence alert, and no spam -----------------------------------
        led3 = TradeLedger(os.path.join(td, "ledger3.jsonl"))
        led3.record_open(300, "XAUUSD", "GoldTrend", entry=1.0, sl=0.9, lots=0.01,
                         risk_cash=10.0, opened=now - timedelta(days=75))
        mon3 = HealthMonitor(led3, silence_days_limit=60,
                             state_path=os.path.join(td, "health3.json"))
        msg = mon3.due_silence_alert(now)
        check("75 days of silence raises an alert", msg is not None and "75" in msg)
        check("alert does not repeat immediately",
              mon3.due_silence_alert(now + timedelta(hours=1)) is None)
        check("alert repeats after the repeat interval",
              mon3.due_silence_alert(now + timedelta(days=31)) is not None)
        mon3.silence_days_limit = 400
        check("silence under the limit is quiet",
              mon3.due_silence_alert(now + timedelta(days=200)) is None)

        # ---- empty ledger is itself a signal ------------------------------
        led4 = TradeLedger(os.path.join(td, "ledger4.jsonl"))
        mon4 = HealthMonitor(led4, state_path=os.path.join(td, "health4.json"))
        msg = mon4.due_silence_alert(now)
        check("empty ledger warns once", msg is not None and "NO TRADES" in msg.upper())
        check("empty-ledger warning does not spam",
              mon4.due_silence_alert(now + timedelta(minutes=5)) is None)

        # ---- safety: the monitor never blocks when disabled ----------------
        mon5 = HealthMonitor(led2, enabled=False, state_path=state)
        check("disabled monitor never blocks", not mon5.should_block_entries(now)[0])

    print()
    if FAILED:
        print(f"❌ {len(FAILED)} test(s) failed: {', '.join(FAILED)}")
        return 1
    print("✅ all trade ledger / health monitor tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
