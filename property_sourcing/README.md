# Property Sourcing Autopilot 🏠🤖

[![Property Sourcing Autopilot Tests](https://github.com/glainejustin/-ict-silver-bullet-bot-/actions/workflows/property-sourcing-tests.yml/badge.svg)](https://github.com/glainejustin/-ict-silver-bullet-bot-/actions/workflows/property-sourcing-tests.yml)

> 🚧 **Status: build-now, launch-later project.** If your current UK
> immigration status doesn't permit self-employment/running a business (e.g.
> a Skilled Worker visa), this is being developed and tested purely as a
> personal software project against demo data — not operated as a live
> business — until that changes. See
> [`docs/LAUNCH_CHECKLIST.md`](docs/LAUNCH_CHECKLIST.md) for exactly what to
> do (legally and technically) the day it can go live. This is not legal or
> immigration advice — confirm your situation with an OISC-registered
> adviser or immigration solicitor.

An automated, AI-agent-driven engine for running two related **UK property
businesses**, both built with as close to zero cost and zero daily
involvement as realistically possible:

1. **Sourcing** — find below-market-value deals → package them → match to
   investors → draft outreach → sell the lead for a one-off sourcing fee.
2. **Lettings referral** — find rental listings (landlord leads) and tenant
   leads → match a tenant to a listing → introduce them → earn a referral
   commission **from the landlord only**. No fee is ever charged to the
   tenant — see
   [`docs/LETTINGS_LEGAL_COMPLIANCE.md`](docs/LETTINGS_LEGAL_COMPLIANCE.md)
   for why (Tenant Fees Act 2019) and
   [`agents/commission.py`](agents/commission.py) for how that rule is
   enforced in code.

> **Read this first:** no software can legally register a company, open a
> bank account, or make you compliant with UK property law on its own. See
> [`docs/LEGAL_COMPLIANCE.md`](docs/LEGAL_COMPLIANCE.md) for the few
> one-off, human steps you still need to do (they're cheap and quick).
> Everything else below *is* automated.

## What it actually does, end to end

```
 Connectors (find signals)       →  AI Agents (think)              →  Outreach (act)
 ───────────────────────            ──────────────────────            ──────────────
 • Companies House                  • Comp-finder: values the         • Drafts a personalised
   (distressed/dissolved              property from real HM Land        email per matched buyer
   property companies)                Registry sold-price data         • Sends automatically
 • The Gazette (official           • Deal-analyzer: BMV%, refurb         (or waits for your
   bankruptcy/winding-up             cost, ROI, strategy, cashflow        one-click approval —
   notices)                        • Investor-matcher: finds which        your choice)
 • Brownfield Land Register           buyers in your CRM actually       • Emails YOU a daily
   (council-identified                want this deal                     digest so you rarely
   development sites)                                                    need to open anything
 • Public auction feeds            • PDF deal-pack generator for
 • Council/open-data CSVs            whoever asks for full details
   (empty-homes registers etc.)
 • HM Land Registry corporate
   ownership (CCOD/OCOD)
 • Manual entry / CSV import
```

Seven free data connectors, all documented in [`connectors/`](connectors/) —
every one of them no-ops quietly and logs a message if you haven't
configured it yet, so it's always safe to leave them all switched on.

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
                                   # + 2 demo rental listings matched to 2 demo tenants
python app.py                      # open http://localhost:8000
```

That's it — you'll see a scored, analyzed deal pipeline, drafted investor
emails, and (on the "Lettings" tab) two demo rental listings matched to two
demo tenants with drafted landlord-introduction emails and calculated
commission — all without needing a single API key.

## The lettings/rental referral module

```
Landlord leads (CSV/manual)   Tenant leads (CSV/public form)
        │                             │
        └──────────────┬──────────────┘
                        ▼
      agents/rental_matcher.py matches on area, budget, bedrooms
                        ▼
   agents/commission.py calculates the fee (landlord pays — always)
                        ▼
  outreach/rental_outreach_writer.py drafts an intro email to the
  landlord sharing only an anonymised tenant profile (no contact
  details) until the landlord confirms interest
                        ▼
      Landlord agrees → mark as let → commission invoice PDF
      (outreach/commission_invoice.py) — states on its face that
      no fee has been or will be charged to the tenant
```

- `COMMISSION_TYPE` / `COMMISSION_VALUE` in `.env` control how the fee is
  calculated: `one_month_rent` (default, multiplier of one month's rent),
  `percent_of_annual_rent`, or `flat_fee`.
- Rental listings and tenant leads can be imported from CSV
  (`connectors/rental_csv_import.py`, `connectors/tenant_csv_import.py`,
  `--rental-csv` / `--tenant-csv` flags on `run_pipeline.py`) or added by
  hand on the dashboard's "Lettings" tab.
- Same safety posture as the sourcing side: `DRY_RUN_OUTREACH` governs
  whether landlord intro emails are actually sent or just drafted, and the
  demo data is fictional throughout.

## Making it real

1. **Copy `.env.example` to `.env`** and fill in what you have (every field
   is optional, everything degrades gracefully):
   - `COMPANIES_HOUSE_API_KEY` — free, instant signup at
     [developer.company-information.service.gov.uk](https://developer.company-information.service.gov.uk/)
   - `AUCTION_FEED_URLS` — public RSS/JSON catalogue feeds from auction
     houses you've checked allow polling
   - `GAZETTE_SEARCH_TERMS` / `BROWNFIELD_LOCAL_AUTHORITY` — these two
     connectors (official insolvency notices, council brownfield sites) are
     free, national and need no signup at all; just enable them in `.env`
   - `OPEN_DATA_CSV_URLS` — any council empty-homes/vacant-property CSV you
     find (search "`<council> empty homes register open data`")
   - `CCOD_CSV_PATH` — optional, most advanced connector: a free one-off
     account at [use-land-property-data.service.gov.uk](https://use-land-property-data.service.gov.uk/)
     gets you the full dataset of which companies own which UK properties —
     turns a vague Companies House signal into an exact address
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

## What's in the dashboard
- **Pipeline view** — every lead, scored and filterable by status.
- **Add lead manually** — log a tip from a contact or local group without touching a CSV.
- **Deal detail page** — full valuation breakdown, comps used, outreach history, and a
  **"Download deal pack (PDF)"** button that generates a client-ready one-pager.
- **Buyer CRM** — your investor list and matching criteria.
- **Re-run valuation** on any single lead on demand.
- **Lettings tab** — rental listings, tenant leads, landlords, one-click
  "find matching tenants now", "mark as let", and a
  **"Commission invoice (PDF)"** button (landlord-only fee, by design).

## Project layout

```
connectors/     7 free, ToS-safe data sources that find raw leads, plus
                rental_csv_import.py / tenant_csv_import.py for lettings
agents/         the "AI" — valuation, deal scoring, buyer matching, email
                writing, plus commission.py / rental_matcher.py for lettings
outreach/       SMTP sending, PDF deal-pack generator, the daily digest
                email, plus rental_outreach_writer.py (landlord intro
                emails) / commission_invoice.py (PDF) for lettings
dashboard/      the Flask web UI templates/assets (sales + lettings tabs)
pipeline.py     orchestrates connectors → agents → outreach, one call (sales)
rental_pipeline.py   same, for lettings: ingest listings/tenants → match →
                draft/send landlord intros → track commission
scheduler.py    runs pipeline.py forever, on a timer, unattended
app.py          the dashboard web server
run_pipeline.py CLI to run everything once (supports --demo, --rentals,
                --rental-csv, --tenant-csv)
seed/           offline demo data: leads, buyers, rental listings, tenants,
                landlords
tests/          automated tests (run `pytest`), including full offline
                end-to-end pipeline tests (sales + lettings) and mocked
                tests for every connector — these run automatically on
                every push via GitHub Actions
                (see `.github/workflows/property-sourcing-tests.yml`)
docs/           legal compliance checklists (sourcing + lettings), launch
                checklist, sourcing agreement template, lettings
                introduction agreement template, deployment guide,
                architecture notes
deploy/systemd/ ready-made systemd service files for VPS deployment
Dockerfile, docker-compose.yml, Procfile, render.yaml
                four different one-command deployment options for later
```

## 📋 Not ready to launch yet?

If you can't legally operate a business right now (for example, a visa that
doesn't permit self-employment), see
[`docs/LAUNCH_CHECKLIST.md`](docs/LAUNCH_CHECKLIST.md) — it's written
specifically for "keep building and testing now, flip the switch later"
and lists exactly what changes (legally and technically) the day you can.
If you want to take a short, specific list of questions to a paid
immigration adviser session rather than a general "can I do this" review,
see [`docs/IMMIGRATION_ADVISER_QUESTIONS.md`](docs/IMMIGRATION_ADVISER_QUESTIONS.md).

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
