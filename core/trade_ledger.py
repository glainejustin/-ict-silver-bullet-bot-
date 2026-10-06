"""
core/trade_ledger.py -- an R-denominated record of every trade the bot takes.

WHY THIS EXISTS
---------------
MetaTrader5's deal history tells you profits in account currency, which is
useless for judging whether an edge is still working: the same result means
different things at different position sizes. Everything in the research that
validated this system is denominated in **R** (multiples of the risk taken), and
a rolling-expectancy stop rule only makes sense in R.

The research measured, over 21 years:

    rolling 20-trade expectancy : median +0.184R, 5th percentile -0.252R
    P(rolling 20-trade expectancy <= -0.30R) = 2.5% (8 of 319 windows)
    P(<= -0.40R)                             = 0.9%

So the ledger's job is to make that measurable in live trading: record the risk
at entry, match the exit from MT5 history, and expose the rolling expectancy that
core/health_monitor.py acts on.

FORMAT
------
JSONL, one record per trade, appended at entry and updated in place on close.
Written to logs/ (gitignored).

    {"ticket": 123, "symbol": "XAUUSD", "strategy": "GoldTrend_XAUUSD",
     "opened": "2026-10-06T09:00:00", "risk_cash": 37.5, "entry": 3841.2,
     "sl": 3803.7, "lots": 0.01, "closed": null, "pnl": null, "r": null}

The record is created from values the bot ALREADY computes at execution time
(lot size and stop distance), so no extra MT5 calls are needed at entry.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Iterable

logger = logging.getLogger("TradeLedger")

__all__ = ["LedgerRecord", "TradeLedger", "compute_r", "rolling_expectancy"]


# --------------------------------------------------------------------------
# pure helpers (testable without MT5)
# --------------------------------------------------------------------------
def compute_r(pnl_net: float, risk_cash: float) -> float | None:
    """R multiple of a closed trade. None when the risk is unknowable."""
    if risk_cash is None or not risk_cash or risk_cash <= 0:
        return None
    return float(pnl_net) / float(risk_cash)


def rolling_expectancy(rs: Iterable[float], window: int) -> float | None:
    """Mean R over the most recent `window` closed trades (input oldest -> newest)."""
    vals = [r for r in rs if r is not None]
    if len(vals) < window:
        return None
    return float(sum(vals[-window:]) / window)


@dataclass
class LedgerRecord:
    ticket: int
    symbol: str
    strategy: str
    opened: str
    risk_cash: float
    entry: float
    sl: float
    lots: float
    # `ticket` is the order ticket; `deal` is the opening deal ticket. MT5 keys
    # history by POSITION id, which equals one or the other depending on the
    # account type (hedging vs netting) -- keeping both means reconcile can match
    # either instead of silently failing to close the record.
    deal: int | None = None
    closed: str | None = None
    pnl: float | None = None
    r: float | None = None
    exit: float | None = None
    checked_at: str | None = None

    @property
    def is_open(self) -> bool:
        return self.closed is None


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------
class TradeLedger:
    """
    Append-only trade log with in-place closure.

    `path` points at a JSONL file; the parent directory is created on demand.
    Every method that touches the network/terminal takes `mt5` as an argument,
    so this class imports and unit-tests without MetaTrader5 present.
    """

    def __init__(self, path: str, magic: int | None = None):
        self.path = path
        self.magic = magic
        self.records: list[LedgerRecord] = []
        self._load()

    # ---------------------------------------------------------------- disk ---
    def _load(self) -> None:
        self.records = []
        if not os.path.exists(self.path):
            return
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.records.append(LedgerRecord(**json.loads(line)))
                except (json.JSONDecodeError, TypeError) as exc:
                    # A corrupt line must never stop the bot from trading.
                    logger.warning(f"ledger: skipping unreadable line ({exc})")

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for rec in self.records:
                fh.write(json.dumps(asdict(rec)) + "\n")
        os.replace(tmp, self.path)          # atomic: a crash cannot truncate

    # ---------------------------------------------------------------- write ---
    def record_open(self, ticket: int, symbol: str, strategy: str, entry: float,
                    sl: float, lots: float, risk_cash: float,
                    opened: datetime | str | None = None,
                    deal: int | None = None) -> LedgerRecord:
        """Called immediately after a successful execution."""
        if isinstance(opened, datetime):
            ts = opened.replace(tzinfo=None).isoformat()
        else:
            ts = opened or datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        rec = LedgerRecord(ticket=int(ticket), symbol=symbol, strategy=strategy,
                           opened=ts, risk_cash=float(risk_cash), entry=float(entry),
                           sl=float(sl), lots=float(lots),
                           deal=None if deal is None else int(deal))
        self.records.append(rec)
        self._save()
        return rec

    def close(self, ticket: int, pnl_net: float, exit_price: float | None = None,
              closed: datetime | str | None = None) -> LedgerRecord | None:
        """Mark a trade closed and compute its R."""
        for rec in self.records:
            if rec.ticket == int(ticket) and rec.is_open:
                rec.pnl = float(pnl_net)
                rec.r = compute_r(pnl_net, rec.risk_cash)
                rec.exit = None if exit_price is None else float(exit_price)
                if isinstance(closed, datetime):
                    rec.closed = closed.replace(tzinfo=None).isoformat()
                else:
                    rec.closed = closed or datetime.now(timezone.utc).replace(
                        tzinfo=None).isoformat()
                self._save()
                return rec
        return None

    # --------------------------------------------------------------- read ---
    @property
    def open_trades(self) -> list[LedgerRecord]:
        return [r for r in self.records if r.is_open]

    @property
    def closed_trades(self) -> list[LedgerRecord]:
        closed = [r for r in self.records if not r.is_open and r.r is not None]
        return sorted(closed, key=lambda r: r.closed or "")

    def rolling_expectancy(self, window: int) -> float | None:
        return rolling_expectancy([r.r for r in self.closed_trades], window)

    def last_signal_time(self) -> datetime | None:
        """
        Most recent entry (or exit) -- used for the silence check.

        Entries only: a system that takes no trades because it sees no setup is
        exactly the situation the alert exists to surface, and counting exits
        would delay it.
        """
        if not self.records:
            return None
        stamps = []
        for rec in self.records:
            try:
                stamps.append(datetime.fromisoformat(rec.opened))
            except ValueError:
                continue
        return max(stamps) if stamps else None

    # --------------------------------------------------------- reconcile ---
    def reconcile(self, mt5, lookback_days: int = 90) -> int:
        """
        Close out ledger rows whose MT5 position has gone.

        Returns the number of records closed. Net P&L is the sum of every deal
        belonging to the position (entry + exit + commissions + swap), which is
        what the account actually experienced.

        Matching is done in ONE history request per call, then by position id
        against either the order ticket or the opening deal ticket -- MT5 keys
        history by position, and which of the two equals it depends on the
        account type. If a trade cannot be matched at all, this says so instead
        of quietly leaving the record open forever (which would silently disable
        the edge-decay guard).
        """
        from datetime import timedelta

        open_recs = self.open_trades
        if not open_recs:
            return 0

        now = datetime.now()
        try:
            deals = mt5.history_deals_get(now - timedelta(days=lookback_days), now)
        except Exception as exc:                                       # noqa: BLE001
            logger.warning(f"reconcile: history request failed ({exc})")
            return 0
        if not deals:
            return 0

        by_position: dict[int, list] = {}
        for d in deals:
            if self.magic is not None and getattr(d, "magic", None) not in (None, self.magic):
                continue
            pid = getattr(d, "position_id", None)
            if pid is None:
                continue
            by_position.setdefault(int(pid), []).append(d)

        closed_count = 0
        unmatched_old = 0
        for rec in open_recs:
            candidates = [c for c in (rec.ticket, rec.deal) if c]
            group = None
            for cand in candidates:
                if int(cand) in by_position:
                    group = by_position[int(cand)]
                    break
            if group is None:
                opened = self._parse_ts(rec.opened)
                if opened and (now - opened).days > 7:
                    unmatched_old += 1
                continue

            net = 0.0
            for d in group:
                net += float(getattr(d, "profit", 0.0) or 0.0)
                net += float(getattr(d, "commission", 0.0) or 0.0)
                net += float(getattr(d, "swap", 0.0) or 0.0)
            out_deals = [d for d in group
                         if getattr(d, "entry", None) == getattr(mt5, "DEAL_ENTRY_OUT", 1)]
            last = out_deals[-1] if out_deals else group[-1]
            exit_price = float(getattr(last, "price", 0.0) or 0.0) or None
            ts = None
            if getattr(last, "time", None):
                ts = datetime.fromtimestamp(int(last.time))
            self.close(rec.ticket, net, exit_price=exit_price, closed=ts)
            closed_count += 1

        if unmatched_old:
            logger.warning(
                f"ledger: {unmatched_old} trade(s) open >7 days with no matching "
                f"broker history. The R ledger (and therefore the edge-decay guard) "
                f"is not tracking them. Check that the recorded ticket/deal ids "
                f"match mt5.history_deals_get()."
            )
        return closed_count

    @staticmethod
    def _parse_ts(value: str | None) -> datetime | None:
        try:
            return datetime.fromisoformat(value) if value else None
        except ValueError:
            return None
