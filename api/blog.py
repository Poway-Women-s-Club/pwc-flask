from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from model.database import db
from model.blog import BlogPost, Comment

blog_bp = Blueprint("blog", __name__)


@blog_bp.route("/posts", methods=["GET"])
def list_posts():
    posts = BlogPost.query.order_by(BlogPost.created_at.desc()).all()
    return jsonify([p.to_dict() for p in posts])


@blog_bp.route("/posts/<int:post_id>", methods=["GET"])
def get_post(post_id):
    post = BlogPost.query.get_or_404(post_id)
    return jsonify(post.to_dict(include_comments=True))


@blog_bp.route("/posts", methods=["POST"])
@login_required
def create_post():
    data = request.get_json()
    if not data or not data.get("title") or not data.get("body"):
        return jsonify({"error": "Title and body required"}), 400

    post = BlogPost(
        title=data["title"],
        body=data["body"],
        author_id=current_user.id,
    )
    db.session.add(post)
    db.session.commit()
    return jsonify(post.to_dict()), 201


@blog_bp.route("/posts/<int:post_id>", methods=["PUT"])
@login_required
def update_post(post_id):
    post = BlogPost.query.get_or_404(post_id)
    if post.author_id != current_user.id and current_user.role != "admin":
        return jsonify({"error": "Not authorized"}), 403

    data = request.get_json()
    if "title" in data:
        post.title = data["title"]
    if "body" in data:
        post.body = data["body"]

    db.session.commit()
    return jsonify(post.to_dict())


@blog_bp.route("/posts/<int:post_id>", methods=["DELETE"])
@login_required
def delete_post(post_id):
    post = BlogPost.query.get_or_404(post_id)
    if post.author_id != current_user.id and current_user.role != "admin":
        return jsonify({"error": "Not authorized"}), 403

    db.session.delete(post)
    db.session.commit()
    return jsonify({"message": "Post deleted"})


# --- Comments ---

@blog_bp.route("/posts/<int:post_id>/comments", methods=["POST"])
@login_required
def create_comment(post_id):
    BlogPost.query.get_or_404(post_id)
    data = request.get_json()
    if not data or not data.get("body"):
        return jsonify({"error": "Body required"}), 400

    comment = Comment(
        body=data["body"],
        author_id=current_user.id,
        post_id=post_id,
    )
    db.session.add(comment)
    db.session.commit()
    return jsonify(comment.to_dict()), 201


@blog_bp.route("/comments/<int:comment_id>", methods=["DELETE"])
@login_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.author_id != current_user.id and current_user.role != "admin":
        return jsonify({"error": "Not authorized"}), 403

    db.session.delete(comment)
    db.session.commit()
    return jsonify({"message": "Comment deleted"})