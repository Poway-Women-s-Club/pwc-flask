from flask import Blueprint, request, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash
from model.database import db
from model.user import User
import requests as http_requests

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400

    username = data.get("username", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not username or not email or not password:
        return jsonify({"error": "Username, email, and password are required"}), 400

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400

    if User.query.filter((User.username == username) | (User.email == email)).first():
        return jsonify({"error": "Username or email already taken"}), 409

    user = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
    )
    db.session.add(user)
    db.session.commit()

    login_user(user)
    return jsonify(user.to_dict()), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400

    identifier = data.get("username", "").strip()  # accepts username or email
    password = data.get("password", "")

    user = User.query.filter(
        (User.username == identifier) | (User.email == identifier.lower())
    ).first()

    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid credentials"}), 401

    login_user(user)
    return jsonify(user.to_dict())


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"message": "Logged out"})


@auth_bp.route("/me", methods=["GET"])
def me():
    if current_user.is_authenticated:
        return jsonify(current_user.to_dict())
    return jsonify({"user": None}), 401


# --- Google OAuth ---

@auth_bp.route("/google", methods=["POST"])
def google_login():
    """
    Frontend sends a Google OAuth authorization code.
    We exchange it for tokens, get user info, and log them in.
    """
    data = request.get_json()
    code = data.get("code")
    if not code:
        return jsonify({"error": "Missing authorization code"}), 400

    client_id = current_app.config["GOOGLE_CLIENT_ID"]
    client_secret = current_app.config["GOOGLE_CLIENT_SECRET"]
    redirect_uri = data.get("redirect_uri", "postmessage")

    if not client_id or not client_secret:
        return jsonify({"error": "Google OAuth not configured on server"}), 500

    # Exchange code for tokens
    token_resp = http_requests.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })

    if token_resp.status_code != 200:
        return jsonify({"error": "Failed to exchange code"}), 400

    access_token = token_resp.json().get("access_token")

    # Get user info
    info_resp = http_requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    if info_resp.status_code != 200:
        return jsonify({"error": "Failed to get user info"}), 400

    info = info_resp.json()
    google_id = info["id"]
    email = info["email"]
    name = info.get("name", email.split("@")[0])
    avatar = info.get("picture")

    # Find or create user
    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        user = User.query.filter_by(email=email).first()
        if user:
            # Link Google to existing account
            user.google_id = google_id
            user.avatar_url = avatar
        else:
            # New user
            user = User(
                username=name.replace(" ", "").lower()[:80],
                email=email,
                google_id=google_id,
                avatar_url=avatar,
            )
            db.session.add(user)

    db.session.commit()
    login_user(user)
    return jsonify(user.to_dict())