"""The Gazette (thegazette.co.uk) — the UK's official public record — connector.

The Gazette publishes every UK personal bankruptcy, company winding-up and
liquidation notice as a matter of law, and makes its search results
available as free structured data with no signup and no API key (append
`.json` to any search URL on thegazette.co.uk). Someone named in a
bankruptcy or winding-up notice, or a company being wound up, is one of the
strongest and most legitimate "motivated seller" signals available publicly
— they frequently need to sell property fast.

This connector surfaces notices as research leads (status = lead_to_research)
— like the Companies House connector, it gives you the *who*, and you then
do a quick manual check (Land Registry title search, Companies House filing
history) to find out if/what property is involved before making contact.

Note: this hits a live public endpoint and has not been tested from this
sandbox (no outbound internet here) — the search/result field names are
based on documented Gazette data-API conventions. If thegazette.co.uk ever
tweaks its JSON shape, the regex-based text extraction below is deliberately
tolerant, but double check your first real run's output.
"""
import logging
import re

import requests

from connectors.base import BaseConnector

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.thegazette.co.uk/all-notices/notice/data.json"

POSTCODE_RE = re.compile(r"[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}")

DEFAULT_SEARCH_TERMS = [
    "winding up order",
    "bankruptcy order",
    "property",
]


class GazetteInsolvencyConnector(BaseConnector):
    name = "gazette_insolvency"

    def __init__(self, search_terms: list = None, max_pages: int = 2):
        self.search_terms = search_terms or DEFAULT_SEARCH_TERMS
        self.max_pages = max_pages

    @staticmethod
    def _entries_from_response(data) -> list:
        """The Gazette's JSON is Atom-feed-shaped; be tolerant of the exact
        key names in case of minor API differences."""
        if isinstance(data, dict):
            for key in ("entry", "entries", "items", "results"):
                if key in data:
                    value = data[key]
                    return value if isinstance(value, list) else [value]
        if isinstance(data, list):
            return data
        return []

    @staticmethod
    def _text(entry: dict, *keys) -> str:
        for key in keys:
            value = entry.get(key)
            if isinstance(value, dict):
                value = value.get("$t") or value.get("#text") or value.get("value")
            if value:
                return str(value)
        return ""

    def fetch_leads(self) -> list:
        leads = []
        for term in self.search_terms:
            for page in range(1, self.max_pages + 1):
                try:
                    resp = requests.get(
                        SEARCH_URL,
                        params={"text": term, "start-page": page},
                        timeout=30,
                        headers={"Accept": "application/json"},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:  # noqa: BLE001 — a flaky public API must never crash the pipeline
                    logger.warning("Gazette search failed for %r (page %s): %s", term, page, exc)
                    break

                entries = self._entries_from_response(data)
                if not entries:
                    break

                for entry in entries:
                    title = self._text(entry, "title")
                    summary = self._text(entry, "summary", "content")
                    notice_id = self._text(entry, "id") or title
                    combined = f"{title} {summary}"
                    match = POSTCODE_RE.search(combined)
                    postcode = self.normalise_postcode(match.group(0) if match else "")

                    leads.append(
                        {
                            "source": self.name,
                            "source_ref": notice_id,
                            "address": title[:255] if title else None,
                            "postcode": postcode,
                            "outcode": self.outcode_of(postcode),
                            "property_type": None,
                            "bedrooms": None,
                            "asking_price": None,
                            "status": "lead_to_research",
                            "motivation_signal": (
                                f"Official Gazette notice ('{term}') — verify what property, "
                                f"if any, is tied to this person/company before contacting."
                            ),
                            "raw_data": {"title": title, "summary": summary, "search_term": term},
                        }
                    )
        return leads
