"""Outreach-writer agent — drafts the investor email for a matched deal.
Falls back to a solid template when no LLM is configured, so outreach never
blocks on having an API key.
"""
from agents import llm_client


def _template(lead: dict, buyer: dict) -> tuple:
    subject = f"Off-market opportunity: {lead.get('address') or lead.get('postcode')} ({lead.get('strategy') or 'deal'})"
    body = f"""Hi {buyer.get('name', 'there').split(' ')[0]},

I've sourced a deal that matches your buying criteria:

Address: {lead.get('address') or 'Address on request'}
Area: {lead.get('postcode') or lead.get('outcode')}
Asking price: £{lead.get('asking_price'):,.0f}
Estimated market value: £{(lead.get('estimated_market_value') or 0):,.0f}
Below market value: {lead.get('bmv_percent')}%
Suggested strategy: {lead.get('strategy')}
Projected ROI: {lead.get('roi_percent')}%
Estimated monthly cashflow: £{(lead.get('monthly_cashflow') or 0):,.0f}

{lead.get('notes', '')}

This is going out to a short list of matched investors — let me know today if
you'd like the full deal pack (comps, photos, refurb breakdown) and I'll send
it straight over, subject to my standard sourcing fee agreement.

Best regards,
{{YOUR_NAME}}
"""
    return subject, body


def draft_email(lead: dict, buyer: dict) -> tuple:
    """Returns (subject, body)."""
    try:
        prompt = (
            f"Buyer name: {buyer.get('name')}\n"
            f"Buyer's investing focus: {', '.join(buyer.get('strategies') or []) or 'general'}\n\n"
            f"Deal:\n"
            f"Address: {lead.get('address')}\n"
            f"Area: {lead.get('postcode') or lead.get('outcode')}\n"
            f"Asking price: £{lead.get('asking_price'):,.0f}\n"
            f"Estimated market value: £{(lead.get('estimated_market_value') or 0):,.0f}\n"
            f"BMV: {lead.get('bmv_percent')}%\n"
            f"Strategy: {lead.get('strategy')}\n"
            f"ROI: {lead.get('roi_percent')}%\n"
            f"Monthly cashflow estimate: £{(lead.get('monthly_cashflow') or 0):,.0f}\n"
            f"Analyst notes: {lead.get('notes')}\n\n"
            "Write a short, professional outreach email (under 150 words) from a property "
            "sourcer to this investor presenting the deal and asking them to request the "
            "full pack. Sign off with the placeholder {YOUR_NAME}. Return a first line "
            "'SUBJECT: ...' followed by a blank line and then the email body."
        )
        raw = llm_client.complete(
            system_prompt="You are an experienced, professional UK property deal sourcer.",
            user_prompt=prompt,
            max_tokens=300,
        )
        if raw.upper().startswith("SUBJECT:"):
            subject_line, _, body = raw.partition("\n")
            subject = subject_line.split(":", 1)[1].strip()
            return subject, body.strip()
        return _template(lead, buyer)[0], raw
    except llm_client.LLMUnavailable:
        return _template(lead, buyer)
