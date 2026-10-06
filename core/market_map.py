"""
core/market_map.py -- liquidity, volume-at-price and depth maps.

Turns an OHLCV frame into the three "maps" that traders actually look at:

  1. VOLUME PROFILE / HEATMAP   where did volume actually trade, by price?
                                -> POC, value area (VAH/VAL), HVN, LVN
  2. LIQUIDITY POOL MAP         where are the cluster of stops?
                                -> clustered swing highs/lows, equal highs/lows,
                                   prior day/week/month extremes, round numbers
  3. DEPTH (DOM) HEATMAP        resting limit orders over time (live MT5 only)
                                -> requires a broker that publishes market depth

Design notes
------------
* Importable without MetaTrader5 installed: every MT5 touch-point is inside a
  function that takes the ``mt5`` module as an argument, so the research harness
  and CI can import this file freely.
* Everything here is a *description of the past*, not a prediction. Whether these
  levels carry any edge is a measured question -- see research/map_validation.py.
  Do not promote a level to a trade filter without reading that output.
* Volume-at-price is approximated by spreading each bar's volume uniformly over
  that bar's high-low range. With M1 bars that is close to tick-accurate; with
  H4 bars it is a smeared approximation. The function records the bar timeframe
  so callers can judge.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "VolumeProfile",
    "volume_profile",
    "swing_points",
    "cluster_levels",
    "liquidity_pools",
    "PoolMap",
    "session_extremes",
    "round_numbers",
    "build_map",
    "record_depth_snapshot",
    "load_depth_history",
    "depth_heatmap",
]


# --------------------------------------------------------------------------
# 1. VOLUME PROFILE
# --------------------------------------------------------------------------
@dataclass
class VolumeProfile:
    """Volume-at-price summary for one window of bars."""

    edges: np.ndarray          # bin edges (len = n_bins + 1)
    volume: np.ndarray         # volume per bin (len = n_bins)
    poc: float                 # point of control (highest-volume price)
    vah: float                 # value area high
    val: float                 # value area low
    hvn: list[float] = field(default_factory=list)   # high volume nodes
    lvn: list[float] = field(default_factory=list)   # low volume nodes (fast travel)
    total_volume: float = 0.0
    bar_count: int = 0
    value_area_pct: float = 0.70

    @property
    def centres(self) -> np.ndarray:
        return (self.edges[:-1] + self.edges[1:]) / 2.0

    def as_series(self) -> pd.Series:
        return pd.Series(self.volume, index=np.round(self.centres, 6), name="volume")

    def summary(self) -> dict:
        return {
            "poc": self.poc, "vah": self.vah, "val": self.val,
            "hvn": self.hvn, "lvn": self.lvn,
            "total_volume": self.total_volume, "bars": self.bar_count,
        }


def volume_profile(
    df: pd.DataFrame,
    bins: int = 80,
    value_area_pct: float = 0.70,
    bin_size: float | None = None,
    volume_col: str = "volume",
    smooth: int = 3,
    origin: float | None = None,
) -> VolumeProfile:
    """
    Volume-at-price histogram, POC and value area.

    Each bar's volume is spread uniformly across its high-low range and binned.
    Fully vectorised -- safe for 1M+ bars.

    `origin` anchors the bin grid. Pass the same origin for every session when
    stacking profiles into a heatmap, otherwise each session's bins start at its
    own low and the columns will not line up.
    """
    if len(df) == 0:
        raise ValueError("volume_profile: empty frame")

    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    if volume_col in df.columns and np.nansum(df[volume_col].to_numpy(dtype=float)) > 0:
        vol = df[volume_col].to_numpy(dtype=float)
    else:
        # No volume in the feed (many FX/gold CFD feeds send 0): fall back to
        # tick-count proxy = one unit per bar. This is what MT5 calls
        # "tick volume" and is a legitimate activity measure, just not size.
        vol = np.ones(len(df), dtype=float)

    lo_edge, hi_edge = float(np.nanmin(low)), float(np.nanmax(high))
    if not np.isfinite(lo_edge) or not np.isfinite(hi_edge) or hi_edge <= lo_edge:
        raise ValueError("volume_profile: degenerate price range")

    if bin_size is None:
        bin_size = (hi_edge - lo_edge) / float(bins)
    base = lo_edge if origin is None else float(origin)
    lo_edge = min(lo_edge, base)
    n_bins = max(1, int(np.ceil((hi_edge - base) / bin_size)) + 1)
    edges = base + np.arange(n_bins + 1) * bin_size
    edges[-1] = max(edges[-1], hi_edge)

    # clip bars into the grid, then spread
    lo_c = np.clip(low, lo_edge, hi_edge - bin_size * 1e-9)
    hi_c = np.clip(high, lo_edge, hi_edge)
    width = np.maximum(hi_c - lo_c, 1e-12)
    density = vol / width                      # volume per unit price

    i_lo = np.clip(np.searchsorted(edges, lo_c, side="right") - 1, 0, n_bins - 1)
    i_hi = np.clip(np.searchsorted(edges, hi_c, side="right") - 1, 0, n_bins - 1)

    profile = np.zeros(n_bins, dtype=float)
    multi = i_hi > i_lo
    # interior bins (fully covered by the bar's range) via a difference array
    diff = np.zeros(n_bins + 1, dtype=float)
    np.add.at(diff, i_lo[multi] + 1, density[multi] * bin_size)
    np.add.at(diff, i_hi[multi], -density[multi] * bin_size)
    profile += np.cumsum(diff)[:n_bins]
    # the two partial edge bins
    left_overlap = np.where(multi, edges[i_lo + 1] - lo_c, hi_c - lo_c)
    right_overlap = np.where(multi, hi_c - edges[i_hi], 0.0)
    np.add.at(profile, i_lo, density * left_overlap)
    np.add.at(profile, i_hi, density * right_overlap)

    total = float(profile.sum())
    poc_idx = int(np.argmax(profile))

    # --- value area: grow from the POC outwards until value_area_pct is covered
    target = total * value_area_pct
    lo_i = hi_i = poc_idx
    covered = profile[poc_idx]
    while covered < target and (lo_i > 0 or hi_i < n_bins - 1):
        below = profile[lo_i - 1] if lo_i > 0 else -1.0
        above = profile[hi_i + 1] if hi_i < n_bins - 1 else -1.0
        if above >= below:
            hi_i += 1
            covered += max(above, 0.0)
        else:
            lo_i -= 1
            covered += max(below, 0.0)

    centres = (edges[:-1] + edges[1:]) / 2.0
    poc = float(centres[poc_idx])
    vah = float(edges[hi_i + 1])
    val = float(edges[lo_i])

    # --- HVN / LVN: local extrema of the smoothed profile
    hvn: list[float] = []
    lvn: list[float] = []
    if smooth and smooth > 1 and n_bins >= smooth + 2:
        sm = pd.Series(profile).rolling(smooth, center=True, min_periods=1).mean().to_numpy()
        half = max(1, smooth // 2)
        for i in range(half, n_bins - half):
            window = sm[i - half:i + half + 1]
            if sm[i] == window.max() and sm[i] > 0:
                hvn.append(float(centres[i]))
            if sm[i] == window.min():
                lvn.append(float(centres[i]))

    return VolumeProfile(
        edges=edges, volume=profile, poc=poc, vah=vah, val=val,
        hvn=hvn, lvn=lvn, total_volume=total, bar_count=len(df),
        value_area_pct=value_area_pct,
    )


@dataclass
class ProfileHeatmap:
    """
    Volume-at-price over time: the actual heatmap.

    matrix[i, j] = volume traded in price-bin i during session j. This is the
    input for a Sierra/Bookmap-style volume picture, and the per-session stats
    (POC / VAH / VAL) are what you draw on the price chart.
    """

    matrix: np.ndarray            # shape (n_price_bins, n_sessions)
    edges: np.ndarray             # price bin edges, len = n_price_bins + 1
    sessions: pd.Index            # session labels, len = n_sessions
    stats: pd.DataFrame           # per-session poc / vah / val / volume

    @property
    def centres(self) -> np.ndarray:
        return (self.edges[:-1] + self.edges[1:]) / 2.0

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.matrix, index=np.round(self.centres, 4),
                            columns=self.sessions)


def profile_heatmap(
    df: pd.DataFrame,
    freq: str = "D",
    bins: int = 120,
    value_area_pct: float = 0.70,
    volume_col: str = "volume",
    min_bars: int = 10,
    log_price: bool = False,
) -> ProfileHeatmap:
    """
    Build the volume heatmap: one column per session (day/week/month).

    A volume profile only means something inside a session -- run it over two
    years and every price looks equally visited. So: a shared price grid across
    the whole frame, one profile per session onto that grid, and per-session POC
    and value area from that session's own distribution.

    `freq` accepts anything pandas understands for a period: 'D', 'W', 'M'.

    `log_price=True` bins on log price instead of linear price. Use it for any
    multi-year view: gold went 400 -> 3800, and on a linear grid the entire
    2004-2015 range collapses into the bottom two rows.
    """
    if len(df) == 0:
        raise ValueError("profile_heatmap: empty frame")
    if volume_col not in df.columns or np.nansum(df[volume_col].to_numpy(float)) <= 0:
        volume_col = "__tickcount__"
        df = df.assign(__tickcount__=1.0)

    idx = pd.DatetimeIndex(df.index)
    key = idx.to_period(freq)
    if log_price:
        df = df.assign(high=np.log(df["high"].to_numpy(float)),
                       low=np.log(df["low"].to_numpy(float)))
    # true range of the data: min of LOWS to max of HIGHS. (Using min-of-highs
    # / max-of-lows here silently shrinks the shared grid and truncates the top
    # of every session column by a percent or two.)
    lo_edge, hi_edge = float(df["low"].min()), float(df["high"].max())
    step = (hi_edge - lo_edge) / float(bins)
    n_bins = max(1, int(np.ceil((hi_edge - lo_edge) / step)))
    edges = lo_edge + np.arange(n_bins + 1) * step

    matrix = np.zeros((n_bins, 0), dtype=float)
    cols, stats = [], []

    for period, sub in df.groupby(pd.Series(key, index=df.index)):
        if len(sub) < min_bars:
            continue
        # Two grids on purpose:
        #   * `col_prof` deposits onto the SHARED display grid (coarse, but the
        #     columns line up into a picture)
        #   * `prof` measures POC/value-area on the session's OWN range, because
        #     a shared 12-month grid is only ~3 bins wide for a single day and
        #     the value area then just swallows the whole session.
        col_prof = volume_profile(sub, bin_size=step, value_area_pct=value_area_pct,
                                  volume_col=volume_col, origin=lo_edge)
        prof = volume_profile(sub, bins=50, value_area_pct=value_area_pct,
                              volume_col=volume_col)
        col = np.zeros(n_bins, dtype=float)
        n = min(n_bins, len(col_prof.volume))
        col[:n] = col_prof.volume[:n]
        matrix = np.column_stack([matrix, col])
        cols.append(period)
        # per-session stats on the shared grid
        if prof.total_volume > 0:
            stats.append({
                "session": period,
                "poc": prof.poc,
                "vah": prof.vah, "val": prof.val,
                "high": float(sub["high"].max()), "low": float(sub["low"].min()),
                "volume": prof.total_volume, "bars": len(sub),
            })

    out_stats = pd.DataFrame(stats)
    if log_price:
        edges = np.exp(edges)
        for c in ("poc", "vah", "val", "high", "low"):
            if c in out_stats.columns:
                out_stats[c] = np.exp(out_stats[c].to_numpy(float))
    return ProfileHeatmap(matrix=matrix, edges=edges, sessions=pd.Index(cols),
                          stats=out_stats)


# --------------------------------------------------------------------------
# 2. LIQUIDITY POOL MAP
# --------------------------------------------------------------------------
def swing_points(df: pd.DataFrame, left: int = 3, right: int = 3
                 ) -> tuple[np.ndarray, np.ndarray]:
    """
    Strict fractal swing highs / lows.

    Returns (high_idx, low_idx) positional indices into df.
    A point is a swing if it is the extreme of the (left+right+1) window centred
    on it. Ties (flat tops) are dropped rather than emitted twice.
    """
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n = len(df)
    if n < left + right + 1:
        return np.array([], dtype=int), np.array([], dtype=int)

    win = left + right + 1
    h_max = pd.Series(high).rolling(win, center=True).max().to_numpy()
    l_min = pd.Series(low).rolling(win, center=True).min().to_numpy()

    # exclude flat tops / bottoms: require strict superiority to the bar before
    # and after, so a plateau yields no swing rather than a cluster of them.
    prev_h = np.roll(high, 1); prev_h[0] = -np.inf
    next_h = np.roll(high, -1); next_h[-1] = -np.inf
    prev_l = np.roll(low, 1); prev_l[0] = np.inf
    next_l = np.roll(low, -1); next_l[-1] = np.inf

    is_high = (high == h_max) & (high > prev_h) & (high > next_h)
    is_low = (low == l_min) & (low < prev_l) & (low < next_l)
    is_high[:left] = False; is_high[n - right:] = False
    is_low[:left] = False; is_low[n - right:] = False

    return np.flatnonzero(is_high), np.flatnonzero(is_low)


def cluster_levels(prices: Sequence[float], tol: float) -> list[dict]:
    """
    Group prices that sit within `tol` of each other into levels.

    Returns a list of dicts: {"price", "touches", "first", "last", "members"}
    sorted by price. `tol` is in price units (a sensible default is 0.15 x ATR).
    """
    arr = np.asarray([p for p in prices if np.isfinite(p)], dtype=float)
    if arr.size == 0:
        return []
    order = np.argsort(arr)
    arr = arr[order]
    clusters: list[list[float]] = [[arr[0]]]
    for p in arr[1:]:
        # chain-linked: compares against the running mean of the open cluster
        if p - float(np.mean(clusters[-1])) <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [
        {"price": float(np.mean(c)), "touches": len(c),
         "low": float(np.min(c)), "high": float(np.max(c))}
        for c in clusters
    ]


@dataclass
class PoolMap:
    """Buy-side (above) and sell-side (below) liquidity pools."""

    price: float
    buyside: pd.DataFrame    # swing-high clusters = resting buy stops (shorts' stops)
    sellside: pd.DataFrame   # swing-low clusters  = resting sell stops (longs' stops)
    atr: float
    tol: float
    levels: dict = field(default_factory=dict)   # prior day/week extremes, etc.

    def nearest(self, n: int = 5) -> pd.DataFrame:
        """Nearest pools on each side, expressed in ATR units away."""
        frames = []
        for side, df in (("buyside", self.buyside), ("sellside", self.sellside)):
            if df is None or len(df) == 0:
                continue
            d = df.copy()
            d["side"] = side
            d["distance"] = d["price"] - self.price
            d["dist_atr"] = d["distance"] / self.atr if self.atr else np.nan
            frames.append(d)
        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, ignore_index=True)
        out = out.reindex(out["dist_atr"].abs().sort_values().index)
        return out.head(n).reset_index(drop=True)

    def summary(self) -> dict:
        return {
            "price": round(self.price, 3),
            "atr": round(self.atr, 3),
            "buyside_pools": 0 if self.buyside is None else len(self.buyside),
            "sellside_pools": 0 if self.sellside is None else len(self.sellside),
            "levels": {k: (round(v, 3) if isinstance(v, float) else v)
                       for k, v in self.levels.items()},
        }


def liquidity_pools(
    df: pd.DataFrame,
    atr: float,
    tol_atr: float = 0.15,
    left: int = 3,
    right: int = 3,
    volume_col: str = "volume",
) -> PoolMap:
    """
    Cluster swing highs and lows into a liquidity map.

    Every swing high is where short stops rest and where breakout buy stops sit;
    when several of them line up within a fraction of an ATR, that is a pool --
    the thing an ICT "liquidity sweep" is supposed to reach for.

    Pools are annotated with touches, the volume that traded at the level, the
    age in bars, and a simple strength score.
    """
    hi_idx, lo_idx = swing_points(df, left=left, right=right)
    tol = max(tol_atr * atr, 1e-9)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n = len(df)

    if volume_col in df.columns and np.nansum(df[volume_col].to_numpy(dtype=float)) > 0:
        vol = df[volume_col].to_numpy(dtype=float)
    else:
        vol = np.ones(n, dtype=float)

    def annotate(idx: np.ndarray, price_arr: np.ndarray, is_high: bool) -> pd.DataFrame:
        if idx.size == 0:
            return pd.DataFrame(columns=["price", "touches", "volume", "age_bars",
                                         "first_bar", "last_bar", "strength"])
        cl = cluster_levels(price_arr[idx], tol)
        rows = []
        for c in cl:
            members = idx[np.abs(price_arr[idx] - c["price"]) <= tol]
            lo_p = c["price"] - tol
            hi_p = c["price"] + tol
            near = (low <= hi_p) & (high >= lo_p)          # bars that visited the level
            rows.append({
                "price": c["price"],
                "touches": int(c["touches"]),
                "volume": float(vol[near].sum()),
                "age_bars": int(n - 1 - members.max()),
                "first_bar": int(members.min()),
                "last_bar": int(members.max()),
            })
        out = pd.DataFrame(rows)
        # strength: touches x recency decay, normalised to 0-1 for convenience
        recency = np.exp(-out["age_bars"] / max(50.0, n / 4.0))
        raw = out["touches"] * recency
        out["strength"] = raw / raw.max() if raw.max() > 0 else 0.0
        return out.sort_values("price").reset_index(drop=True)

    buyside = annotate(hi_idx, high, True)
    sellside = annotate(lo_idx, low, False)

    price = float(df["close"].iloc[-1])
    if len(buyside):
        buyside = buyside[buyside["price"] > price].reset_index(drop=True)
    if len(sellside):
        sellside = sellside[sellside["price"] < price].reset_index(drop=True)

    return PoolMap(price=price, buyside=buyside, sellside=sellside, atr=float(atr), tol=tol)


def session_extremes(df: pd.DataFrame, session_col: str | None = None) -> dict:
    """
    Prior day / week / month extremes -- the levels every desk quotes.

    `session_col` names a column of session dates (e.g. the 'ny' clock built by
    research/xau_data.py or core.time_utils). Without it, the frame's own index
    date is used.
    """
    if len(df) == 0:
        return {}
    d = df
    if session_col and session_col in df.columns:
        day = pd.to_datetime(df[session_col]).dt.date
    else:
        day = pd.Index(df.index).date
    day = pd.Series(day, index=df.index)

    daily = df.groupby(day).agg(high=("high", "max"), low=("low", "min"),
                                close=("close", "last"))
    week_key = pd.to_datetime(daily.index).to_period("W")
    monthly = daily.groupby(pd.to_datetime(daily.index).to_period("M")).agg(
        high=("high", "max"), low=("low", "min"))
    weekly = daily.groupby(week_key).agg(high=("high", "max"), low=("low", "min"))

    out: dict[str, float] = {}
    if len(daily) >= 2:
        out["prior_day_high"] = float(daily["high"].iloc[-2])
        out["prior_day_low"] = float(daily["low"].iloc[-2])
        out["prior_day_close"] = float(daily["close"].iloc[-2])
    if len(weekly) >= 2:
        out["prior_week_high"] = float(weekly["high"].iloc[-2])
        out["prior_week_low"] = float(weekly["low"].iloc[-2])
    if len(monthly) >= 2:
        out["prior_month_high"] = float(monthly["high"].iloc[-2])
        out["prior_month_low"] = float(monthly["low"].iloc[-2])
    return out


def round_numbers(price: float, span_pct: float = 0.02, step: float = 10.0) -> list[float]:
    """Round-number magnets near the current price (gold respects $10/$50/$100)."""
    lo, hi = price * (1 - span_pct), price * (1 + span_pct)
    first = np.floor(lo / step) * step
    return [float(p) for p in np.arange(first, hi + step, step) if p > 0]


# --------------------------------------------------------------------------
# 3. MAP ASSEMBLY
# --------------------------------------------------------------------------
def build_map(df: pd.DataFrame, atr: float | None = None, profile_bars: int = 2000,
              session_col: str | None = None, tol_atr: float = 0.15) -> dict:
    """
    One call that returns the whole map for a symbol: profile + pools + levels.

    `df` should be the finest reliable frame you have (M5/M15 live). `atr` is the
    ATR of that same frame; it is computed if omitted.
    """
    if atr is None:
        atr = float((df["high"] - df["low"]).tail(50).mean())
    window = df.tail(profile_bars)
    prof = volume_profile(window)
    pools = liquidity_pools(window, atr=atr, tol_atr=tol_atr)
    extremes = session_extremes(window, session_col=session_col)
    pools.levels = extremes
    return {"profile": prof, "pools": pools, "extremes": extremes, "atr": atr}


# --------------------------------------------------------------------------
# 4. LIVE DEPTH (DOM) HEATMAP
# --------------------------------------------------------------------------
def record_depth_snapshot(mt5, symbol: str, path: str) -> dict | None:
    """
    Append one depth-of-market snapshot to a JSONL file.

    Returns the snapshot dict, or None if the broker publishes no depth.
    MetaTrader5 must have been subscribed with mt5.market_book_add(symbol).

    NOTE: this is the only part of the module that needs a live terminal. The
    quality of the book depends entirely on your broker -- plenty of CFD brokers
    publish only a single level or nothing at all, in which case this returns
    None and the rest of the map still works.
    """
    book = mt5.market_book_get(symbol)
    if not book:
        return None
    snap = {
        "t": pd.Timestamp.utcnow().isoformat(),
        "symbol": symbol,
        "levels": [
            {"type": int(e.type), "price": float(e.price), "volume": float(e.volume),
             "volume_real": float(getattr(e, "volume_real", 0.0) or 0.0)}
            for e in book
        ],
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(snap) + "\n")
    return snap


def load_depth_history(path: str) -> pd.DataFrame:
    """Read a JSONL depth log into a long frame: time x price x side x size."""
    rows = []
    if not os.path.exists(path):
        return pd.DataFrame(columns=["time", "price", "side", "volume"])
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                snap = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = pd.Timestamp(snap["t"])
            for lv in snap.get("levels", []):
                rows.append({"time": t, "price": float(lv["price"]),
                             "side": "bid" if lv["type"] == 1 else "ask",
                             "volume": float(lv.get("volume_real") or lv["volume"])})
    return pd.DataFrame(rows)


def depth_heatmap(path: str, resample: str = "5s", price_bins: int = 120
                  ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Pivot a depth log into (bids, asks) heatmap matrices: price rows x time cols.

    This is the input for a Bookmap-style picture. Cells hold the resting size
    observed at that price in that time slice (mean over the slice, so a wall
    that flickers reads weaker than one that sits).
    """
    df = load_depth_history(path)
    if df.empty:
        return pd.DataFrame(), pd.DataFrame()
    lo, hi = df["price"].min(), df["price"].max()
    step = (hi - lo) / max(1, price_bins) or 1e-9
    df["bucket"] = (np.floor((df["price"] - lo) / step) * step + lo).round(6)
    df["slice"] = df["time"].dt.floor(resample)
    out = {}
    for side in ("bid", "ask"):
        sub = df[df["side"] == side]
        if sub.empty:
            out[side] = pd.DataFrame()
            continue
        piv = sub.pivot_table(index="bucket", columns="slice", values="volume",
                              aggfunc="mean")
        out[side] = piv.sort_index()
    return out["bid"], out["ask"]
