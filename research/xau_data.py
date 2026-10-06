"""
XAUUSD data pipeline for research / backtesting.

WHY THIS FILE EXISTS
--------------------
The live bot reads bars straight from MetaTrader 5, where every bar timestamp is
BROKER SERVER TIME (usually GMT+2 winter / GMT+3 summer). Every strategy in this
repo then makes time-of-day decisions (Silver Bullet windows, London sessions)
on top of whatever timestamp it is handed.

For research we need three simultaneously-true views of the same bar:

  1. broker_time : what MT5 would label the bar (what strategies actually see)
  2. utc_time    : the true instant in time (what economics/news/liquidity follow)
  3. ny / london : the session clocks the strategies are *trying* to reference

SOURCE DATA
-----------
HistData.com M1 bars for XAUUSD, 2023-01-02 .. 2026-05-29, mirrored in the
public repo `Paaktingc/forex_bot` under `m1_data/`.

VERIFIED TIMEZONE CONVENTION (do not "fix" this without re-verifying):
The CSV files carry a literal "Z" suffix, but the timestamps are NOT UTC --
they are America/New_York wall clock (DST aware). Evidence from the data itself:
    - NFP (08:30 ET) prints the largest M1 range of the day at label 08:30
    - FOMC (14:00 ET) prints at label 14:00
    - The daily 17:00-18:00 ET maintenance break and the Sunday 18:00 ET weekly
      reopen both land on those labels in BOTH winter and summer
So we parse labels as America/New_York, then convert to true UTC. Getting this
wrong shifts every session window by 4-5 hours and silently destroys any
time-of-day strategy (this is exactly the class of bug that makes live results
differ from backtests).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")

# MetaTrader servers of the brokers this bot targets (FundedNext / FundingPips /
# IC Markets etc.) run on EET/EEST: GMT+2 in winter, GMT+3 in summer.
BROKER_TZ = pytz.timezone("Europe/Athens")
NY_TZ = pytz.timezone("America/New_York")
LONDON_TZ = pytz.timezone("Europe/London")

SOURCE_TZ = NY_TZ

TIMEFRAMES = {"M1": "1min", "M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h"}

OHLC_AGG = {"open": "first", "high": "max", "low": "min", "close": "last"}


def source_files() -> list[str]:
    """CSV files expected in the research/data/raw directory."""
    return [os.path.join(DATA_DIR, "raw", f"XAUUSD_M1_{y}.csv") for y in (2023, 2024, 2025, 2026)]


def load_raw_m1(paths: list[str] | None = None) -> pd.DataFrame:
    """Load the HistData CSVs and return an M1 frame indexed by TRUE UTC."""
    paths = paths or source_files()
    frames = []
    for p in paths:
        if not os.path.exists(p):
            continue
        frames.append(pd.read_csv(p))
    if not frames:
        raise FileNotFoundError(
            "No source CSVs found. Run research/fetch_data.py first (downloads the "
            "public HistData mirror into research/data/raw/)."
        )
    df = pd.concat(frames, ignore_index=True)
    # Files carry a literal "Z" suffix; strip it so the raw label digits survive
    # exactly (they are NY wall clock, see the module docstring).
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_localize(None)

    # The label is NY wall-clock. Fall-back-hour duplicates are inferred from order.
    local = df["datetime"].dt.tz_localize(
        SOURCE_TZ, ambiguous="infer", nonexistent="NaT"
    )
    df["utc"] = local.dt.tz_convert("UTC").dt.tz_localize(None)
    df = df.dropna(subset=["utc"])
    df = df.sort_values("utc").drop_duplicates(subset="utc", keep="last")
    df = df[["utc", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
    return df


@dataclass
class BarSet:
    """All timeframes for one symbol, plus the session clock columns."""

    m1: pd.DataFrame
    frames: dict[str, pd.DataFrame]
    broker_tz: str = "Europe/Athens"

    def __getitem__(self, tf: str) -> pd.DataFrame:
        return self.frames[tf]

    @property
    def span(self) -> str:
        return f"{self.m1.index[0]} -> {self.m1.index[-1]}"


def _resample(utc_df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Resample true-UTC M1 bars onto BROKER-server clock boundaries.

    MT5 H1 bars are aligned to broker midnight (GMT+2/+3), NOT UTC midnight, so we
    must resample in broker local time and then keep both clocks on the frame.
    """
    b = utc_df.set_index("utc")
    b = b.tz_localize("UTC").tz_convert(BROKER_TZ)
    agg = {k: v for k, v in OHLC_AGG.items() if k in b.columns}
    if "volume" in b.columns:
        agg["volume"] = "sum"
    out = b.resample(rule, label="left", closed="left").agg(agg)
    out = out.dropna(subset=["open", "high", "low", "close"])
    out["utc"] = out.index.tz_convert("UTC").tz_localize(None)
    out.index = out.index.tz_localize(None)  # broker-naive index == what MT5 shows
    out.index.name = "time"
    # extra session clocks every strategy needs
    out["ny"] = out["utc"].dt.tz_localize("UTC").dt.tz_convert(NY_TZ).dt.tz_localize(None)
    out["london"] = out["utc"].dt.tz_localize("UTC").dt.tz_convert(LONDON_TZ).dt.tz_localize(None)
    out["ny_hour"] = out["ny"].dt.hour + out["ny"].dt.minute / 60.0
    out["weekday"] = out["ny"].dt.weekday
    return out


def build(force: bool = False) -> BarSet:
    """Build (and cache as parquet) all timeframes."""
    os.makedirs(DATA_DIR, exist_ok=True)
    cache = os.path.join(DATA_DIR, "XAUUSD_M1.parquet")
    if force or not os.path.exists(cache):
        m1 = load_raw_m1()
        m1.to_parquet(cache, index=False)
    else:
        m1 = pd.read_parquet(cache)
        m1["utc"] = pd.to_datetime(m1["utc"])

    frames = {}
    frames["M1"] = _resample(m1, "1min").sort_index()
    for tf, rule in TIMEFRAMES.items():
        if tf == "M1":
            continue
        frames[tf] = _resample(m1, rule).sort_index()
    return BarSet(m1=frames["M1"], frames=frames)


def session_summary(m1: pd.DataFrame) -> pd.DataFrame:
    """Sanity check: hourly volatility by NY clock hour (should peak 08:00-11:00 NY)."""
    ny = m1.copy()
    ny["rng"] = ny["high"] - ny["low"]
    return ny.groupby(ny["ny_hour"].astype(int))["rng"].agg(["mean", "count"])


if __name__ == "__main__":
    # force=True only when the parquet cache is missing: rebuilding from the raw
    # CSVs requires research/fetch_data.py to have run first.
    cache_exists = os.path.exists(os.path.join(DATA_DIR, "XAUUSD_M1.parquet"))
    bs = build(force=not cache_exists)
    print("Built XAUUSD dataset:", bs.span)
    for tf, df in bs.frames.items():
        print(f"  {tf:>3}: {len(df):>8,} bars   {df.index[0]} -> {df.index[-1]}  (broker time)")
    print("\nMean M1 range by NY hour (top of session structure):")
    print(session_summary(bs["M1"]).round(3).to_string())
    print("\nSample M5 row (all clocks present):")
    print(bs["M5"].iloc[[-1]].to_string())
