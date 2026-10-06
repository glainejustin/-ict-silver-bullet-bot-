"""Manual / open-data CSV import connector.

Use this for the many free, legitimate lead sources that only come as a CSV
or spreadsheet rather than an API — council empty-homes registers, planning
application exports, probate research lists you've compiled by hand, a
Facebook/WhatsApp group lead you want to log, auction results you downloaded,
etc. Drop a CSV into `seed/` or anywhere else and point this connector at it.

Expected columns (case-insensitive, flexible — missing ones are fine):
  address, postcode, property_type, bedrooms, asking_price, motivation_signal, source_ref
"""
import csv
import logging
from pathlib import Path

from connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class CsvImportConnector(BaseConnector):
    name = "csv_import"

    def __init__(self, csv_paths: list):
        self.csv_paths = [Path(p) for p in csv_paths]

    def fetch_leads(self) -> list:
        leads = []
        for path in self.csv_paths:
            if not path.exists():
                logger.warning("CSV import path not found: %s", path)
                continue
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    row = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
                    postcode = self.normalise_postcode(row.get("postcode", ""))
                    leads.append(
                        {
                            "source": self.name,
                            "source_ref": row.get("source_ref") or f"{path.name}:{i}",
                            "address": row.get("address"),
                            "postcode": postcode,
                            "outcode": self.outcode_of(postcode),
                            "property_type": (row.get("property_type") or "other").lower(),
                            "bedrooms": int(row["bedrooms"]) if row.get("bedrooms", "").isdigit() else None,
                            "asking_price": float(row["asking_price"])
                            if row.get("asking_price", "").replace(".", "", 1).isdigit()
                            else None,
                            "motivation_signal": row.get("motivation_signal")
                            or "Manually sourced / open-data lead",
                            "raw_data": row,
                        }
                    )
        return leads
