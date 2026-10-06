# Property Sourcing Autopilot 🏠🤖

An automated, AI-agent-driven engine for running a **UK property deal-sourcing
business** (find below-market-value deals → package them → match to
investors → draft outreach → sell the lead for a sourcing fee) with as close
to zero cost and zero daily involvement as realistically possible.

> **Read this first:** no software can legally register a company, open a
> bank account, or make you compliant with UK property law on its own. See
> [`docs/LEGAL_COMPLIANCE.md`](docs/LEGAL_COMPLIANCE.md) for the few
> one-off, human steps you still need to do (they're cheap and quick).
> Everything else below *is* automated.

## What it actually does, end to end

```
 Connectors (find signals)  →  AI Agents (think)              →  Outreach (act)
 ───────────────────────       ──────────────────────            ──────────────
 • Companies House            • Comp-finder: values the         • Drafts a personalised
   (distressed/dissolved        property from real HM Land        email per matched buyer
   property companies)          Registry sold-price data         • Sends automatically
 • Public auction feeds       • Deal-analyzer: BMV%, refurb         (or waits for your
 • CSV / open-data imports      cost, ROI, strategy, cashflow        one-click approval —
   (council registers,        • Investor-matcher: finds which        your choice)
   planning data, manual         buyers in your CRM actually       • Emails YOU a daily
   leads)                        want this deal                     digest so you rarely
                                                                      need to open anything
```

Everything runs on a schedule (`scheduler.py`) with no human in the loop by
default, except the two safety switches you control:
`DRY_RUN_OUTREACH` (review before sending) and your buyer CRM (who's allowed
to be contacted).

## Quick start (fully offline demo, zero cost, zero signup)

```bash
cd property_sourcing
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python run_pipeline.py --demo     # ingest, value, analyze & draft outreach for 4 sample leads
python app.py                      # open http://localhost:8000
```

That's it — you'll see a scored, analyzed deal pipeline and drafted investor
emails without needing a single API key.

## Making it real

1. **Copy `.env.example` to `.env`** and fill in what you have (every field
   is optional, everything degrades gracefully):
   - `COMPANIES_HOUSE_API_KEY` — free, instant signup at
     [developer.company-information.service.gov.uk](https://developer.company-information.service.gov.uk/)
   - `AUCTION_FEED_URLS` — public RSS/JSON catalogue feeds from auction
     houses you've checked allow polling
   - `SMTP_USERNAME` / `SMTP_PASSWORD` — a free Gmail account + an
     [App Password](https://myaccount.google.com/apppasswords)
   - `LLM_PROVIDER` / `LLM_API_KEY` — optional. Leave as `none` for the
     built-in rule-based writer, or add a free-tier key (e.g.
     [Groq](https://console.groq.com)) for noticeably better-written
     analysis and outreach emails
2. **Add your real buyers/investors** on the "Buyer CRM" page (or edit
   `seed/buyers_seed.csv` and reload) — the AI agent will only ever email
   people on this list, matched against their own stated area/budget/strategy.
3. **Run `python scheduler.py`** on any always-on machine (a £3-5/month VPS,
   a free-tier Render/Railway worker, a Raspberry Pi, or even just a
   cron job) so it keeps finding and packaging deals every day without you.
4. Leave `DRY_RUN_OUTREACH=true` until you've read a day or two of drafted
   emails and I'm happy with the quality — then flip it to `false` for fully
   autonomous sending.

## Project layout

```
connectors/     free, ToS-safe data sources that find raw leads
agents/         the "AI" — valuation, deal scoring, buyer matching, email writing
outreach/       SMTP sending + the daily digest email to you
dashboard/      the Flask web UI templates/assets
pipeline.py     orchestrates connectors → agents → outreach, one call
scheduler.py    runs pipeline.py forever, on a timer, unattended
app.py          the dashboard web server
run_pipeline.py CLI to run everything once (supports --demo)
seed/           offline demo data + your buyer CRM starter file
tests/          automated tests (run `pytest`), including a full offline
                end-to-end pipeline test
docs/           legal compliance checklist, architecture notes, getting started
```

## Why this can't be truly "zero investment or zero involvement"

Being transparent about the honest limits, because a tool that pretends
otherwise would get you into trouble:

- **Legal registration is non-negotiable and is you, not code**: UK property
  sourcing/deal-packaging is regulated — see
  [`docs/LEGAL_COMPLIANCE.md`](docs/LEGAL_COMPLIANCE.md). Budget ~£100-250
  one-off/yearly for redress scheme + ICO registration; this is a legal
  requirement, not a nice-to-have.
- **Scraping Rightmove/Zoopla directly is against their Terms of Service**,
  so this system deliberately avoids them and instead uses official free
  data (Land Registry, Companies House) and ToS-permitted public auction
  feeds. This is slightly more manual-setup work than "scrape everything",
  but it won't get your IP banned or you sued.
- **An LLM key costs a few pounds a month at most** if you want the AI
  writing to be more persuasive than the built-in templates — genuinely
  optional, not required to operate.
- **You still need to actually do the deal-closing human parts** — call a
  motivated seller, sign a sourcing agreement with an investor, view a
  property. This system is built to make sure your time only ever goes on
  those high-value conversations, never on data entry or writing emails from
  scratch.
