"""Generic connector for council / open-data CSV URLs — e.g. empty-homes
registers, long-term-vacant-property lists, or brownfield registers that
individual councils publish themselves (search "<council name> empty homes
register open data" or check the council's page on data.gov.uk). No two
councils use identical column names, so this connector maps flexibly rather
than expecting one fixed schema.

Add URLs to OPEN_DATA_CSV_URLS in .env (comma-separated). Each CSV is
downloaded fresh on every pipeline run (no caching — these lists are small
and change infrequently, and freshness matters more than speed here).
"""
import csv
import io
import logging

import requests

import config
from connectors.base import BaseConnector

logger = logging.getLogger(__name__)

# Flexible column aliases — first match wins, case-insensitive.
COLUMN_ALIASES = {
    "address": ["address", "property address", "site address", "location"],
    "postcode": ["postcode", "post code"],
    "property_type": ["property type", "type", "dwelling type"],
    "bedrooms": ["bedrooms", "beds", "no of bedrooms"],
    "motivation_signal": [
        "status", "empty since", "date identified", "reason", "notes",
        "vacancy reason", "condition",
    ],
}


def _find_column(fieldnames, aliases):
    lower_map = {f.strip().lower(): f for f in fieldnames}
    for alias in aliases:
        if alias in lower_map:
            return lower_map[alias]
    return None


class OpenDataCsvConnector(BaseConnector):
    name = "open_data_csv"

    def __init__(self, urls: list = None):
        self.urls = urls if urls is not None else config.OPEN_DATA_CSV_URLS

    def fetch_leads(self) -> list:
        if not self.urls:
            logger.info("No OPEN_DATA_CSV_URLS configured — skipping open-data CSV connector.")
            return []

        leads = []
        for url in self.urls:
            try:
                resp = requests.get(url, timeout=60)
                resp.raise_for_status()
            except Exception as exc:  # noqa: BLE001 — a flaky source must never crash the pipeline
                logger.warning("Failed to download open-data CSV %s: %s", url, exc)
                continue

            try:
                reader = csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig", errors="replace")))
                fieldnames = reader.fieldnames or []
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to parse open-data CSV %s: %s", url, exc)
                continue

            col = {key: _find_column(fieldnames, aliases) for key, aliases in COLUMN_ALIASES.items()}

            for i, row in enumerate(reader):
                postcode = self.normalise_postcode(row.get(col["postcode"], "")) if col["postcode"] else ""
                address = row.get(col["address"], "") if col["address"] else ""
                leads.append(
                    {
                        "source": self.name,
                        "source_ref": f"{url}:{i}",
                        "address": address or None,
                        "postcode": postcode,
                        "outcode": self.outcode_of(postcode),
                        "property_type": (row.get(col["property_type"], "") or "other").lower() if col["property_type"] else "other",
                        "bedrooms": _safe_int(row.get(col["bedrooms"])) if col["bedrooms"] else None,
                        "asking_price": None,
                        "status": "lead_to_research",
                        "motivation_signal": (
                            (row.get(col["motivation_signal"], "") if col["motivation_signal"] else "")
                            or "Council / open-data register entry — verify current status manually."
                        ),
                        "raw_data": dict(row),
                    }
                )
        return leads


def _safe_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
