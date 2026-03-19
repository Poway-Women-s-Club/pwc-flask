"""
Events API — list, get, create, update, delete, RSVP.

SRP: Query, creation, update, and RSVP logic are separate functions.
Orchestrator: Routes chain helpers in sequence.
Error handling: @handle_errors on every route.
"""

from flask import Blueprint, request, jsonify
from flask_login import current_user
from datetime import datetime

from model.database import db
from model.event import Event, RSVP
from api.utils import (
    APIError, handle_errors, require_json, require_fields,
    require_auth, require_admin,
)

events_bp = Blueprint("events", __name__)


# ── Single-responsibility helpers ──

def query_events(upcoming_only):
    """Fetch events, optionally filtering to upcoming only."""
    query = Event.query
    if upcoming_only:
        query = query.filter(Event.start_time >= datetime.utcnow())
    return query.order_by(Event.start_time.asc()).all()


def get_event_or_404(event_id):
    """Fetch a single event by ID or raise APIError."""
    event = Event.query.get(event_id)
    if not event:
        raise APIError("Event not found", 404)
    return event


def parse_datetime(value, field_name):
    """Parse an ISO datetime string, raising APIError on bad format."""
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise APIError(f"Invalid datetime format for {field_name}", 400)


def build_event(data, creator_id):
    """Create an Event object from validated data."""
    return Event(
        title=data["title"],
        description=data.get("description", ""),
        location=data.get("location", ""),
        start_time=parse_datetime(data["start_time"], "start_time"),
        end_time=parse_datetime(data["end_time"], "end_time") if data.get("end_time") else None,
        created_by=creator_id,
    )


def apply_event_updates(event, data):
    """Apply partial updates to an existing event."""
    if "title" in data:
        event.title = data["title"]
    if "description" in data:
        event.description = data["description"]
    if "location" in data:
        event.location = data["location"]
    if "start_time" in data:
        event.start_time = parse_datetime(data["start_time"], "start_time")
    if "end_time" in data:
        event.end_time = parse_datetime(data["end_time"], "end_time") if data["end_time"] else None


def check_existing_rsvp(user_id, event_id):
    """Return existing RSVP or None."""
    return RSVP.query.filter_by(user_id=user_id, event_id=event_id).first()


# ── Orchestrator routes ──

@events_bp.route("/", methods=["GET"])
@handle_errors
def list_events():
    """Orchestrator: parse query param → query → respond."""
    upcoming = request.args.get("upcoming", "true").lower() == "true"
    events = query_events(upcoming)
    return jsonify([e.to_dict() for e in events])


@events_bp.route("/<int:event_id>", methods=["GET"])
@handle_errors
def get_event(event_id):
    """Orchestrator: fetch event → check RSVP status if logged in → respond."""
    event = get_event_or_404(event_id)
    data = event.to_dict()
    if current_user.is_authenticated:
        data["user_rsvped"] = check_existing_rsvp(current_user.id, event_id) is not None
    return jsonify(data)


@events_bp.route("/", methods=["POST"])
@handle_errors
def create_event():
    """Orchestrator: require admin → parse body → validate → build → save → respond."""
    admin = require_admin()
    data = require_json()
    require_fields(data, "title", "start_time")
    event = build_event(data, admin.id)
    db.session.add(event)
    db.session.commit()
    return jsonify(event.to_dict()), 201


@events_bp.route("/<int:event_id>", methods=["PUT"])
@handle_errors
def update_event(event_id):
    """Orchestrator: require admin → fetch event → parse body → apply updates → respond."""
    require_admin()
    event = get_event_or_404(event_id)
    data = require_json()
    apply_event_updates(event, data)
    db.session.commit()
    return jsonify(event.to_dict())


@events_bp.route("/<int:event_id>", methods=["DELETE"])
@handle_errors
def delete_event(event_id):
    """Orchestrator: require admin → fetch event → delete → respond."""
    require_admin()
    event = get_event_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    return jsonify({"message": "Event deleted"})


@events_bp.route("/<int:event_id>/rsvp", methods=["POST"])
@handle_errors
def rsvp(event_id):
    """Orchestrator: require auth → verify event exists → check duplicate → create RSVP."""
    user = require_auth()
    get_event_or_404(event_id)
    if check_existing_rsvp(user.id, event_id):
        return jsonify({"message": "Already RSVPed"}), 200
    new_rsvp = RSVP(user_id=user.id, event_id=event_id)
    db.session.add(new_rsvp)
    db.session.commit()
    return jsonify({"message": "RSVPed"}), 201


@events_bp.route("/<int:event_id>/rsvp", methods=["DELETE"])
@handle_errors
def cancel_rsvp(event_id):
    """Orchestrator: require auth → find RSVP → delete → respond."""
    user = require_auth()
    existing = check_existing_rsvp(user.id, event_id)
    if not existing:
        raise APIError("No RSVP found", 404)
    db.session.delete(existing)
    db.session.commit()
    return jsonify({"message": "RSVP cancelled"})