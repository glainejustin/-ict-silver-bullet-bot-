#!/usr/bin/env python3
"""Run the whole sourcing pipeline once, right now, from the command line.

    python run_pipeline.py                 # use live connectors (needs internet + API keys)
    python run_pipeline.py --demo          # fully offline demo using seed data, no keys needed
    python run_pipeline.py --csv path.csv  # also import leads from a CSV file
    python run_pipeline.py --rentals       # also run the lettings/rental matching pipeline
"""
import argparse
import csv
import datetime
import logging
import shutil

import config
import db
import pipeline
import rental_pipeline

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
    parser.add_argument("--demo", action="store_true", help="Run fully offline with bundled seed data (sales + rentals)")
    parser.add_argument("--csv", action="append", default=[], help="Extra CSV file(s) of sale leads to import")
    parser.add_argument("--rentals", action="store_true", help="Also run the lettings/rental matching pipeline")
    parser.add_argument("--rental-csv", action="append", default=[], help="Extra CSV file(s) of rental listings to import")
    parser.add_argument("--tenant-csv", action="append", default=[], help="Extra CSV file(s) of tenant leads to import")
    args = parser.parse_args()

    db.init_db()

    if args.demo:
        setup_demo_data()
        demo_leads_csv = config.SEED_DIR / "demo_leads.csv"
        _seed_buyers_if_empty(config.SEED_DIR / "buyers_seed.csv")
        stats = pipeline.run_full_pipeline(extra_csv_paths=[str(demo_leads_csv)])

        _seed_landlords_if_empty(config.SEED_DIR / "landlords_seed.csv")
        rental_pipeline.ingest_rental_data(
            extra_listing_csv_paths=[str(config.SEED_DIR / "rental_listings_demo.csv")],
            extra_tenant_csv_paths=[str(config.SEED_DIR / "tenants_demo.csv")],
        )
        _link_demo_listings_to_first_landlord()
        rental_pipeline.match_and_draft_rental_outreach()
        rental_stats = db.rental_stats()
    else:
        stats = pipeline.run_full_pipeline(extra_csv_paths=args.csv or None)
        rental_stats = None
        if args.rentals or args.rental_csv or args.tenant_csv:
            rental_stats = rental_pipeline.run_rental_pipeline(
                extra_listing_csv_paths=args.rental_csv or None,
                extra_tenant_csv_paths=args.tenant_csv or None,
            )

    print("\n=== Sales pipeline run complete ===")
    for k, v in stats.items():
        print(f"{k}: {v}")

    if rental_stats:
        print("\n=== Lettings pipeline run complete ===")
        for k, v in rental_stats.items():
            print(f"{k}: {v}")

    print("\nOpen the dashboard with:  python app.py")


def _seed_buyers_if_empty(buyers_csv):
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


def _seed_landlords_if_empty(landlords_csv):
    if db.list_landlords():
        return
    if not landlords_csv.exists():
        return
    with open(landlords_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            db.add_landlord(
                {"name": row["name"], "email": row.get("email"), "phone": row.get("phone"), "notes": row.get("notes")}
            )


def _link_demo_listings_to_first_landlord():
    """Demo convenience only: assigns the seeded landlords to the demo
    listings so the dashboard shows a fully connected example end to end."""
    landlords = db.list_landlords()
    if not landlords:
        return
    listings = db.list_rental_listings()
    for i, listing in enumerate(listings):
        if not listing.get("landlord_id"):
            landlord = landlords[i % len(landlords)]
            db.update_rental_listing(listing["id"], {"landlord_id": landlord["id"]})


if __name__ == "__main__":
    main()
