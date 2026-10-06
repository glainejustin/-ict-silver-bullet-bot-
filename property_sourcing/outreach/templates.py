"""Builds the daily digest email sent to you (not investors) — this is the
whole point of "low involvement": instead of checking a dashboard, you get
one email a day summarising everything the system did and the few things
left that need your decision.
"""


def build_digest(stats: dict, hot_leads: list, outreach_pending: int) -> tuple:
    subject = f"Property sourcing digest — {stats['hot_deals']} hot deal(s), {stats['total_leads']} total leads"

    lines = [
        "Good morning — here's what your sourcing system found overnight:",
        "",
        f"- Total leads tracked: {stats['total_leads']}",
        f"- Hot deals (meets your BMV/ROI thresholds): {stats['hot_deals']}",
        f"- Outreach emails drafted, awaiting your send: {stats['outreach_drafted']}",
        f"- Outreach emails sent: {stats['outreach_sent']}",
        f"- Buyers in your CRM: {stats['buyers']}",
        "",
    ]

    if hot_leads:
        lines.append("Top deals right now:")
        for lead in hot_leads[:10]:
            lines.append(
                f"  #{lead['id']} {lead.get('address') or lead.get('postcode')} — "
                f"asking £{lead.get('asking_price') or 0:,.0f}, "
                f"BMV {lead.get('bmv_percent')}%, "
                f"ROI {lead.get('roi_percent')}%, "
                f"strategy: {lead.get('strategy')}"
            )
    else:
        lines.append("No new hot deals today — the system will keep scanning automatically.")

    if outreach_pending:
        lines.append("")
        lines.append(
            f"{outreach_pending} outreach email(s) are drafted and waiting in the dashboard "
            "for your review before sending (or set DRY_RUN_OUTREACH=false to auto-send)."
        )

    lines.append("")
    lines.append("Open the dashboard to review, approve or tweak anything.")

    return subject, "\n".join(lines)
