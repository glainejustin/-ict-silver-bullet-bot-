"""Generates a professional one-page PDF "deal pack" for a lead - the kind of
document a real sourcing business sends to an investor once they've asked
for full details after an outreach email. Pure-Python (fpdf2), no system
dependencies, so it works anywhere this project runs.
"""
from pathlib import Path

from fpdf import FPDF

import config

# The built-in core PDF fonts (Helvetica) only support latin-1, so we
# transliterate common "smart" punctuation before writing any text (this
# avoids pulling in a full Unicode font just to render a dash or curly
# quote that might show up in free-text notes or addresses).
_REPLACEMENTS = {
    "\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"', "\u2026": "...",
}


def _s(text) -> str:
    """Sanitize any dynamic text so it's always safe for the core PDF fonts."""
    if text is None:
        return ""
    text = str(text)
    for bad, good in _REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


class DealPackPDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 10, "Property Deal Pack", ln=True)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 6, "Prepared by your sourcing business - figures are estimates, buyer to verify independently.", ln=True)
        self.set_text_color(0, 0, 0)
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def _row(pdf: FPDF, label: str, value: str):
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(60, 8, _s(label))
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, _s(value), ln=True)


def build_deal_pack(lead: dict, comps: list, output_path: str = None) -> str:
    """Renders a PDF deal pack for one lead and returns the file path."""
    pdf = DealPackPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, _s(lead.get("address") or lead.get("postcode") or "Address on request"), ln=True)
    pdf.ln(2)

    _row(pdf, "Postcode:", lead.get("postcode") or "-")
    _row(pdf, "Property type:", (lead.get("property_type") or "-").title())
    _row(pdf, "Bedrooms:", str(lead.get("bedrooms") or "-"))
    _row(pdf, "Asking price:", f"£{lead['asking_price']:,.0f}" if lead.get("asking_price") else "-")
    _row(pdf, "Est. market value:", f"£{lead['estimated_market_value']:,.0f}" if lead.get("estimated_market_value") else "-")
    _row(pdf, "Below market value:", f"{lead.get('bmv_percent')}%" if lead.get("bmv_percent") is not None else "-")
    _row(pdf, "Refurb estimate:", f"£{lead['refurb_estimate']:,.0f}" if lead.get("refurb_estimate") else "-")
    _row(pdf, "Suggested strategy:", lead.get("strategy") or "-")
    _row(pdf, "Projected ROI:", f"{lead.get('roi_percent')}%" if lead.get("roi_percent") is not None else "-")
    _row(pdf, "Est. monthly cashflow:", f"£{lead['monthly_cashflow']:,.0f}" if lead.get("monthly_cashflow") else "-")

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Analyst summary", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, _s(lead.get("notes") or "No analysis notes available."))

    if comps:
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Comparable sold prices (HM Land Registry)", ln=True)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(90, 7, "Address")
        pdf.cell(35, 7, "Price")
        pdf.cell(35, 7, "Date")
        pdf.cell(0, 7, "Type", ln=True)
        pdf.set_font("Helvetica", "", 9)
        for c in comps[:12]:
            price = f"£{c['sale_price']:,.0f}" if c.get("sale_price") else "-"
            pdf.cell(90, 6, _s((c.get("address") or "")[:48]))
            pdf.cell(35, 6, _s(price))
            pdf.cell(35, 6, _s((c.get("sale_date") or "")[:10]))
            pdf.cell(0, 6, _s(c.get("property_type") or ""), ln=True)

    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(130, 130, 130)
    pdf.multi_cell(
        0, 5,
        "This document is for information purposes only and does not constitute financial, "
        "legal or investment advice. Figures are estimates based on asking price and nearby "
        "Land Registry sold prices and should be independently verified before any purchase "
        "decision. Subject to our standard sourcing fee agreement.",
    )

    output_path = output_path or str(config.DATA_DIR / f"deal_pack_lead_{lead.get('id', 'x')}.pdf")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(output_path)
    return output_path
