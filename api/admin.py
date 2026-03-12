from functools import wraps
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from model.database import db
from model.user import User
from model.event import Event
from model.blog import BlogPost
from model.payment import Payment

admin_bp = Blueprint("admin", __name__)


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/stats", methods=["GET"])
@admin_required
def stats():
    return jsonify({
        "users": User.query.count(),
        "active_members": User.query.filter_by(is_active_member=True).count(),
        "events": Event.query.count(),
        "posts": BlogPost.query.count(),
        "payments_total": db.session.query(db.func.sum(Payment.amount_cents)).filter_by(status="completed").scalar() or 0,
    })


@admin_bp.route("/users", methods=["GET"])
@admin_required
def list_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify([u.to_dict() for u in users])


@admin_bp.route("/users/<int:user_id>", methods=["PUT"])
@admin_required
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json()

    if "role" in data and data["role"] in ("member", "admin"):
        user.role = data["role"]
    if "is_active_member" in data:
        user.is_active_member = bool(data["is_active_member"])

    db.session.commit()
    return jsonify(user.to_dict())


@admin_bp.route("/users/<int:user_id>", methods=["DELETE"])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        return jsonify({"error": "Cannot delete yourself"}), 400
    db.session.delete(user)
    db.session.commit()
    return jsonify({"message": "User deleted"})