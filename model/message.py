"""
Message model for the DM system.

A message belongs to a conversation between two users.
Conversations are identified by the sorted pair of user IDs
so there is always exactly one thread between any two members.
"""

from datetime import datetime
from model.database import db


class Message(db.Model):
    __tablename__ = "messages"

    id           = db.Column(db.Integer,  primary_key=True)
    sender_id    = db.Column(db.Integer,  db.ForeignKey("users.id"), nullable=False)
    recipient_id = db.Column(db.Integer,  db.ForeignKey("users.id"), nullable=False)
    body         = db.Column(db.Text,     nullable=False)
    read_at      = db.Column(db.DateTime, nullable=True)   # None = unread
    created_at   = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":           self.id,
            "sender_id":    self.sender_id,
            "recipient_id": self.recipient_id,
            "body":         self.body,
            "read_at":      self.read_at.isoformat() if self.read_at else None,
            "created_at":   self.created_at.isoformat(),
        }