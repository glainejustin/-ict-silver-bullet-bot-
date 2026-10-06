"""Central configuration, loaded from environment variables / .env file.

Every setting has a safe, zero-cost default so the system runs out of the box
in demo mode even if you never create a .env file.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# ---- LLM ----
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "none").strip().lower()
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")

# ---- Data connectors ----
COMPANIES_HOUSE_API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY", "")
LAND_REGISTRY_CACHE_DIR = Path(
    os.getenv("LAND_REGISTRY_CACHE_DIR", BASE_DIR / "data" / "land_registry_cache")
)
AUCTION_FEED_URLS = [
    u.strip() for u in os.getenv("AUCTION_FEED_URLS", "").split(",") if u.strip()
]
OPEN_DATA_CSV_URLS = [
    u.strip() for u in os.getenv("OPEN_DATA_CSV_URLS", "").split(",") if u.strip()
]
GAZETTE_SEARCH_TERMS = [
    t.strip() for t in os.getenv("GAZETTE_SEARCH_TERMS", "").split(",") if t.strip()
] or None  # None lets the connector use its own sensible defaults
BROWNFIELD_LOCAL_AUTHORITY = os.getenv("BROWNFIELD_LOCAL_AUTHORITY", "") or None
CCOD_CSV_PATH = os.getenv("CCOD_CSV_PATH", "")

# ---- Outreach ----
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Your Sourcing Business")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")
DIGEST_TO_EMAIL = os.getenv("DIGEST_TO_EMAIL", "")
DRY_RUN_OUTREACH = _bool("DRY_RUN_OUTREACH", True)

# ---- Deal scoring ----
MIN_BMV_PERCENT = _int("MIN_BMV_PERCENT", 15)
MIN_ROI_PERCENT = _int("MIN_ROI_PERCENT", 12)

# ---- Lettings / commission (landlord pays, tenant never pays — see
# docs/LETTINGS_LEGAL_COMPLIANCE.md) ----
COMMISSION_TYPE = os.getenv("COMMISSION_TYPE", "one_month_rent")  # one_month_rent | percent_of_annual_rent | flat_fee
try:
    COMMISSION_VALUE = float(os.getenv("COMMISSION_VALUE", "1"))
except ValueError:
    COMMISSION_VALUE = 1.0

# ---- Dashboard ----
FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "change-me")
DASHBOARD_PORT = _int("DASHBOARD_PORT", 8000)

# ---- Paths ----
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "sourcing.db"
SEED_DIR = BASE_DIR / "seed"

DATA_DIR.mkdir(parents=True, exist_ok=True)
