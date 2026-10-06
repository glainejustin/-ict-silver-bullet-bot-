# Next steps — prioritised, with the numbers behind each

Everything here follows from measurement, not opinion. Where a recommendation
depends on a number, the number is inline and reproducible from `research/`.

Current state, for reference:

| | |
|---|---|
| Validated edge | H4 Donchian55 / 2×ATR(14) stop / 4×ATR trail, long-only, XAUUSD |
| Expectancy | **+0.260R** per trade, PF 1.54, 338 trades over 21.3 years |
| Rate | ~1.3 trades per month |
| Annual outcome at 0.5% risk | median **+1.4%**, best +14.0%, worst −3.8%, positive 15/22 years |
| Walk-forward (params on prior 4y) | +30.3% over 17 out-of-sample years, 12/17 positive |
| Challenge (8% / 30 days) | 3.1% pass at 1% risk, 8% at 2% |

---

## 1. Decide what you are optimising for — everything else branches on this

**If it is "pass a funded challenge": the arithmetic says don't.**
The pass probability is 3.1% at 1% risk (`research/challenge_sim.py`). A pass is
only worth it if the average passed account pays out more than `fee / pass_rate`:
**32× the challenge fee** at 1% risk. A $500 challenge therefore needs ~$16,000
of expected lifetime payout per pass to break even. That is not a claim about
your skill; it is the structure. If you still want one, buy the structure that
suits a slow trend system — no time limit, low target, generous drawdown — and
treat the fee as entertainment, not investment.

**If it is "compound a personal account": the system does that, slowly and
honestly.** Median +1.4% a year at 0.5% risk. Then the priority is
*operational correctness and patience*, not finding more strategies — and the
rest of this document is about that.

---

## 2. Expect to be underwater for years. Size the account for that, not for the return

In the 21-year shipping run, the **longest stretch of trades below a previous
equity peak was 116 trades — about 7.3 years** at 1.3 trades/month. Median
12-month outcome is +1.4%; the worst was −3.8%; 7 of 22 years were negative.

This is the single most important expectation to internalise, and the reason
not to watch this daily. It is also the reason risk stays at 0.5-0.75%: the
system's problem is not that it loses too much, it is that it wins too rarely to
be psychologically free. Raising risk to make it "worth it" shortens the
drawdown you can survive — a 4× larger position is a 4× deeper drawdown against
the same 7-year wait.

---

## 3. Demo-forward with a pre-committed stop rule (do this before live money)

Go on demo for 2-3 months and check two things:

**a. Is the bot doing what the research did?** Expect **1-2 trades per month**,
H4 breakouts only, no intraday entries, no entries on gold when price is below
the 200-bar average. If you see 20 trades in a month, something is misconfigured
and the research numbers do not describe what you are running.

**b. Falsification rule, decided now rather than in the moment.** Over 21 years
of *good* history, the rolling **20-trade expectancy** had a median of +0.184R
and a 5th percentile of −0.252R. A reasonable stop rule:

| Rolling 20-trade expectancy | Frequency in 21 years | What it means |
|---|---|---|
| ≤ −0.20R | 10.7% of windows | normal bad run, keep going |
| **≤ −0.30R** | **2.5% of windows** | **stop, investigate — this is rare in a working system** |
| ≤ −0.40R | 0.9% of windows | stop; almost certainly broken or decayed |

That is 8 occurrences in 319 windows. If it fires live, assume something real
changed before assuming it is variance.

---

## 4. Get real data — your own MT5 already has it

The binding constraint on every further question is history. This research ran
on a public 21-year M15 export; the FX breadth test ran on 3.4 years because
that is what was reachable. Your terminal can export decades of M1 for every
symbol your broker offers — indices, energies, rates, crypto, other FX crosses.

`tools/export_mt5_history.py` (to be written) would dump them to parquet in the
same layout the harness reads, and then every question below becomes testable in
the same afternoon. **This is the highest-leverage single action available.**

---

## 5. If you want more return, the extra bets must come from markets with a documented trend premium — not FX CFDs

I tested this rather than assuming it (`research/breadth_test.py`). Same logic,
same window (2023-2026), five instruments:

| Instrument | Trades | Expectancy | 95% CI | PF |
|---|---|---|---|---|
| XAUUSD | 36 | **+0.545R** | [−0.117, +1.335] | 1.85 |
| USDJPY | 60 | +0.083R | [−0.264, +0.463] | 1.23 |
| GBPUSD | 55 | −0.114R | [−0.448, +0.263] | 0.84 |
| EURUSD | 13 | −0.224R | [−0.714, +0.343] | 0.57 |
| AUDUSD | 58 | −0.231R | [−0.542, +0.136] | 0.63 |
| **Portfolio** | **222** | **+0.009R** | [−0.185, +0.222] | — |

Two conclusions:

* **Diversification works mechanically** — average pairwise monthly correlation
  was only **+0.15**, so adding instruments genuinely spreads risk.
* **But you cannot diversify your way out of a zero edge.** Adding four
  zero-and-negative-expectancy instruments produced a portfolio with +0.009R
  expectancy and a *deeper* drawdown (−7.4%) than gold alone (−1.1%).

Note what this also says about the gold result: in this 3.4-year window even
gold's +0.545R has a confidence interval that includes zero. The confidence in
the gold edge comes from the **21 years**, not from the recent rally — so do not
let a good recent window convince you to size up.

If you want breadth, get it from markets where trend following has decades of
published evidence (equity indices, rates, energies, crypto) — and test each one
through this harness before trading it. Do not add an instrument because of how
its chart looks.

---

## 6. Do not re-optimise the parameters

With 338 trades, more tuning fits noise rather than signal. Evidence from the
existing work: the walk-forward's "best" parameters wander (D20 → D30 → D40 →
D55 chosen in different years) while the out-of-sample result barely moves, and
**all 24 grid cells are positive** (CAGR 1.0% → 4.1%). The current defaults are
deliberately at the conservative end. Freeze them and judge the system on
whether it keeps producing trades within expectation, not on whether you can
find a better Donchian length on the data you already have.

---

## 7. Operational hygiene before any live money

- [ ] **Kill switch exists and is reachable.** The 20-trade rule from §3 is the
      trade-based one; the account-level one is the risk guardian's trailing
      drawdown. Know where both are.
- [ ] **Keep `LEGACY_STRATEGIES_ENABLED = False`.** Those four strategies
      measured −0.15R to −0.39R per trade. They are in the repo for study only.
- [ ] **Risk at 0.5-0.75%.** Not 2%, not "just for the first trade".
- [ ] **Verify the cost guard is live.** With a 25-point gold spread, a setup
      whose stop is under ~400 points is refused — check the log line appears
      rather than assuming it.
- [ ] **Alerts on silence.** Given this system should trade ~1.3 times a month,
      add a "no signal in 60 days" alert — a silently-broken indicator (200-bar
      MA over 100 fetched bars) is exactly the failure this repo has already hit
      once, and it produces no error, just nothing.
- [ ] **VPS with a stable connection.** MT5 has to stay up for a system that can
      wait weeks for a signal.
- [ ] **Keep the trade log.** Every fill, with the strategy reason string. The
      log is what lets you tell "the edge decayed" from "the bot broke".

---

## 8. What I would not do

- **Buy challenges with this system** (§1).
- **Add leverage to make it faster.** The edge is +0.26R; leverage scales both
  the return and the 7-year wait, and matters less than whether you can hold.
- **Re-run the intraday families.** 27,135 setups measured, all negative, and
  negative before costs.
- **Add market-map filters.** Tested against a permutation null
  (`research/map_filter_test.py`): nothing survived, threshold p < 0.006, best
  observed p = 0.11. See `docs/MARKET_MAPS.md` §3.
- **Trade an instrument because it looks like it trends.** NQ looks like it
  trends; so does everything on a log chart.

---

## 9. The one thing worth more than the strategy

Four investigations have now been run: intraday ICT families (negative),
the H4 trend system (positive, validated), market-map levels (one real
microstructure effect, no tradable signal), and map-based filters (rejected).
Three of the four came back negative and are documented as such.

That is the asset: `research/` can now falsify an idea against real data, real
costs, and matched controls in minutes, before it touches an account. Any idea
you meet online — from me or anyone else — can be put through it. If a claim
does not survive a matched null model and a permutation test, it was never an
edge; it was a story that happened to fit some history.
