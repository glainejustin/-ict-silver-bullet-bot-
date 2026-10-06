"""UK HM Land Registry Price Paid Data — 100% free, Open Government Licence,
no API key, no signup. This is what the comp-finder agent uses to work out a
property's real market value (and therefore how far "below market value" an
asking price really is).

Docs: https://www.gov.uk/government/statistical-data-sets/price-paid-data-downloads

Note: this module is a *comps* data source, not a lead source — it tells you
what things actually sold for near a lead, it doesn't find leads by itself.
"""
import csv
import logging
from pathlib import Path

import requests

import config

logger = logging.getLogger(__name__)

PPD_COLUMNS = [
    "transaction_id", "price", "date_of_transfer", "postcode", "property_type",
    "old_new", "duration", "paon", "saon", "street", "locality", "town_city",
    "district", "county", "ppd_category_type", "record_status",
]

# Official per-year download pattern documented by HM Land Registry.
YEAR_URL = "http://prod1.publicdata.landregistry.gov.uk/pp-{year}.csv"

PROPERTY_TYPE_MAP = {"D": "detached", "S": "semi", "T": "terraced", "F": "flat", "O": "other"}


def _cache_path(year: int) -> Path:
    config.LAND_REGISTRY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return config.LAND_REGISTRY_CACHE_DIR / f"pp-{year}.csv"


def ensure_year_downloaded(year: int, timeout: int = 180) -> Path:
    """Downloads (and caches on disk) one year of the full national dataset.
    Each file is downloaded once and reused for every future lookup, so after
    the first run this is instant and still free."""
    path = _cache_path(year)
    if path.exists() and path.stat().st_size > 0:
        return path
    url = YEAR_URL.format(year=year)
    logger.info("Downloading Land Registry Price Paid Data for %s from %s", year, url)
    resp = requests.get(url, timeout=timeout, stream=True)
    resp.raise_for_status()
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            if chunk:
                f.write(chunk)
    tmp_path.rename(path)
    return path


def iter_rows_for_outcode(year: int, outcode: str):
    """Stream a cached year file and yield every row whose postcode starts
    with the given outcode (e.g. 'M14'), without ever loading the whole
    multi-hundred-MB file into memory at once."""
    path = ensure_year_downloaded(year)
    outcode = outcode.strip().upper()
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 5:
                continue
            postcode = row[3].strip().upper()
            if postcode.startswith(outcode):
                yield dict(zip(PPD_COLUMNS, row))


def comps_for_outcode(outcode: str, years: list, property_type: str = None, limit: int = 25) -> list:
    """Return recent comparable sales near `outcode`, newest first."""
    comps = []
    for year in years:
        try:
            for row in iter_rows_for_outcode(year, outcode):
                ptype = PROPERTY_TYPE_MAP.get(row["property_type"], "other")
                if property_type and ptype != property_type:
                    continue
                try:
                    price = float(row["price"]) if row["price"] else None
                except ValueError:
                    price = None
                comps.append(
                    {
                        "address": ", ".join(
                            p for p in [row["paon"], row["street"], row["town_city"]] if p
                        ),
                        "postcode": row["postcode"],
                        "sale_price": price,
                        "sale_date": row["date_of_transfer"],
                        "property_type": ptype,
                    }
                )
        except requests.RequestException as exc:
            logger.warning("Land Registry fetch failed for year %s: %s", year, exc)
        except FileNotFoundError:
            logger.warning("No cached/downloadable Land Registry file for year %s", year)

    comps.sort(key=lambda c: c["sale_date"] or "", reverse=True)
    return comps[:limit]
