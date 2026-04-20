"""
Blog API — posts and comments.

SRP: Lookup, creation, ownership checks are separate functions.
Orchestrator: Routes chain helpers in sequence.
Error handling: @handle_errors on every route.
"""

from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request
from flask_login import current_user

from model.database import db
from model.blog import BlogPost, Comment
from model.group import UserGroup
from api.utils import (
    APIError, handle_errors, require_json, require_fields,
    require_auth, require_admin, require_owner_or_admin,
)

blog_bp = Blueprint("blog", __name__)


# ── Single-responsibility helpers ──

def get_visible_group_ids():
    """Return set of group IDs the current user belongs to (empty if not logged in)."""
    if not current_user.is_authenticated:
        return set()
    memberships = UserGroup.query.filter_by(user_id=current_user.id).all()
    return {m.group_id for m in memberships}


def build_post_query(args):
    """Build a filtered, sorted query from request args."""
    q = BlogPost.query

    # Group visibility: hide group-exclusive posts unless user is a member
    user_group_ids = get_visible_group_ids()
    if user_group_ids:
        q = q.filter(db.or_(
            BlogPost.group_id.is_(None),
            BlogPost.group_id.in_(user_group_ids),
        ))
    else:
        q = q.filter(BlogPost.group_id.is_(None))

    # Filter by group
    group_id = args.get("group_id", "").strip()
    if group_id:
        q = q.filter(BlogPost.group_id == int(group_id))

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

    # Sort: pinned always first, then by requested sort order
    from sqlalchemy import func
    sort = args.get("sort", "newest")

    if sort == "oldest":
        secondary_sort = BlogPost.created_at.asc()
    elif sort == "popular":
        comment_count_subq = (
            db.session.query(func.count(Comment.id))
            .filter(Comment.post_id == BlogPost.id)
            .correlate(BlogPost)
            .scalar_subquery()
        )
        secondary_sort = comment_count_subq.desc()
    elif sort == "az":
        secondary_sort = BlogPost.title.asc()
    elif sort == "za":
        secondary_sort = BlogPost.title.desc()
    else:  # newest (default)
        secondary_sort = BlogPost.created_at.desc()

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
        secondary_sort,
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


def create_blog_post(title, body, author_id, group_id=None):
    """Create and persist a new blog post."""
    post = BlogPost(title=title, body=body, author_id=author_id, group_id=group_id)
    db.session.add(post)
    db.session.commit()
    return post


def apply_post_updates(post, data):
    """Apply partial updates to an existing post."""
    if "title" in data:
        post.title = data["title"]
    if "body" in data:
        post.body = data["body"]
    if "group_id" in data:
        post.group_id = data["group_id"] or None


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
    group_id = data.get("group_id") or None
    if group_id:
        group_id = int(group_id)
        from model.group import Group
        grp = Group.query.get(group_id)
        if not grp:
            raise APIError("Group not found", 404)
    post = create_blog_post(data["title"], data["body"], user.id, group_id=group_id)
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
