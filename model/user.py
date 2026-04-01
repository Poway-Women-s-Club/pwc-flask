"""
User model.

Fields match what the frontend expects in to_dict():
  id, username, email, role, is_active_member,
  first_name, last_name, bio, languages, interests,
  avatar_url, google_id, created_at
"""

from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import check_password_hash

from model.database import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id               = db.Column(db.Integer, primary_key=True)
    username         = db.Column(db.String(80),  unique=True, nullable=False)
    email            = db.Column(db.String(120), unique=True, nullable=False)
    password_hash    = db.Column(db.String(256), nullable=True)   # null for Google-only accounts
    role             = db.Column(db.String(20),  nullable=False, default="member")
    is_active_member = db.Column(db.Boolean,     nullable=False, default=False)

    # Profile fields (match profile.js session contract)
    first_name  = db.Column(db.String(80),  nullable=False, default="")
    last_name   = db.Column(db.String(80),  nullable=False, default="")
    bio         = db.Column(db.Text,        nullable=False, default="")
    languages   = db.Column(db.JSON,        nullable=False, default=list)
    interests   = db.Column(db.JSON,        nullable=False, default=list)

    # OAuth / avatar
    google_id   = db.Column(db.String(128), unique=True, nullable=True)
    avatar_url  = db.Column(db.String(512), nullable=True)

    created_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    blog_posts  = db.relationship("BlogPost", backref="author_user", lazy="dynamic",
                                  foreign_keys="BlogPost.author_id")
    comments    = db.relationship("Comment",  backref="author_user", lazy="dynamic",
                                  foreign_keys="Comment.author_id")
    payments    = db.relationship("Payment",  backref="user",        lazy="dynamic")
    rsvps       = db.relationship("RSVP",     backref="user",        lazy="dynamic")
    sent_messages     = db.relationship("Message", foreign_keys="Message.sender_id",
                                        backref="sender", lazy="dynamic")
    received_messages = db.relationship("Message", foreign_keys="Message.recipient_id",
                                        backref="recipient", lazy="dynamic")

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            "id":               self.id,
            "username":         self.username,
            "email":            self.email,
            "role":             self.role,
            "is_active_member": self.is_active_member,
            "hasGoogleLinked":  bool(self.google_id),
            # Profile fields — match sessionStorage contract in profile.js
            "firstName":        self.first_name,
            "lastName":         self.last_name,
            "bio":              self.bio,
            "languages":        self.languages or [],
            "interests":        self.interests  or [],
            "avatar_url":       self.avatar_url,
            "created_at":       self.created_at.isoformat(),
        }