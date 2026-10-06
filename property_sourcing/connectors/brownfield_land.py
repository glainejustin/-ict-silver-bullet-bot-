"""Brownfield Land Register connector — free, national, no API key.

Every UK local authority is legally required to publish a register of
brownfield land suitable for housing, and the government aggregates them all
into one free open dataset on the Planning Data Platform
(https://www.planning.data.gov.uk/dataset/brownfield-land). These are
publicly identified, council-endorsed development opportunities — exactly
the kind of site a developer-focused sourcer packages deals around.

Note: like the other live-API connectors, this hits a public endpoint not
reachable from this offline sandbox, so double-check the first real response
shape matches what's parsed below (the official field names are documented
at https://www.planning.data.gov.uk/dataset/brownfield-land but can evolve).
"""
import logging

import requests

from connectors.base import BaseConnector

logger = logging.getLogger(__name__)

ENTITY_URL = "https://www.planning.data.gov.uk/entity.json"


class BrownfieldLandConnector(BaseConnector):
    name = "brownfield_land"

    def __init__(self, local_authority: str = None, limit: int = 100, max_pages: int = 2):
        # e.g. local_authority="MAN" (council org code) to scope to one area;
        # leave None to pull the most recently added entries nationally.
        self.local_authority = local_authority
        self.limit = limit
        self.max_pages = max_pages

    def fetch_leads(self) -> list:
        leads = []
        offset = 0
        for _ in range(self.max_pages):
            params = {"dataset": "brownfield-land", "limit": self.limit, "offset": offset}
            if self.local_authority:
                params["organisation_entity"] = self.local_authority

            try:
                resp = requests.get(ENTITY_URL, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:  # noqa: BLE001 — a flaky public API must never crash the pipeline
                logger.warning("Brownfield Land Register fetch failed: %s", exc)
                break

            entities = data.get("entities", []) if isinstance(data, dict) else []
            if not entities:
                break

            for entity in entities:
                name = entity.get("name") or entity.get("reference") or "Unnamed brownfield site"
                dwellings = entity.get("minimum-net-dwellings") or entity.get("maximum-net-dwellings")
                leads.append(
                    {
                        "source": self.name,
                        "source_ref": str(entity.get("entity") or entity.get("reference")),
                        "address": name,
                        "postcode": "",
                        "outcode": "",
                        "property_type": "land",
                        "bedrooms": None,
                        "asking_price": None,
                        "status": "lead_to_research",
                        "motivation_signal": (
                            "Council-registered brownfield site identified as suitable for "
                            f"housing (est. {dwellings or 'unknown'} dwellings) — a development "
                            "sourcing/packaging opportunity, not a direct resale."
                        ),
                        "raw_data": entity,
                    }
                )

            offset += self.limit
            if len(entities) < self.limit:
                break

        return leads
