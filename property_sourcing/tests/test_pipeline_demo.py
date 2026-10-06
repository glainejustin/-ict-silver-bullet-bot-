"""End-to-end test of the full pipeline in fully offline demo mode: ingest ->
value -> analyze -> match buyers -> draft outreach. No network, no API keys.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402


def test_full_demo_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "LAND_REGISTRY_CACHE_DIR", tmp_path / "lr_cache")
    monkeypatch.setattr(config, "DRY_RUN_OUTREACH", True)
    monkeypatch.setattr(config, "COMPANIES_HOUSE_API_KEY", "")
    monkeypatch.setattr(config, "AUCTION_FEED_URLS", [])

    import db
    import pipeline
    import run_pipeline as cli

    db.init_db()
    cli.setup_demo_data()
    cli._seed_buyers_if_empty(config.SEED_DIR / "buyers_seed.csv")

    stats = pipeline.run_full_pipeline(extra_csv_paths=[str(config.SEED_DIR / "demo_leads.csv")])

    assert stats["total_leads"] >= 4
    assert stats["buyers"] >= 3

    leads = db.list_leads()
    by_ref = {}
    for lead in leads:
        if lead["source"] == "csv_import":
            raw_ref = lead["source_ref"] or ""
            by_ref[raw_ref] = lead

    demo_001 = by_ref.get("DEMO-001")
    assert demo_001 is not None
    assert demo_001["status"] in {"analyzed", "outreach_drafted"}
    assert demo_001["estimated_market_value"], "comp finder should have valued this lead from seed Land Registry data"
    assert demo_001["bmv_percent"] is not None and demo_001["bmv_percent"] > 0, "DEMO-001 is priced below the seeded comps"

    # DEMO-004 is priced above local comps, so it should NOT look like a hot deal.
    demo_004 = by_ref.get("DEMO-004")
    assert demo_004 is not None
    assert (demo_004["bmv_percent"] or 0) < config.MIN_BMV_PERCENT

    # A hot deal should have been matched to at least one buyer and an email drafted.
    outreach_rows = db.list_outreach(demo_001["id"])
    assert len(outreach_rows) >= 1
    assert outreach_rows[0]["status"] == "draft"  # DRY_RUN_OUTREACH=True
