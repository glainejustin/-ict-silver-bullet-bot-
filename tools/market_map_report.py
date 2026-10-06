"""
Render a market map for a symbol: volume heatmap + profile + liquidity pools.

Works two ways:

    # from the research parquet (no MT5 needed)
    python tools/market_map_report.py --parquet research/data/XAUUSD_M15_2004_2025.parquet \
        --freq W --log-price --out out/xauusd_map_21y.png

    # live from a running MetaTrader 5 terminal
    python tools/market_map_report.py --symbol XAUUSD --timeframe M15 --bars 20000 \
        --freq D --out out/xauusd_map.png

The picture is three things stacked into one figure:

  * background  volume traded at each (price, session) cell -- the heatmap
  * white line  price
  * cyan line   developing POC (where the session's volume concentrated)
  * band        the 70% value area for each session
  * right panel the volume profile, aggregated over the whole window
  * markers     liquidity pools above / below the current price

This is a *description of the past*. research/map_validation.py measures whether
any of these levels carry predictive information before you trade them.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.market_map import profile_heatmap, liquidity_pools, session_extremes  # noqa: E402


def load_parquet(path: str, start: str | None = None) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if start:
        df = df.loc[start:]
    return df


def load_mt5(symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
    import MetaTrader5 as mt5  # noqa: N813
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")
    tf = getattr(mt5, f"TIMEFRAME_{timeframe.upper()}")
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
    mt5.shutdown()
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"no bars for {symbol} {timeframe}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")
    df["volume"] = df.get("tick_volume", df.get("volume", 1.0))
    return df


def _session_closes(df: pd.DataFrame, sessions: pd.Index) -> np.ndarray:
    """Last close of each session -- the white price line on the map."""
    out = []
    for s in sessions:
        try:
            seg = df.loc[str(s.start_time):str(s.end_time)]
        except Exception:
            seg = df.iloc[0:0]
        out.append(seg["close"].iloc[-1] if len(seg) else np.nan)
    return np.array(out, dtype=float)


def _draw_panel(ax, ax_prof, hm, df, pools, extremes, log_price, freq, annotate_pools):
    """Draw one price panel + its matching volume profile."""
    from matplotlib.colors import LogNorm

    x = np.arange(hm.matrix.shape[1] + 1) - 0.5
    pos = hm.matrix[hm.matrix > 0]
    pcm = ax.pcolormesh(
        x, hm.edges, hm.matrix, cmap="inferno", shading="flat", rasterized=True,
        norm=LogNorm(vmin=max(1.0, np.percentile(pos, 10) if pos.size else 1.0),
                     vmax=np.percentile(hm.matrix, 99.5) if pos.size else 1.0))

    closes = _session_closes(df, hm.sessions)
    if not np.all(np.isnan(closes)):
        ax.plot(np.arange(len(closes)), closes, color="white", lw=1.4, alpha=0.95,
                label="price", zorder=5)
    ax.plot(np.arange(len(hm.stats)), hm.stats["poc"], color="#25e6d0", lw=0.9,
            ls=(0, (3, 2)), alpha=0.9, label="POC", zorder=4)
    ax.fill_between(np.arange(len(hm.stats)), hm.stats["val"], hm.stats["vah"],
                    color="#25e6d0", alpha=0.10, label="value area")

    if annotate_pools:
        shown = set()
        for _, p in pools.nearest(12).iterrows():
            bucket = round(p["price"] / (pools.atr or 1.0))
            if bucket in shown:            # one line per ~1 ATR of price
                continue
            shown.add(bucket)
            colour = "#ffd166" if p["side"] == "buyside" else "#ff6b9d"
            ax.axhline(p["price"], color=colour, lw=0.8, ls=(0, (4, 4)), alpha=0.5)
            ax.text(0.015, p["price"], f"{'BUY-side' if p['side'] == 'buyside' else 'SELL-side'} "
                                       f"{p['price']:.1f}  {int(p['touches'])}x",
                    transform=ax.get_yaxis_transform(), color=colour, fontsize=6.5,
                    va="bottom", ha="left")
        for k, v in extremes.items():
            if "high" in k:
                ax.axhline(v, color="#8be9fd", lw=0.6, alpha=0.45)

    # trim dead space: only show the range that actually traded
    used = hm.matrix.sum(axis=1) > 0
    lo = float(np.nanmin(hm.edges[:-1][used]))     # edges has n_bins+1 entries
    hi = float(np.nanmax(hm.edges[1:][used]))
    pad = (hi - lo) * 0.02
    ax.set_ylim(lo - pad, hi + pad)
    if log_price:
        ax.set_yscale("log")

    ax.set_ylabel("price", color="#c8c8d0", fontsize=9)
    # Take over the axis labels completely. matplotlib's log formatter draws its
    # labels on MINOR ticks (2x10^3, 3x10^3 ...), so anything that touches only
    # the major formatter looks like it silently did nothing. Explicit round
    # levels + a NullLocator is the only version that renders predictably.
    from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator
    y0, y1 = ax.get_ylim()
    step = 10.0
    for cand in (10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
        step = float(cand)
        if (y1 - y0) / step <= 9:
            break
    first = np.floor(y0 / step) * step
    ticks = np.arange(first, y1 + step, step)
    ax.yaxis.set_major_locator(FixedLocator(ticks))
    ax.yaxis.set_minor_locator(NullLocator())
    ax.yaxis.set_major_formatter(FuncFormatter(
        lambda v, _: f"{v:,.0f}" if v >= 10 else f"{v:,.2f}"))
    ax.yaxis.set_minor_formatter(FuncFormatter(lambda v, _: ""))
    ax.tick_params(colors="#c8c8d0", labelsize=8)
    ax.set_facecolor("#12121a")
    for sp in ax.spines.values():
        sp.set_color("#2a2a38")
    if annotate_pools:
        ax.set_title(f"each column = one {freq} session", color="#9a9aa8",
                     fontsize=9, loc="right", pad=4)
    leg = ax.legend(loc="upper left", fontsize=8, framealpha=0.2, labelcolor="#dcdce4")
    leg.get_frame().set_facecolor("#0d0d12")

    total = hm.matrix.sum(axis=1)
    height = (hm.edges[1] - hm.edges[0]) * 0.92
    ax_prof.barh(hm.centres, total, height=height, color="#ff9f43", alpha=0.85)
    ax_prof.axhline(float(hm.stats["poc"].iloc[-1]), color="#25e6d0", lw=1.0)
    ax_prof.set_ylim(ax.get_ylim())          # same window, independent axis
    ax_prof.set_facecolor("#12121a")
    ax_prof.set_yticks([])                   # no ticks at all -> nothing to label
    ax_prof.tick_params(colors="#c8c8d0", labelsize=7)
    ax_prof.set_title("profile", color="#9a9aa8", fontsize=9, pad=4)
    for sp in ax_prof.spines.values():
        sp.set_color("#2a2a38")
    return pcm


def render(df: pd.DataFrame, freq: str, bins: int, log_price: bool, out: str,
           title: str, zoom_bars: int = 3000) -> str:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    hm = profile_heatmap(df, freq=freq, bins=bins, log_price=log_price)
    atr = float((df["high"] - df["low"]).tail(200).mean())
    pools = liquidity_pools(df.tail(3000), atr=atr)
    extremes = session_extremes(df.tail(3000))

    dfz = df.tail(zoom_bars)
    hmz = profile_heatmap(dfz, freq=freq, bins=bins, log_price=log_price)
    atrz = float((dfz["high"] - dfz["low"]).tail(200).mean())
    poolsz = liquidity_pools(dfz.tail(2000), atr=atrz)
    exz = session_extremes(dfz.tail(2000))

    fig = plt.figure(figsize=(19, 10), facecolor="#0d0d12")
    gs = fig.add_gridspec(1, 5, width_ratios=[4.4, 0.8, 0.07, 4.4, 0.8], wspace=0.05)

    ax1 = fig.add_subplot(gs[0, 0])
    ax1p = fig.add_subplot(gs[0, 1])
    pcm = _draw_panel(ax1, ax1p, hm, df, pools, extremes, log_price, freq, False)
    ax1.set_title(title, color="white", fontsize=11, loc="left", pad=10)

    ax2 = fig.add_subplot(gs[0, 3])
    ax2p = fig.add_subplot(gs[0, 4])
    _draw_panel(ax2, ax2p, hmz, dfz, poolsz, exz, log_price, freq, True)
    ax2.set_title(f"recent {len(dfz):,} bars (zoom) - liquidity pools marked",
                  color="white", fontsize=11, loc="left", pad=10)

    cax = fig.add_axes([0.915, 0.12, 0.007, 0.74])
    cb = fig.colorbar(pcm, cax=cax)
    cb.set_label("volume traded", color="#c8c8d0", fontsize=8)
    cb.ax.tick_params(colors="#c8c8d0", labelsize=7)
    cb.outline.set_edgecolor("#2a2a38")

    fig.suptitle("XAUUSD market map - volume-at-price heatmap, session POC/value area, "
                 "and liquidity pools", color="white", fontsize=14, y=0.975)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    fig.savefig(out, dpi=115, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")
    print(f"  full window : {len(hm.sessions)} sessions x {len(hm.edges)-1} price bins, "
          f"{len(df):,} bars")
    print(f"  zoom window : {len(hmz.sessions)} sessions, {len(dfz):,} bars")
    print(f"  ATR {atr:.2f}  pools in zoom: {len(poolsz.buyside)} buy / "
          f"{len(poolsz.sellside)} sell")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default=None)
    ap.add_argument("--start", default=None, help="slice start for --parquet")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--timeframe", default="M15")
    ap.add_argument("--bars", type=int, default=20000)
    ap.add_argument("--freq", default="D", help="session length: D, W, M")
    ap.add_argument("--bins", type=int, default=110)
    ap.add_argument("--log-price", action="store_true")
    ap.add_argument("--out", default="out/market_map.png")
    ap.add_argument("--zoom-bars", type=int, default=3000)
    args = ap.parse_args()

    if args.parquet:
        df = load_parquet(args.parquet, args.start)
        label = "XAUUSD M15" if "M15" in args.parquet else "XAUUSD M1"
        title = f"{label}  {df.index[0].date()} -> {df.index[-1].date()}"
    else:
        df = load_mt5(args.symbol, args.timeframe, args.bars)
        title = f"{args.symbol} {args.timeframe}  {df.index[0].date()} -> {df.index[-1].date()}"
    render(df, args.freq, args.bins, args.log_price, args.out, title,
           zoom_bars=args.zoom_bars)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
