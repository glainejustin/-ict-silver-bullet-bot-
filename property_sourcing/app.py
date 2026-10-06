#!/usr/bin/env python3
"""The dashboard — the one thing you actually look at. Shows the deal
pipeline, lets you review/send drafted outreach, and manage your buyer CRM.

    python app.py
"""
import logging

from flask import Flask, redirect, render_template, request, url_for

import config
import db
import pipeline
from outreach import email_sender

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
    else:
        pipeline.run_full_pipeline()
    return redirect(url_for("index"))


if __name__ == "__main__":
    import os

    debug = os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes"}
    app.run(host="0.0.0.0", port=config.DASHBOARD_PORT, debug=debug)
