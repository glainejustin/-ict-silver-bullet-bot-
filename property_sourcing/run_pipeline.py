#!/usr/bin/env python3
"""Run the whole sourcing pipeline once, right now, from the command line.

    python run_pipeline.py                 # use live connectors (needs internet + API keys)
    python run_pipeline.py --demo          # fully offline demo using seed data, no keys needed
    python run_pipeline.py --csv path.csv  # also import leads from a CSV file
"""
import argparse
import datetime
import logging
import shutil

import config
import db
import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def setup_demo_data():
    """Copies bundled sample data into place so the full pipeline can run
    completely offline, with no API keys and no internet access — useful for
    trying the system out or for CI tests."""
    config.LAND_REGISTRY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    sample = config.SEED_DIR / "sample_land_registry_pp_2024.csv"
    current_year = datetime.date.today().year
    if sample.exists():
        for year in (current_year, current_year - 1):
            shutil.copyfile(sample, config.LAND_REGISTRY_CACHE_DIR / f"pp-{year}.csv")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="Run fully offline with bundled seed data")
    parser.add_argument("--csv", action="append", default=[], help="Extra CSV file(s) of leads to import")
    args = parser.parse_args()

    db.init_db()

    if args.demo:
        setup_demo_data()
        demo_leads_csv = config.SEED_DIR / "demo_leads.csv"
        demo_buyers_csv = config.SEED_DIR / "buyers_seed.csv"
        _seed_buyers_if_empty(demo_buyers_csv)
        stats = pipeline.run_full_pipeline(extra_csv_paths=[str(demo_leads_csv)])
    else:
        stats = pipeline.run_full_pipeline(extra_csv_paths=args.csv or None)

    print("\n=== Pipeline run complete ===")
    for k, v in stats.items():
        print(f"{k}: {v}")
    print("\nOpen the dashboard with:  python app.py")


def _seed_buyers_if_empty(buyers_csv):
    import csv

    if db.list_buyers():
        return
    if not buyers_csv.exists():
        return
    with open(buyers_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            db.add_buyer(
                {
                    "name": row["name"],
                    "email": row["email"],
                    "phone": row.get("phone"),
                    "areas": [a.strip() for a in row.get("areas", "").split(";") if a.strip()],
                    "budget_min": float(row["budget_min"]) if row.get("budget_min") else None,
                    "budget_max": float(row["budget_max"]) if row.get("budget_max") else None,
                    "strategies": [s.strip() for s in row.get("strategies", "").split(";") if s.strip()],
                    "min_roi_percent": float(row["min_roi_percent"]) if row.get("min_roi_percent") else None,
                    "notes": row.get("notes"),
                }
            )


if __name__ == "__main__":
    main()
