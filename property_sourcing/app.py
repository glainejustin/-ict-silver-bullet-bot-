#!/usr/bin/env python3
"""The dashboard — the one thing you actually look at. Shows the deal
pipeline, lets you review/send drafted outreach, and manage your buyer CRM.

    python app.py
"""
import logging

from flask import Flask, redirect, render_template, request, send_file, url_for

import config
import db
import pipeline
import rental_pipeline
from agents import comp_finder, commission, deal_analyzer, rental_matcher
from outreach import commission_invoice, deal_pack, email_sender, rental_outreach_writer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = Flask(
    __name__,
    template_folder="dashboard/templates",
    static_folder="dashboard/static",
)
app.secret_key = config.FLASK_SECRET_KEY

db.init_db()


@app.route("/")
def index():
    status_filter = request.args.get("status")
    leads = db.list_leads(status=status_filter)
    return render_template(
        "index.html",
        leads=leads,
        stats=db.stats(),
        status_filter=status_filter,
        min_bmv=config.MIN_BMV_PERCENT,
        dry_run=config.DRY_RUN_OUTREACH,
    )


@app.route("/leads/<int:lead_id>")
def lead_detail(lead_id):
    lead = db.get_lead(lead_id)
    comps = db.get_comps(lead_id)
    outreach = db.list_outreach(lead_id)
    return render_template("deal_detail.html", lead=lead, comps=comps, outreach=outreach)


@app.route("/leads/<int:lead_id>/analyze", methods=["POST"])
def analyze_lead_now(lead_id):
    lead = db.get_lead(lead_id)
    if lead:
        valuation = comp_finder.find_market_value(lead)
        analysis = deal_analyzer.analyze(lead, valuation["estimated_market_value"])
        db.update_lead(lead_id, {**analysis, "status": "analyzed"})
        if valuation["comps"]:
            db.add_comps(lead_id, valuation["comps"])
        db.log_activity(lead_id, "analyzed", "manually triggered from dashboard")
    return redirect(url_for("lead_detail", lead_id=lead_id))


@app.route("/leads/<int:lead_id>/deal-pack.pdf")
def deal_pack_pdf(lead_id):
    lead = db.get_lead(lead_id)
    if not lead:
        return redirect(url_for("index"))
    comps = db.get_comps(lead_id)
    path = deal_pack.build_deal_pack(lead, comps)
    return send_file(path, as_attachment=True, download_name=f"deal_pack_{lead_id}.pdf")


@app.route("/leads/add", methods=["GET", "POST"])
def add_lead():
    if request.method == "POST":
        postcode = request.form.get("postcode", "").strip().upper()
        from connectors.base import BaseConnector

        lead = {
            "source": "manual",
            "source_ref": f"manual-{db.now()}",
            "address": request.form.get("address"),
            "postcode": postcode,
            "outcode": BaseConnector.outcode_of(postcode),
            "property_type": request.form.get("property_type") or "other",
            "bedrooms": int(request.form["bedrooms"]) if request.form.get("bedrooms") else None,
            "asking_price": float(request.form["asking_price"]) if request.form.get("asking_price") else None,
            "motivation_signal": request.form.get("motivation_signal") or "Manually added lead",
            "raw_data": {},
        }
        lead_id, _ = db.upsert_lead(lead)
        db.log_activity(lead_id, "ingested", "manually added via dashboard")
        return redirect(url_for("lead_detail", lead_id=lead_id))

    return render_template("add_lead.html")


@app.route("/outreach/<int:outreach_id>/send", methods=["POST"])
def send_outreach(outreach_id):
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM outreach WHERE id = ?", (outreach_id,)).fetchone()
    if row:
        was_dry_run = config.DRY_RUN_OUTREACH
        config.DRY_RUN_OUTREACH = False
        try:
            sent = email_sender.send_email(row["recipient"], row["subject"], row["body"])
        finally:
            config.DRY_RUN_OUTREACH = was_dry_run
        if sent:
            db.mark_outreach_sent(outreach_id)
        return redirect(url_for("lead_detail", lead_id=row["lead_id"]))
    return redirect(url_for("index"))


@app.route("/buyers", methods=["GET", "POST"])
def buyers():
    if request.method == "POST":
        db.add_buyer(
            {
                "name": request.form["name"],
                "email": request.form.get("email"),
                "phone": request.form.get("phone"),
                "areas": [a.strip() for a in request.form.get("areas", "").split(",") if a.strip()],
                "budget_min": float(request.form["budget_min"]) if request.form.get("budget_min") else None,
                "budget_max": float(request.form["budget_max"]) if request.form.get("budget_max") else None,
                "strategies": [s.strip() for s in request.form.get("strategies", "").split(",") if s.strip()],
                "min_roi_percent": float(request.form["min_roi_percent"]) if request.form.get("min_roi_percent") else None,
                "notes": request.form.get("notes"),
            }
        )
        return redirect(url_for("buyers"))

    return render_template("buyers.html", buyers=db.list_buyers())


@app.route("/run-pipeline", methods=["POST"])
def run_pipeline_now():
    demo = request.form.get("demo") == "1"
    if demo:
        import run_pipeline as cli

        cli.setup_demo_data()
        cli._seed_buyers_if_empty(config.SEED_DIR / "buyers_seed.csv")
        pipeline.run_full_pipeline(extra_csv_paths=[str(config.SEED_DIR / "demo_leads.csv")])

        cli._seed_landlords_if_empty(config.SEED_DIR / "landlords_seed.csv")
        rental_pipeline.ingest_rental_data(
            extra_listing_csv_paths=[str(config.SEED_DIR / "rental_listings_demo.csv")],
            extra_tenant_csv_paths=[str(config.SEED_DIR / "tenants_demo.csv")],
        )
        cli._link_demo_listings_to_first_landlord()
        rental_pipeline.match_and_draft_rental_outreach()
    else:
        pipeline.run_full_pipeline()
        rental_pipeline.run_rental_pipeline()
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Lettings module
# ---------------------------------------------------------------------------

@app.route("/rentals")
def rentals():
    status_filter = request.args.get("status")
    listings = db.list_rental_listings(status=status_filter)
    landlords_by_id = {l["id"]: l for l in db.list_landlords()}
    return render_template(
        "rentals.html",
        listings=listings,
        landlords_by_id=landlords_by_id,
        stats=db.rental_stats(),
        status_filter=status_filter,
        dry_run=config.DRY_RUN_OUTREACH,
    )


@app.route("/rentals/add", methods=["GET", "POST"])
def add_rental_listing():
    if request.method == "POST":
        postcode = request.form.get("postcode", "").strip().upper()
        from connectors.base import BaseConnector

        landlord_id = request.form.get("landlord_id")
        listing = {
            "source": "manual",
            "source_ref": f"manual-{db.now()}",
            "landlord_id": int(landlord_id) if landlord_id else None,
            "address": request.form.get("address"),
            "postcode": postcode,
            "outcode": BaseConnector.outcode_of(postcode),
            "property_type": request.form.get("property_type") or "other",
            "bedrooms": int(request.form["bedrooms"]) if request.form.get("bedrooms") else None,
            "monthly_rent": float(request.form["monthly_rent"]) if request.form.get("monthly_rent") else None,
            "available_from": request.form.get("available_from"),
            "furnishing": request.form.get("furnishing"),
            "motivation_signal": request.form.get("motivation_signal") or "Manually added rental listing",
            "raw_data": {},
        }
        listing_id, _ = db.upsert_rental_listing(listing)
        return redirect(url_for("rental_listing_detail", listing_id=listing_id))

    return render_template("add_rental_listing.html", landlords=db.list_landlords())


@app.route("/rentals/<int:listing_id>")
def rental_listing_detail(listing_id):
    listing = db.get_rental_listing(listing_id)
    matches = db.list_rental_matches(listing_id)
    landlord = None
    if listing and listing.get("landlord_id"):
        landlord = next((l for l in db.list_landlords() if l["id"] == listing["landlord_id"]), None)
    tenants_by_id = {t["id"]: t for t in db.list_tenants()}
    return render_template(
        "rental_listing_detail.html",
        listing=listing,
        matches=matches,
        landlord=landlord,
        tenants_by_id=tenants_by_id,
        commission_terms=commission.describe_commission_terms(),
    )


@app.route("/rentals/<int:listing_id>/match-now", methods=["POST"])
def match_listing_now(listing_id):
    listing = db.get_rental_listing(listing_id)
    if listing:
        tenants = db.list_tenants()
        matches = rental_matcher.find_matching_tenants(listing, tenants)
        for tenant in matches:
            existing = db.list_rental_matches(listing_id)
            if any(m["tenant_id"] == tenant["id"] for m in existing):
                continue
            commission_amount = commission.calculate_commission(listing.get("monthly_rent"))
            subject, body = rental_outreach_writer.draft_landlord_intro(listing, tenant, commission_amount)
            db.add_rental_match(
                {
                    "listing_id": listing_id,
                    "tenant_id": tenant["id"],
                    "status": "draft",
                    "subject": subject,
                    "body": body,
                    "commission_amount": commission_amount,
                }
            )
    return redirect(url_for("rental_listing_detail", listing_id=listing_id))


@app.route("/rentals/<int:listing_id>/mark-let/<int:tenant_id>", methods=["POST"])
def mark_listing_let(listing_id, tenant_id):
    db.update_rental_listing(listing_id, {"status": "let"})
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM rental_matches WHERE listing_id = ? AND tenant_id = ?", (listing_id, tenant_id)
        ).fetchone()
    if row:
        db.update_rental_match(row["id"], {"status": "let", "commission_status": "pending"})
    return redirect(url_for("rental_listing_detail", listing_id=listing_id))


@app.route("/rentals/<int:listing_id>/commission-invoice/<int:tenant_id>.pdf")
def commission_invoice_pdf(listing_id, tenant_id):
    listing = db.get_rental_listing(listing_id)
    tenant = db.get_tenant(tenant_id)
    if not listing or not tenant:
        return redirect(url_for("rentals"))
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM rental_matches WHERE listing_id = ? AND tenant_id = ?", (listing_id, tenant_id)
        ).fetchone()
    commission_amount = row["commission_amount"] if row else commission.calculate_commission(listing.get("monthly_rent"))
    path = commission_invoice.build_commission_invoice(listing, tenant, commission_amount)
    return send_file(path, as_attachment=True, download_name=f"commission_invoice_{listing_id}_{tenant_id}.pdf")


@app.route("/tenants", methods=["GET", "POST"])
def tenants():
    if request.method == "POST":
        db.add_tenant(
            {
                "name": request.form["name"],
                "email": request.form.get("email"),
                "phone": request.form.get("phone"),
                "areas": [a.strip() for a in request.form.get("areas", "").split(",") if a.strip()],
                "budget_max": float(request.form["budget_max"]) if request.form.get("budget_max") else None,
                "bedrooms_needed": int(request.form["bedrooms_needed"]) if request.form.get("bedrooms_needed") else None,
                "move_in_date": request.form.get("move_in_date"),
                "notes": request.form.get("notes"),
            }
        )
        return redirect(url_for("tenants"))

    return render_template("tenants.html", tenants=db.list_tenants())


@app.route("/landlords", methods=["GET", "POST"])
def landlords():
    if request.method == "POST":
        db.add_landlord(
            {
                "name": request.form["name"],
                "email": request.form.get("email"),
                "phone": request.form.get("phone"),
                "notes": request.form.get("notes"),
            }
        )
        return redirect(url_for("landlords"))

    return render_template("landlords.html", landlords=db.list_landlords())


if __name__ == "__main__":
    import os

    debug = os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes"}
    app.run(host="0.0.0.0", port=config.DASHBOARD_PORT, debug=debug)
