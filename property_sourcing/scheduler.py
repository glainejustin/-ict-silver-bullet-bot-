#!/usr/bin/env python3
"""Keeps the pipeline running automatically, forever, with no further input
from you — this is what makes it "low involvement". Run this as a background
service (systemd, pm2, a Docker container, Render/Railway cron, etc.) on any
always-on machine.

    python scheduler.py

By default it runs the full pipeline once immediately, then every 24 hours.
Tune the schedule with PIPELINE_INTERVAL_HOURS in your .env.
"""
import logging
import os
import time

from apscheduler.schedulers.background import BackgroundScheduler

import db
import pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

INTERVAL_HOURS = int(os.getenv("PIPELINE_INTERVAL_HOURS", "24"))


def job():
    logger.info("Running scheduled sourcing pipeline...")
    try:
        stats = pipeline.run_full_pipeline()
        logger.info("Pipeline run finished: %s", stats)
    except Exception:
        logger.exception("Pipeline run failed")


def main():
    db.init_db()
    job()  # run once immediately so you see results right away

    scheduler = BackgroundScheduler()
    scheduler.add_job(job, "interval", hours=INTERVAL_HOURS, id="sourcing_pipeline")
    scheduler.start()
    logger.info("Scheduler started — pipeline will run every %s hour(s). Ctrl+C to stop.", INTERVAL_HOURS)

    try:
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    main()
