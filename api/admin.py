"""
Admin API — dashboard stats and user management.

SRP: Stats aggregation, user lookup, and role changes are separate.
Orchestrator: Routes chain helpers.
Error handling: @handle_errors on every route, uses require_admin from utils.
"""

from flask import Blueprint, jsonify

from model.database import db
from model.user import User
from model.event import Event
from model.blog import BlogPost
from model.payment import Payment
from api.utils import (
    APIError, handle_errors, require_json, require_admin,
)

admin_bp = Blueprint("admin", __name__)


# ── Single-responsibility helpers ──

def aggregate_stats():
    """Gather dashboard statistics from all models."""
    return {
        "users": User.query.count(),
        "active_members": User.query.filter_by(is_active_member=True).count(),
        "events": Event.query.count(),
        "posts": BlogPost.query.count(),
        "payments_total": db.session.query(
            db.func.sum(Payment.amount_cents)
        ).filter_by(status="completed").scalar() or 0,
    }


def get_user_or_404(user_id):
    """Fetch a user by ID or raise APIError."""
    user = User.query.get(user_id)
    if not user:
        raise APIError("User not found", 404)
    return user


def apply_user_updates(user, data):
    """Apply role and membership changes to a user."""
    if "role" in data and data["role"] in ("member", "admin"):
        user.role = data["role"]
    if "is_active_member" in data:
        user.is_active_member = bool(data["is_active_member"])


def check_not_self_delete(admin_user, target_user):
    """Prevent an admin from deleting their own account."""
    if admin_user.id == target_user.id:
        raise APIError("Cannot delete yourself", 400)


# ── Orchestrator routes ──

@admin_bp.route("/stats", methods=["GET"])
@handle_errors
def stats():
    """Orchestrator: require admin → aggregate → respond."""
    require_admin()
    return jsonify(aggregate_stats())


@admin_bp.route("/users", methods=["GET"])
@handle_errors
def list_users():
    """Orchestrator: require admin → query all users → respond."""
    require_admin()
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify([u.to_dict() for u in users])


@admin_bp.route("/users/<int:user_id>", methods=["PUT"])
@handle_errors
def update_user(user_id):
    """Orchestrator: require admin → fetch user → parse body → apply updates → respond."""
    require_admin()
    user = get_user_or_404(user_id)
    data = require_json()
    apply_user_updates(user, data)
    db.session.commit()
    return jsonify(user.to_dict())


@admin_bp.route("/users/<int:user_id>", methods=["DELETE"])
@handle_errors
def delete_user(user_id):
    """Orchestrator: require admin → fetch user → safety check → delete → respond."""
    admin = require_admin()
    user = get_user_or_404(user_id)
    check_not_self_delete(admin, user)
    db.session.delete(user)
    db.session.commit()
    return jsonify({"message": "User deleted"})