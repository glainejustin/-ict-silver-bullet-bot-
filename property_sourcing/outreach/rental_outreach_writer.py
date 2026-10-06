"""Drafts the landlord introduction email for a matched tenant. Deliberately
shares only an anonymised tenant profile (no email/phone) until the landlord
confirms interest — protects tenant privacy and is standard lettings
practice. Falls back to a template when no LLM is configured.
"""
from agents import commission, llm_client


def _tenant_profile(tenant: dict) -> str:
    bits = []
    if tenant.get("bedrooms_needed"):
        bits.append(f"needs {tenant['bedrooms_needed']}+ bedroom(s)")
    if tenant.get("budget_max"):
        bits.append(f"budget up to £{tenant['budget_max']:,.0f}/month")
    if tenant.get("move_in_date"):
        bits.append(f"looking to move in from {tenant['move_in_date']}")
    if tenant.get("notes"):
        bits.append(tenant["notes"])
    return "; ".join(bits) or "General enquiry — details available on request."


def _template(listing: dict, tenant: dict, commission_amount: float) -> tuple:
    subject = f"Prospective tenant for {listing.get('address') or listing.get('postcode')}"
    terms = commission.describe_commission_terms()
    body = f"""Hi {{LANDLORD_NAME}},

I have a prospective tenant who matches the property you asked me to help let:

Property: {listing.get('address') or listing.get('postcode')}
Monthly rent: £{(listing.get('monthly_rent') or 0):,.0f}

Tenant profile: {_tenant_profile(tenant)}

If you'd like me to put you in touch, just reply and I'll share their full
details and arrange a viewing. As agreed, my introduction fee is {terms},
payable once a tenancy is signed — no cost to you unless this results in a
let, and nothing is ever charged to the tenant.

Best regards,
{{YOUR_NAME}}
"""
    return subject, body


def draft_landlord_intro(listing: dict, tenant: dict, commission_amount: float) -> tuple:
    """Returns (subject, body)."""
    try:
        terms = commission.describe_commission_terms()
        prompt = (
            f"Property: {listing.get('address')}\n"
            f"Monthly rent: £{(listing.get('monthly_rent') or 0):,.0f}\n"
            f"Tenant profile (anonymised): {_tenant_profile(tenant)}\n"
            f"Your commission terms: {terms}, payable by the landlord only on signing, "
            f"nothing charged to the tenant.\n\n"
            "Write a short, professional email (under 130 words) from a letting "
            "introducer to the landlord, presenting this prospective tenant and asking "
            "if they'd like to proceed to a viewing. Mention the commission terms clearly. "
            "Sign off with the placeholder {YOUR_NAME} and address the landlord as {LANDLORD_NAME}. "
            "Return a first line 'SUBJECT: ...' then a blank line then the body."
        )
        raw = llm_client.complete(
            system_prompt="You are an experienced, professional UK letting introducer.",
            user_prompt=prompt,
            max_tokens=250,
        )
        if raw.upper().startswith("SUBJECT:"):
            subject_line, _, body = raw.partition("\n")
            return subject_line.split(":", 1)[1].strip(), body.strip()
        return _template(listing, tenant, commission_amount)[0], raw
    except llm_client.LLMUnavailable:
        return _template(listing, tenant, commission_amount)
