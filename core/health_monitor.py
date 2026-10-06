"""
core/health_monitor.py -- the two guards that catch "silently not working".

The research on 21 years of gold produced two numbers worth turning into code,
because both describe failures that are invisible in a live log:

1. SILENCE. The shipping system averages ~1.3 trades/month, and long stretches
   of nothing are normal. That makes a broken bot indistinguishable from a
   patient one -- and this project has already shipped one bug of exactly that
   shape (a 200-bar average computed over 100 fetched bars silently produced no
   signals at all, with no error in the log). A "no trade in N days" alert is the
   only thing that catches it.

2. EDGE DECAY. A 30-trade rolling expectancy at or below -0.30R NEVER happened in
   the 21-year, 338-trade shipping run (0 of 309 windows), while drawing 30-trade
   stretches at random from that same outcome distribution breaches it 3.6% of
   the time. Rare when the system is working, plausible when it has broken -- and
   0.30R is the level the report's stop rule committed to in advance, so stopping
   is never a judgement call made while losing. (A 20-trade window was tried
   first and rejected: it breached in 2.5% of real windows but 8.2% of random
   draws, i.e. too easily triggered by ordinary variance.)

Neither guard closes positions or cancels orders. They stop NEW entries and
shout, which is the conservative failure mode: an open trade keeps its stop and
its management plan.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime

logger = logging.getLogger("HealthMonitor")

__all__ = ["HealthState", "HealthMonitor", "silence_days", "evaluate_edge"]


def silence_days(last_signal: datetime | None, now: datetime) -> float | None:
    """Days since the last entry. None when there has never been one."""
    if last_signal is None:
        return None
    return (now - last_signal).total_seconds() / 86400.0


def evaluate_edge(rolling_r: float | None, trades: int, window: int,
                  threshold_r: float) -> tuple[bool, str]:
    """
    Decide whether the rolling edge has decayed.

    Returns (should_halt, reason). Requires a FULL window of trades: halting a
    system on 6 trades would be noise, not evidence.
    """
    if rolling_r is None or trades < window:
        return False, (f"only {trades}/{window} closed trades - edge check not "
                       f"meaningful yet")
    if rolling_r <= threshold_r:
        return True, (f"rolling {window}-trade expectancy {rolling_r:+.3f}R is at or "
                      f"below the {threshold_r:+.2f}R stop line (a level the 21-year "
                      f"validated run never reached in {window}-trade windows)")
    return False, f"rolling {window}-trade expectancy {rolling_r:+.3f}R is acceptable"


@dataclass
class HealthState:
    """Persisted so a halt survives a bot restart -- and cannot be forgotten."""

    halted: bool = False
    halt_reason: str = ""
    halted_at: str | None = None
    last_silence_alert: str | None = None
    # When a human clears a halt, the rolling window restarts from that moment.
    # Without this the monitor would instantly re-halt on the same stale trades
    # and the bot could never resume (you would need 20 new trades to clear a
    # window that will not let you trade).
    resumed_at: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def load(cls, path: str) -> "HealthState":
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    return cls(**json.load(fh))
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning(f"health state unreadable ({exc}); starting fresh")
        return cls()

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_json())


class HealthMonitor:
    """
    Wraps the ledger and answers two questions each loop:

        should_block_entries()  ->  (bool, reason)
        due_silence_alert()     ->  str | None
    """

    def __init__(self, ledger, enabled: bool = True, silence_days_limit: float = 60.0,
                 edge_window: int = 30, edge_threshold_r: float = -0.30,
                 state_path: str = "logs/health_state.json",
                 silence_alert_repeat_days: float = 30.0):
        self.ledger = ledger
        self.enabled = enabled
        self.silence_days_limit = silence_days_limit
        self.edge_window = edge_window
        self.edge_threshold_r = edge_threshold_r
        self.silence_alert_repeat_days = silence_alert_repeat_days
        self.state = HealthState.load(state_path)
        self.state_path = state_path

    # ------------------------------------------------------------- entries ---
    def should_block_entries(self, now: datetime | None = None) -> tuple[bool, str]:
        """True when the bot must stop opening new positions."""
        if not self.enabled:
            return False, ""

        if self.state.halted:
            return True, self.state.halt_reason

        closed = self.ledger.closed_trades
        if self.state.resumed_at:
            # only trades that closed after the manual resume count
            cutoff = self.state.resumed_at
            closed = [r for r in closed if (r.closed or "") > cutoff]
        rs = [r.r for r in closed]
        from core.trade_ledger import rolling_expectancy as _re
        rolling = _re(rs, self.edge_window)
        halt, reason = evaluate_edge(rolling, len(closed), self.edge_window,
                                     self.edge_threshold_r)
        if halt:
            self.state.halted = True
            self.state.halt_reason = reason
            self.state.halted_at = (now or datetime.now()).isoformat()
            self.state.save(self.state_path)
            return True, reason
        return False, reason

    # ------------------------------------------------------------- silence ---
    def due_silence_alert(self, now: datetime | None = None) -> str | None:
        """
        A message when no trade has been taken for longer than the limit.

        Repeats at most every `silence_alert_repeat_days`, so a quiet market does
        not turn into a daily notification.
        """
        if not self.enabled:
            return None
        now = now or datetime.now()
        days = silence_days(self.ledger.last_signal_time(), now)
        baseline = (f"the system averages ~1.3 trades/month and quiet stretches "
                    f"are normal")
        if days is None:
            last = self.state.last_silence_alert
            if last and (now - datetime.fromisoformat(last)).days < self.silence_alert_repeat_days:
                return None
            self.state.last_silence_alert = now.isoformat()
            self.state.save(self.state_path)
            return (f"⚠️ <b>NO TRADES RECORDED YET</b>\n"
                    f"The ledger is empty. If the bot has been running for more than "
                    f"{self.silence_days_limit:.0f} days, something is suppressing every "
                    f"signal -- check the filter logs before assuming {baseline}.")
        if days > self.silence_days_limit:
            last = self.state.last_silence_alert
            if last and (now - datetime.fromisoformat(last)).days < self.silence_alert_repeat_days:
                return None
            self.state.last_silence_alert = now.isoformat()
            self.state.save(self.state_path)
            return (f"⚠️ <b>NO TRADES FOR {days:.0f} DAYS</b>\n"
                    f"Expected at most ~{self.silence_days_limit:.0f} days between entries "
                    f"({baseline}). This is consistent with a strategy being silently "
                    f"disabled -- check that signals are being generated and are not all "
                    f"being filtered, then check the data fetcher is receiving bars.")
        return None

    # -------------------------------------------------------------- status ---
    def status_line(self) -> str:
        closed = self.ledger.closed_trades
        if self.state.resumed_at:
            closed = [r for r in closed if (r.closed or "") > self.state.resumed_at]
        from core.trade_ledger import rolling_expectancy as _re
        rolling = _re([r.r for r in closed], self.edge_window)
        days = silence_days(self.ledger.last_signal_time(), datetime.now())
        r_txt = "n/a" if rolling is None else f"{rolling:+.3f}R"
        d_txt = "n/a" if days is None else f"{days:.0f}d"
        return (f"HEALTH | trades {len(closed)} | rolling{self.edge_window} {r_txt} | "
                f"last entry {d_txt} ago | "
                f"{'HALTED: ' + self.state.halt_reason if self.state.halted else 'ok'}")

    # --------------------------------------------------------------- reset ---
    def clear_halt(self, note: str = "") -> None:
        """
        Manual re-enable after investigating a decay halt.

        Deliberately manual: the whole point of the rule is that a human looks at
        the logs before it resumes.
        """
        now = datetime.now()
        self.state.halted = False
        self.state.halt_reason = ""
        self.state.halted_at = None
        self.state.resumed_at = now.isoformat()
        self.state.save(self.state_path)
        logger.warning(f"health halt cleared{': ' + note if note else ''}")
