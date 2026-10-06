# Getting Started

## 1. Try the offline demo (2 minutes, no signups)

```bash
cd property_sourcing
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run_pipeline.py --demo
python app.py
```

Open the dashboard URL printed in the terminal (defaults to
`http://localhost:8000`). You'll see 4 sample leads already ingested, valued
against sample comps, scored, and — for the ones that clear your BMV/ROI
thresholds — matched to sample buyers with draft emails ready to view.

## 2. Add your real buyer/investor list
Go to **Buyer CRM** in the dashboard and add each investor you already know,
or bulk-edit `seed/buyers_seed.csv` (format documented in the file) and
re-run `python run_pipeline.py --demo` to reload it. The more specific their
area/budget/strategy, the better the AI's matching.

## 3. Turn on real data sources
Copy `.env.example` → `.env`, then enable as many of these free connectors
as you like — each one no-ops quietly if left unconfigured:
- **Companies House** (free, needs a key): register at
  developer.company-information.service.gov.uk, paste the key in. Finds
  dissolved/distressed property companies.
- **The Gazette** (free, no key): official bankruptcy/winding-up notices —
  set `GAZETTE_SEARCH_TERMS` or leave blank for sensible defaults.
- **Brownfield Land Register** (free, no key): national register of
  council-identified development sites — set `BROWNFIELD_LOCAL_AUTHORITY`
  to scope to one council, or leave blank for the latest nationally.
- **Auction feeds** (free, optional): find a UK auction house's public lot
  RSS/JSON feed, confirm their terms allow polling, add the URL(s) to
  `AUCTION_FEED_URLS`.
- **Council open-data CSVs** (free): empty-homes/vacant-property registers
  individual councils publish — add direct CSV URLs to `OPEN_DATA_CSV_URLS`.
- **HM Land Registry corporate ownership** (free, needs a one-off signup):
  get the CCOD/OCOD dataset from use-land-property-data.service.gov.uk,
  set `CCOD_CSV_PATH` — turns a Companies House signal into an exact address.
- **CSV leads** (free, always available): export anything from a council
  open-data portal, planning register, or your own notes into a CSV with
  columns `address,postcode,property_type,bedrooms,asking_price,motivation_signal`
  and run `python run_pipeline.py --csv yourfile.csv`, or use the "Add lead
  manually" button in the dashboard for one-off entries.

## 4. Turn on real outreach
- Create (or use) a Gmail account, generate an **App Password**
  (myaccount.google.com/apppasswords), add `SMTP_USERNAME`/`SMTP_PASSWORD`/
  `SMTP_FROM_EMAIL` to `.env`.
- Set `DIGEST_TO_EMAIL` to your own email so you get a daily one-page summary.
- Leave `DRY_RUN_OUTREACH=true` at first — read a few days of drafted emails
  in the dashboard. When you trust the output, set it to `false`.

## 5. Make it run unattended
On any always-on machine (a cheap VPS, a free-tier cloud worker, even a
Raspberry Pi at home):

```bash
python scheduler.py
```

This runs the full pipeline immediately, then every 24 hours (configurable
via `PIPELINE_INTERVAL_HOURS`), forever, with no further input from you.

## 6. (Optional) Make the AI agent smarter
By default, all analysis and emails use a solid built-in rule-based writer —
genuinely free, no signup. To upgrade the *writing quality* only (the maths
is always done in plain Python either way):

```
LLM_PROVIDER=groq
LLM_API_KEY=your-free-groq-key
```

Get a free key at console.groq.com — their free tier is generous and this
app's usage is light (a few short completions per deal).
