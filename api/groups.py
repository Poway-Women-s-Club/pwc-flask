"""
Groups API — group CRUD and membership management.

SRP: Lookup, creation, membership checks are separate functions.
Orchestrator: Routes chain helpers in sequence.
Error handling: @handle_errors on every route.
"""

from flask import Blueprint, jsonify, request

from model.database import db
from model.group import Group, UserGroup
from model.user import User
from api.utils import (
    APIError, handle_errors, require_json, require_fields,
    require_auth, require_admin, require_owner_or_admin,
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


def create_group(name, description, creator_id):
    """Create and persist a new group."""
    group = Group(name=name, description=description, created_by=creator_id)
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


# ── Orchestrator routes ──

@groups_bp.route("/", methods=["GET"])
@handle_errors
def list_groups():
    """List all groups."""
    groups = Group.query.order_by(Group.name.asc()).all()
    return jsonify([g.to_dict() for g in groups])


@groups_bp.route("/<int:group_id>", methods=["GET"])
@handle_errors
def get_group(group_id):
    """Fetch group details including member list."""
    group = get_group_or_404(group_id)
    data = group.to_dict()
    data["members"] = get_group_members(group_id)
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
    group = create_group(data["name"].strip(), data.get("description", "").strip(), user.id)
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
    get_group_or_404(group_id)
    if check_existing_membership(user.id, group_id):
        return jsonify({"message": "Already a member"}), 200
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
