"""The core automation pipeline — this is "the AI agent doing the work".

Run end to end with `python run_pipeline.py`, or let `scheduler.py` trigger
it automatically every day. Each step is independent and safe to re-run.
"""
import logging

import config
import db
from agents import comp_finder, deal_analyzer, investor_matcher, outreach_writer
from connectors.auction_feeds import AuctionFeedConnector
from connectors.brownfield_land import BrownfieldLandConnector
from connectors.companies_house import CompaniesHouseConnector
from connectors.corporate_ownership import CorporateOwnershipConnector
from connectors.gazette_insolvency import GazetteInsolvencyConnector
from connectors.open_data_csv import OpenDataCsvConnector
from outreach import email_sender, templates

logger = logging.getLogger(__name__)


def get_connectors(extra_csv_paths=None):
    """Every connector here is free and ToS-safe. Each one no-ops quietly
    (logs and returns []) if you haven't configured it yet, so it's always
    safe to leave all of them enabled."""
    connectors = [
        CompaniesHouseConnector(),
        AuctionFeedConnector(),
        GazetteInsolvencyConnector(search_terms=config.GAZETTE_SEARCH_TERMS),
        BrownfieldLandConnector(local_authority=config.BROWNFIELD_LOCAL_AUTHORITY),
        OpenDataCsvConnector(),
    ]
    if config.CCOD_CSV_PATH:
        distressed_company_numbers = {
            lead["source_ref"]
            for lead in db.list_leads()
            if lead["source"] == "companies_house" and lead.get("source_ref")
        }
        connectors.append(
            CorporateOwnershipConnector(
                ccod_csv_path=config.CCOD_CSV_PATH,
                target_company_numbers=distressed_company_numbers or None,
            )
        )
    if extra_csv_paths:
        from connectors.csv_import import CsvImportConnector

        connectors.append(CsvImportConnector(extra_csv_paths))
    return connectors


def ingest_leads(connectors) -> int:
    """Step 1: pull fresh leads from every configured connector."""
    new_count = 0
    for connector in connectors:
        try:
            leads = connector.fetch_leads()
        except Exception as exc:  # noqa: BLE001 — one bad connector must not stop the others
            logger.error("Connector %s failed: %s", connector.name, exc)
            continue

        for lead in leads:
            lead_id, is_new = db.upsert_lead(lead)
            if is_new:
                new_count += 1
                db.log_activity(lead_id, "ingested", f"from {connector.name}")
    logger.info("Ingested %s new lead(s) from %s connector(s).", new_count, len(connectors))
    return new_count


def analyze_new_leads() -> int:
    """Step 2: value + score every lead that hasn't been analyzed yet."""
    analyzed = 0
    for lead in db.list_leads(status="new"):
        valuation = comp_finder.find_market_value(lead)
        analysis = deal_analyzer.analyze(lead, valuation["estimated_market_value"])

        db.update_lead(lead["id"], {**analysis, "status": "analyzed"})
        if valuation["comps"]:
            db.add_comps(lead["id"], valuation["comps"])
        db.log_activity(
            lead["id"], "analyzed",
            f"BMV={analysis.get('bmv_percent')}% ROI={analysis.get('roi_percent')}% strategy={analysis.get('strategy')}",
        )
        analyzed += 1
    logger.info("Analyzed %s lead(s).", analyzed)
    return analyzed


def match_and_draft_outreach() -> int:
    """Step 3: for every hot deal, match buyers from the CRM and draft a
    personalised outreach email for each match (sent for real only if
    DRY_RUN_OUTREACH=false)."""
    buyers = db.list_buyers()
    drafted = 0

    hot_leads = [
        lead
        for lead in db.list_leads(status="analyzed")
        if (lead.get("bmv_percent") or 0) >= config.MIN_BMV_PERCENT
    ]

    for lead in hot_leads:
        matches = investor_matcher.find_matching_buyers(lead, buyers)
        if not matches:
            db.log_activity(lead["id"], "no_buyer_match", "No buyer in CRM matches this deal yet.")
            continue

        for buyer in matches:
            already_sent = any(
                o["buyer_id"] == buyer["id"] for o in db.list_outreach(lead["id"])
            )
            if already_sent:
                continue

            subject, body = outreach_writer.draft_email(lead, buyer)
            sent = email_sender.send_email(buyer["email"], subject, body)
            outreach_id = db.add_outreach(
                {
                    "lead_id": lead["id"],
                    "buyer_id": buyer["id"],
                    "recipient": buyer["email"],
                    "subject": subject,
                    "body": body,
                    "status": "sent" if sent else "draft",
                }
            )
            if sent:
                db.mark_outreach_sent(outreach_id)
            drafted += 1

        db.update_lead(lead["id"], {"status": "outreach_drafted"})
        db.log_activity(lead["id"], "outreach_drafted", f"{len(matches)} buyer(s) matched")

    logger.info("Drafted/sent %s outreach email(s).", drafted)
    return drafted


def send_daily_digest():
    """Step 4: email you a one-page summary so you rarely need to open the dashboard."""
    if not config.DIGEST_TO_EMAIL:
        logger.info("DIGEST_TO_EMAIL not set — skipping daily digest.")
        return

    stats = db.stats()
    hot_leads = [
        lead for lead in db.list_leads() if (lead.get("bmv_percent") or 0) >= config.MIN_BMV_PERCENT
    ]
    subject, body = templates.build_digest(stats, hot_leads, stats["outreach_drafted"])

    # The digest always sends to YOU regardless of DRY_RUN_OUTREACH, since it's
    # not outward-facing outreach to a lead/investor — toggle separately if desired.
    was_dry_run = config.DRY_RUN_OUTREACH
    try:
        config.DRY_RUN_OUTREACH = False
        email_sender.send_email(config.DIGEST_TO_EMAIL, subject, body)
    finally:
        config.DRY_RUN_OUTREACH = was_dry_run


def run_full_pipeline(extra_csv_paths=None):
    db.init_db()
    connectors = get_connectors(extra_csv_paths)
    ingest_leads(connectors)
    analyze_new_leads()
    match_and_draft_outreach()
    send_daily_digest()
    return db.stats()
