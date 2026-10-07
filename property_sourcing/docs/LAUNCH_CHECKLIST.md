# Launch Checklist — "build now, launch later"

This project is currently a **personal technical project / portfolio
build**, not an operating business — that's a deliberate choice if your
current UK immigration status (e.g. a Skilled Worker visa) doesn't permit
self-employment or running your own business. Writing software, learning,
and testing it with your own fictional/demo data is fine; taking fees from
clients or operating as a sourcing agent is the part that requires the right
status. **Always confirm your specific situation with an OISC-registered
immigration adviser or immigration solicitor before switching this from
"project" to "business" — this document is not legal advice.**

Use this checklist the day your situation changes (see triggers below) to go
from "code that works" to "business that's legally running" as fast as
possible, because the hard technical work will already be done.

This applies equally to **both lines built in this repo**: the property
sourcing/deal-packaging side, and the lettings/rental referral side. The
lettings module has its own legal-compliance notes and agreement template —
see [`docs/LETTINGS_LEGAL_COMPLIANCE.md`](LETTINGS_LEGAL_COMPLIANCE.md) and
[`docs/LETTINGS_INTRODUCTION_AGREEMENT_TEMPLATE.md`](LETTINGS_INTRODUCTION_AGREEMENT_TEMPLATE.md).
Neither line should be operated for real — outreach sent, fees taken,
landlords/tenants contacted for real — until an adviser confirms your status
allows it.

Not sure what's worth actually paying an adviser to clarify, versus what's
already settled? See
[`docs/IMMIGRATION_ADVISER_QUESTIONS.md`](IMMIGRATION_ADVISER_QUESTIONS.md)
for a short, specific list of the genuinely ambiguous questions (e.g.
personal buy-to-let investment, open-sourcing the code for free) worth a
paid session, versus the ones already answered here.

## Triggers that commonly change what's allowed
*(confirm current rules for your exact case with an adviser — don't rely on this list)*
- You're granted **Indefinite Leave to Remain (ILR)** / settled status.
- You switch to a visa route that does permit self-employment (e.g.
  **Innovator Founder visa**, **Global Talent visa**, a family/partner visa
  with no work restrictions, or British citizenship).
- You partner with someone who is eligible (UK citizen / ILR holder) to be
  the legal owner/operator, and your involvement stays limited to what your
  own visa allows (get this structure checked by an immigration adviser
  *before* relying on it — "I just help a friend's business for free" can
  still be scrutinised).
- Your sponsor explicitly approves relevant supplementary work arrangements
  that an adviser confirms are compliant.

## Day 1 of going live — legal steps (see `LEGAL_COMPLIANCE.md` for detail)
- [ ] Confirm with an immigration adviser that your current status permits this.
- [ ] Decide structure: sole trader (whoever is the eligible legal operator) or limited company.
- [ ] Register for AML supervision (HMRC or relevant supervisor).
- [ ] Join a redress scheme (TPO or PRS).
- [ ] Register with the ICO (data protection).
- [ ] Get a sourcing agreement / terms of business template reviewed by a
      solicitor — a starting draft is in
      [`docs/SOURCING_AGREEMENT_TEMPLATE.md`](SOURCING_AGREEMENT_TEMPLATE.md).
- [ ] If operating the lettings side too: get the landlord introduction
      agreement reviewed by a solicitor — a starting draft is in
      [`docs/LETTINGS_INTRODUCTION_AGREEMENT_TEMPLATE.md`](LETTINGS_INTRODUCTION_AGREEMENT_TEMPLATE.md) —
      and re-confirm with an adviser that your redress scheme/AML
      registration covers lettings agency work, not just sourcing (they are
      regulated separately in the UK).
- [ ] Open a business bank account in the legal operator's name.

## Day 1 of going live — technical steps (all in this repo already)
- [ ] `cp .env.example .env` and fill in real values.
- [ ] Get a free Companies House API key.
- [ ] Set up a dedicated business email (not a personal Gmail) + App Password/SMTP creds, using the **legal operator's** business details, not yours, if you're in the "trusted partner" structure.
- [ ] Add real buyers/investors to the CRM (`/buyers` in the dashboard).
- [ ] Review a few days of drafted outreach with `DRY_RUN_OUTREACH=true` before going live.
- [ ] Deploy `scheduler.py` on an always-on host (see `docs/DEPLOYMENT.md`).
- [ ] Set `DRY_RUN_OUTREACH=false` only once you're legally and operationally ready.

## In the meantime (safe to do right now, no business activity involved)
- [ ] Keep improving the codebase (more connectors, better analysis, nicer dashboard) — this is software development, not trading.
- [ ] Run it only against demo/seed data or your own test leads (`python run_pipeline.py --demo`).
- [ ] Never add real sellers/investors' personal data or send any real outreach while `DRY_RUN_OUTREACH` isn't explicitly and legally cleared.
- [ ] Keep `DIGEST_TO_EMAIL`/`SMTP_*` pointed only at your own test inbox for now.
- [ ] Revisit this checklist periodically or whenever your visa status changes.
