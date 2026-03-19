"""
Blog API — posts and comments.

SRP: Lookup, creation, ownership checks are separate functions.
Orchestrator: Routes chain helpers in sequence.
Error handling: @handle_errors on every route.
"""

from flask import Blueprint, jsonify

from model.database import db
from model.blog import BlogPost, Comment
from api.utils import (
    APIError, handle_errors, require_json, require_fields,
    require_auth, require_owner_or_admin,
)

blog_bp = Blueprint("blog", __name__)


# ── Single-responsibility helpers ──

def get_all_posts():
    """Fetch all blog posts, newest first."""
    return BlogPost.query.order_by(BlogPost.created_at.desc()).all()


def get_post_or_404(post_id):
    """Fetch a single post by ID or raise APIError."""
    post = BlogPost.query.get(post_id)
    if not post:
        raise APIError("Post not found", 404)
    return post


def get_comment_or_404(comment_id):
    """Fetch a single comment by ID or raise APIError."""
    comment = Comment.query.get(comment_id)
    if not comment:
        raise APIError("Comment not found", 404)
    return comment


def create_blog_post(title, body, author_id):
    """Create and persist a new blog post."""
    post = BlogPost(title=title, body=body, author_id=author_id)
    db.session.add(post)
    db.session.commit()
    return post


def apply_post_updates(post, data):
    """Apply partial updates to an existing post."""
    if "title" in data:
        post.title = data["title"]
    if "body" in data:
        post.body = data["body"]


def create_comment_on_post(post_id, body, author_id):
    """Create and persist a new comment on a post."""
    comment = Comment(body=body, author_id=author_id, post_id=post_id)
    db.session.add(comment)
    db.session.commit()
    return comment


# ── Orchestrator routes ──

@blog_bp.route("/posts", methods=["GET"])
@handle_errors
def list_posts():
    """Orchestrator: fetch all → respond."""
    posts = get_all_posts()
    return jsonify([p.to_dict() for p in posts])


@blog_bp.route("/posts/<int:post_id>", methods=["GET"])
@handle_errors
def get_post(post_id):
    """Orchestrator: fetch post → respond with comments."""
    post = get_post_or_404(post_id)
    return jsonify(post.to_dict(include_comments=True))


@blog_bp.route("/posts", methods=["POST"])
@handle_errors
def create_post():
    """Orchestrator: require auth → parse body → validate → create → respond."""
    user = require_auth()
    data = require_json()
    require_fields(data, "title", "body")
    post = create_blog_post(data["title"], data["body"], user.id)
    return jsonify(post.to_dict()), 201


@blog_bp.route("/posts/<int:post_id>", methods=["PUT"])
@handle_errors
def update_post(post_id):
    """Orchestrator: fetch post → check ownership → parse body → update → respond."""
    post = get_post_or_404(post_id)
    require_owner_or_admin(post.author_id)
    data = require_json()
    apply_post_updates(post, data)
    db.session.commit()
    return jsonify(post.to_dict())


@blog_bp.route("/posts/<int:post_id>", methods=["DELETE"])
@handle_errors
def delete_post(post_id):
    """Orchestrator: fetch post → check ownership → delete → respond."""
    post = get_post_or_404(post_id)
    require_owner_or_admin(post.author_id)
    db.session.delete(post)
    db.session.commit()
    return jsonify({"message": "Post deleted"})


@blog_bp.route("/posts/<int:post_id>/comments", methods=["POST"])
@handle_errors
def add_comment(post_id):
    """Orchestrator: require auth → verify post exists → parse body → create → respond."""
    user = require_auth()
    get_post_or_404(post_id)
    data = require_json()
    require_fields(data, "body")
    comment = create_comment_on_post(post_id, data["body"], user.id)
    return jsonify(comment.to_dict()), 201


@blog_bp.route("/comments/<int:comment_id>", methods=["DELETE"])
@handle_errors
def delete_comment(comment_id):
    """Orchestrator: fetch comment → check ownership → delete → respond."""
    comment = get_comment_or_404(comment_id)
    require_owner_or_admin(comment.author_id)
    db.session.delete(comment)
    db.session.commit()
    return jsonify({"message": "Comment deleted"})