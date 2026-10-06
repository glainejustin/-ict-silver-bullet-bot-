"""HM Land Registry "Overseas/UK Companies that own property in England and
Wales" (OCOD/CCOD) connector.

This dataset is free but requires a one-off, free account at
https://use-land-property-data.service.gov.uk/ to download the CSV (it's not
a plain open URL like Price Paid Data, so this connector reads a file you've
already downloaded, rather than fetching it live).

Why it's worth the five minutes of setup: it's the single most powerful way
to turn a vague "this company might be distressed" signal (from the
Companies House connector) into an actual street address worth
investigating — CCOD/OCOD lists the exact registered property address for
every UK-registered company that owns freehold/leasehold property.

Usage:
    connector = CorporateOwnershipConnector(
        ccod_csv_path="data/CCOD_FULL_2024_10.csv",
        target_company_numbers={"01234567", "07654321"},  # e.g. from the
                                                            # Companies House
                                                            # connector's leads
    )
"""
import csv
import logging
from pathlib import Path

from connectors.base import BaseConnector

logger = logging.getLogger(__name__)

# CCOD/OCOD column names as published by HM Land Registry (subject to the
# proprietor being listed as Proprietor 1..4 — most titles only have one).
PROPRIETOR_SLOTS = 4


class CorporateOwnershipConnector(BaseConnector):
    name = "corporate_ownership"

    def __init__(self, ccod_csv_path: str, target_company_numbers: set = None):
        self.ccod_csv_path = Path(ccod_csv_path)
        # If set, only property rows for these company numbers are returned —
        # essential, since the full national file has millions of rows.
        # Leave None only for small, pre-filtered extracts.
        self.target_company_numbers = (
            {str(n).strip() for n in target_company_numbers} if target_company_numbers else None
        )

    def fetch_leads(self) -> list:
        if not self.ccod_csv_path.exists():
            logger.info(
                "No CCOD/OCOD file at %s — skipping corporate ownership connector. "
                "Download one free from use-land-property-data.service.gov.uk.",
                self.ccod_csv_path,
            )
            return []

        leads = []
        with open(self.ccod_csv_path, newline="", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row = {k.strip(): (v or "").strip() for k, v in row.items()}
                for slot in range(1, PROPRIETOR_SLOTS + 1):
                    company_no = row.get(f"Company Registration No. ({slot})", "")
                    if not company_no:
                        continue
                    if self.target_company_numbers and company_no not in self.target_company_numbers:
                        continue

                    postcode = self.normalise_postcode(row.get("Postcode", ""))
                    proprietor = row.get(f"Proprietor Name ({slot})", "Unknown company")
                    leads.append(
                        {
                            "source": self.name,
                            "source_ref": f"{row.get('Title Number', '')}:{slot}",
                            "address": row.get("Property Address", ""),
                            "postcode": postcode,
                            "outcode": self.outcode_of(postcode),
                            "property_type": None,
                            "bedrooms": None,
                            "asking_price": None,
                            "status": "lead_to_research",
                            "motivation_signal": (
                                f"Property registered to '{proprietor}' (company no. {company_no}), "
                                "a company flagged as potentially distressed — verify ownership "
                                "and intent before contacting."
                            ),
                            "raw_data": row,
                        }
                    )
                    break  # one lead per title row is enough even if matched on multiple slots
        return leads
