from datetime import datetime
from model.database import db


class Event(db.Model):
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(200), nullable=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    rsvps = db.relationship("RSVP", backref="event", lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "location": self.location,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "created_by": self.created_by,
            "rsvp_count": len(self.rsvps),
        }


class RSVP(db.Model):
    __tablename__ = "rsvps"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "event_id"),)


class PublicRSVP(db.Model):
    """
    Stores public (non-logged-in) RSVPs for calendar events.
    This supports events that are generated client-side (e.g., recurring meetings)
    as well as events stored in the backend database.
    """

    __tablename__ = "public_rsvps"

    id = db.Column(db.Integer, primary_key=True)

    # Optional link to an internal Event row.
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=True)

    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    attendance = db.Column(db.String(20), nullable=False)  # yes/no/maybe
    notes = db.Column(db.Text, nullable=True)

    event_title = db.Column(db.String(200), nullable=False)
    event_start_time = db.Column(db.DateTime, nullable=False)
    event_location = db.Column(db.String(200), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Prevent duplicate submissions for the same person/time/title.
    __table_args__ = (
        db.UniqueConstraint("email", "event_start_time", "event_title"),
    )


class MeetingRequest(db.Model):
    """Public form submissions for proposed/suggested meetings."""

    __tablename__ = "meeting_requests"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(200), nullable=False)

    preferred_datetime = db.Column(db.DateTime, nullable=True)
    preferred_end_datetime = db.Column(db.DateTime, nullable=True)
    topic = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)