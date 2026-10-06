"""Companies House connector — free official API (register a free key at
https://developer.company-information.service.gov.uk/).

Strategy: property-holding companies that are dissolving, being struck off,
or have filed for liquidation are a classic, 100%-legitimate "motivated
seller" signal real sourcers use every day — the directors often need to
offload property assets quickly. This connector surfaces those companies as
research leads (you then look up their registered property via Companies
House filing history / Land Registry before making contact).

This does NOT give you an exact address+asking price — it gives you a
starting point to investigate, which is exactly what this stage of sourcing
is supposed to do.
"""
import logging

import requests

import config
from connectors.base import BaseConnector

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.company-information.service.gov.uk/search/companies"

# SIC codes for property-holding / real-estate companies.
PROPERTY_SIC_CODES = {"68100", "68209", "68320", "68201", "68202"}

TARGET_STATUSES = {"dissolved", "liquidation", "proposal to strike off", "administration"}


class CompaniesHouseConnector(BaseConnector):
    name = "companies_house"

    def __init__(self, api_key: str = None, query_terms: list = None, max_pages: int = 2):
        self.api_key = api_key or config.COMPANIES_HOUSE_API_KEY
        # e.g. ["property", "homes", "estates", "lettings"] — tune to your target area/niche
        self.query_terms = query_terms or ["property", "homes", "estates"]
        self.max_pages = max_pages

    def fetch_leads(self) -> list:
        if not self.api_key:
            logger.info("COMPANIES_HOUSE_API_KEY not set — skipping Companies House connector.")
            return []

        leads = []
        for term in self.query_terms:
            for page in range(self.max_pages):
                try:
                    resp = requests.get(
                        SEARCH_URL,
                        params={"q": term, "items_per_page": 50, "start_index": page * 50},
                        auth=(self.api_key, ""),
                        timeout=30,
                    )
                    resp.raise_for_status()
                except requests.RequestException as exc:
                    logger.warning("Companies House search failed for %r: %s", term, exc)
                    continue

                items = resp.json().get("items", [])
                if not items:
                    break

                for item in items:
                    status = (item.get("company_status") or "").lower()
                    if not any(s in status for s in TARGET_STATUSES):
                        continue

                    address = item.get("address", {})
                    postcode = address.get("postal_code", "")
                    leads.append(
                        {
                            "source": self.name,
                            "source_ref": item.get("company_number"),
                            "address": address.get("address_line_1")
                            or item.get("title"),
                            "postcode": postcode,
                            "outcode": self.outcode_of(postcode),
                            "property_type": None,
                            "bedrooms": None,
                            "asking_price": None,
                            "status": "lead_to_research",
                            "motivation_signal": (
                                f"Company '{item.get('title')}' status is "
                                f"'{item.get('company_status')}' — potential distressed "
                                f"property asset sale. Verify via filing history."
                            ),
                            "raw_data": item,
                        }
                    )
        return leads
