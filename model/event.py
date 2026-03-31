"""Event and RSVP models."""

from datetime import datetime
from model.database import db


class Event(db.Model):
    __tablename__ = "events"

    id          = db.Column(db.Integer,     primary_key=True)
    title       = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text,        nullable=False, default="")
    location    = db.Column(db.String(255), nullable=False, default="")
    start_time  = db.Column(db.DateTime,    nullable=False)
    end_time    = db.Column(db.DateTime,    nullable=True)
    created_by  = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    group_id    = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=True)
    # "club" (entire club) or "groups" (restricted to selected groups).
    visibility_scope = db.Column(db.String(16), nullable=False, default="club")
    # None means unlimited seats.
    max_attendees = db.Column(db.Integer, nullable=True)
    created_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    rsvps = db.relationship("RSVP", backref="event", lazy="dynamic",
                            cascade="all, delete-orphan")
    visible_groups = db.relationship("EventVisibleGroup", backref="event", lazy="dynamic",
                                     cascade="all, delete-orphan")

    def to_dict(self):
        group_name = None
        if self.group_id:
            from model.group import Group
            grp = Group.query.get(self.group_id)
            if grp:
                group_name = grp.name
        public_yes = (
            PublicRSVP.query.filter_by(event_id=self.id)
            .filter(PublicRSVP.attendance == "yes")
            .count()
        )
        logged_in = self.rsvps.count()
        seats_used = logged_in + public_yes
        fill_ratio = (seats_used / self.max_attendees) if self.max_attendees else 0.0
        return {
            "id":          self.id,
            "title":       self.title,
            "description": self.description,
            "location":    self.location,
            "start_time":  self.start_time.isoformat(),
            "end_time":    self.end_time.isoformat() if self.end_time else None,
            "rsvp_count":  logged_in,
            "max_attendees": self.max_attendees,
            "seats_used": seats_used,
            "fill_ratio": round(fill_ratio, 4),
            "is_full": bool(self.max_attendees and seats_used >= self.max_attendees),
            "created_by":  self.created_by,
            "group_id":    self.group_id,
            "group_name":  group_name,
            "visibility_scope": self.visibility_scope or "club",
            "visible_group_ids": [vg.group_id for vg in self.visible_groups.all()],
            "created_at":  self.created_at.isoformat(),
        }


class RSVP(db.Model):
    __tablename__ = "rsvps"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"),   nullable=False)
    event_id   = db.Column(db.Integer, db.ForeignKey("events.id"),  nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

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


class EventVisibleGroup(db.Model):
    """Group visibility mapping for events restricted to selected groups."""
    __tablename__ = "event_visible_groups"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False)

    __table_args__ = (db.UniqueConstraint("event_id", "group_id"),)