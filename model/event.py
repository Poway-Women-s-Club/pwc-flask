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
    created_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    rsvps = db.relationship("RSVP", backref="event", lazy="dynamic",
                            cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id":          self.id,
            "title":       self.title,
            "description": self.description,
            "location":    self.location,
            "start_time":  self.start_time.isoformat(),
            "end_time":    self.end_time.isoformat() if self.end_time else None,
            "rsvp_count":  self.rsvps.count(),
            "created_by":  self.created_by,
            "created_at":  self.created_at.isoformat(),
        }


class RSVP(db.Model):
    __tablename__ = "rsvps"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"),   nullable=False)
    event_id   = db.Column(db.Integer, db.ForeignKey("events.id"),  nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "event_id"),)

    def to_dict(self):
        return {
            "id":         self.id,
            "user_id":    self.user_id,
            "event_id":   self.event_id,
            "created_at": self.created_at.isoformat(),
        }