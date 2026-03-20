"""
Blog API — posts and comments.

SRP: Lookup, creation, ownership checks are separate functions.
Orchestrator: Routes chain helpers in sequence.
Error handling: @handle_errors on every route.
"""

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from model.database import db
from model.blog import BlogPost, Comment
from api.utils import (
    APIError, handle_errors, require_json, require_fields,
    require_auth, require_admin, require_owner_or_admin,
)

blog_bp = Blueprint("blog", __name__)


# ── Single-responsibility helpers ──

def build_post_query(args):
    """Build a filtered, sorted query from request args."""
    q = BlogPost.query

    # Search by title or body
    search = args.get("search", "").strip()
    if search:
        pattern = f"%{search}%"
        q = q.filter(db.or_(
            BlogPost.title.ilike(pattern),
            BlogPost.body.ilike(pattern),
        ))

    # Filter by author username
    author = args.get("author", "").strip()
    if author:
        from model.user import User
        user = User.query.filter_by(username=author).first()
        if user:
            q = q.filter_by(author_id=user.id)
        else:
            q = q.filter(db.false())

    # Filter pinned only
    if args.get("pinned") == "true":
        now = datetime.utcnow()
        q = q.filter(
            BlogPost.is_pinned == True,
            db.or_(
                BlogPost.pin_expires_at.is_(None),
                BlogPost.pin_expires_at > now,
            ),
        )

    # Sort: pinned first, then newest
    now = datetime.utcnow()
    q = q.order_by(
        db.case(
            (db.and_(
                BlogPost.is_pinned == True,
                db.or_(
                    BlogPost.pin_expires_at.is_(None),
                    BlogPost.pin_expires_at > now,
                ),
            ), 0),
            else_=1,
        ),
        BlogPost.created_at.desc(),
    )

    return q


def paginate_query(query, args):
    """Apply pagination and return (items, total, page, per_page)."""
    page = max(int(args.get("page", 1)), 1)
    per_page = min(max(int(args.get("per_page", 10)), 1), 50)
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return items, total, page, per_page


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
    """Orchestrator: build query → paginate → respond."""
    query = build_post_query(request.args)
    items, total, page, per_page = paginate_query(query, request.args)
    return jsonify({
        "posts": [p.to_dict() for p in items],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    })


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


@blog_bp.route("/posts/<int:post_id>/pin", methods=["POST"])
@handle_errors
def pin_post(post_id):
    """Admin only: pin a post, optionally for a duration (days)."""
    require_admin()
    post = get_post_or_404(post_id)
    data = request.get_json(silent=True) or {}
    days = data.get("days")
    post.is_pinned = True
    if days and int(days) > 0:
        post.pin_expires_at = datetime.utcnow() + timedelta(days=int(days))
    else:
        post.pin_expires_at = None
    db.session.commit()
    return jsonify(post.to_dict())


@blog_bp.route("/posts/<int:post_id>/pin", methods=["DELETE"])
@handle_errors
def unpin_post(post_id):
    """Admin only: unpin a post."""
    require_admin()
    post = get_post_or_404(post_id)
    post.is_pinned = False
    post.pin_expires_at = None
    db.session.commit()
    return jsonify(post.to_dict())


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
