"""
Groups API — group CRUD and membership management.

SRP: Lookup, creation, membership checks are separate functions.
Orchestrator: Routes chain helpers in sequence.
Error handling: @handle_errors on every route.
"""

from datetime import datetime

from flask import Blueprint, jsonify, request

from model.database import db
from model.group import Group, GroupApplication, UserGroup
from model.user import User
from api.utils import (
    APIError, handle_errors, require_json, require_fields,
    require_auth, require_owner_or_admin, optional_auth,
)

groups_bp = Blueprint("groups", __name__)


# ── Single-responsibility helpers ──

def get_group_or_404(group_id):
    """Fetch a single group by ID or raise APIError."""
    group = Group.query.get(group_id)
    if not group:
        raise APIError("Group not found", 404)
    return group


def check_existing_membership(user_id, group_id):
    """Return existing membership or None."""
    return UserGroup.query.filter_by(user_id=user_id, group_id=group_id).first()


def create_group(name, description, creator_id, requires_application=False):
    """Create and persist a new group."""
    group = Group(
        name=name,
        description=description,
        created_by=creator_id,
        requires_application=bool(requires_application),
    )
    db.session.add(group)
    db.session.flush()
    return group


def add_member(user_id, group_id):
    """Add a user to a group."""
    membership = UserGroup(user_id=user_id, group_id=group_id)
    db.session.add(membership)
    return membership


def remove_member(user_id, group_id):
    """Remove a user from a group. Returns True if removed, False if not found."""
    membership = check_existing_membership(user_id, group_id)
    if not membership:
        return False
    db.session.delete(membership)
    return True


def get_group_members(group_id):
    """Return list of user dicts for members of a group."""
    memberships = UserGroup.query.filter_by(group_id=group_id).all()
    user_ids = [m.user_id for m in memberships]
    if not user_ids:
        return []
    users = User.query.filter(User.id.in_(user_ids)).all()
    return [{"id": u.id, "username": u.username, "firstName": u.first_name,
             "lastName": u.last_name} for u in users]


def get_user_group_ids(user_id):
    """Return set of group IDs the user belongs to."""
    memberships = UserGroup.query.filter_by(user_id=user_id).all()
    return {m.group_id for m in memberships}


def apply_group_updates(group, data):
    """Apply partial updates to an existing group."""
    if "name" in data:
        group.name = data["name"]
    if "description" in data:
        group.description = data["description"]
    if "requires_application" in data:
        group.requires_application = bool(data["requires_application"])


def get_application_or_404(group_id, application_id):
    app = GroupApplication.query.filter_by(id=application_id, group_id=group_id).first()
    if not app:
        raise APIError("Application not found", 404)
    return app


def application_to_dict(app):
    u = User.query.get(app.user_id)
    return {
        "id":         app.id,
        "user_id":    app.user_id,
        "message":    app.message,
        "status":     app.status,
        "created_at": app.created_at.isoformat(),
        "decided_at": app.decided_at.isoformat() if app.decided_at else None,
        "user": {
            "id":         u.id,
            "username":   u.username,
            "firstName":  u.first_name,
            "lastName":   u.last_name,
        } if u else None,
    }


# ── Orchestrator routes ──

@groups_bp.route("/", methods=["GET"])
@handle_errors
def list_groups():
    """List all groups."""
    groups = Group.query.order_by(Group.name.asc()).all()
    viewer = optional_auth()
    app_map = {}
    if viewer and groups:
        gids = [g.id for g in groups]
        apps = GroupApplication.query.filter(
            GroupApplication.user_id == viewer.id,
            GroupApplication.group_id.in_(gids),
        ).all()
        app_map = {a.group_id: a for a in apps}
    out = []
    for g in groups:
        d = g.to_dict()
        if viewer:
            row = app_map.get(g.id)
            d["my_application"] = (
                {"status": row.status, "message": row.message} if row else None
            )
        else:
            d["my_application"] = None
        out.append(d)
    return jsonify(out)


@groups_bp.route("/<int:group_id>", methods=["GET"])
@handle_errors
def get_group(group_id):
    """Fetch group details including member list."""
    group = get_group_or_404(group_id)
    data = group.to_dict()
    data["members"] = get_group_members(group_id)
    viewer = optional_auth()
    if viewer:
        row = GroupApplication.query.filter_by(user_id=viewer.id, group_id=group_id).first()
        if row:
            data["my_application"] = {"status": row.status, "message": row.message}
        else:
            data["my_application"] = None
    else:
        data["my_application"] = None
    return jsonify(data)


@groups_bp.route("/", methods=["POST"])
@handle_errors
def create_group_route():
    """Orchestrator: require auth -> parse body -> validate -> create group -> auto-join creator -> respond."""
    user = require_auth()
    data = require_json()
    require_fields(data, "name")
    existing = Group.query.filter_by(name=data["name"].strip()).first()
    if existing:
        raise APIError("A group with that name already exists", 409)
    group = create_group(
        data["name"].strip(),
        data.get("description", "").strip(),
        user.id,
        requires_application=data.get("requires_application", False),
    )
    add_member(user.id, group.id)
    db.session.commit()
    return jsonify(group.to_dict()), 201


@groups_bp.route("/<int:group_id>", methods=["PUT"])
@handle_errors
def update_group(group_id):
    """Orchestrator: fetch group -> check ownership -> parse body -> update -> respond."""
    group = get_group_or_404(group_id)
    require_owner_or_admin(group.created_by)
    data = require_json()
    if "name" in data:
        existing = Group.query.filter(Group.name == data["name"].strip(), Group.id != group_id).first()
        if existing:
            raise APIError("A group with that name already exists", 409)
    apply_group_updates(group, data)
    db.session.commit()
    return jsonify(group.to_dict())


@groups_bp.route("/<int:group_id>", methods=["DELETE"])
@handle_errors
def delete_group(group_id):
    """Orchestrator: fetch group -> check ownership -> delete -> respond."""
    group = get_group_or_404(group_id)
    require_owner_or_admin(group.created_by)
    db.session.delete(group)
    db.session.commit()
    return jsonify({"message": "Group deleted"})


@groups_bp.route("/<int:group_id>/join", methods=["POST"])
@handle_errors
def join_group(group_id):
    """Orchestrator: require auth -> verify group exists -> check duplicate -> add member."""
    user = require_auth()
    group = get_group_or_404(group_id)
    if check_existing_membership(user.id, group_id):
        return jsonify({"message": "Already a member"}), 200
    if group.requires_application:
        raise APIError("This group requires an application. Use Apply instead of Join.", 400)
    add_member(user.id, group_id)
    db.session.commit()
    return jsonify({"message": "Joined group"}), 201


@groups_bp.route("/<int:group_id>/leave", methods=["DELETE"])
@handle_errors
def leave_group(group_id):
    """Orchestrator: require auth -> find membership -> remove -> respond."""
    user = require_auth()
    get_group_or_404(group_id)
    if not remove_member(user.id, group_id):
        raise APIError("Not a member of this group", 404)
    db.session.commit()
    return jsonify({"message": "Left group"})


@groups_bp.route("/my", methods=["GET"])
@handle_errors
def my_groups():
    """Return groups the current user belongs to."""
    user = require_auth()
    memberships = UserGroup.query.filter_by(user_id=user.id).all()
    group_ids = [m.group_id for m in memberships]
    if not group_ids:
        return jsonify([])
    groups = Group.query.filter(Group.id.in_(group_ids)).order_by(Group.name.asc()).all()
    return jsonify([g.to_dict() for g in groups])


@groups_bp.route("/<int:group_id>/applications", methods=["POST"])
@handle_errors
def submit_application(group_id):
    """Member requests to join a group that requires approval."""
    user = require_auth()
    group = get_group_or_404(group_id)
    if not group.requires_application:
        raise APIError("This group is open to join. Use Join instead of Apply.", 400)
    if check_existing_membership(user.id, group_id):
        raise APIError("You are already a member of this group", 400)
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()[:2000]

    existing = GroupApplication.query.filter_by(user_id=user.id, group_id=group_id).first()
    if existing:
        if existing.status == "pending":
            raise APIError("You already have a pending application for this group", 409)
        if existing.status == "accepted":
            raise APIError("You have already been accepted to this group", 400)
        existing.status = "pending"
        existing.message = message
        existing.created_at = datetime.utcnow()
        existing.decided_at = None
    else:
        db.session.add(
            GroupApplication(
                user_id=user.id,
                group_id=group_id,
                message=message,
                status="pending",
            )
        )
    db.session.commit()
    return jsonify({"message": "Application submitted"}), 201


@groups_bp.route("/<int:group_id>/applications", methods=["GET"])
@handle_errors
def list_applications(group_id):
    """List applications for a group (group owner or site admin)."""
    user = require_auth()
    group = get_group_or_404(group_id)
    if user.id != group.created_by and user.role != "admin":
        raise APIError("Not authorized", 403)
    status = request.args.get("status", "pending").strip()
    if status not in ("pending", "accepted", "denied", "all"):
        status = "pending"
    q = GroupApplication.query.filter_by(group_id=group_id)
    if status != "all":
        q = q.filter_by(status=status)
    rows = q.order_by(GroupApplication.created_at.asc()).all()
    return jsonify([application_to_dict(a) for a in rows])


@groups_bp.route("/<int:group_id>/applications/<int:application_id>/approve", methods=["POST"])
@handle_errors
def approve_application(group_id, application_id):
    application = get_application_or_404(group_id, application_id)
    user = require_auth()
    group = get_group_or_404(group_id)
    if user.id != group.created_by and user.role != "admin":
        raise APIError("Not authorized", 403)
    if application.status != "pending":
        raise APIError("Application is not pending", 400)
    if check_existing_membership(application.user_id, group_id):
        application.status = "accepted"
        application.decided_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"message": "User is already a member"})
    add_member(application.user_id, group_id)
    application.status = "accepted"
    application.decided_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"message": "Application approved"})


@groups_bp.route("/<int:group_id>/applications/<int:application_id>/deny", methods=["POST"])
@handle_errors
def deny_application(group_id, application_id):
    application = get_application_or_404(group_id, application_id)
    user = require_auth()
    group = get_group_or_404(group_id)
    if user.id != group.created_by and user.role != "admin":
        raise APIError("Not authorized", 403)
    if application.status != "pending":
        raise APIError("Application is not pending", 400)
    application.status = "denied"
    application.decided_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"message": "Application denied"})
