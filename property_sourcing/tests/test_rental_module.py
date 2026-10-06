"""Tests for the lettings/rental referral module: commission calculation
(landlord-only, by design), tenant-listing matching, and a full offline
end-to-end rental pipeline run.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from agents import commission, rental_matcher  # noqa: E402


def test_commission_one_month_rent(monkeypatch):
    monkeypatch.setattr(config, "COMMISSION_TYPE", "one_month_rent")
    monkeypatch.setattr(config, "COMMISSION_VALUE", 1)
    assert commission.calculate_commission(1000) == 1000.0


def test_commission_percent_of_annual_rent(monkeypatch):
    monkeypatch.setattr(config, "COMMISSION_TYPE", "percent_of_annual_rent")
    monkeypatch.setattr(config, "COMMISSION_VALUE", 10)
    # 1000/month * 12 = 12000 annual, 10% = 1200
    assert commission.calculate_commission(1000) == 1200.0


def test_commission_flat_fee(monkeypatch):
    monkeypatch.setattr(config, "COMMISSION_TYPE", "flat_fee")
    monkeypatch.setattr(config, "COMMISSION_VALUE", 500)
    assert commission.calculate_commission(1000) == 500.0


def test_commission_zero_when_no_rent():
    assert commission.calculate_commission(None) == 0.0
    assert commission.calculate_commission(0) == 0.0


def test_commission_never_charges_tenant():
    """There must be no function in this module that accepts a tenant
    identity/record to compute a fee — commission is derived from the
    listing's rent only. This is a hard legal requirement (Tenant Fees
    Act 2019), not just a design choice."""
    import inspect

    for name, func in inspect.getmembers(commission, inspect.isfunction):
        params = list(inspect.signature(func).parameters)
        assert not any("tenant" in p.lower() for p in params), (
            f"{name} must not accept a tenant parameter"
        )


def make_tenant(**kwargs):
    base = {
        "id": 1, "name": "Test Tenant", "email": "tenant@example.com",
        "areas": [], "budget_max": None, "bedrooms_needed": None, "status": "new",
    }
    base.update(kwargs)
    return base


def test_rental_matcher_area_budget_bedrooms():
    listing = {"outcode": "M14", "monthly_rent": 1000, "bedrooms": 3}
    good = make_tenant(areas=["M14"], budget_max=1200, bedrooms_needed=2)
    wrong_area = make_tenant(areas=["B1"], budget_max=1200)
    over_budget = make_tenant(areas=["M14"], budget_max=500)
    too_many_beds_needed = make_tenant(areas=["M14"], bedrooms_needed=5)

    matches = rental_matcher.find_matching_tenants(
        listing, [good, wrong_area, over_budget, too_many_beds_needed]
    )
    assert good in matches
    assert wrong_area not in matches
    assert over_budget not in matches
    assert too_many_beds_needed not in matches


def test_rental_matcher_excludes_placed_tenants():
    listing = {"outcode": "M14", "monthly_rent": 1000, "bedrooms": 2}
    placed = make_tenant(status="placed")
    assert rental_matcher.find_matching_tenants(listing, [placed]) == []


def test_full_demo_rental_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test_rentals.db")
    monkeypatch.setattr(config, "DRY_RUN_OUTREACH", True)

    import db
    import rental_pipeline
    import run_pipeline as cli

    db.init_db()
    cli._seed_landlords_if_empty(config.SEED_DIR / "landlords_seed.csv")
    rental_pipeline.ingest_rental_data(
        extra_listing_csv_paths=[str(config.SEED_DIR / "rental_listings_demo.csv")],
        extra_tenant_csv_paths=[str(config.SEED_DIR / "tenants_demo.csv")],
    )
    cli._link_demo_listings_to_first_landlord()
    rental_pipeline.match_and_draft_rental_outreach()

    stats = db.rental_stats()
    assert stats["rental_listings"] == 2
    assert stats["tenants"] == 2
    assert stats["rental_matches"] >= 1

    matches = db.list_rental_matches()
    assert all(m["status"] == "draft" for m in matches)  # DRY_RUN_OUTREACH=True
    assert all(m["commission_amount"] is not None for m in matches)
