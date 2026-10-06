"""Generates a simple commission invoice PDF for a landlord once a tenancy
has been signed — mirrors outreach/deal_pack.py's approach (pure-Python
fpdf2, no system dependencies, latin-1-safe text sanitisation).
"""
from pathlib import Path

from fpdf import FPDF

import config

_REPLACEMENTS = {
    "\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"', "\u2026": "...",
}


def _s(text) -> str:
    if text is None:
        return ""
    text = str(text)
    for bad, good in _REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


def build_commission_invoice(listing: dict, tenant: dict, commission_amount: float, output_path: str = None) -> str:
    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Tenant Introduction Commission Invoice", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, "No fee has been or will be charged to the tenant.", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(60, 8, "Property:")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, _s(listing.get("address") or listing.get("postcode") or "-"), ln=True)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(60, 8, "Monthly rent:")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, f"GBP {listing.get('monthly_rent', 0):,.2f}" if listing.get("monthly_rent") else "-", ln=True)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(60, 8, "Tenant introduced:")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, _s(tenant.get("name") or "-"), ln=True)

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 10, f"Commission due: GBP {commission_amount:,.2f}", ln=True)

    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(130, 130, 130)
    pdf.multi_cell(
        0, 5,
        "Payable in accordance with the tenant introduction agreement between the parties. "
        "This invoice is for the landlord only - no fee has been charged to the tenant, "
        "consistent with the Tenant Fees Act 2019.",
    )

    output_path = output_path or str(config.DATA_DIR / f"commission_invoice_match_{listing.get('id', 'x')}.pdf")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    pdf.output(output_path)
    return output_path
