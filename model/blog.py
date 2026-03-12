from datetime import datetime
from model.database import db


class BlogPost(db.Model):
    __tablename__ = "blog_posts"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    comments = db.relationship("Comment", backref="post", lazy=True, cascade="all, delete-orphan")

    def to_dict(self, include_comments=False):
        data = {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "author": self.author.username if self.author else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "comment_count": len(self.comments),
        }
        if include_comments:
            data["comments"] = [c.to_dict() for c in self.comments]
        return data


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey("blog_posts.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "body": self.body,
            "author": self.author.username if self.author else None,
            "created_at": self.created_at.isoformat(),
        }