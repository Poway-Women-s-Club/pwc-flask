"""
Profile API — update the current user's profile fields.

The frontend profile.js sends firstName, lastName, bio, languages, interests.
This blueprint maps those to the User model and persists them.

Endpoints:
  GET  /api/profile/me      — return current user's full profile
  PUT  /api/profile/me      — update profile fields
  PUT  /api/profile/password — change password
"""

from flask import Blueprint, jsonify
from werkzeug.security import generate_password_hash

from model.database import db
from api.utils import (
    APIError, handle_errors, require_json, require_auth,
)

profile_bp = Blueprint("profile", __name__)


# ── Single-responsibility helpers ──

def apply_profile_updates(user, data):
    """Apply whitelisted profile field updates to user."""
    if "firstName" in data:
        user.first_name = data["firstName"].strip()
    if "lastName" in data:
        user.last_name = data["lastName"].strip()
    if "email" in data:
        email = data["email"].strip().lower()
        if not email or "@" not in email:
            raise APIError("Invalid email address", 400)
        user.email = email
    if "bio" in data:
        user.bio = data["bio"].strip()
    if "languages" in data:
        if not isinstance(data["languages"], list):
            raise APIError("languages must be a list", 400)
        user.languages = [str(l).strip() for l in data["languages"] if str(l).strip()]
    if "interests" in data:
        if not isinstance(data["interests"], list):
            raise APIError("interests must be a list", 400)
        user.interests = [str(i).strip() for i in data["interests"] if str(i).strip()]


def verify_and_change_password(user, current_pw, new_pw, confirm_pw):
    """Verify current password then apply new one."""
    if not user.check_password(current_pw):
        raise APIError("Current password is incorrect", 401)
    if len(new_pw) < 8:
        raise APIError("New password must be at least 8 characters", 400)
    if new_pw != confirm_pw:
        raise APIError("Passwords do not match", 400)
    user.password_hash = generate_password_hash(new_pw)


# ── Orchestrator routes ──

@profile_bp.route("/me", methods=["GET"])
@handle_errors
def get_profile():
    """Return the current user's profile."""
    user = require_auth()
    return jsonify(user.to_dict())


@profile_bp.route("/me", methods=["PUT"])
@handle_errors
def update_profile():
    """Orchestrator: require auth → parse body → apply updates → save → respond."""
    user = require_auth()
    data = require_json()
    apply_profile_updates(user, data)
    db.session.commit()
    return jsonify(user.to_dict())


@profile_bp.route("/password", methods=["PUT"])
@handle_errors
def change_password():
    """Orchestrator: require auth → verify old password → apply new → respond."""
    user = require_auth()
    data = require_json()
    for field in ("currentPassword", "newPassword", "confirmPassword"):
        if not data.get(field):
            raise APIError(f"Missing field: {field}", 400)
    verify_and_change_password(
        user,
        data["currentPassword"],
        data["newPassword"],
        data["confirmPassword"],
    )
    db.session.commit()
    return jsonify({"message": "Password updated"})