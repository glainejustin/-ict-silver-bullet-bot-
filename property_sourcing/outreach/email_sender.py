"""SMTP email sending — works with a free Gmail account (use an App Password,
not your real password: https://myaccount.google.com/apppasswords) or any
other SMTP provider.

Respects DRY_RUN_OUTREACH: while true (the default), nothing is actually
emailed — messages are only written to the database as drafts so you can
review them first. Flip DRY_RUN_OUTREACH=false in .env once you trust the
output, and the exact same pipeline starts sending for real with zero other
changes.
"""
import logging
import smtplib
from email.mime.text import MIMEText

import config

logger = logging.getLogger(__name__)


def send_email(to_email: str, subject: str, body: str) -> bool:
    if config.DRY_RUN_OUTREACH:
        logger.info("[DRY RUN] Would send email to %s: %s", to_email, subject)
        return False

    if not (config.SMTP_USERNAME and config.SMTP_PASSWORD and config.SMTP_FROM_EMAIL):
        logger.warning("SMTP not configured — cannot send email to %s", to_email)
        return False

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = f"{config.SMTP_FROM_NAME} <{config.SMTP_FROM_EMAIL}>"
    msg["To"] = to_email

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
            server.sendmail(config.SMTP_FROM_EMAIL, [to_email], msg.as_string())
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send email to %s: %s", to_email, exc)
        return False
