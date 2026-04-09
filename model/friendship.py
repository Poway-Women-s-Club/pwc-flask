"""
Friendship model.

A friendship is directional at creation (requester → addressee) but
symmetric once accepted.  Status values: pending | accepted | declined.

Uniqueness is enforced on the requester/addressee pair so there is at most
one row per ordered pair.  The helpers in api/friends.py treat the pair as
unordered (look up both orderings) to keep queries simple.
"""

from datetime import datetime
from model.database import db


class Friendship(db.Model):
    __tablename__ = "friendships"

    id           = db.Column(db.Integer,  primary_key=True)
    requester_id = db.Column(db.Integer,  db.ForeignKey("users.id"), nullable=False)
    addressee_id = db.Column(db.Integer,  db.ForeignKey("users.id"), nullable=False)
    status       = db.Column(db.String(16), nullable=False, default="pending")
    created_at   = db.Column(db.DateTime,  nullable=False, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime,  nullable=True)

    __table_args__ = (
        db.UniqueConstraint("requester_id", "addressee_id", name="uq_friendship_pair"),
    )

    def to_dict(self):
        return {
            "id":           self.id,
            "requester_id": self.requester_id,
            "addressee_id": self.addressee_id,
            "status":       self.status,
            "created_at":   self.created_at.isoformat(),
            "updated_at":   self.updated_at.isoformat() if self.updated_at else None,
        }
