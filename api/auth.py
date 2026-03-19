"""
Auth API — register, login, logout, current user, Google OAuth.

SRP: Each helper function does exactly one thing.
Orchestrator: Route handlers chain the helpers in sequence.
Error handling: @handle_errors catches APIError and unexpected exceptions.
"""

from flask import Blueprint, jsonify, current_app
from flask_login import login_user, logout_user, current_user
from werkzeug.security import generate_password_hash
import requests as http_requests

from model.database import db
from model.user import User
from api.utils import (
    APIError, handle_errors, require_json, require_fields, require_auth,
)

auth_bp = Blueprint("auth", __name__)


# ── Single-responsibility helpers ──

def validate_registration(data):
    """Validate registration fields. Returns cleaned (username, email, password)."""
    require_fields(data, "username", "email", "password")
    username = data["username"].strip()
    email = data["email"].strip().lower()
    password = data["password"]
    if len(password) < 6:
        raise APIError("Password must be at least 6 characters", 400)
    return username, email, password


def check_user_available(username, email):
    """Raise APIError if username or email is already taken."""
    existing = User.query.filter(
        (User.username == username) | (User.email == email)
    ).first()
    if existing:
        raise APIError("Username or email already taken", 409)


def create_user(username, email, password):
    """Create a new user in the database and return it."""
    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
    )
    db.session.add(user)
    db.session.commit()
    return user


def find_user_by_credentials(identifier, password):
    """Look up user by username or email and verify password. Returns user or raises."""
    user = User.query.filter(
        (User.username == identifier) | (User.email == identifier.lower())
    ).first()
    if not user or not user.check_password(password):
        raise APIError("Invalid credentials", 401)
    return user


def exchange_google_code(code, redirect_uri):
    """Exchange a Google authorization code for an access token."""
    client_id = current_app.config["GOOGLE_CLIENT_ID"]
    client_secret = current_app.config["GOOGLE_CLIENT_SECRET"]
    if not client_id or not client_secret:
        raise APIError("Google OAuth not configured on server", 500)

    resp = http_requests.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=10)

    if resp.status_code != 200:
        raise APIError("Failed to exchange Google authorization code", 400)

    token = resp.json().get("access_token")
    if not token:
        raise APIError("No access token in Google response", 400)
    return token


def fetch_google_user_info(access_token):
    """Fetch user profile from Google using an access token."""
    resp = http_requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        raise APIError("Failed to fetch Google user info", 400)
    return resp.json()


def find_or_create_google_user(info):
    """Find existing user by google_id or email, or create a new one."""
    google_id = info["id"]
    email = info["email"]
    name = info.get("name", email.split("@")[0])
    avatar = info.get("picture")

    user = User.query.filter_by(google_id=google_id).first()
    if user:
        return user

    # Check if email already exists (link accounts)
    user = User.query.filter_by(email=email).first()
    if user:
        user.google_id = google_id
        user.avatar_url = avatar
        db.session.commit()
        return user

    # Brand new user
    user = User(
        username=name.replace(" ", "").lower()[:80],
        email=email,
        google_id=google_id,
        avatar_url=avatar,
    )
    db.session.add(user)
    db.session.commit()
    return user


# ── Orchestrator routes (chain helpers in sequence) ──

@auth_bp.route("/register", methods=["POST"])
@handle_errors
def register():
    """Orchestrator: parse → validate → check availability → create → login → respond."""
    data = require_json()
    username, email, password = validate_registration(data)
    check_user_available(username, email)
    user = create_user(username, email, password)
    login_user(user)
    return jsonify(user.to_dict()), 201


@auth_bp.route("/login", methods=["POST"])
@handle_errors
def login():
    """Orchestrator: parse → find user → login → respond."""
    data = require_json()
    require_fields(data, "username", "password")
    user = find_user_by_credentials(data["username"].strip(), data["password"])
    login_user(user)
    return jsonify(user.to_dict())


@auth_bp.route("/logout", methods=["POST"])
@handle_errors
def logout():
    """Orchestrator: verify auth → logout → respond."""
    require_auth()
    logout_user()
    return jsonify({"message": "Logged out"})


@auth_bp.route("/me", methods=["GET"])
@handle_errors
def me():
    """Return current user or 401."""
    if current_user.is_authenticated:
        return jsonify(current_user.to_dict())
    raise APIError("Not logged in", 401)


@auth_bp.route("/google", methods=["POST"])
@handle_errors
def google_login():
    """Orchestrator: parse → exchange code → fetch profile → find/create user → login → respond."""
    data = require_json()
    require_fields(data, "code")
    redirect_uri = data.get("redirect_uri", "postmessage")
    access_token = exchange_google_code(data["code"], redirect_uri)
    info = fetch_google_user_info(access_token)
    user = find_or_create_google_user(info)
    login_user(user)
    return jsonify(user.to_dict())