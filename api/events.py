"""
Events API — list, get, create, update, delete, RSVP.

SRP: Query, creation, update, and RSVP logic are separate functions.
Orchestrator: Routes chain helpers in sequence.
Error handling: @handle_errors on every route.
"""

import os
import secrets

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timezone

from model.database import db
from model.event import Event, RSVP, PublicRSVP, MeetingRequest, EventVisibleGroup
from model.user import User
from model.group import UserGroup, Group
from api.utils import (
    APIError, handle_errors, require_json, require_fields,
    require_auth, require_admin,
)

events_bp = Blueprint("events", __name__)

ALLOWED_ATTENDANCE = {"yes", "no", "maybe"}


def _default_event_capacity():
    try:
        return int(os.environ.get("DEFAULT_EVENT_MAX_ATTENDEES", "25"))
    except (TypeError, ValueError):
        return 25


def _recurring_capacity():
    try:
        return int(os.environ.get("RECURRING_EVENT_MAX_ATTENDEES", "30"))
    except (TypeError, ValueError):
        return 30


def _seats_used_for_event(event_id):
    logged_in_count = RSVP.query.filter_by(event_id=event_id).count()
    public_yes_count = (
        PublicRSVP.query.filter_by(event_id=event_id)
        .filter(PublicRSVP.attendance == "yes")
        .count()
    )
    return logged_in_count + public_yes_count


def _parse_iso_datetime(value):
    """
    Accepts:
    - ISO strings like 2026-04-14T17:00:00Z
    - ISO strings without Z
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if not s:
        return None
    try:
        # Python doesn't like trailing 'Z' in fromisoformat
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _normalize_utc_naive(dt):
    """
    SQLite + SQLAlchemy DateTime columns are effectively naive in this project.
    Normalize incoming datetimes to UTC and drop tzinfo so equality queries work.
    """
    if dt is None:
        return None
    try:
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc)
        return dt.replace(tzinfo=None)
    except Exception:
        return dt.replace(tzinfo=None)


def _get_payload():
    # Prefer JSON if present, otherwise use HTML form fields.
    json_data = request.get_json(silent=True)
    if isinstance(json_data, dict) and json_data:
        return json_data
    return request.form.to_dict()


# ── Single-responsibility helpers ──

def query_events(upcoming_only):
    """Fetch events, optionally filtering to upcoming only."""
    query = Event.query
    if upcoming_only:
        query = query.filter(Event.start_time >= datetime.utcnow())
    events = query.order_by(Event.start_time.asc()).all()

    # Visibility filter:
    # - admin sees all
    # - anonymous sees only club-wide
    # - member sees club-wide + events visible to their groups
    if current_user.is_authenticated and getattr(current_user, "role", "") == "admin":
        return events
    if not current_user.is_authenticated:
        return [e for e in events if (e.visibility_scope or "club") != "groups"]

    my_group_ids = {
        row.group_id for row in UserGroup.query.filter_by(user_id=current_user.id).all()
    }
    filtered = []
    for e in events:
        scope = e.visibility_scope or "club"
        if scope != "groups":
            filtered.append(e)
            continue
        allowed_group_ids = {vg.group_id for vg in e.visible_groups.all()}
        if allowed_group_ids.intersection(my_group_ids):
            filtered.append(e)
    return filtered


def get_event_or_404(event_id):
    """Fetch a single event by ID or raise APIError."""
    event = Event.query.get(event_id)
    if not event:
        raise APIError("Event not found", 404)
    return event


def _is_event_visible_to_user(event, user):
    scope = event.visibility_scope or "club"
    if scope != "groups":
        return True
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "role", "") == "admin":
        return True
    my_group_ids = {
        row.group_id for row in UserGroup.query.filter_by(user_id=user.id).all()
    }
    allowed_group_ids = {vg.group_id for vg in event.visible_groups.all()}
    return bool(allowed_group_ids.intersection(my_group_ids))


def _apply_event_visibility(event, data):
    # Admin-only feature; defaults to club-wide.
    scope_raw = data.get("visibility_scope")
    scope = (scope_raw or event.visibility_scope or "club").strip().lower()
    if scope not in {"club", "groups"}:
        raise APIError("visibility_scope must be 'club' or 'groups'", 400)

    group_ids = data.get("visible_group_ids") or []
    if scope == "groups":
        if not isinstance(group_ids, list):
            raise APIError("visible_group_ids must be an array", 400)
        parsed_ids = []
        for gid in group_ids:
            try:
                parsed_ids.append(int(gid))
            except (TypeError, ValueError):
                raise APIError("visible_group_ids must contain integers", 400)
        parsed_ids = sorted(set(parsed_ids))
        if not parsed_ids:
            raise APIError("At least one group is required for group visibility", 400)

        existing = Group.query.filter(Group.id.in_(parsed_ids)).all()
        existing_ids = {g.id for g in existing}
        if len(existing_ids) != len(parsed_ids):
            raise APIError("One or more group ids are invalid", 400)

        event.visibility_scope = "groups"
        EventVisibleGroup.query.filter_by(event_id=event.id).delete()
        for gid in parsed_ids:
            db.session.add(EventVisibleGroup(event_id=event.id, group_id=gid))
    else:
        event.visibility_scope = "club"
        EventVisibleGroup.query.filter_by(event_id=event.id).delete()


def parse_datetime(value, field_name):
    """Parse an ISO datetime string, raising APIError on bad format."""
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        raise APIError(f"Invalid datetime format for {field_name}", 400)


def build_event(data, creator_id):
    """Create an Event object from validated data."""
    max_attendees = data.get("max_attendees")
    if max_attendees in ("", None):
        parsed_max = None
    else:
        try:
            parsed_max = int(max_attendees)
        except (TypeError, ValueError):
            raise APIError("max_attendees must be a positive integer", 400)
        if parsed_max < 1:
            raise APIError("max_attendees must be a positive integer", 400)
    event = Event(
        title=data["title"],
        description=data.get("description", ""),
        location=data.get("location", ""),
        start_time=parse_datetime(data["start_time"], "start_time"),
        end_time=parse_datetime(data["end_time"], "end_time") if data.get("end_time") else None,
        created_by=creator_id,
        group_id=int(data["group_id"]) if data.get("group_id") else None,
        max_attendees=parsed_max,
        visibility_scope=(data.get("visibility_scope") or "club").strip().lower() or "club",
    )
    return event


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
    if "group_id" in data:
        event.group_id = int(data["group_id"]) if data["group_id"] else None
    if "max_attendees" in data:
        ma = data.get("max_attendees")
        if ma in ("", None):
            event.max_attendees = None
        else:
            try:
                parsed = int(ma)
            except (TypeError, ValueError):
                raise APIError("max_attendees must be a positive integer", 400)
            if parsed < 1:
                raise APIError("max_attendees must be a positive integer", 400)
            event.max_attendees = parsed


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
    if not _is_event_visible_to_user(event, current_user):
        raise APIError("Event not found", 404)
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
    db.session.flush()
    _apply_event_visibility(event, data)
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
    if "visibility_scope" in data or "visible_group_ids" in data:
        _apply_event_visibility(event, data)
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
    event = get_event_or_404(event_id)
    if not _is_event_visible_to_user(event, user):
        raise APIError("Not authorized for this event", 403)
    if check_existing_rsvp(user.id, event_id):
        return jsonify({"message": "Already RSVPed"}), 200
    if event.max_attendees and _seats_used_for_event(event_id) >= event.max_attendees:
        raise APIError("Event is full", 403)
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


@events_bp.route("/public-rsvp", methods=["POST"])
def public_rsvp():
    """
    Public RSVP endpoint for non-logged-in users.
    Expects either JSON or form-encoded fields:
      - event_id (optional, numeric)
      - event_title (required)
      - event_datetime (required; ISO string)
      - name (required)
      - email (required)
      - attendance (required: yes/no/maybe)
      - notes (optional)
      - event_location (optional)
    """

    data = _get_payload()

    event_title = (data.get("event_title") or "").strip()
    event_datetime_raw = (data.get("event_datetime") or "").strip()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    attendance = (data.get("attendance") or "").strip().lower()
    notes = data.get("notes")
    event_location = (data.get("event_location") or "").strip() if data.get("event_location") else None

    if not name or not email or not event_title or not event_datetime_raw or not attendance:
        return jsonify({"error": "Missing required fields"}), 400

    if attendance not in ALLOWED_ATTENDANCE:
        return jsonify({"error": "Invalid attendance value"}), 400

    event_start_time = _parse_iso_datetime(event_datetime_raw)
    if not event_start_time:
        return jsonify({"error": "Invalid event_datetime"}), 400
    event_start_time = _normalize_utc_naive(event_start_time)

    # event_id is optional; if present and parseable, we can link it.
    event_id_raw = (data.get("event_id") or "").strip()
    event_id = None
    if event_id_raw:
        try:
            event_id = int(event_id_raw)
        except ValueError:
            event_id = None

    existing = PublicRSVP.query.filter_by(
        email=email,
        event_start_time=event_start_time,
        event_title=event_title,
    ).first()

    # Enforce seat caps when RSVP is "yes".
    if event_id:
        ev = Event.query.get(event_id)
        # Group-restricted events require authenticated membership RSVP.
        if ev and (ev.visibility_scope or "club") == "groups":
            return jsonify({"error": "Login required for this event"}), 403
        if ev and ev.max_attendees:
            current = _seats_used_for_event(event_id)
            if existing and existing.attendance == "yes":
                current -= 1
            projected = current + (1 if attendance == "yes" else 0)
            if projected > ev.max_attendees:
                return jsonify({"error": "Event is full"}), 403
    else:
        # For client-generated recurring events without event_id.
        cap = _recurring_capacity()
        yes_count = (
            PublicRSVP.query.filter_by(event_title=event_title, event_start_time=event_start_time)
            .filter(PublicRSVP.attendance == "yes")
            .count()
        )
        if existing and existing.attendance == "yes":
            yes_count -= 1
        projected_recurring = yes_count + (1 if attendance == "yes" else 0)
        if projected_recurring > cap:
            return jsonify({"error": "Event is full"}), 403

    if existing:
        existing.attendance = attendance
        existing.notes = notes
        if event_location:
            existing.event_location = event_location
        if event_id:
            existing.event_id = event_id
        db.session.commit()
        return jsonify({"message": "RSVP updated"}), 200

    rsvp = PublicRSVP(
        event_id=event_id,
        name=name,
        email=email,
        attendance=attendance,
        notes=notes,
        event_title=event_title,
        event_start_time=event_start_time,
        event_location=event_location,
    )
    db.session.add(rsvp)
    db.session.commit()
    return jsonify({"message": "RSVP saved"}), 201


@events_bp.route("/meeting-request", methods=["POST"])
def meeting_request():
    """
    Public meeting request endpoint.
    Expects either JSON or form-encoded fields:
      - name (required)
      - email (required)
      - topic (required)
      - description (required)
      - preferred_datetime (start; ISO string) or preferred_start_datetime
      - preferred_end_datetime (ISO string)
      - max_attendees (optional positive integer)
    """

    data = _get_payload()

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    topic = (data.get("topic") or "").strip()
    description = (data.get("description") or "").strip()
    max_attendees_raw = data.get("max_attendees")
    visibility_scope_raw = (data.get("visibility_scope") or "club").strip().lower()
    # Keep backwards compatibility:
    # - old clients might send `preferred_datetime` only (start)
    # - new UI sends both start/end using `preferred_datetime` + `preferred_end_datetime`
    preferred_start_raw = (
        (data.get("preferred_start_datetime") or "").strip()
        if data.get("preferred_start_datetime") else None
    )
    if not preferred_start_raw:
        preferred_start_raw = (data.get("preferred_datetime") or "").strip() if data.get("preferred_datetime") else None

    preferred_end_raw = (data.get("preferred_end_datetime") or "").strip() if data.get("preferred_end_datetime") else None

    if not name or not email or not topic or not description:
        return jsonify({"error": "Missing required fields"}), 400
    if visibility_scope_raw not in {"club", "groups"}:
        return jsonify({"error": "visibility_scope must be 'club' or 'groups'"}), 400
    if visibility_scope_raw == "groups":
        # Restrict group-scoped meetings to admins only.
        if not current_user.is_authenticated or getattr(current_user, "role", "") != "admin":
            return jsonify({"error": "Admin access required for group-scoped events"}), 403

    preferred_start_dt = _parse_iso_datetime(preferred_start_raw) if preferred_start_raw else None
    preferred_end_dt = _parse_iso_datetime(preferred_end_raw) if preferred_end_raw else None

    if not preferred_start_dt or not preferred_end_dt:
        return jsonify({"error": "preferred_datetime (start) and preferred_end_datetime are required"}), 400

    if preferred_end_dt <= preferred_start_dt:
        return jsonify({"error": "preferred_end_datetime must be after preferred_datetime"}), 400

    parsed_max_attendees = None
    if max_attendees_raw not in (None, ""):
        try:
            parsed_max_attendees = int(max_attendees_raw)
        except (TypeError, ValueError):
            return jsonify({"error": "max_attendees must be a positive integer"}), 400
        if parsed_max_attendees < 1:
            return jsonify({"error": "max_attendees must be a positive integer"}), 400

    preferred_start_dt = _normalize_utc_naive(preferred_start_dt)
    preferred_end_dt = _normalize_utc_naive(preferred_end_dt)

    req = MeetingRequest(
        name=name,
        email=email,
        preferred_datetime=preferred_start_dt,
        preferred_end_datetime=preferred_end_dt,
        topic=topic,
        description=description,
    )
    db.session.add(req)
    db.session.commit()

    # Auto-create a scheduled Event so it appears on the calendar immediately.
    # (If you want admin approval instead, we can change this to a pending state.)
    admin_user = User.query.filter_by(role="admin").first()
    if not admin_user:
        return jsonify({"error": "No admin user found to create events"}), 500

    event_title = topic if topic else "Scheduled Meeting"
    event = Event(
        title=event_title,
        description=description,
        location="",
        start_time=preferred_start_dt,
        end_time=preferred_end_dt,
        created_by=admin_user.id,
        max_attendees=parsed_max_attendees if parsed_max_attendees is not None else _default_event_capacity(),
        visibility_scope=visibility_scope_raw or "club",
    )
    db.session.add(event)
    db.session.flush()
    _apply_event_visibility(event, data)
    db.session.commit()

    return jsonify({"message": "Meeting scheduled", "event": event.to_dict()}), 201


@events_bp.route("/public-rsvp-count", methods=["GET"])
def public_rsvp_count():
    """
    Returns count of public RSVPs for a specific event title + start datetime.

    Query params:
      - event_title (string)
      - event_datetime (ISO string)
    """
    event_title = (request.args.get("event_title") or "").strip()
    event_datetime_raw = (request.args.get("event_datetime") or "").strip()

    if not event_title or not event_datetime_raw:
        return jsonify({"error": "event_title and event_datetime are required"}), 400

    event_start_time = _parse_iso_datetime(event_datetime_raw)
    if not event_start_time:
        return jsonify({"error": "Invalid event_datetime"}), 400
    event_start_time = _normalize_utc_naive(event_start_time)

    count = PublicRSVP.query.filter_by(
        event_title=event_title,
        event_start_time=event_start_time,
    ).count()
    return jsonify({"attending": count}), 200


@events_bp.route("/<int:event_id>/attending-count", methods=["GET"])
def event_attending_count(event_id):
    """
    Public count endpoint: returns logged-in RSVPs + public RSVPs for the given event id.
    """
    event = get_event_or_404(event_id)
    logged_in_count = RSVP.query.filter_by(event_id=event_id).count()
    public_count = PublicRSVP.query.filter_by(event_id=event_id).count()
    seats_used = _seats_used_for_event(event_id)
    ma = event.max_attendees
    return jsonify({
        "attending": logged_in_count + public_count,
        "attending_logged_in": logged_in_count,
        "attending_public": public_count,
        "seats_used": seats_used,
        "max_attendees": ma,
        "fill_ratio": round((seats_used / ma), 4) if ma else 0.0,
        "is_full": bool(ma and seats_used >= ma),
    }), 200


@events_bp.route("/<int:event_id>/admin-test-signup", methods=["POST"])
@handle_errors
def admin_test_signup(event_id):
    """Admin-only: add synthetic public 'yes' RSVPs for testing seat fill."""
    require_admin()
    event = get_event_or_404(event_id)

    data = request.get_json(silent=True) or {}
    raw_count = data.get("count", 1)
    try:
        requested_count = int(raw_count)
    except (TypeError, ValueError):
        raise APIError("count must be an integer", 400)
    if requested_count < 1:
        raise APIError("count must be at least 1", 400)
    if requested_count > 200:
        raise APIError("count must be <= 200", 400)

    seats_used = _seats_used_for_event(event_id)
    available = None if not event.max_attendees else max(event.max_attendees - seats_used, 0)
    if event.max_attendees and available <= 0:
        raise APIError("Event is full", 403)

    to_add = requested_count if available is None else min(requested_count, available)
    for _ in range(to_add):
        token = secrets.token_hex(4)
        rsvp = PublicRSVP(
            event_id=event.id,
            name=f"Test User {token}",
            email=f"test-{token}@example.com",
            attendance="yes",
            notes="Admin test signup",
            event_title=event.title,
            event_start_time=event.start_time,
            event_location=event.location or None,
        )
        db.session.add(rsvp)
    db.session.commit()

    seats_used_after = _seats_used_for_event(event_id)
    ma = event.max_attendees
    return jsonify({
        "message": "Test signups added",
        "requested": requested_count,
        "added": to_add,
        "seats_used": seats_used_after,
        "max_attendees": ma,
        "fill_ratio": round((seats_used_after / ma), 4) if ma else 0.0,
        "is_full": bool(ma and seats_used_after >= ma),
    }), 201


@events_bp.route("/<int:event_id>/admin-remove-user-rsvp/<int:user_id>", methods=["DELETE"])
@handle_errors
def admin_remove_user_rsvp(event_id, user_id):
    """Admin-only: remove a logged-in user's RSVP from an event."""
    require_admin()
    get_event_or_404(event_id)
    rsvp = RSVP.query.filter_by(event_id=event_id, user_id=user_id).first()
    if not rsvp:
        raise APIError("RSVP not found", 404)
    db.session.delete(rsvp)
    db.session.commit()
    return jsonify({"message": "Logged-in RSVP removed"}), 200


@events_bp.route("/public-rsvp/<int:public_rsvp_id>", methods=["DELETE"])
@handle_errors
def admin_remove_public_rsvp(public_rsvp_id):
    """Admin-only: remove a public RSVP record."""
    require_admin()
    row = PublicRSVP.query.get(public_rsvp_id)
    if not row:
        raise APIError("Public RSVP not found", 404)
    db.session.delete(row)
    db.session.commit()
    return jsonify({"message": "Public RSVP removed"}), 200


@events_bp.route("/<int:event_id>/attendees", methods=["GET"])
@login_required
def event_attendees(event_id):
    """
    Admin-only endpoint:
    Returns exact attendees for an event id (logged-in RSVPs + public RSVPs).
    """
    if current_user.role != "admin":
        return jsonify({"error": "Admin access required"}), 403

    event = Event.query.get_or_404(event_id)

    rsvps = RSVP.query.filter_by(event_id=event_id).all()
    user_ids = [r.user_id for r in rsvps]
    users = User.query.filter(User.id.in_(user_ids)).all() if user_ids else []
    logged_in_attendees = [{
        "user_id": u.id,
        "username": u.username,
        "email": u.email,
        "role": u.role,
    } for u in users]

    public_rsvps = PublicRSVP.query.filter_by(event_id=event_id).all()
    public_attendees = [{
        "public_rsvp_id": r.id,
        "name": r.name,
        "email": r.email,
        "attendance": r.attendance,
        "notes": r.notes,
    } for r in public_rsvps]

    return jsonify({
        "event": {
            "id": event.id,
            "title": event.title,
            "start_time": event.start_time.isoformat(),
            "end_time": event.end_time.isoformat() if event.end_time else None,
        },
        "counts": {
            "attending_logged_in": len(logged_in_attendees),
            "attending_public": len(public_attendees),
            "attending_total": len(logged_in_attendees) + len(public_attendees),
        },
        "attendees": {
            "logged_in": logged_in_attendees,
            "public": public_attendees,
        }
    }), 200


@events_bp.route("/public-rsvp-attendees", methods=["GET"])
@login_required
def public_rsvp_attendees():
    """
    Admin-only attendee list for public RSVPs (works for recurring/client-generated events).
    Query params:
      - event_title
      - event_datetime (ISO string)
    """
    if current_user.role != "admin":
        return jsonify({"error": "Admin access required"}), 403

    event_title = (request.args.get("event_title") or "").strip()
    event_datetime_raw = (request.args.get("event_datetime") or "").strip()
    if not event_title or not event_datetime_raw:
        return jsonify({"error": "event_title and event_datetime are required"}), 400

    event_start_time = _parse_iso_datetime(event_datetime_raw)
    if not event_start_time:
        return jsonify({"error": "Invalid event_datetime"}), 400
    event_start_time = _normalize_utc_naive(event_start_time)

    public_rsvps = PublicRSVP.query.filter_by(
        event_title=event_title,
        event_start_time=event_start_time,
    ).all()

    attendees = [{
        "public_rsvp_id": r.id,
        "name": r.name,
        "email": r.email,
        "attendance": r.attendance,
        "notes": r.notes,
    } for r in public_rsvps]

    return jsonify({"attending": len(attendees), "attendees": attendees}), 200