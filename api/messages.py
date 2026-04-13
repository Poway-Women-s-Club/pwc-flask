"""
Messages API — direct messages between members.

SRP: Conversation lookup, message creation, and read-marking are separate.
Orchestrator: Routes chain helpers.
Error handling: @handle_errors on every route.

Endpoints:
  GET  /api/messages/conversations        — list all conversations for current user
  GET  /api/messages/conversations/<id>   — messages with a specific user
  POST /api/messages/conversations/<id>   — send a message to a user
  POST /api/messages/conversations/<id>/read — mark all messages from user as read
"""

from flask import Blueprint, jsonify, request
from datetime import datetime

from model.database import db
from model.user import User
from model.message import Message
from api.utils import (
    APIError, handle_errors, require_json, require_fields, require_auth,
)
from api.friends import are_friends

messages_bp = Blueprint("messages", __name__)


# ── Single-responsibility helpers ──

def get_other_user_or_404(user_id):
    """Fetch the other participant by ID or raise APIError."""
    user = User.query.get(user_id)
    if not user:
        raise APIError("User not found", 404)
    return user


def get_thread(user_a_id, user_b_id, since=None):
    """Fetch all messages between two users, oldest first. Optionally only messages after `since` (datetime)."""
    q = (
        Message.query
        .filter(
            db.or_(
                db.and_(Message.sender_id == user_a_id, Message.recipient_id == user_b_id),
                db.and_(Message.sender_id == user_b_id, Message.recipient_id == user_a_id),
            )
        )
    )
    if since:
        q = q.filter(Message.created_at > since)
    return q.order_by(Message.created_at.asc()).all()


def get_latest_message(user_a_id, user_b_id):
    """Fetch just the most recent message between two users."""
    return (
        Message.query
        .filter(
            db.or_(
                db.and_(Message.sender_id == user_a_id, Message.recipient_id == user_b_id),
                db.and_(Message.sender_id == user_b_id, Message.recipient_id == user_a_id),
            )
        )
        .order_by(Message.created_at.desc())
        .first()
    )


def count_unread_from(reader_id, sender_id):
    """Count unread messages sent by sender_id to reader_id."""
    return (
        Message.query
        .filter_by(sender_id=sender_id, recipient_id=reader_id, read_at=None)
        .count()
    )


def build_conversation_list(current_user_id):
    """
    Return a list of conversation summaries — one per unique partner —
    sorted by the timestamp of the most recent message (newest first).
    """
    # Find all distinct users this person has exchanged messages with
    sent_to = db.session.query(Message.recipient_id).filter_by(sender_id=current_user_id)
    received_from = db.session.query(Message.sender_id).filter_by(recipient_id=current_user_id)

    partner_ids = {row[0] for row in sent_to.union(received_from).all()}

    conversations = []
    for pid in partner_ids:
        partner = User.query.get(pid)
        if not partner:
            continue
        latest  = get_latest_message(current_user_id, pid)
        unread  = count_unread_from(current_user_id, pid)
        conversations.append({
            "user":         partner.to_dict(),
            "last_message": latest.to_dict() if latest else None,
            "unread_count": unread,
        })

    conversations.sort(
        key=lambda c: c["last_message"]["created_at"] if c["last_message"] else "",
        reverse=True,
    )
    return conversations


def create_message(sender_id, recipient_id, body):
    """Persist a new message and return it."""
    msg = Message(sender_id=sender_id, recipient_id=recipient_id, body=body.strip())
    db.session.add(msg)
    db.session.commit()
    return msg


def mark_thread_as_read(reader_id, sender_id):
    """Mark all messages from sender_id to reader_id as read."""
    now = datetime.utcnow()
    (
        Message.query
        .filter_by(sender_id=sender_id, recipient_id=reader_id, read_at=None)
        .update({"read_at": now})
    )
    db.session.commit()


# ── Orchestrator routes ──

@messages_bp.route("/conversations", methods=["GET"])
@handle_errors
def list_conversations():
    """Orchestrator: require auth → build conversation list → respond."""
    user = require_auth()
    convos = build_conversation_list(user.id)
    return jsonify(convos)


@messages_bp.route("/conversations/<int:other_id>", methods=["GET"])
@handle_errors
def get_conversation(other_id):
    """Orchestrator: require auth → verify partner exists → check friends → fetch thread → respond.

    Optional query param: ?since=<ISO-8601 datetime> — returns only messages after that timestamp.
    Use this for polling: pass the created_at of the last known message to fetch only new ones.
    """
    user  = require_auth()
    other = get_other_user_or_404(other_id)
    if not are_friends(user.id, other.id):
        raise APIError("You must be friends to view this conversation", 403)

    since = None
    since_str = request.args.get("since")
    if since_str:
        try:
            since = datetime.fromisoformat(since_str.replace("Z", "+00:00"))
        except ValueError:
            raise APIError("Invalid 'since' timestamp — use ISO-8601 format", 400)

    msgs = get_thread(user.id, other.id, since=since)
    return jsonify({
        "partner":  other.to_dict(),
        "messages": [m.to_dict() for m in msgs],
    })


@messages_bp.route("/conversations/<int:other_id>", methods=["POST"])
@handle_errors
def send_message(other_id):
    """Orchestrator: require auth → verify partner → check friends → parse body → create → respond."""
    user  = require_auth()
    other = get_other_user_or_404(other_id)
    if other.id == user.id:
        raise APIError("Cannot send a message to yourself", 400)
    if not are_friends(user.id, other.id):
        raise APIError("You must be friends to send a message", 403)
    data = require_json()
    require_fields(data, "body")
    msg = create_message(user.id, other.id, data["body"])
    return jsonify(msg.to_dict()), 201


@messages_bp.route("/conversations/<int:other_id>/read", methods=["POST"])
@handle_errors
def mark_read(other_id):
    """Orchestrator: require auth → verify partner → mark read → respond."""
    user  = require_auth()
    get_other_user_or_404(other_id)
    mark_thread_as_read(user.id, other_id)
    return jsonify({"message": "Marked as read"})


@messages_bp.route("/unread", methods=["GET"])
@handle_errors
def unread_count():
    """Return total number of unread messages for the current user."""
    user = require_auth()
    count = Message.query.filter_by(recipient_id=user.id, read_at=None).count()
    return jsonify({"unread": count})