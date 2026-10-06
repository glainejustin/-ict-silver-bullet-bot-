import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents import deal_analyzer  # noqa: E402


def test_bmv_and_roi_calculation():
    lead = {
        "address": "1 Test Street",
        "asking_price": 100000,
        "property_type": "terraced",
        "bedrooms": 3,
    }
    result = deal_analyzer.analyze(lead, estimated_market_value=150000)

    assert result["bmv_percent"] == round((150000 - 100000) / 150000 * 100, 1)
    assert result["refurb_estimate"] == 12000
    assert result["strategy"] in {
        "BRRR (buy, refurb, refinance, rent)",
        "Flip / quick resale",
        "HMO conversion",
        "Buy-to-let (hold)",
    }
    assert result["score"] > 0
    assert "below market" in result["notes"] or "BMV" in result["notes"] or len(result["notes"]) > 0


def test_missing_data_is_handled_gracefully():
    lead = {"address": "Unknown", "asking_price": None}
    result = deal_analyzer.analyze(lead, estimated_market_value=None)
    assert result["bmv_percent"] is None
    assert "manual research" in result["notes"]


def test_hmo_strategy_for_large_properties():
    lead = {"asking_price": 150000, "property_type": "detached", "bedrooms": 5}
    result = deal_analyzer.analyze(lead, estimated_market_value=200000)
    assert result["strategy"] == "HMO conversion"
