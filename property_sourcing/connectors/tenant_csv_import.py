"""CSV import for tenant leads — e.g. exported from a public "register your
interest" form, or compiled manually. See dashboard's "/tenants/add" page
for a one-at-a-time alternative (also usable as a public-facing form).

Expected columns (case-insensitive, flexible):
  name, email, phone, areas (semicolon-separated), budget_max,
  bedrooms_needed, move_in_date, notes
"""
import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def import_tenants_from_csv(csv_paths: list) -> list:
    tenants = []
    for path in [Path(p) for p in csv_paths]:
        if not path.exists():
            logger.warning("Tenant CSV import path not found: %s", path)
            continue
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
                if not row.get("name"):
                    continue
                tenants.append(
                    {
                        "name": row["name"],
                        "email": row.get("email"),
                        "phone": row.get("phone"),
                        "areas": [a.strip() for a in row.get("areas", "").split(";") if a.strip()],
                        "budget_max": float(row["budget_max"]) if row.get("budget_max", "").replace(".", "", 1).isdigit() else None,
                        "bedrooms_needed": int(row["bedrooms_needed"]) if row.get("bedrooms_needed", "").isdigit() else None,
                        "move_in_date": row.get("move_in_date"),
                        "notes": row.get("notes"),
                    }
                )
    return tenants
