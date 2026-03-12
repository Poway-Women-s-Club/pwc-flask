from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from model.database import db
from model.event import Event, RSVP

events_bp = Blueprint("events", __name__)


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