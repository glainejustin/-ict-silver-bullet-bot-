# UK Property Sourcing — Legal & Compliance Checklist

**This is not legal advice.** It's a practical starting checklist based on
publicly available UK government guidance, so you know what to check with a
solicitor/accountant before trading. Rules change — always verify current
requirements before you start taking fees from clients.

Property sourcing / deal-packaging is legally treated similarly to estate
agency and property investment advice in several respects. The main things
every real UK sourcer is expected to have in place:

## 1. Anti-Money Laundering (AML) supervision — likely required
If you're introducing buyers to sellers of property, HMRC generally treats
this as "estate agency business" under the Money Laundering Regulations,
which requires:
- Registering for AML supervision with HMRC (or another supervisor if you're
  also a letting/estate agent elsewhere).
- Carrying out customer due diligence (ID checks) on clients.
- Fee: currently a modest annual HMRC registration fee.
- Guidance: search "HMRC anti-money laundering supervision estate agency
  business" on gov.uk for the current process and fee.

## 2. Redress scheme membership — required if you fall under the Estate
   Agents Act 1979 definition
Many sourcers register with **The Property Ombudsman (TPO)** or the
**Property Redress Scheme (PRS)** — required by law for UK estate agency
work, and widely adopted by sourcers as a trust signal and legal safety net
even where the exact scope is debated. Cost is typically a low annual fee.

## 3. ICO registration (data protection)
You will be storing personal data (seller/investor names, emails, phone
numbers) — register with the **Information Commissioner's Office (ICO)**.
This is a legal requirement for almost any UK business handling personal
data, costs a small annual fee, and takes minutes online.

## 4. Client money handling
If you ever hold a buyer's deposit or fee before a deal completes, UK rules
around client money protection may apply. Simplest safe approach for a
sourcer: **take your sourcing fee only after an investor has exchanged
contracts via their own solicitor** — avoid holding client money at all
while you're starting out.

## 5. A proper sourcing agreement / terms of business
Every deal you package should go out with a clear, written agreement stating
your fee, when it's payable, and what you have and haven't verified about
the property. Get a solicitor or a reputable template (many UK property
investment associations publish these) reviewed once, then reuse it.

## 6. Advertising standards & honesty in outreach
- Don't claim numbers (BMV%, ROI, comps) that you haven't actually verified
  — this tool is built so every number traces back to real Land Registry
  data or your own asking price input, specifically to avoid this risk.
- UK GDPR/PECR rules on unsolicited marketing emails (PECR) apply —
  generally safe for B2B outreach to investors about a specific relevant
  opportunity, but always include a clear way to opt out, and never email
  anyone not already in your own CRM / who hasn't engaged with you before.

## 7. Scraping & data source terms of service
- Rightmove, Zoopla, and most property portals explicitly prohibit
  automated scraping in their Terms of Service — this toolkit deliberately
  does **not** touch them.
- HM Land Registry Price Paid Data and Companies House data are published
  under the Open Government Licence / as a free public API — safe and
  intended for this kind of use.
- Before enabling any `AUCTION_FEED_URLS`, check that specific auction
  house's terms allow automated polling of their public feed.

## Suggested order of operations
1. Decide your business name/structure (sole trader is the simplest zero-cost
   start; a limited company is ~£50 and more credible to investors).
2. Register for AML supervision with HMRC.
3. Join a redress scheme (TPO or PRS).
4. Register with the ICO.
5. Get a sourcing agreement template reviewed once.
6. Only then start sending real outreach (flip `DRY_RUN_OUTREACH=false`).

Total realistic one-off + annual cost for steps 1-4: roughly **£100-250/year**
— genuinely the minimum viable legal footprint for a UK sourcing business,
automation or not.
