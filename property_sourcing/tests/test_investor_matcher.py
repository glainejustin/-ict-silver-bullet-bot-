import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import investor_matcher  # noqa: E402


def make_buyer(**kwargs):
    base = {
        "id": 1,
        "name": "Test Buyer",
        "email": "buyer@example.com",
        "areas": [],
        "budget_min": None,
        "budget_max": None,
        "strategies": [],
        "min_roi_percent": None,
    }
    base.update(kwargs)
    return base


def test_area_and_budget_filtering():
    lead = {"outcode": "M14", "asking_price": 100000, "strategy": "Flip / quick resale", "roi_percent": 20}
    good_buyer = make_buyer(areas=["M14"], budget_min=50000, budget_max=150000)
    bad_area_buyer = make_buyer(areas=["B1"], budget_min=50000, budget_max=150000)
    bad_budget_buyer = make_buyer(areas=["M14"], budget_min=200000, budget_max=300000)

    matches = investor_matcher.find_matching_buyers(lead, [good_buyer, bad_area_buyer, bad_budget_buyer])
    assert good_buyer in matches
    assert bad_area_buyer not in matches
    assert bad_budget_buyer not in matches


def test_buyer_without_email_is_excluded():
    lead = {"outcode": "M14", "asking_price": 100000}
    buyer = make_buyer(email=None)
    assert investor_matcher.find_matching_buyers(lead, [buyer]) == []


def test_no_preferences_matches_everything():
    lead = {"outcode": "ZZ9", "asking_price": 999999}
    buyer = make_buyer()
    assert buyer in investor_matcher.find_matching_buyers(lead, [buyer])
