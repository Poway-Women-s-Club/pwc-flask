from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from model.database import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)  # null for OAuth-only users
    role = db.Column(db.String(20), default="member")  # member, admin
    google_id = db.Column(db.String(256), unique=True, nullable=True)
    avatar_url = db.Column(db.String(512), nullable=True)
    is_active_member = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    posts = db.relationship("BlogPost", backref="author", lazy=True)
    comments = db.relationship("Comment", backref="author", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "role": self.role,
            "avatar_url": self.avatar_url,
            "is_active_member": self.is_active_member,
            "created_at": self.created_at.isoformat(),
        }