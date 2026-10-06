"""Lightweight SQLite data layer — no ORM, no extra dependencies.

Tables:
  leads      — every property opportunity the connectors find, through its
               whole lifecycle (new -> analyzed -> outreach -> sold/dead).
  comps      — comparable sold prices attached to a lead, used for valuation.
  buyers     — your cash-buyer / investor CRM.
  outreach   — every email the AI agent drafted or sent, and to whom.
  activity   — a simple audit log so you can see exactly what the system did
               and when, with zero guesswork.

  Lettings module (separate domain — commission always charges the
  landlord, never the tenant, per the Tenant Fees Act 2019):
  landlords        — your landlord contacts.
  rental_listings  — properties a landlord has instructed you to find a
                     tenant for.
  tenants          — prospective tenants looking for a property.
  rental_matches   — a tenant matched to a listing, through introduction to
                     (hopefully) a signed tenancy and your commission.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_ref TEXT,
    address TEXT,
    postcode TEXT,
    outcode TEXT,
    property_type TEXT,
    bedrooms INTEGER,
    asking_price REAL,
    status TEXT NOT NULL DEFAULT 'new',
    motivation_signal TEXT,
    estimated_market_value REAL,
    bmv_percent REAL,
    refurb_estimate REAL,
    gdv REAL,
    strategy TEXT,
    roi_percent REAL,
    monthly_cashflow REAL,
    score REAL,
    notes TEXT,
    raw_data TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source, source_ref)
);

CREATE TABLE IF NOT EXISTS comps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL REFERENCES leads(id),
    address TEXT,
    postcode TEXT,
    sale_price REAL,
    sale_date TEXT,
    property_type TEXT
);

CREATE TABLE IF NOT EXISTS buyers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    areas TEXT,
    budget_min REAL,
    budget_max REAL,
    strategies TEXT,
    min_roi_percent REAL,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outreach (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL REFERENCES leads(id),
    buyer_id INTEGER REFERENCES buyers(id),
    channel TEXT NOT NULL DEFAULT 'email',
    recipient TEXT,
    subject TEXT,
    body TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    sent_at TEXT
);

CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER,
    event TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS landlords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rental_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL DEFAULT 'manual',
    source_ref TEXT,
    landlord_id INTEGER REFERENCES landlords(id),
    address TEXT,
    postcode TEXT,
    outcode TEXT,
    property_type TEXT,
    bedrooms INTEGER,
    monthly_rent REAL,
    available_from TEXT,
    furnishing TEXT,
    status TEXT NOT NULL DEFAULT 'available',
    motivation_signal TEXT,
    raw_data TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source, source_ref)
);

CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    areas TEXT,
    budget_max REAL,
    bedrooms_needed INTEGER,
    move_in_date TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rental_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES rental_listings(id),
    tenant_id INTEGER NOT NULL REFERENCES tenants(id),
    status TEXT NOT NULL DEFAULT 'draft',
    subject TEXT,
    body TEXT,
    commission_amount REAL,
    commission_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(listing_id, tenant_id)
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def log_activity(lead_id, event: str, detail: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO activity (lead_id, event, detail, created_at) VALUES (?, ?, ?, ?)",
            (lead_id, event, detail, now()),
        )


def upsert_lead(lead: dict) -> tuple:
    """Insert a lead, or return the existing id if (source, source_ref) exists.
    Returns (lead_id, is_new)."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT id FROM leads WHERE source = ? AND source_ref = ?",
            (lead["source"], lead.get("source_ref")),
        )
        row = cur.fetchone()
        if row:
            return row["id"], False

        ts = now()
        cur = conn.execute(
            """INSERT INTO leads
               (source, source_ref, address, postcode, outcode, property_type,
                bedrooms, asking_price, status, motivation_signal, raw_data,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                lead["source"],
                lead.get("source_ref"),
                lead.get("address"),
                lead.get("postcode"),
                lead.get("outcode"),
                lead.get("property_type"),
                lead.get("bedrooms"),
                lead.get("asking_price"),
                lead.get("status", "new"),
                lead.get("motivation_signal"),
                json.dumps(lead.get("raw_data", {})),
                ts,
                ts,
            ),
        )
        return cur.lastrowid, True


def update_lead(lead_id: int, fields: dict):
    if not fields:
        return
    fields = dict(fields)
    fields["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE leads SET {cols} WHERE id = ?", (*fields.values(), lead_id))


def get_lead(lead_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return dict(row) if row else None


def list_leads(status: str = None, order_by: str = "score DESC, created_at DESC"):
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                f"SELECT * FROM leads WHERE status = ? ORDER BY {order_by}", (status,)
            ).fetchall()
        else:
            rows = conn.execute(f"SELECT * FROM leads ORDER BY {order_by}").fetchall()
        return [dict(r) for r in rows]


def add_comps(lead_id: int, comps: list):
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO comps (lead_id, address, postcode, sale_price, sale_date, property_type)
               VALUES (?,?,?,?,?,?)""",
            [
                (
                    lead_id,
                    c.get("address"),
                    c.get("postcode"),
                    c.get("sale_price"),
                    c.get("sale_date"),
                    c.get("property_type"),
                )
                for c in comps
            ],
        )


def get_comps(lead_id: int):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM comps WHERE lead_id = ?", (lead_id,)).fetchall()
        return [dict(r) for r in rows]


def add_buyer(buyer: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO buyers (name, email, phone, areas, budget_min, budget_max,
                                    strategies, min_roi_percent, notes, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                buyer["name"],
                buyer.get("email"),
                buyer.get("phone"),
                json.dumps(buyer.get("areas", [])),
                buyer.get("budget_min"),
                buyer.get("budget_max"),
                json.dumps(buyer.get("strategies", [])),
                buyer.get("min_roi_percent"),
                buyer.get("notes"),
                now(),
            ),
        )
        return cur.lastrowid


def list_buyers():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM buyers ORDER BY name").fetchall()
        buyers = []
        for r in rows:
            b = dict(r)
            b["areas"] = json.loads(b["areas"] or "[]")
            b["strategies"] = json.loads(b["strategies"] or "[]")
            buyers.append(b)
        return buyers


def add_outreach(entry: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO outreach (lead_id, buyer_id, channel, recipient, subject,
                                      body, status, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                entry["lead_id"],
                entry.get("buyer_id"),
                entry.get("channel", "email"),
                entry.get("recipient"),
                entry.get("subject"),
                entry.get("body"),
                entry.get("status", "draft"),
                now(),
            ),
        )
        return cur.lastrowid


def mark_outreach_sent(outreach_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE outreach SET status = 'sent', sent_at = ? WHERE id = ?",
            (now(), outreach_id),
        )


def list_outreach(lead_id: int = None):
    with get_conn() as conn:
        if lead_id:
            rows = conn.execute(
                "SELECT * FROM outreach WHERE lead_id = ? ORDER BY created_at DESC", (lead_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM outreach ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def stats():
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
        hot = conn.execute(
            "SELECT COUNT(*) c FROM leads WHERE bmv_percent >= ?", (config.MIN_BMV_PERCENT,)
        ).fetchone()["c"]
        drafted = conn.execute(
            "SELECT COUNT(*) c FROM outreach WHERE status = 'draft'"
        ).fetchone()["c"]
        sent = conn.execute(
            "SELECT COUNT(*) c FROM outreach WHERE status = 'sent'"
        ).fetchone()["c"]
        buyers_count = conn.execute("SELECT COUNT(*) c FROM buyers").fetchone()["c"]
        return {
            "total_leads": total,
            "hot_deals": hot,
            "outreach_drafted": drafted,
            "outreach_sent": sent,
            "buyers": buyers_count,
        }


# ---------------------------------------------------------------------------
# Lettings module
# ---------------------------------------------------------------------------

def add_landlord(landlord: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO landlords (name, email, phone, notes, created_at) VALUES (?,?,?,?,?)",
            (landlord["name"], landlord.get("email"), landlord.get("phone"), landlord.get("notes"), now()),
        )
        return cur.lastrowid


def list_landlords():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM landlords ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def upsert_rental_listing(listing: dict) -> tuple:
    """Returns (listing_id, is_new), same idempotency pattern as upsert_lead."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT id FROM rental_listings WHERE source = ? AND source_ref = ?",
            (listing.get("source", "manual"), listing.get("source_ref")),
        )
        row = cur.fetchone()
        if row:
            return row["id"], False

        ts = now()
        cur = conn.execute(
            """INSERT INTO rental_listings
               (source, source_ref, landlord_id, address, postcode, outcode, property_type,
                bedrooms, monthly_rent, available_from, furnishing, status, motivation_signal,
                raw_data, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                listing.get("source", "manual"),
                listing.get("source_ref"),
                listing.get("landlord_id"),
                listing.get("address"),
                listing.get("postcode"),
                listing.get("outcode"),
                listing.get("property_type"),
                listing.get("bedrooms"),
                listing.get("monthly_rent"),
                listing.get("available_from"),
                listing.get("furnishing"),
                listing.get("status", "available"),
                listing.get("motivation_signal"),
                json.dumps(listing.get("raw_data", {})),
                ts,
                ts,
            ),
        )
        return cur.lastrowid, True


def update_rental_listing(listing_id: int, fields: dict):
    if not fields:
        return
    fields = dict(fields)
    fields["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE rental_listings SET {cols} WHERE id = ?", (*fields.values(), listing_id))


def get_rental_listing(listing_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM rental_listings WHERE id = ?", (listing_id,)).fetchone()
        return dict(row) if row else None


def list_rental_listings(status: str = None):
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM rental_listings WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM rental_listings ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def add_tenant(tenant: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tenants (name, email, phone, areas, budget_max, bedrooms_needed,
                                     move_in_date, notes, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                tenant["name"],
                tenant.get("email"),
                tenant.get("phone"),
                json.dumps(tenant.get("areas", [])),
                tenant.get("budget_max"),
                tenant.get("bedrooms_needed"),
                tenant.get("move_in_date"),
                tenant.get("notes"),
                tenant.get("status", "new"),
                now(),
            ),
        )
        return cur.lastrowid


def list_tenants(status: str = None):
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM tenants WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM tenants ORDER BY created_at DESC").fetchall()
        tenants = []
        for r in rows:
            t = dict(r)
            t["areas"] = json.loads(t["areas"] or "[]")
            tenants.append(t)
        return tenants


def get_tenant(tenant_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        if not row:
            return None
        t = dict(row)
        t["areas"] = json.loads(t["areas"] or "[]")
        return t


def add_rental_match(match: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute("SELECT id FROM rental_matches WHERE listing_id = ? AND tenant_id = ?",
                            (match["listing_id"], match["tenant_id"]))
        row = cur.fetchone()
        if row:
            return row["id"]
        ts = now()
        cur = conn.execute(
            """INSERT INTO rental_matches
               (listing_id, tenant_id, status, subject, body, commission_amount,
                commission_status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                match["listing_id"],
                match["tenant_id"],
                match.get("status", "draft"),
                match.get("subject"),
                match.get("body"),
                match.get("commission_amount"),
                match.get("commission_status", "pending"),
                ts,
                ts,
            ),
        )
        return cur.lastrowid


def update_rental_match(match_id: int, fields: dict):
    if not fields:
        return
    fields = dict(fields)
    fields["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE rental_matches SET {cols} WHERE id = ?", (*fields.values(), match_id))


def list_rental_matches(listing_id: int = None):
    with get_conn() as conn:
        if listing_id:
            rows = conn.execute(
                "SELECT * FROM rental_matches WHERE listing_id = ? ORDER BY created_at DESC", (listing_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM rental_matches ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def rental_stats():
    with get_conn() as conn:
        listings = conn.execute("SELECT COUNT(*) c FROM rental_listings").fetchone()["c"]
        available = conn.execute(
            "SELECT COUNT(*) c FROM rental_listings WHERE status = 'available'"
        ).fetchone()["c"]
        tenants_count = conn.execute("SELECT COUNT(*) c FROM tenants").fetchone()["c"]
        matches = conn.execute("SELECT COUNT(*) c FROM rental_matches").fetchone()["c"]
        let_count = conn.execute(
            "SELECT COUNT(*) c FROM rental_listings WHERE status = 'let'"
        ).fetchone()["c"]
        commission_pending = conn.execute(
            "SELECT COALESCE(SUM(commission_amount), 0) s FROM rental_matches WHERE commission_status = 'pending' AND status = 'let'"
        ).fetchone()["s"]
        return {
            "rental_listings": listings,
            "rental_available": available,
            "tenants": tenants_count,
            "rental_matches": matches,
            "rental_let": let_count,
            "commission_pending": commission_pending,
        }
