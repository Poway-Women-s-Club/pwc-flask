"""
Friends API — friend requests and connections.

A friendship starts as a pending request (requester → addressee).
The addressee can accept or decline.  Once accepted both users are
"friends" and can DM each other.

Endpoints:
  GET  /api/friends                     — list accepted friends
  GET  /api/friends/requests            — incoming pending requests
  GET  /api/friends/status/<user_id>    — friendship status with a user
  POST /api/friends/request/<user_id>   — send a friend request
  POST /api/friends/accept/<user_id>    — accept a request from user_id
  POST /api/friends/decline/<user_id>   — decline a request from user_id
  DELETE /api/friends/<user_id>         — unfriend (remove accepted friendship)
"""

from datetime import datetime

from flask import Blueprint, jsonify

from model.database import db
from model.user import User
from model.friendship import Friendship
from api.utils import APIError, handle_errors, require_auth

friends_bp = Blueprint("friends", __name__)


# ── Single-responsibility helpers ──

def get_user_or_404(user_id):
    user = User.query.get(user_id)
    if not user:
        raise APIError("User not found", 404)
    return user


def find_friendship(user_a_id, user_b_id):
    """Return the Friendship row for this pair (either direction), or None."""
    return Friendship.query.filter(
        db.or_(
            db.and_(Friendship.requester_id == user_a_id, Friendship.addressee_id == user_b_id),
            db.and_(Friendship.requester_id == user_b_id, Friendship.addressee_id == user_a_id),
        )
    ).first()


def are_friends(user_a_id, user_b_id):
    """Return True if there is an accepted friendship between the two users."""
    f = find_friendship(user_a_id, user_b_id)
    return f is not None and f.status == "accepted"


def get_friend_ids(user_id):
    """Return the set of user IDs that are accepted friends of user_id."""
    rows = Friendship.query.filter(
        db.or_(
            Friendship.requester_id == user_id,
            Friendship.addressee_id == user_id,
        ),
        Friendship.status == "accepted",
    ).all()
    ids = set()
    for f in rows:
        ids.add(f.addressee_id if f.requester_id == user_id else f.requester_id)
    return ids


def friendship_status_for(current_user_id, other_id):
    """
    Return a status string from the perspective of current_user_id:
      none | pending_sent | pending_received | accepted | declined
    """
    f = find_friendship(current_user_id, other_id)
    if not f:
        return "none"
    if f.status == "accepted":
        return "accepted"
    if f.status == "declined":
        return "declined"
    # pending — which direction?
    if f.requester_id == current_user_id:
        return "pending_sent"
    return "pending_received"


# ── Orchestrator routes ──

@friends_bp.route("", methods=["GET"])
@handle_errors
def list_friends():
    """Return all accepted friends of the current user."""
    user = require_auth()
    friend_ids = get_friend_ids(user.id)
    friends = User.query.filter(User.id.in_(friend_ids)).all() if friend_ids else []
    return jsonify([u.to_dict() for u in friends])


@friends_bp.route("/requests", methods=["GET"])
@handle_errors
def list_requests():
    """Return pending incoming friend requests for the current user."""
    user = require_auth()
    pending = Friendship.query.filter_by(addressee_id=user.id, status="pending").all()
    result = []
    for f in pending:
        requester = User.query.get(f.requester_id)
        if requester:
            result.append({
                "friendship": f.to_dict(),
                "user": requester.to_dict(),
            })
    return jsonify(result)


@friends_bp.route("/status/<int:other_id>", methods=["GET"])
@handle_errors
def friendship_status(other_id):
    """Return the friendship status between the current user and other_id."""
    user = require_auth()
    get_user_or_404(other_id)
    status = friendship_status_for(user.id, other_id)
    return jsonify({"status": status})


@friends_bp.route("/request/<int:other_id>", methods=["POST"])
@handle_errors
def send_request(other_id):
    """Send a friend request to other_id."""
    user = require_auth()
    other = get_user_or_404(other_id)

    if other.id == user.id:
        raise APIError("Cannot send a friend request to yourself", 400)

    existing = find_friendship(user.id, other.id)
    if existing:
        if existing.status == "accepted":
            raise APIError("Already friends", 400)
        if existing.status == "pending":
            return jsonify(existing.to_dict()), 200
        if existing.status == "declined":
            # Allow re-requesting by resetting the row
            existing.requester_id = user.id
            existing.addressee_id = other.id
            existing.status = "pending"
            existing.updated_at = datetime.utcnow()
            db.session.commit()
            return jsonify(existing.to_dict()), 200

    f = Friendship(requester_id=user.id, addressee_id=other.id)
    db.session.add(f)
    db.session.commit()
    return jsonify(f.to_dict()), 201


@friends_bp.route("/accept/<int:other_id>", methods=["POST"])
@handle_errors
def accept_request(other_id):
    """Accept a pending friend request from other_id."""
    user = require_auth()
    get_user_or_404(other_id)

    f = Friendship.query.filter_by(requester_id=other_id, addressee_id=user.id, status="pending").first()
    if not f:
        raise APIError("No pending request from that user", 404)

    f.status = "accepted"
    f.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(f.to_dict())


@friends_bp.route("/decline/<int:other_id>", methods=["POST"])
@handle_errors
def decline_request(other_id):
    """Decline a pending friend request from other_id."""
    user = require_auth()
    get_user_or_404(other_id)

    f = Friendship.query.filter_by(requester_id=other_id, addressee_id=user.id, status="pending").first()
    if not f:
        raise APIError("No pending request from that user", 404)

    f.status = "declined"
    f.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify(f.to_dict())


@friends_bp.route("/search", methods=["GET"])
@handle_errors
def search_users():
    """Search users by username prefix/substring. Returns up to 20 results with friendship status."""
    from flask import request
    user = require_auth()
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    matches = User.query.filter(
        User.username.ilike(f"%{q}%"),
        User.id != user.id,
    ).limit(20).all()
    result = []
    for u in matches:
        status = friendship_status_for(user.id, u.id)
        result.append({**u.to_dict(), "friendship_status": status})
    return jsonify(result)


@friends_bp.route("/<int:other_id>", methods=["DELETE"])
@handle_errors
def unfriend(other_id):
    """Remove an accepted friendship with other_id."""
    user = require_auth()
    f = find_friendship(user.id, other_id)
    if not f or f.status != "accepted":
        raise APIError("Not friends with that user", 404)
    db.session.delete(f)
    db.session.commit()
    return jsonify({"message": "Friendship removed"})
