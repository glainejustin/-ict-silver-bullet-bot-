"""
Fetch the historical XAUUSD M1 dataset used by the research harness.

Two datasets are used:

  1. HistData.com 1-minute bid bars (2023-01-02 .. 2026-05-29), mirrored in the
     public GitHub repo `Paaktingc/forex_bot` under `m1_data/`.
     -> used for every M5/intraday measurement (research/setups.py, family_search.py,
        edge_test.py, validate_live.py)

  2. XAUUSD 15-minute bars (2004-06-11 .. 2025-09-30 = 21.3 years), from the
     public GitHub repo `BaseMax/XAUUSD-LSTM` (file `XAU_15m_data.csv`).
     -> used for the long-horizon walk-forward (research/long_history.py)

Run:  python research/fetch_data.py
Then: python research/xau_data.py     # builds research/data/*.parquet
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "raw")
REPO = "https://github.com/Paaktingc/forex_bot"
TMP = "/tmp/_xau_histdata_mirror"


BREADTH_SYMBOLS = ("GBPUSD", "USDJPY", "AUDUSD", "EURUSD")
BREADTH_DIR = os.path.join(HERE, "data", "breadth")

LONG_REPO = "https://github.com/BaseMax/XAUUSD-LSTM"
LONG_FILE = "XAU_15m_data.csv"
LONG_TMP = "/tmp/_xau_long_history"
LONG_OUT = os.path.join(HERE, "data", "XAUUSD_M15_2004_2025.parquet")


def fetch_long_history() -> None:
    """21-year M15 series used by research/long_history.py."""
    if os.path.exists(LONG_OUT):
        print(f"Long history already built: {LONG_OUT}")
        return
    import pandas as pd
    print("Fetching the 21-year M15 series (BaseMax/XAUUSD-LSTM) ...")
    if os.path.exists(LONG_TMP):
        shutil.rmtree(LONG_TMP)
    subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
                    LONG_REPO, LONG_TMP], check=True)
    subprocess.run(["git", "sparse-checkout", "set", "--no-cone", f"/{LONG_FILE}"],
                   cwd=LONG_TMP, check=True)
    df = pd.read_csv(os.path.join(LONG_TMP, LONG_FILE), sep=";")
    df.columns = [c.strip() for c in df.columns]
    df["Date"] = pd.to_datetime(df["Date"], format="%Y.%m.%d %H:%M")
    df = df.rename(columns={"Date": "time", "Open": "open", "High": "high",
                            "Low": "low", "Close": "close", "Volume": "volume"})
    df = df.set_index("time").sort_index()
    os.makedirs(os.path.dirname(LONG_OUT), exist_ok=True)
    df.to_parquet(LONG_OUT)
    print(f"  wrote {LONG_OUT} ({len(df):,} bars, "
          f"{df.index[0].date()} -> {df.index[-1].date()})")


def fetch_breadth(tmp: str) -> None:
    """
    Multi-instrument M15 series for the portfolio-breadth test.

    The mirror carries GBPUSD / USDJPY / AUDUSD (2023-2026) and EURUSD (2024
    only). Only M15 is kept: the raw M1 CSVs are ~1.3M rows per symbol, and the
    trend system never looks below H4 -- resampling here keeps the cache small
    enough to rebuild in seconds.
    """
    import pandas as pd

    os.makedirs(BREADTH_DIR, exist_ok=True)
    files = {}
    for name in os.listdir(os.path.join(tmp, "m1_data")):
        if not name.endswith(".csv"):
            continue
        sym = name.split("_M1_")[0]
        if sym in BREADTH_SYMBOLS:
            files.setdefault(sym, []).append(name)

    for sym, names in sorted(files.items()):
        out = os.path.join(BREADTH_DIR, f"{sym}_M15_2023_2026.parquet")
        if os.path.exists(out):
            print(f"  {sym}: cache present")
            continue
        frames = []
        for name in sorted(names):
            df = pd.read_csv(os.path.join(tmp, "m1_data", name))
            tcol = "datetime" if "datetime" in df.columns else df.columns[0]
            df["time"] = pd.to_datetime(df[tcol], utc=True).dt.tz_localize(None)
            df = df.set_index("time").sort_index()
            frames.append(df[[c for c in ("open", "high", "low", "close") if c in df.columns]])
        m1 = pd.concat(frames)
        m1 = m1[~m1.index.duplicated(keep="first")]
        m15 = m1.resample("15min").agg({"open": "first", "high": "max", "low": "min",
                                        "close": "last"}).dropna(subset=["open", "close"])
        m15.to_parquet(out)
        print(f"  {sym}: {len(m15):,} M15 bars  {m15.index[0].date()} -> {m15.index[-1].date()}")


def main() -> int:
    os.makedirs(RAW, exist_ok=True)
    fetch_long_history()
    have = [f for f in os.listdir(RAW) if f.endswith(".csv")]
    breadth_have = (os.path.isdir(BREADTH_DIR) and
                    len([f for f in os.listdir(BREADTH_DIR) if f.endswith(".parquet")]) >= 3)
    if len(have) >= 4 and breadth_have:
        print(f"Raw CSVs already present in {RAW} ({len(have)} files) and breadth "
              f"caches exist. Nothing to do.")
        return 0
    if len(have) >= 4 and not breadth_have:
        print(f"Raw CSVs present ({len(have)} files); building missing breadth caches ...")

    if os.path.exists(TMP):
        shutil.rmtree(TMP)
    print("Cloning mirror (sparse checkout of m1_data/) ...")
    subprocess.run(
        ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", REPO, TMP],
        check=True,
    )
    subprocess.run(["git", "sparse-checkout", "set", "m1_data"], cwd=TMP, check=True)

    copied = 0
    for name in os.listdir(os.path.join(TMP, "m1_data")):
        if name.startswith("XAUUSD_M1_") and name.endswith(".csv"):
            shutil.copy2(os.path.join(TMP, "m1_data", name), os.path.join(RAW, name))
            copied += 1
            print("  ", name)
    print(f"Copied {copied} files to {RAW}")

    os.makedirs(BREADTH_DIR, exist_ok=True)
    print("Building multi-instrument M15 caches for the breadth test ...")
    fetch_breadth(TMP)

    print("Next: python research/xau_data.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
