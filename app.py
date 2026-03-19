"""
app.py — Flask application factory.

Creates the app, configures extensions, registers all blueprints,
seeds an admin user on first run, and exposes a health endpoint.
"""

import os
from flask import Flask, jsonify
from flask_login import LoginManager
from werkzeug.security import generate_password_hash

from model.database import db
from model.user import User


def create_app(config=None):
    app = Flask(__name__)

    # ── Config ────────────────────────────────────────────────────
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-in-production"),
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///pwc.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,

        # Google OAuth (optional — leave blank to disable)
        GOOGLE_CLIENT_ID=os.environ.get("GOOGLE_CLIENT_ID", ""),
        GOOGLE_CLIENT_SECRET=os.environ.get("GOOGLE_CLIENT_SECRET", ""),

        # CORS / session cookies
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
    )

    if config:
        app.config.update(config)

    # ── Extensions ─────────────────────────────────────────────────
    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        return jsonify({"error": "Login required"}), 401

    # ── CORS headers (for Jekyll frontend on a different origin) ───
    @app.after_request
    def add_cors(response):
        origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:4000")
        response.headers["Access-Control-Allow-Origin"]      = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"]     = "Content-Type"
        response.headers["Access-Control-Allow-Methods"]     = "GET, POST, PUT, DELETE, OPTIONS"
        return response

    @app.route("/api/options-preflight", methods=["OPTIONS"])
    def options_preflight():
        return "", 204

    # Handle OPTIONS pre-flight for all routes
    @app.before_request
    def handle_options():
        from flask import request
        if request.method == "OPTIONS":
            return "", 204

    # ── Blueprints ─────────────────────────────────────────────────
    from api.auth     import auth_bp
    from api.admin    import admin_bp
    from api.blogs     import blog_bp
    from api.events   import events_bp
    from api.payments import payments_bp
    from api.messages import messages_bp
    from api.profile  import profile_bp

    app.register_blueprint(auth_bp,     url_prefix="/api/auth")
    app.register_blueprint(admin_bp,    url_prefix="/api/admin")
    app.register_blueprint(blog_bp,     url_prefix="/api/blog")
    app.register_blueprint(events_bp,   url_prefix="/api/events")
    app.register_blueprint(payments_bp, url_prefix="/api/payments")
    app.register_blueprint(messages_bp, url_prefix="/api/messages")
    app.register_blueprint(profile_bp,  url_prefix="/api/profile")

    # ── Health check ───────────────────────────────────────────────
    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok"})

    # ── DB init + seed ─────────────────────────────────────────────
    with app.app_context():
        db.create_all()
        _seed_admin()

    return app


def _seed_admin():
    """
    Create the default admin account on first run if it doesn't exist.
    Credentials come from env vars; falls back to insecure defaults for dev.

    Override in production:
      ADMIN_USERNAME=yourname ADMIN_EMAIL=you@example.com ADMIN_PASSWORD=strongpassword
    """
    username = os.environ.get("ADMIN_USERNAME", "admin")
    email    = os.environ.get("ADMIN_EMAIL",    "admin@powaywoman.org")
    password = os.environ.get("ADMIN_PASSWORD", "admin123")

    if User.query.filter_by(username=username).first():
        return  # already seeded

    admin = User(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        role="admin",
        is_active_member=True,
        first_name="Club",
        last_name="Admin",
    )
    db.session.add(admin)
    db.session.commit()
    print(f"[seed] Admin user created: {username}")


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)