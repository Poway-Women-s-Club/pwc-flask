"""Group and membership models."""

from datetime import datetime
from model.database import db


class Group(db.Model):
    __tablename__ = "groups"

    id          = db.Column(db.Integer,     primary_key=True)
    name        = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text,        nullable=False, default="")
    created_by  = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    requires_application = db.Column(db.Boolean, nullable=False, default=False)

    members = db.relationship("UserGroup", backref="group", lazy="dynamic",
                              cascade="all, delete-orphan")
    applications = db.relationship("GroupApplication", backref="group", lazy="dynamic",
                                   cascade="all, delete-orphan")

    def member_count(self):
        """Return the number of members in this group."""
        return self.members.count()

    def has_member(self, user_id):
        """Check whether a user belongs to this group."""
        return self.members.filter_by(user_id=user_id).first() is not None

    def to_dict(self):
        return {
            "id":                    self.id,
            "name":                  self.name,
            "description":           self.description,
            "created_by":            self.created_by,
            "member_count":          self.member_count(),
            "created_at":            self.created_at.isoformat(),
            "requires_application":  bool(self.requires_application),
        }


class UserGroup(db.Model):
    __tablename__ = "user_groups"

    id        = db.Column(db.Integer, primary_key=True)
    user_id   = db.Column(db.Integer, db.ForeignKey("users.id"),   nullable=False)
    group_id  = db.Column(db.Integer, db.ForeignKey("groups.id"),  nullable=False)
    joined_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "group_id"),)


class GroupApplication(db.Model):
    """Join request when a group requires admin approval."""

    __tablename__ = "group_applications"

    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    group_id    = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False)
    message     = db.Column(db.Text, nullable=False, default="")
    status      = db.Column(db.String(16), nullable=False, default="pending")
    created_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    decided_at  = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint("user_id", "group_id"),)
