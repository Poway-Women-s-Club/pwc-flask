from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timezone
from model.database import db
from model.event import Event, RSVP, PublicRSVP, MeetingRequest
from model.user import User

events_bp = Blueprint("events", __name__)

ALLOWED_ATTENDANCE = {"yes", "no", "maybe"}


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


@events_bp.route("/", methods=["GET"])
def list_events():
    upcoming = request.args.get("upcoming", "true").lower() == "true"
    query = Event.query
    if upcoming:
        query = query.filter(Event.start_time >= datetime.utcnow())
    events = query.order_by(Event.start_time.asc()).all()
    return jsonify([e.to_dict() for e in events])


@events_bp.route("/<int:event_id>", methods=["GET"])
def get_event(event_id):
    event = Event.query.get_or_404(event_id)
    data = event.to_dict()
    # Include RSVP list for logged-in users
    if current_user.is_authenticated:
        data["user_rsvped"] = RSVP.query.filter_by(
            user_id=current_user.id, event_id=event_id
        ).first() is not None
    return jsonify(data)


@events_bp.route("/", methods=["POST"])
@login_required
def create_event():
    if current_user.role != "admin":
        return jsonify({"error": "Admin only"}), 403

    data = request.get_json()
    if not data or not data.get("title") or not data.get("start_time"):
        return jsonify({"error": "Title and start_time required"}), 400

    event = Event(
        title=data["title"],
        description=data.get("description", ""),
        location=data.get("location", ""),
        start_time=datetime.fromisoformat(data["start_time"]),
        end_time=datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None,
        created_by=current_user.id,
    )
    db.session.add(event)
    db.session.commit()
    return jsonify(event.to_dict()), 201


@events_bp.route("/<int:event_id>", methods=["PUT"])
@login_required
def update_event(event_id):
    if current_user.role != "admin":
        return jsonify({"error": "Admin only"}), 403

    event = Event.query.get_or_404(event_id)
    data = request.get_json()

    if "title" in data:
        event.title = data["title"]
    if "description" in data:
        event.description = data["description"]
    if "location" in data:
        event.location = data["location"]
    if "start_time" in data:
        event.start_time = datetime.fromisoformat(data["start_time"])
    if "end_time" in data:
        event.end_time = datetime.fromisoformat(data["end_time"]) if data["end_time"] else None

    db.session.commit()
    return jsonify(event.to_dict())


@events_bp.route("/<int:event_id>", methods=["DELETE"])
@login_required
def delete_event(event_id):
    if current_user.role != "admin":
        return jsonify({"error": "Admin only"}), 403

    event = Event.query.get_or_404(event_id)
    db.session.delete(event)
    db.session.commit()
    return jsonify({"message": "Event deleted"})


@events_bp.route("/<int:event_id>/rsvp", methods=["POST"])
@login_required
def rsvp(event_id):
    Event.query.get_or_404(event_id)
    existing = RSVP.query.filter_by(user_id=current_user.id, event_id=event_id).first()
    if existing:
        return jsonify({"message": "Already RSVPed"}), 200

    rsvp = RSVP(user_id=current_user.id, event_id=event_id)
    db.session.add(rsvp)
    db.session.commit()
    return jsonify({"message": "RSVPed"}), 201


@events_bp.route("/<int:event_id>/rsvp", methods=["DELETE"])
@login_required
def cancel_rsvp(event_id):
    rsvp = RSVP.query.filter_by(user_id=current_user.id, event_id=event_id).first()
    if not rsvp:
        return jsonify({"error": "No RSVP found"}), 404
    db.session.delete(rsvp)
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
    """

    data = _get_payload()

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    topic = (data.get("topic") or "").strip()
    description = (data.get("description") or "").strip()
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

    preferred_start_dt = _parse_iso_datetime(preferred_start_raw) if preferred_start_raw else None
    preferred_end_dt = _parse_iso_datetime(preferred_end_raw) if preferred_end_raw else None

    if not preferred_start_dt or not preferred_end_dt:
        return jsonify({"error": "preferred_datetime (start) and preferred_end_datetime are required"}), 400

    if preferred_end_dt <= preferred_start_dt:
        return jsonify({"error": "preferred_end_datetime must be after preferred_datetime"}), 400

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
    )
    db.session.add(event)
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
    logged_in_count = RSVP.query.filter_by(event_id=event_id).count()
    public_count = PublicRSVP.query.filter_by(event_id=event_id).count()
    return jsonify({
        "attending": logged_in_count + public_count,
        "attending_logged_in": logged_in_count,
        "attending_public": public_count,
    }), 200


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
        "username": u.username,
        "email": u.email,
        "role": u.role,
    } for u in users]

    public_rsvps = PublicRSVP.query.filter_by(event_id=event_id).all()
    public_attendees = [{
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
        "name": r.name,
        "email": r.email,
        "attendance": r.attendance,
        "notes": r.notes,
    } for r in public_rsvps]

    return jsonify({"attending": len(attendees), "attendees": attendees}), 200