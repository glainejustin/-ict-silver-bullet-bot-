"""The lettings automation pipeline — mirrors pipeline.py's shape, but for
matching tenants to rental listings and drafting landlord introductions
instead of matching buyers to sale deals.

Run with `python run_pipeline.py --rentals` (or `--demo` runs both sales and
rentals together), or let `scheduler.py` trigger it automatically.
"""
import logging

import config
import db
from agents import commission, rental_matcher
from outreach import email_sender, rental_outreach_writer

logger = logging.getLogger(__name__)


def match_and_draft_rental_outreach() -> int:
    """For every available listing, find matching tenants and draft a
    landlord-introduction email per match (sent for real only if
    DRY_RUN_OUTREACH=false). Commission is always calculated against the
    landlord, never the tenant."""
    tenants = db.list_tenants()
    drafted = 0

    for listing in db.list_rental_listings(status="available"):
        matches = rental_matcher.find_matching_tenants(listing, tenants)
        if not matches:
            db.log_activity(None, "no_tenant_match", f"No tenant matches rental listing {listing['id']} yet.")
            continue

        landlord_email = None
        if listing.get("landlord_id"):
            landlord = next((l for l in db.list_landlords() if l["id"] == listing["landlord_id"]), None)
            landlord_email = landlord.get("email") if landlord else None

        for tenant in matches:
            existing = db.list_rental_matches(listing["id"])
            if any(m["tenant_id"] == tenant["id"] for m in existing):
                continue

            commission_amount = commission.calculate_commission(listing.get("monthly_rent"))
            subject, body = rental_outreach_writer.draft_landlord_intro(listing, tenant, commission_amount)

            recipient = landlord_email or "landlord-email-not-on-file@example.com"
            sent = email_sender.send_email(recipient, subject, body) if landlord_email else False

            db.add_rental_match(
                {
                    "listing_id": listing["id"],
                    "tenant_id": tenant["id"],
                    "status": "sent" if sent else "draft",
                    "subject": subject,
                    "body": body,
                    "commission_amount": commission_amount,
                }
            )
            drafted += 1

        db.update_rental_listing(listing["id"], {"status": "under_offer" if matches else listing["status"]})
        db.log_activity(None, "rental_outreach_drafted", f"listing={listing['id']} matches={len(matches)}")

    logger.info("Drafted/sent %s landlord introduction email(s).", drafted)
    return drafted


def ingest_rental_data(extra_listing_csv_paths=None, extra_tenant_csv_paths=None):
    """Step 1: import any CSV-sourced listings/tenants. Safe to call with
    nothing configured (both default to no-ops)."""
    if extra_listing_csv_paths:
        from connectors.rental_csv_import import RentalCsvImportConnector

        for listing in RentalCsvImportConnector(extra_listing_csv_paths).fetch_leads():
            db.upsert_rental_listing(listing)
    if extra_tenant_csv_paths:
        from connectors.tenant_csv_import import import_tenants_from_csv

        for tenant in import_tenants_from_csv(extra_tenant_csv_paths):
            db.add_tenant(tenant)


def run_rental_pipeline(extra_listing_csv_paths=None, extra_tenant_csv_paths=None):
    db.init_db()
    ingest_rental_data(extra_listing_csv_paths, extra_tenant_csv_paths)
    match_and_draft_rental_outreach()
    return db.rental_stats()

