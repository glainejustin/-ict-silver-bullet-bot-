"""CSV import for rental listings — a landlord's own list of properties they
want let, a council HMO/licence register repurposed as landlord leads, or
anything else you've compiled. Note this returns *rental listing* dicts
(different shape to the sales `leads` table), so it's used by
rental_pipeline.py rather than pipeline.py.

Expected columns (case-insensitive, flexible — missing ones are fine):
  address, postcode, property_type, bedrooms, monthly_rent, available_from,
  furnishing, motivation_signal, source_ref
"""
import csv
import logging
from pathlib import Path

from connectors.base import BaseConnector

logger = logging.getLogger(__name__)


class RentalCsvImportConnector:
    name = "rental_csv_import"

    def __init__(self, csv_paths: list):
        self.csv_paths = [Path(p) for p in csv_paths]

    def fetch_leads(self) -> list:
        listings = []
        for path in self.csv_paths:
            if not path.exists():
                logger.warning("Rental CSV import path not found: %s", path)
                continue
            with open(path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    row = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
                    postcode = BaseConnector.normalise_postcode(row.get("postcode", ""))
                    listings.append(
                        {
                            "source": self.name,
                            "source_ref": row.get("source_ref") or f"{path.name}:{i}",
                            "address": row.get("address"),
                            "postcode": postcode,
                            "outcode": BaseConnector.outcode_of(postcode),
                            "property_type": (row.get("property_type") or "other").lower(),
                            "bedrooms": int(row["bedrooms"]) if row.get("bedrooms", "").isdigit() else None,
                            "monthly_rent": float(row["monthly_rent"])
                            if row.get("monthly_rent", "").replace(".", "", 1).isdigit()
                            else None,
                            "available_from": row.get("available_from"),
                            "furnishing": row.get("furnishing"),
                            "motivation_signal": row.get("motivation_signal") or "Manually sourced rental listing",
                            "raw_data": row,
                        }
                    )
        return listings
