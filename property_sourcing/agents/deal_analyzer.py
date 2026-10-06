"""Deal-analyzer agent — turns a lead + a market valuation into the numbers
that actually decide whether a deal is worth packaging: BMV%, refurb cost,
strategy recommendation, ROI and estimated monthly cashflow.

All assumptions are deliberately conservative and clearly documented so you
can tune them in one place (`config.py` or the constants below) instead of
trusting a black box. Where an LLM is configured it only writes the
*narrative*, never the numbers — the maths is always done in plain Python so
it's auditable.
"""
import logging

import config
from agents import llm_client

logger = logging.getLogger(__name__)

# Rough refurb budgets by property type (tune to your actual region/trades costs).
REFURB_RATE_BY_TYPE = {
    "flat": 8000,
    "terraced": 12000,
    "semi": 15000,
    "detached": 20000,
    "other": 12000,
}

GROSS_YIELD_ASSUMPTION = 0.07  # conservative UK buy-to-let gross yield assumption


def _estimate_mortgage_payment(asking_price, deposit_pct=0.25, rate=0.065, term_years=25):
    principal = asking_price * (1 - deposit_pct)
    monthly_rate = rate / 12
    n = term_years * 12
    if monthly_rate == 0:
        return principal / n
    payment = principal * (monthly_rate * (1 + monthly_rate) ** n) / ((1 + monthly_rate) ** n - 1)
    return payment


def _narrative(lead, estimated_market_value, bmv_percent, refurb, roi_percent, strategy, monthly_cashflow):
    prompt = (
        f"Address: {lead.get('address')}\n"
        f"Asking price: £{lead.get('asking_price'):,.0f}\n"
        f"Estimated market value: £{estimated_market_value:,.0f}\n"
        f"Below market value: {bmv_percent}%\n"
        f"Refurb estimate: £{refurb:,.0f}\n"
        f"Projected ROI: {roi_percent}%\n"
        f"Suggested strategy: {strategy}\n"
        f"Estimated monthly cashflow once let: £{monthly_cashflow:,.0f}\n"
    )
    try:
        return llm_client.complete(
            system_prompt=(
                "You are a UK property sourcing analyst writing for a busy investor. "
                "In 3-4 plain-English sentences, summarise why this deal is (or isn't) "
                "worth pursuing, referencing the BMV%, strategy and ROI given. "
                "Never invent numbers that are not provided."
            ),
            user_prompt=prompt,
            max_tokens=200,
        )
    except llm_client.LLMUnavailable:
        return (
            f"{lead.get('address') or 'This property'} is priced at "
            f"£{lead.get('asking_price'):,.0f} against an estimated market value of "
            f"£{estimated_market_value:,.0f} ({bmv_percent}% below market). Allowing "
            f"~£{refurb:,.0f} for refurbishment, the projected ROI is {roi_percent}% "
            f"with suggested strategy: {strategy}. Estimated monthly cashflow once "
            f"let: £{monthly_cashflow:,.0f}."
        )


def analyze(lead: dict, estimated_market_value) -> dict:
    """Pure-Python financial analysis of one lead. Returns a dict ready to be
    written straight into the `leads` table."""
    asking = lead.get("asking_price")
    result = {
        "estimated_market_value": estimated_market_value,
        "bmv_percent": None,
        "refurb_estimate": None,
        "gdv": None,
        "strategy": None,
        "roi_percent": None,
        "monthly_cashflow": None,
        "score": 0,
        "notes": "Not enough data yet to value this lead — needs manual research "
                 "(no asking price and/or no comparable sales found nearby).",
    }

    if not estimated_market_value or not asking:
        return result

    bmv_percent = round((estimated_market_value - asking) / estimated_market_value * 100, 1)
    refurb = REFURB_RATE_BY_TYPE.get((lead.get("property_type") or "other"), 12000)
    gdv = estimated_market_value  # conservative: refurb brings it back to local market value
    total_in = asking + refurb
    profit_if_flip = gdv - total_in
    roi_percent = round((profit_if_flip / total_in) * 100, 1) if total_in else None

    annual_rent_estimate = estimated_market_value * GROSS_YIELD_ASSUMPTION
    monthly_cashflow = round(annual_rent_estimate / 12 - _estimate_mortgage_payment(asking))

    bedrooms = lead.get("bedrooms") or 0
    if bedrooms >= 4:
        strategy = "HMO conversion"
    elif bmv_percent >= config.MIN_BMV_PERCENT and roi_percent and roi_percent >= config.MIN_ROI_PERCENT:
        strategy = "BRRR (buy, refurb, refinance, rent)"
    elif bmv_percent >= config.MIN_BMV_PERCENT:
        strategy = "Flip / quick resale"
    else:
        strategy = "Buy-to-let (hold)"

    score = round(max(0, bmv_percent) * 0.6 + max(0, roi_percent or 0) * 0.4, 1)

    result.update(
        {
            "bmv_percent": bmv_percent,
            "refurb_estimate": refurb,
            "gdv": gdv,
            "strategy": strategy,
            "roi_percent": roi_percent,
            "monthly_cashflow": monthly_cashflow,
            "score": score,
            "notes": _narrative(
                lead, estimated_market_value, bmv_percent, refurb, roi_percent, strategy, monthly_cashflow
            ),
        }
    )
    return result
