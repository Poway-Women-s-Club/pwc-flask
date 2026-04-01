"""SMTP email sending; configured via environment variables."""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app


def smtp_configured():
    cfg = current_app.config
    return bool(
        cfg.get("MAIL_SERVER")
        and cfg.get("MAIL_USERNAME")
        and cfg.get("MAIL_PASSWORD")
    )


def send_plain_email(to_address, subject, body):
    """
    Send a plain-text email. Returns True if sent, False if SMTP is not configured.
    Raises on SMTP failure (caller may catch).
    """
    if not smtp_configured():
        current_app.logger.warning("Email skipped: MAIL_* not configured")
        return False

    cfg = current_app.config
    sender = cfg.get("MAIL_DEFAULT_SENDER") or cfg["MAIL_USERNAME"]

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_address
    msg.attach(MIMEText(body, "plain", "utf-8"))

    server = cfg["MAIL_SERVER"]
    port = int(cfg.get("MAIL_PORT") or 587)
    use_tls = bool(cfg.get("MAIL_USE_TLS", True))

    with smtplib.SMTP(server, port, timeout=30) as smtp:
        if use_tls:
            smtp.starttls()
        smtp.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
        smtp.sendmail(sender, [to_address], msg.as_string())
    return True
