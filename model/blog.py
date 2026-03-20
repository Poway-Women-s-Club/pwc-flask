"""Blog post and comment models."""

from datetime import datetime
from model.database import db


class BlogPost(db.Model):
    __tablename__ = "blog_posts"

    id             = db.Column(db.Integer, primary_key=True)
    title          = db.Column(db.String(255), nullable=False)
    body           = db.Column(db.Text,        nullable=False)
    author_id      = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    is_pinned      = db.Column(db.Boolean, nullable=False, default=False)
    pin_expires_at = db.Column(db.DateTime, nullable=True)
    created_at     = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at     = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                               onupdate=datetime.utcnow)

    comments = db.relationship("Comment", backref="post", lazy="dynamic",
                               cascade="all, delete-orphan")

    @property
    def effectively_pinned(self):
        if not self.is_pinned:
            return False
        if self.pin_expires_at and self.pin_expires_at < datetime.utcnow():
            return False
        return True

    def to_dict(self, include_comments=False):
        d = {
            "id":             self.id,
            "title":          self.title,
            "body":           self.body,
            "author_id":      self.author_id,
            "author":         self.author_user.username if self.author_user else None,
            "is_pinned":      self.effectively_pinned,
            "pin_expires_at": self.pin_expires_at.isoformat() if self.pin_expires_at else None,
            "comment_count":  self.comments.count(),
            "created_at":     self.created_at.isoformat(),
            "updated_at":     self.updated_at.isoformat(),
        }
        if include_comments:
            d["comments"] = [c.to_dict() for c in self.comments.order_by(Comment.created_at)]
        return d


class Comment(db.Model):
    __tablename__ = "comments"

    id         = db.Column(db.Integer, primary_key=True)
    body       = db.Column(db.Text,    nullable=False)
    author_id  = db.Column(db.Integer, db.ForeignKey("users.id"),      nullable=False)
    post_id    = db.Column(db.Integer, db.ForeignKey("blog_posts.id"),  nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id":         self.id,
            "body":       self.body,
            "author_id":  self.author_id,
            "author":     self.author_user.username if self.author_user else None,
            "post_id":    self.post_id,
            "created_at": self.created_at.isoformat(),
        }