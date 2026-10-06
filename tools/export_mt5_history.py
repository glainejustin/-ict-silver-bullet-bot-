"""
tools/export_mt5_history.py -- pull real history out of your own MT5 terminal.

WHY THIS EXISTS
---------------
Every open question in this project is limited by data. The research runs on a
public 21-year M15 export of gold; the FX breadth test ran on 3.4 years because
that was all that was reachable. Your terminal, by contrast, can export decades
of M1 for every symbol your broker offers -- indices, energies, rates, crypto,
other FX crosses -- which is the single highest-leverage input to any further
research.

WHAT IT WRITES
--------------
One parquet per symbol/timeframe, in the layout research/ expects:

    research/data/mt5/XAUUSD_H4.parquet
      columns: open, high, low, close, tick_volume, spread, real_volume
      index  : bar OPEN time, naive broker-server clock (as MT5 reports it)
      extra  : a 'utc' column with the same instant converted to true UTC, so
               time-of-day work cannot repeat the broker/UTC mixing bug

Notes that matter:
  * MT5 timestamps are BROKER SERVER time, not UTC. That distinction was a real
    bug in this repo's strategies (see XAUUSD_EDGE_REPORT.md section 2), so both
    clocks are stored.
  * History is requested in year-long chunks: a single wide request is silently
    truncated by most brokers, which looks like "the data starts in 2019".
  * Bars are never edited; the file is a faithful dump.

Usage
-----
    python tools/export_mt5_history.py --symbols XAUUSD,GBPUSD --timeframes M1,M5,H1,H4
    python tools/export_mt5_history.py --all --timeframes H1,H4 --start 2003-01-01
    python tools/export_mt5_history.py --list          # what the broker offers

Then point the research harness at it:

    python research/map_validation.py                 # uses research/data/*.parquet
    cp research/data/mt5/XAUUSD_M15.parquet research/data/XAUUSD_M15_2004_2025.parquet

It is deliberately Windows/MT5-only, and imports MetaTrader5 lazily so the
helpers below can be unit-tested anywhere.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TIMEFRAME_NAMES = ["M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15",
                   "M20", "M30", "H1", "H2", "H3", "H4", "H6", "H8", "H12",
                   "D1", "W1", "MN1"]


# --------------------------------------------------------------------------
# pure helpers (testable without MT5)
# --------------------------------------------------------------------------
def year_chunks(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """
    Split a span into <=1-year windows.

    Brokers truncate or refuse very wide copy_rates_range requests, and the
    failure is silent -- you just get fewer bars and assume history is short.
    """
    if end <= start:
        return []
    out = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=365), end)
        out.append((cur, nxt))
        cur = nxt
    return out


def rates_to_frame(rates, broker_tz=None) -> pd.DataFrame:
    """MT5 rate array -> frame indexed by bar open time, with a utc column."""
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    if "time" not in df.columns:
        return pd.DataFrame()
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df.set_index("time").sort_index()
    df = df[~df.index.duplicated(keep="first")]
    rename = {"tick_volume": "tick_volume", "real_volume": "real_volume"}
    df = df.rename(columns=rename)
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"rates are missing the '{col}' column")
    if "tick_volume" not in df.columns:
        df["tick_volume"] = 0.0
    if "spread" not in df.columns:
        df["spread"] = 0

    try:
        from core.time_utils import broker_naive_to_utc
        df["utc"] = [broker_naive_to_utc(t) for t in df.index.to_pydatetime()]
    except Exception:                                             # noqa: BLE001
        df["utc"] = df.index
    cols = ["open", "high", "low", "close", "tick_volume", "spread"]
    if "real_volume" in df.columns:
        cols.append("real_volume")
    cols.append("utc")
    return df[cols]


def summarize(df: pd.DataFrame, symbol: str, tf: str) -> str:
    if df.empty:
        return f"{symbol:10s} {tf:4s} no data"
    span = (df.index[-1] - df.index[0]).days / 365.25
    spread_txt = ""
    if "spread" in df.columns and len(df):
        med = pd.to_numeric(df["spread"], errors="coerce").median()
        if pd.notna(med):
            spread_txt = f"  median spread {med:.0f} pts"
    return (f"{symbol:10s} {tf:4s} {len(df):>9,} bars  "
            f"{df.index[0].date()} -> {df.index[-1].date()}  "
            f"({span:.1f}y){spread_txt}")


# --------------------------------------------------------------------------
# MT5 side
# --------------------------------------------------------------------------
def export_symbol(mt5, symbol: str, tf_name: str, start: datetime, end: datetime,
                  out_dir: str, chunk_days: int = 365) -> pd.DataFrame:
    tf = getattr(mt5, f"TIMEFRAME_{tf_name}", None)
    if tf is None:
        print(f"  {symbol} {tf_name}: unsupported timeframe")
        return pd.DataFrame()

    frames = []
    for lo, hi in year_chunks(start, end) if chunk_days >= 365 else \
            [(lo, min(lo + timedelta(days=chunk_days), end))
             for lo in pd.date_range(start, end, freq=f"{chunk_days}D").to_pydatetime()]:
        rates = mt5.copy_rates_range(symbol, tf, lo, hi)
        if rates is not None and len(rates):
            frames.append(rates_to_frame(rates))
    if not frames:
        print(f"  {symbol} {tf_name}: nothing returned (symbol name? history not "
              f"downloaded? try opening the chart in the terminal first)")
        return pd.DataFrame()

    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{symbol}_{tf_name}.parquet")
    df.to_parquet(path)
    print("  " + summarize(df, symbol, tf_name) + f"  -> {path}")
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="XAUUSD",
                    help="comma-separated, e.g. XAUUSD,GBPUSD,US500")
    ap.add_argument("--all", action="store_true",
                    help="every symbol the terminal offers (Market Watch + all)")
    ap.add_argument("--timeframes", default="M1,M5,H1,H4")
    ap.add_argument("--start", default="2003-01-01")
    ap.add_argument("--end", default=None, help="default: now")
    ap.add_argument("--out", default=os.path.join(ROOT, "research", "data", "mt5"))
    ap.add_argument("--list", action="store_true", help="list available symbols and exit")
    args = ap.parse_args()

    import MetaTrader5 as mt5
    if not mt5.initialize():
        print(f"MT5 initialize() failed: {mt5.last_error()}")
        return 1
    try:
        if args.list:
            syms = mt5.symbols_get()
            print(f"{len(syms)} symbols available:")
            for s in syms:
                print(f"  {s.name:16s} {s.description}")
            return 0

        if args.all:
            symbols = [s.name for s in (mt5.symbols_get() or [])]
        else:
            symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

        start = datetime.fromisoformat(args.start)
        end = datetime.fromisoformat(args.end) if args.end else datetime.now()
        tfs = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]
        for t in tfs:
            if t not in TIMEFRAME_NAMES:
                print(f"unknown timeframe {t}; valid: {', '.join(TIMEFRAME_NAMES)}")
                return 1

        print(f"Exporting {len(symbols)} symbol(s) x {len(tfs)} timeframe(s), "
              f"{start.date()} -> {end.date()} -> {args.out}")
        # ensure the terminal actually knows each symbol before asking for history
        for sym in symbols:
            if not mt5.symbol_select(sym, True):
                print(f"  {sym}: not available at this broker (skipped)")
        ok = 0
        for sym in symbols:
            for tf in tfs:
                if not export_symbol(mt5, sym, tf, start, end, args.out).empty:
                    ok += 1
        print(f"\n{ok} file(s) written to {args.out}")
        print("Next: point the research harness at them, e.g.\n"
              "  cp research/data/mt5/XAUUSD_M15.parquet "
              "research/data/XAUUSD_M15_2004_2025.parquet")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
