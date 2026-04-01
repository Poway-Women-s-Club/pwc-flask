"""Background job: send event reminder emails ~30 minutes before start."""

from datetime import datetime, timedelta

from model.database import db
from model.event import RSVP, Event
from services.email_outbound import send_plain_email


def process_event_reminders():
    """
    For each RSVP with wants_email_reminder and no reminder_sent_at, if the event's
    start time is between 30 and 29 minutes away (first scheduler pass after T-30),
    send one reminder email.

    Uses: now >= start_time - 30min and now < start_time (send once before event).
    """
    now = datetime.utcnow()
    due_rows = (
        RSVP.query.filter(
            RSVP.wants_email_reminder.is_(True),
            RSVP.reminder_sent_at.is_(None),
        )
        .join(Event, RSVP.event_id == Event.id)
        .filter(Event.start_time > now)
        .all()
    )

    for rsvp in due_rows:
        event = rsvp.event
        remind_at = event.start_time - timedelta(minutes=30)
        if now < remind_at or now >= event.start_time:
            continue

        user = rsvp.user
        if not user or not user.email:
            continue
        if not user.google_id:
            continue

        when = event.start_time.strftime("%Y-%m-%d %H:%M UTC")
        loc = event.location or "TBA"
        delta_min = max(1, int((event.start_time - now).total_seconds() // 60))
        subject = f"Reminder: {event.title}"
        body = (
            f"This is your Poway Woman's Club meeting reminder.\n\n"
            f"Event: {event.title}\n"
            f"Starts in about {delta_min} minutes (at {when}).\n"
            f"Where: {loc}\n\n"
            f"We look forward to seeing you there.\n"
        )
        try:
            if send_plain_email(user.email, subject, body):
                rsvp.reminder_sent_at = now
                db.session.commit()
        except Exception as exc:
            db.session.rollback()
            try:
                from flask import current_app
                current_app.logger.exception("Reminder email failed: %s", exc)
            except Exception:
                pass
