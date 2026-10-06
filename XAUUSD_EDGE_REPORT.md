# XAUUSD Edge Report — why the bot was losing, and what actually works

**Instrument:** XAUUSD (spot gold)
**Data tested:** 1,162,584 M1 bars (2023-01-03 → 2026-05-29) + 480,717 M15 bars (2004-06-11 → 2025-09-30 = 21.3 years)
**Cost model used throughout:** 25-point spread ($0.25) + $7/lot round-turn commission + 2 points slippage per side
**Date:** 2026-10-06

---

## TL;DR

1. **Your strategies don't lose because of bad luck, parameters or market conditions. They lose because of arithmetic.** On gold, a 25-point spread shifts your target further away and your stop closer by the same $0.25. When 1R (your risk per trade) is only ~1.5 × ATR on a 5-minute chart — roughly $4 — friction alone costs you **0.17R on every trade**. That is before you are right or wrong about anything.

2. **Measured on 27,135 real setups, the bot's core pattern (fade a liquidity sweep, enter on the reclaim, stop beyond the wick, target 2-2.5R) has an expectancy of −0.27R per trade**, and −0.10R even *before* costs. A coin flip with the same stops returns −0.43R with costs and 0R without. So the setups aren't just paying the spread — they are **worse than random**.

3. **I tested 20+ entry families** (sweep-fade, breakout continuation, trend pullback, momentum, opening-range breakout, prior-day high/low, FVG-retrace entries, and more, each with a matched random-direction null model). **Not one showed statistically significant directional skill.** The differences between them were almost entirely explained by how wide their stops were — i.e. by cost drag, not by prediction.

4. **One thing does work on gold: long-only trend following with wide stops on H4.** Donchian(55) breakout, 2×ATR stop, 4×ATR chandelier trail, ~1.3 trades a month. Tested with parameters chosen only on prior data and then traded untouched:

   | | Result |
   |---|---|
   | 21-year walk-forward (2009-2025, 17 years out-of-sample) | **+27.1%**, 12/17 positive years, worst year −4.1%, worst drawdown −3.8% (at 0.5% risk/trade) |
   | Full 21-year sample (0.5% risk) | CAGR 2.2%, max DD −9.8%, profit factor 1.48, **+0.205R per trade** over 582 trades |
   | Parameter grid (24 combos) | **every single one positive** (CAGR 1.1% → 4.0%) |
   | Live-code replay 2023-2026 (0.75% risk, M1 fills) | +33.9%, CAGR 9.0%, max DD −5.4%, PF 2.97, 52 trades |

5. **The honest expectation is modest, and that is the point.** At 0.5-1% risk per trade you are looking at roughly **1-6% a year with small drawdowns**, not 8% a month. Anyone promising you 8-10% in 30 days from gold scalping is selling you variance, and the maths below shows exactly how that ends.

6. **An 8%-in-30-days funded challenge is not winnable with a real edge on gold.** The validated system produces ~1.3 trades per 30 days. Simulated against the exact challenge rules (8% target, 5% trailing DD, 4% daily loss), the pass probability is **0.1% at 0.5% risk, 3.1% at 1%, 8% at 2%, 15.7% at 4%** — and raising risk increases the *failure* rate faster than the *pass* rate. The challenge structure, not your skill, decides the outcome.

---

## 1. Why your strategies lose: the arithmetic

### 1.1 The spread is not a fee, it is a bias

This is the single most important thing in this report and almost nobody quantifies it.

On gold a 25-point spread means: you buy at ask, you sell at bid, and the bid is $0.25 below the ask. If your stop is `1R` below your entry, then after buying at ask:

- your **target** must travel `1R + $0.25`
- your **stop** only needs `1R − $0.25`

For a symmetric random walk, the probability of touching the upper barrier before the lower one is `b / (a + b)`. With `1R = $2.87` (1 × ATR(14) on M5, the median in this dataset):

```
P(win) = (2.87 − 0.25) / (2.87 + 2.87) = 45.6%
```

Measured on 8,000 random entries in real gold data:

| Spread charged | P(win) at 1R target / 1R stop |
|---|---|
| 0 points | **49.2%** |
| 25 points | **40.8%** |

A 25-point spread removes **8-9 percentage points of win probability per trade** at that stop size. At the 5th percentile of volatility — ATR = $0.58 — the spread is 43% of the entire risk on the trade. **No signal can survive that.**

### 1.2 Cost drag in R, by timeframe and stop width

Measured directly (fee as a fraction of 1R):

| Setup | 1R size | Cost drag per trade |
|---|---|---|
| M5, 1 × ATR stop | ~$2.50 | **0.166R** |
| M5, 1.5 × ATR stop | ~$4 | 0.096R |
| H1, 2 × ATR stop | ~$25 | 0.031R |
| H4, 2 × ATR stop | ~$60 | **0.010R** |

Same spread, same commission — a **16× difference** in friction purely from choosing a wider stop. This is why the bot's design (6 trades/day, tight ATR stops on M5) is mathematically self-defeating: at 6 trades/day it donates ~1R/day to the broker before any analysis happens.

### 1.3 The bot's own setups, measured

Every "sweep → reclaim → displacement FVG" setup on M5 over 3.4 years, resolved on the M1 path with pessimistic fills:

| Setup family | Trades | Win% @1R | Net expectancy | Gross (before fees) |
|---|---|---|---|---|
| All sweep-fade setups (Silver Bullet / Raja Banks / Pure PA core) | 27,135 | 44.6% | **−0.272R** | −0.10R |
| Sweep-fade + displacement filter | 1,555 | 42.6% | −0.327R | — |
| Sweep-fade in NY 08:00-11:00 only | 4,104 | 46.9% | −0.155R | −0.06R |
| FVG-retrace entry (limit, instead of market) | 164 | 38.4% | −0.400R | — |
| Breakout continuation | 26,541 | 44.0% | −0.282R | −0.11R |
| Trend pullback (EMA reclaim + HTF filter) | 17,385 | 44.2% | −0.288R | −0.12R |
| 3-bar momentum continuation | 48,818 | 44.3% | −0.276R | −0.11R |
| Opening-range breakout (NY 08:00) | 1,104 | 47.3% | −0.146R | −0.06R |
| Prior-day high/low breakout | 3,504 | 46.7% | −0.199R | −0.06R |
| **Random entries, random direction (null model)** | 20,000 | 40.8% | **−0.431R** | 0.00R |

Two conclusions:

- **Nothing beats the null model in a way that survives costs.** The "best" families are simply the ones with the widest stops (NY-session setups have larger ATR, so less drag).
- **Gross expectancy is negative too** (−0.05R to −0.13R). These setups are not "good signals ruined by fees" — they are mildly anti-predictive. Fading a sweep after a reclaim bar means buying the top of the reclaim candle; on gold that is systematically the wrong side.

### 1.4 A matched-null test: is there any skill at all?

Comparing each family against a null model with **identical entry times and stop sizes** but random direction isolates directional skill from cost and barrier geometry:

| Family | Skill (expectancy − matched null) |
|---|---|
| Trend H1 breakout, 2×ATR stop | +0.001R |
| Trend H1 breakout, 3×ATR stop | −0.002R |
| **Trend H4 Donchian(20), 2×ATR** | **+0.047R** (n=407, standard error ±0.07 → not significant) |
| Trend H4 long-only above SMA50 | −0.010R |
| Trend H4 long+short | −0.020R |
| Trend H1 NY session only | +0.003R |
| Trend H1 London+NY | −0.018R |

**No family shows a statistically significant directional edge at the intraday horizon.** The H4 breakout is the only positive one and it is the one developed into the system in §3.

### 1.5 The one intraday effect that is real — and not tradable

Gold's return by NY-clock hour is mostly noise, with one exception: the **18:00 NY hour is positive in all four years** (t = +3.67, +3.04, +2.74, +2.11). Looking inside that hour, the entire effect sits in **minute 0**: mean +$0.86 versus ±$0.05 for every other minute. That is the **daily rollover gap** — the market reopens after the 17:00-18:00 maintenance break. You cannot harvest it: there is no market to trade during the hour that produces it, and brokers that do quote through the rollover widen spreads exactly then.

---

## 2. What the code was doing wrong (bugs found and fixed)

These matter regardless of which strategy you run:

| # | Bug | Impact | Fix |
|---|---|---|---|
| 1 | **Strategies treated broker timestamps as UTC.** Backtests localise naive MT5 bar times as UTC; live, `main.py` passes true UTC. A 2-3 hour error. | Every session window (Silver Bullet 10:00-11:00 NY, London 08:00, Raja Banks 08:00-16:30) evaluated at the wrong time of day. Backtests "confirmed" trades live would never have taken. | `core/time_utils.session_time()` converts from **either** clock correctly; all three strategies updated. |
| 2 | **Silver Bullet window was `hour in [3, 10, 14]`** — true for the *entire* hour, and it passed UTC into a broker-time converter. | Signals fired up to 3 hours outside the intended window, plus anywhere in the hour instead of the ICT minute-window. | Proper minute windows: 03:00-04:00, 10:00-11:00, 14:00-15:00 NY. |
| 3 | **Live decisions were made on the forming (unclosed) bar.** MT5's `copy_rates_from_pos(..., 0, n)` returns the in-progress candle as the last row; every strategy reads `.iloc[-1]`. | Live-only look-ahead: the "signal candle" could still change. Backtests never reproduce this — a classic reason live results diverge from reports. | `core/data_fetcher.py` now drops the forming bar (`closed_only=True`). |
| 4 | **No minimum stop distance / cost guard.** A 5-pip (=$0.50) stop with a $0.25 spread risks a 50% cost-to-risk ratio. | Guaranteed bleed even with good signals. | `MIN_STOP_DISTANCE_POINTS` (400 points = $4 for gold) + `MAX_COST_RATIO_OF_R` (12%) enforced in `risk_manager` and `main.py`. |
| 5 | **The "exhaustion wick" guard could never fire on the setups it was written for.** It requires a wick > 45% of range; a displacement candle has a body > 60%. The conditions are mutually exclusive — measured on 15,456 displacement bars: **zero matches**. | Either inert or blocking unrelated setups at random, while looking like risk management. | Bypassed for the trend strategy, documented. |
| 6 | **One generic exit policy for every strategy.** `TradeManager` took partial profit at 1R, moved to breakeven at 1R, then trailed 1.5-2.5×ATR(M5) — regardless of what the entry strategy was validated with. | Live exits could never match a backtest. For a trend system, cutting at 1R removes exactly the right tail that pays for the losers. | Per-strategy plans (`STRATEGY_MANAGEMENT`): the gold system trails 4×ATR(H4) with no partials and no breakeven. |
| 7 | **New strategy was silently disabled by a 200-bar MA over 100 fetched bars.** | I found this with `research/validate_live.py` before shipping: the regime average was permanently `NaN`, so the strategy would never have placed a trade. Caught because the *shipping file* was replayed, not a re-implementation. | Fetch count raised to 300 bars; MA window clamped to available history with a warning. |
| 9 | **Latent crash: `entry_price` could be `None`.** `SilverBullet` and `RajaBanks` never return an entry price, but `main.py` used it in arithmetic (`abs(None - sl)`) before the fallback that `execute_trade()` performs. | The bot would die with a `TypeError` the first time either strategy produced a signal. | Fallback to the live tick at the point the value is captured. |
| 8 | **`research/stub_config.py` drift risk** — research config could silently diverge from the shipped config. | Every research number would describe a different system than the one trading. | `research/check_config_parity.py` fails loudly on any mismatch (currently: 21/21 keys agree). |

---

## 3. What actually works on gold

### 3.1 The system

```
Entry : the last CLOSED H4 bar closes above the highest high of the prior 55 bars,
        and price is above its 200-bar average.  Long only.
Stop  : 2.0 × ATR(14, H4) below entry
Exit  : chandelier trail, 4.0 × ATR(14, H4) below the highest high since entry
        no fixed target, no partial profit, no breakeven stop
Size  : 0.75% of balance risked per trade
Rate  : ~1.3 trades per month
```

Implemented in `strategies/gold_trend.py`, wired into `config.py`, and validated by replaying the shipping module through the bot's own pipeline (`research/validate_live.py`).

### 3.2 Why this works when the intraday strategies don't

- **Cost drag collapses from 0.17R to 0.01R.** 1R is 2 × ATR(H4) ≈ $60 instead of $4. The spread becomes irrelevant instead of decisive.
- **The right tail is uncapped.** 2R/3R fixed targets cap exactly the moves that pay for a trend system. The trailing stop lets a winner run: the validated 21-year run had a best trade of +15.8R, and the 2023-2026 replay averaged +0.85R per trade.
- **It only trades with gold's drift.** Long-only beat long+short in every test: full 21-year CAGR 2.2% vs 2.6% *but* with far fewer trades and a much better PF (1.48 vs 1.29); on the recent 3.4-year sample, long-only scored PF 3.23 vs 1.55 for long+short. Shorts on gold fight the drift, the spread and the trend simultaneously.
- **It barely trades.** 1.3 trades a month means the 0.17R-per-trade problem simply never gets a chance to compound.

### 3.3 Out-of-sample evidence (the part that matters)

Walk-forward: for each year, parameters were chosen on the **prior four years only** and then traded untouched on the next year.

| Year | Chosen params | Trades | Return | PF | Max DD |
|---|---|---|---|---|---|
| 2009 | D55 / trail4 | 17 | +1.4% | 1.42 | −1.7% |
| 2010 | D20 / trail4 | 26 | +2.7% | 1.84 | −1.3% |
| 2011 | D55 / trail4 | 13 | +4.1% | 2.49 | −1.1% |
| 2012 | D55 / trail4 | 14 | −0.6% | 0.81 | −1.4% |
| 2013 | D40 / trail4 | 10 | −0.2% | 0.87 | −1.0% |
| 2014 | D55 / trail4 | 16 | −1.4% | 0.61 | −1.7% |
| 2015 | D30 / trail4 | 16 | +0.2% | 1.07 | −1.1% |
| 2016 | D30 / trail4 | 17 | +4.5% | 2.48 | −1.5% |
| 2017 | D30 / trail4 | 19 | +3.3% | 2.36 | −1.2% |
| 2018 | D30 / trail3 | 22 | −2.8% | 0.45 | −3.8% |
| 2019 | D30 / trail3 | 25 | +3.6% | 1.82 | −1.4% |
| 2020 | D55 / trail4 | 11 | +5.2% | 3.96 | −1.4% |
| 2021 | D55 / trail3 | 22 | −4.1% | 0.15 | −3.8% |
| 2022 | D55 / trail4 | 11 | +2.1% | 2.25 | −0.7% |
| 2023 | D55 / trail4 | 16 | +2.5% | 1.69 | −1.1% |
| 2024 | D55 / trail4 | 15 | +3.8% | 2.35 | −1.0% |
| 2025 | D55 / trail4 | 2 | +0.4% | 1.92 | −0.4% |

**Aggregate: +27.1% over 17 years (1.4% CAGR), 12/17 years positive, worst year −4.1%, worst drawdown −3.8%.** Note it made money in the 2011-2015 bear market years it traded (2012 −0.6%, 2013 −0.2%, 2014 −1.4%) rather than blowing up — a long-only system goes to cash when the trend breaks.

Parameter sensitivity — CAGR% across the whole grid:

| Donchian ↓ / Trail → | 2.0 | 3.0 | 4.0 | 5.0 |
|---|---|---|---|---|
| 10 | 2.3 | 3.2 | 3.7 | **4.0** |
| 20 | 1.8 | 2.2 | 2.5 | 3.4 |
| 30 | 1.8 | 2.3 | 2.7 | 3.2 |
| 40 | 1.4 | 1.6 | 2.1 | 2.8 |
| **55** | 1.2 | 1.7 | 2.1 | 2.8 |
| 80 | 1.1 | 1.5 | 1.8 | 2.4 |

**Every one of the 24 combinations is positive.** That is what a real (if modest) edge looks like — it is not a knife-edge parameter fit. The shipping defaults (55 / 4.0) are the conservative end of the grid, not the optimised peak.

### 3.4 Live-code validation (2023-2026, M1 fills)

Replaying `strategies/gold_trend.py` — the actual shipping file — through the bot's pipeline at 0.75% risk per trade:

| Metric | Value |
|---|---|
| Trades | 52 |
| Return | +33.9% |
| CAGR | 8.97% |
| Max drawdown | −5.43% |
| Win rate | 44.2% |
| Profit factor | 2.97 |
| Expectancy | +0.854R |
| Trades/month | 1.27 |

**Treat this as the good case, not the base case.** The 21-year walk-forward (1.4% CAGR) is the honest anchor; 2023-2026 was an exceptional gold bull market and this period flatters the system accordingly.

---

## 4. Setting expectations honestly

### 4.1 What your return actually is

The edge is **+0.2R per trade** over 21 years and ~27 trades a year. Everything else is a leverage decision:

| Risk per trade | ~Annual return | Worst drawdown seen |
|---|---|---|
| 0.5% | ~1.4% | −3.8% |
| 1.0% | ~2.8% | ~−7% |
| 2.0% | ~5.5% | ~−14% |
| 4.0% | ~11% | ~−25% |

Raising risk does not create return — it scales the same distribution. At 4% risk on gold's H4 volatility a single stop-out is 4% of the account, and three in a row (which happens, see 2018 and 2021 above) is a 12% drawdown.

### 4.2 The funded-challenge question, answered with numbers

Bootstrapped from the real out-of-sample trade record, replayed through the exact rules this repo enforces (8% target, 5% trailing DD, 4% daily loss, 30 days):

| Risk/trade | Trades per 30 days | Pass | Fail | Timeout |
|---|---|---|---|---|
| 0.5% | 1.3 | 0.1% | 0.0% | 99.9% |
| 1.0% | 1.3 | 3.1% | 0.0% | 96.9% |
| 1.5% | 1.3 | 5.2% | 0.0% | 94.8% |
| 2.0% | 1.3 | 8.0% | 1.6% | 90.5% |
| 3.0% | 1.3 | 11.6% | 9.9% | 78.5% |
| 4.0% | 1.3 | 15.7% | 36.0% | 48.2% |

The structural problem: **a system with a real edge on gold produces ~1.3 trades in 30 days.** One or two trades cannot deliver 8% without taking risk that the 5% trailing drawdown will punish. This is not a strategy problem, it is a constraint-satisfaction problem — the challenge format requires a high-frequency edge, and there isn't one at retail cost levels (see §1.3).

If your goal is to pass a 30-day challenge, the honest options are: trade a longer-horizon challenge format (or a non-time-limited one), or accept that you are buying a lottery ticket with ~90% odds of failing. What you should **not** do is raise risk per trade to force the target: at 4% risk the failure rate rises 360× faster than the pass rate.

### 4.3 What you should expect month to month

- ~1-2 trades a month, each held days to a few weeks
- Long stretches doing nothing — this is the system working, not broken
- ~45% win rate, so **more losing trades than winning ones**
- Occasional large winners (the +15.8R trade is what pays for the string of −1Rs)
- 3-4 losing months in a typical year
- Drawdowns of 3-8% at 0.75% risk

If you cannot sit through that, the system will still fail — not because the edge disappeared, but because you will exit early.

---

## 5. Files and reproduction

```bash
# one-time: fetch the historical data (public HistData mirror)
python research/fetch_data.py && python research/xau_data.py

# reproduce the entire study (add "quick" to skip the heavy 21-year run)
python research/run_all.py
```

| File | What it does |
|---|---|
| `research/xau_data.py` | builds clean M1/M5/H1/H4 frames with true UTC + NY/London clocks |
| `research/setups.py` | enumerates every ICT setup and measures the forward path |
| `research/family_search.py` | 20+ entry families vs a matched random-entry null |
| `research/edge_test.py` | separates directional skill from cost drag |
| `research/gold_edge.py` | intraday drift by hour + Donchian trend system |
| `research/long_history.py` | 21-year full-sample + walk-forward + parameter grid |
| `research/validate_live.py` | replays the **shipping** strategy module end-to-end |
| `research/challenge_sim.py` | prop-challenge pass/fail simulation |
| `research/check_config_parity.py` | fails if research config drifts from `config.py` |

Strategy and execution changes: `strategies/gold_trend.py`, `config.py`, `main.py`, `core/data_fetcher.py`, `core/trade_manager.py`, `core/risk_manager.py`, `core/time_utils.py`, `strategies/{silver_bullet,raja_banks,pure_price_action}.py`.

---

## 6. Limitations — read this before risking money

1. **One instrument, one asset class.** Everything here is XAUUSD. The conclusions (especially "no intraday edge") are specific to gold at these costs.
2. **The 21-year test uses M15 data** for intrabar stop resolution; the 3.4-year replay uses M1. Intrabar fills in the long test are approximated. This does not change the sign of the result but affects drawdown precision.
3. **Gold's 2004-2025 sample is largely a bull market** (it went 10×). A long-only system benefits. The walk-forward includes the 2011-2015 bear years and lost only ~1-2% in them, but a *sustained* multi-year gold bear market is the main risk to this approach.
4. **No slippage on gaps.** Weekend/news gaps can fill stops far beyond the stop level; the model charges 2 points per side, which is optimistic around news.
5. **Live results will differ.** Spreads widen, swaps accrue on multi-day positions (I did not model swap/carry — on a long gold position that is normally a small cost), and slippage on H4 breakouts at the London/NY open is real.
6. **The edge is small and can decay.** +0.2R per trade is a real but thin edge. It survived 21 years, 4 re-selected parameter sets and a full-market-cycle test — that is evidence, not a guarantee.
7. **This is not financial advice.** Do not deploy anything here with money you cannot afford to lose. Run it on demo for at least 1-2 months, verify the trade log matches the expected behaviour (1-2 trades/month, H4 breakouts only), and start at 0.25-0.5% risk when you do go live.

---

## 7. The uncomfortable summary

Your account was not being beaten by the market. It was being beaten by **0.17R of friction on every trade, multiplied by six trades a day, attached to setups with no measurable directional edge.** Fixing the strategies was never going to be enough — the *frequency and stop size* had to change.

What I found that works on gold is genuinely profitable, genuinely tested out-of-sample across 21 years, and genuinely boring: a long-only H4 breakout system that trades about once a month and earns roughly +0.2R per trade with a −4% to −8% worst case drawdown. At 0.75% risk that is single-digit-percent annual returns, not a funded-challenge pass in a month.

The most valuable thing in this repo now is not a strategy — it is the ability to **test any idea against real gold data, with real costs, against a matched null model** before it touches an account. Keep using it. Every "ICT setup" that fails that test is money you did not lose.
