"""
Profile API — update the current user's profile fields.

Endpoints:
  GET    /api/profile/me           — full profile
  PUT    /api/profile/me           — text fields
  PUT    /api/profile/password      — change password
  POST   /api/profile/avatar       — upload cropped JPEG/PNG (multipart field "file")
  DELETE /api/profile/avatar       — remove custom photo
  GET    /api/profile/avatar-image/<user_id> — public image bytes
"""

import io
import time
from pathlib import Path

from flask import Blueprint, abort, current_app, jsonify, make_response, request, send_file
from werkzeug.security import generate_password_hash

from model.database import db
from api.utils import (
    APIError, handle_errors, require_json, require_auth,
)

profile_bp = Blueprint("profile", __name__)

AVATAR_MAX_BYTES = 3 * 1024 * 1024
AVATAR_MAX_EDGE = 512


def _avatar_dir():
    d = Path(current_app.instance_path) / "avatars"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _avatar_disk_path(user_id):
    return _avatar_dir() / f"{int(user_id)}.jpg"


def _delete_avatar_file(user_id):
    p = _avatar_disk_path(user_id)
    try:
        if p.is_file():
            p.unlink()
    except OSError:
        pass


def _public_api_base():
    """
    Build the absolute base URL used in avatar_url.

    Works behind reverse proxies by honoring X-Forwarded-* headers.
    Prefer PUBLIC_BASE_URL when explicitly set.
    """
    base = (current_app.config.get("PUBLIC_BASE_URL") or "").rstrip("/")
    if base:
        # If PUBLIC_BASE_URL was accidentally set to localhost, prefer forwarded headers instead.
        forwarded_host = request.headers.get("X-Forwarded-Host") or ""
        if ("localhost" not in base and "127.0.0.1" not in base) or not forwarded_host:
            return base

    # Reverse proxy friendliness: prefer forwarded proto/host if present.
    proto = request.headers.get("X-Forwarded-Proto") or request.scheme or "https"
    host = request.headers.get("X-Forwarded-Host") or request.host
    return f"{proto}://{host}".rstrip("/")


def _set_custom_avatar_url(user):
    user.avatar_url = "%s/api/profile/avatar-image/%s?v=%s" % (
        _public_api_base(),
        user.id,
        int(time.time()),
    )


def _pil_image():
    try:
        from PIL import Image
        return Image
    except ImportError:
        raise APIError(
            "Photo upload requires Pillow on the server. Run: pip install Pillow "
            "(or rebuild Docker so requirements.txt is installed).",
            503,
        )


def _process_avatar_upload(stream) -> bytes:
    Image = _pil_image()
    try:
        im = Image.open(stream)
        im = im.convert("RGB")
    except Exception:
        raise APIError("Invalid image file.", 400)
    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    im.thumbnail((AVATAR_MAX_EDGE, AVATAR_MAX_EDGE), resample)
    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    im = im.crop((left, top, left + side, top + side))
    if im.size[0] > AVATAR_MAX_EDGE:
        im = im.resize((AVATAR_MAX_EDGE, AVATAR_MAX_EDGE), resample)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88, optimize=True)
    out = buf.getvalue()
    if len(out) > AVATAR_MAX_BYTES:
        raise APIError("Processed image is still too large.", 400)
    return out


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
        if email != user.email:
            user.google_id = None
            user.avatar_url = None
            user.avatar_custom = False
            _delete_avatar_file(user.id)
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


@profile_bp.route("/avatar", methods=["POST"])
@handle_errors
def upload_avatar():
    user = require_auth()
    if request.content_length and request.content_length > AVATAR_MAX_BYTES:
        raise APIError("Image too large (max 3 MB).", 400)
    f = request.files.get("file")
    if not f or not f.filename:
        raise APIError("Missing file field \"file\".", 400)
    raw = f.read()
    if len(raw) > AVATAR_MAX_BYTES:
        raise APIError("Image too large (max 3 MB).", 400)
    jpeg = _process_avatar_upload(io.BytesIO(raw))
    path = _avatar_disk_path(user.id)
    path.write_bytes(jpeg)
    user.avatar_custom = True
    _set_custom_avatar_url(user)
    db.session.commit()
    return jsonify(user.to_dict())


@profile_bp.route("/avatar", methods=["DELETE"])
@handle_errors
def delete_avatar():
    user = require_auth()
    if not user.avatar_custom:
        raise APIError("No profile photo to remove.", 400)
    _delete_avatar_file(user.id)
    user.avatar_custom = False
    user.avatar_url = None
    db.session.commit()
    return jsonify(user.to_dict())


@profile_bp.route("/avatar-image/<int:user_id>", methods=["GET"])
def get_avatar_image(user_id):
    path = _avatar_disk_path(user_id)
    if not path.is_file():
        abort(404)
    rv = make_response(send_file(path, mimetype="image/jpeg", conditional=True))
    rv.headers["Cache-Control"] = "public, max-age=86400"
    return rv


@profile_bp.route("/recommendations", methods=["GET"])
@handle_errors
def profile_recommendations():
    """
    ML-style content-based ranking: TF–IDF profile vector vs groups/events (cosine similarity).
    Excludes groups the member already joined and events they already RSVPed.
    """
    from api.events import query_events, _is_event_visible_to_user
    from api.groups import get_user_group_ids
    from model.event import RSVP
    from model.group import Group
    from services.recommendation_ml import recommend_groups_events

    user = require_auth()
    bio = (user.bio or "").strip()
    interests = list(user.interests or [])
    languages = list(user.languages or [])
    if not bio and not interests and not languages:
        raise APIError(
            "Add a bio, interests, or languages to your profile to run recommendations.",
            400,
        )

    try:
        top_gi = max(1, min(20, int(request.args.get("top_groups", "5"))))
        top_ei = max(1, min(20, int(request.args.get("top_events", "5"))))
    except (TypeError, ValueError):
        top_gi, top_ei = 5, 5

    my_groups = get_user_group_ids(user.id)
    group_rows = []
    for g in Group.query.order_by(Group.name.asc()).all():
        if g.id in my_groups:
            continue
        combined = f"{g.name}\n{g.description or ''}"
        group_rows.append((g.id, g.name, g.description or "", combined))

    rsvped_ids = {r.event_id for r in RSVP.query.filter_by(user_id=user.id).all()}
    raw_events = query_events(upcoming_only=True)
    event_rows = []
    for e in raw_events:
        if e.id in rsvped_ids:
            continue
        if not _is_event_visible_to_user(e, user):
            continue
        gn = ""
        if e.group_id:
            grp = Group.query.get(e.group_id)
            if grp:
                gn = grp.name
        combined = f"{e.title}\n{e.description or ''}\n{e.location or ''}\n{gn}"
        event_rows.append(
            (
                e.id,
                e.title,
                e.start_time.isoformat(),
                e.location or "",
                combined,
            )
        )

    payload = recommend_groups_events(
        bio,
        interests,
        languages,
        group_rows,
        event_rows,
        top_groups=top_gi,
        top_events=top_ei,
    )
    return jsonify(payload)