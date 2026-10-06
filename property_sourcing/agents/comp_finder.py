"""Comp-finder agent — works out what a property is really worth by pulling
recent, genuinely comparable sold prices from free HM Land Registry data.
"""
import datetime
import logging
import statistics

from connectors import land_registry

logger = logging.getLogger(__name__)


def find_market_value(lead: dict) -> dict:
    """Returns {"estimated_market_value": float|None, "comps": [...]}"""
    outcode = lead.get("outcode")
    if not outcode:
        return {"estimated_market_value": None, "comps": []}

    property_type = lead.get("property_type")
    current_year = datetime.date.today().year
    years = [current_year, current_year - 1]  # roughly the last 24 months

    try:
        comps = land_registry.comps_for_outcode(
            outcode, years, property_type=property_type, limit=20
        )
    except Exception as exc:  # noqa: BLE001 — never let a data source outage kill the pipeline
        logger.warning("Comp lookup failed for %s: %s", outcode, exc)
        comps = []

    prices = [c["sale_price"] for c in comps if c.get("sale_price")]
    estimated = round(statistics.median(prices) / 1000) * 1000 if prices else None

    return {"estimated_market_value": estimated, "comps": comps}
