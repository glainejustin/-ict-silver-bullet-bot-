# Architecture

```
            ┌────────────────────┐
            │     Connectors      │   free, ToS-safe lead sources
            │  (find raw signals) │
            └─────────┬───────────┘
                       │ dicts matching the `leads` schema
                       ▼
                 ┌───────────┐
                 │  SQLite   │   leads / comps / buyers / outreach / activity
                 │   (db.py) │
                 └─────┬─────┘
                       │
      ┌────────────────┼─────────────────┐
      ▼                ▼                  ▼
 comp_finder      deal_analyzer     investor_matcher     (agents/*)
 (Land Registry   (BMV%, refurb,    (matches CRM buyers
  median comps)    ROI, strategy)    by area/budget/strategy)
      │                │                  │
      └────────┬───────┴─────────┬────────┘
               ▼                 ▼
        outreach_writer   outreach/email_sender
        (drafts email,     (SMTP send or dry-run draft)
         LLM or template)
               │
               ▼
        dashboard (Flask app.py) + daily digest email
```

## Design principles
1. **Every connector is independent and replaceable.** Adding a new free
   data source means writing one new file implementing `fetch_leads()` —
   nothing else needs to change (see `connectors/base.py`).
2. **The maths is never hidden inside an LLM call.** `agents/deal_analyzer.py`
   computes BMV%, refurb budget, ROI and strategy in plain, auditable Python.
   The LLM (if configured) only ever writes the *narrative* explaining
   numbers that already exist — this avoids the classic "AI hallucinated a
   fake return" trap that would be a serious liability in a financial tool.
3. **Nothing requires an LLM to function.** Every agent that calls
   `agents/llm_client.py` catches `LLMUnavailable` and has a solid
   rule-based fallback, so the system is useful at absolute zero cost.
4. **Outreach has an explicit safety switch** (`DRY_RUN_OUTREACH`), separate
   from whether an LLM is configured, separate from which connectors are
   enabled — three independent levers so you can dial automation up
   gradually as you build trust in the output.
5. **SQLite, not a hosted database.** Zero cost, zero ops, one file,
   trivially backed up — appropriate for a single-operator sourcing
   business. Swap for Postgres later if you ever need concurrent writers.

## Data flow guarantees
- `source + source_ref` is a unique key on `leads`, so re-running connectors
  (e.g. every day via the scheduler) never creates duplicate leads — the
  pipeline is idempotent and safe to re-run as often as you like.
- `outreach` rows are only ever created once per (lead, buyer) pair
  (`match_and_draft_outreach` checks existing rows first), so a buyer never
  gets emailed about the same deal twice even across many scheduled runs.
