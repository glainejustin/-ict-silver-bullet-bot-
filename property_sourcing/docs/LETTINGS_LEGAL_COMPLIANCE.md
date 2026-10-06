# UK Lettings Referrals — Legal & Compliance Checklist

**Not legal advice** — the same disclaimer as `LEGAL_COMPLIANCE.md` applies:
verify current rules with a solicitor/OISC-registered immigration adviser
before operating. This covers what's specifically different about adding a
**lettings/tenant-introduction** business line on top of sales sourcing.

## The core rule that shapes the whole model: Tenant Fees Act 2019
You **cannot** charge a tenant a fee for finding them a property, referencing,
inventory checks, "admin", or renewals. The only payments a tenant can
legally be asked for are:
- Rent.
- A refundable security deposit (capped at 5 weeks' rent, or 6 weeks if
  annual rent is over £50,000).
- A refundable holding deposit (capped at 1 week's rent).
- Payments for defaulting (late rent, lost keys) — capped and specific.

**This is why this module's commission model always charges the landlord,
never the tenant** — `agents/commission.py` has no tenant-fee code path at
all, deliberately, so it's not possible to misconfigure this by accident.

## Redress scheme
If you already joined The Property Ombudsman (TPO) or Property Redress
Scheme (PRS) for sourcing, check whether your membership category needs
extending to cover lettings agency work too — most schemes have a single
membership that covers both, but confirm with them directly.

## Client Money Protection (CMP) — only if you ever hold money
If you only *introduce* a tenant to a landlord and the landlord handles rent
and deposits directly between themselves and the tenant, you are not holding
client money and CMP typically doesn't apply to you.

**The moment you hold any rent, deposit, or fee on behalf of a landlord or
tenant — even briefly — you are legally required to be a member of a
government-approved Client Money Protection scheme.** The simplest way to
stay outside this requirement while you're small: never touch the money,
have the tenant pay the landlord (or the landlord's agent) directly, and
invoice the landlord for your commission separately and afterward.

## Deposit protection
If a landlord you've introduced a tenant to takes a deposit, it's their
responsibility (or their appointed agent's) to protect it in a government
-approved scheme within 30 days. You're not liable for this as a pure
introducer, but it's worth knowing so you can flag it if a landlord seems
unaware of the requirement — this protects your reputation with tenants too.

## AML supervision for lettings specifically
HMRC's "letting agency business" AML registration requirement is specifically
triggered when the **monthly rent is 10,000 EUR or more** (roughly £8,500+
depending on the rate) — most residential lettings fall under this threshold.
If you're already AML-registered for sales/sourcing work, that registration
generally covers your business as a whole; check with HMRC/your supervisor
if your lettings activity includes any high-value tenancies.

## Right to Rent checks
Whoever actually lets the property (the landlord, or their appointed
managing/letting agent) is legally required to check every adult tenant's
right to rent in the UK before the tenancy starts. As a pure introducer who
doesn't manage the tenancy, this duty normally sits with the landlord — but
flag it clearly in your landlord communications so there's no ambiguity
about whose responsibility it is.

## Advertising
- Rental listings must show the amount of rent, and advertising a property
  as available before you have authority from the landlord to market it
  (sole or multi-agency) is not advisable — get a simple written instruction
  from the landlord first, even just an email confirming you can introduce
  tenants for X commission.
- As with sourcing, no scraping Rightmove/Zoopla's listings — a landlord
  gives you their listing directly, or you source it through the same free,
  ToS-safe connectors used elsewhere in this project (e.g. a council's HMO
  licence register as a landlord-lead source, not as a tenant-facing listing
  scrape).

## Suggested order of operations (adds to the existing sales checklist)
1. Confirm your redress scheme membership covers lettings.
2. Get a simple written landlord instruction/agreement before introducing
   tenants on their behalf (template in `SOURCING_AGREEMENT_TEMPLATE.md` can
   be adapted — a lettings-specific version is in
   `LETTINGS_INTRODUCTION_AGREEMENT_TEMPLATE.md`).
3. Decide your commission structure (e.g. one month's rent, or a % of annual
   rent) and set it once in `.env` (`COMMISSION_TYPE` / `COMMISSION_VALUE`).
4. Never accept rent, deposits, or any tenant payment yourself.
5. Only then start real landlord/tenant outreach (flip `DRY_RUN_OUTREACH=false`).
