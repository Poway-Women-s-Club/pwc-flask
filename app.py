"""
app.py — Flask application factory.

Creates the app, configures extensions, registers all blueprints,
seeds sample data on first run, and exposes a health endpoint.
"""

import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template
from flask_cors import CORS
from flask_login import LoginManager
from werkzeug.security import generate_password_hash

from model.database import db
from model.user import User

load_dotenv()


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

        # Session cookies
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
    )

    if config:
        app.config.update(config)

    # ── Extensions ─────────────────────────────────────────────────
    frontend_origin = os.environ.get("FRONTEND_URL", "http://localhost:4600")
    CORS(app, supports_credentials=True, origins=[
        "http://localhost:4600",
        "http://127.0.0.1:4600",
        frontend_origin,
    ])

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        return jsonify({"error": "Login required"}), 401

    # ── Blueprints ─────────────────────────────────────────────────
    from api.auth     import auth_bp
    from api.admin    import admin_bp
    from api.blog     import blog_bp
    from api.events   import events_bp
    from api.payments import payments_bp
    from api.messages import messages_bp
    from api.profile  import profile_bp
    from api.groups   import groups_bp

    app.register_blueprint(auth_bp,     url_prefix="/api/auth")
    app.register_blueprint(admin_bp,    url_prefix="/api/admin")
    app.register_blueprint(blog_bp,     url_prefix="/api/blog")
    app.register_blueprint(events_bp,   url_prefix="/api/events")
    app.register_blueprint(payments_bp, url_prefix="/api/payments")
    app.register_blueprint(messages_bp, url_prefix="/api/messages")
    app.register_blueprint(profile_bp,  url_prefix="/api/profile")
    app.register_blueprint(groups_bp,   url_prefix="/api/groups")

    # ── Health check ───────────────────────────────────────────────
    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok"})

    @app.route("/")
    def admin_panel():
        return render_template("admin.html")

    # ── DB init + seed ─────────────────────────────────────────────
    with app.app_context():
        db.create_all()
        _sync_schema()
        _seed_data()

    return app


def _sync_schema():
    """Add any missing columns to existing SQLite tables (no migration tool)."""
    try:
        from sqlalchemy import inspect as sql_inspect, text

        inspector = sql_inspect(db.engine)

        if "meeting_requests" in inspector.get_table_names():
            cols = {c["name"] for c in inspector.get_columns("meeting_requests")}
            if "preferred_end_datetime" not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text("ALTER TABLE meeting_requests ADD COLUMN preferred_end_datetime DATETIME"))

        if "users" in inspector.get_table_names():
            user_cols = {c["name"] for c in inspector.get_columns("users")}
            new_cols = {
                "first_name": "VARCHAR(80) NOT NULL DEFAULT ''",
                "last_name":  "VARCHAR(80) NOT NULL DEFAULT ''",
                "bio":        "TEXT NOT NULL DEFAULT ''",
                "languages":  "TEXT NOT NULL DEFAULT '[]'",
                "interests":  "TEXT NOT NULL DEFAULT '[]'",
            }
            with db.engine.begin() as conn:
                for col, typedef in new_cols.items():
                    if col not in user_cols:
                        conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {typedef}"))
        if "blog_posts" in inspector.get_table_names():
            blog_cols = {c["name"] for c in inspector.get_columns("blog_posts")}
            blog_new = {
                "is_pinned":      "BOOLEAN NOT NULL DEFAULT 0",
                "pin_expires_at": "DATETIME",
                "group_id":       "INTEGER REFERENCES groups(id)",
            }
            with db.engine.begin() as conn:
                for col, typedef in blog_new.items():
                    if col not in blog_cols:
                        conn.execute(text(f"ALTER TABLE blog_posts ADD COLUMN {col} {typedef}"))

        if "events" in inspector.get_table_names():
            event_cols = {c["name"] for c in inspector.get_columns("events")}
            if "group_id" not in event_cols:
                with db.engine.begin() as conn:
                    conn.execute(text("ALTER TABLE events ADD COLUMN group_id INTEGER REFERENCES groups(id)"))

    except Exception as e:
        print("Schema sync skipped/failed:", e)


def _seed_data():
    """Seed sample users and content on first run (empty database)."""
    if User.query.count() > 0:
        return

    print("Seeding database with sample data...")

    from model.event import Event, RSVP
    from model.blog import BlogPost, Comment
    from model.payment import Payment
    from model.group import Group, UserGroup

    # --- Users ---
    admin = User(
        username="admin",
        email="admin@powaywomansclub.org",
        password_hash=generate_password_hash(
            os.environ.get("ADMIN_PASSWORD", "admin123")
        ),
        role="admin",
        is_active_member=True,
        first_name="Club",
        last_name="Admin",
    )
    evan = User(
        username="evan",
        email="evan@example.com",
        password_hash=generate_password_hash("password"),
        role="member",
        is_active_member=True,
        first_name="Evan",
        last_name="S",
    )
    maya = User(
        username="maya",
        email="maya@example.com",
        password_hash=generate_password_hash("password"),
        role="member",
        is_active_member=True,
        first_name="Maya",
        last_name="R",
    )
    cyrus = User(
        username="cyrus",
        email="cyrus@example.com",
        password_hash=generate_password_hash("password"),
        role="member",
        is_active_member=False,
        first_name="Cyrus",
        last_name="K",
    )
    linda = User(
        username="linda",
        email="linda@powaywomansclub.org",
        password_hash=generate_password_hash("password"),
        role="admin",
        is_active_member=True,
        first_name="Linda",
        last_name="M",
    )
    karen = User(
        username="karen",
        email="karen@example.com",
        password_hash=generate_password_hash("password"),
        role="member",
        is_active_member=True,
        first_name="Karen",
        last_name="B",
    )
    janet = User(
        username="janet",
        email="janet@example.com",
        password_hash=generate_password_hash("password"),
        role="member",
        is_active_member=False,
        first_name="Janet",
        last_name="W",
    )

    db.session.add_all([admin, evan, maya, cyrus, linda, karen, janet])
    db.session.flush()

    # --- Events ---
    events = [
        Event(title="General Meeting — April",
              description="Monthly general meeting. All members welcome.",
              location="Templars Hall, Old Poway Park",
              start_time=datetime(2026, 4, 14, 17, 0),
              end_time=datetime(2026, 4, 14, 18, 30),
              created_by=admin.id),
        Event(title="General Meeting — May",
              description="Monthly general meeting with guest speaker.",
              location="Templars Hall, Old Poway Park",
              start_time=datetime(2026, 5, 12, 17, 0),
              end_time=datetime(2026, 5, 12, 18, 30),
              created_by=admin.id),
        Event(title="Celebrate Women Art Exhibit",
              description="Annual art exhibit showcasing women artists from the Poway community.",
              location="Poway Center for the Performing Arts",
              start_time=datetime(2026, 4, 25, 14, 0),
              end_time=datetime(2026, 4, 25, 18, 0),
              created_by=linda.id),
        Event(title="Old-Fashioned Friendship Tea",
              description="Afternoon tea with finger sandwiches, scones, and good company.",
              location="Templars Hall, Old Poway Park",
              start_time=datetime(2026, 4, 26, 21, 0),
              end_time=datetime(2026, 4, 26, 23, 0),
              created_by=admin.id),
        Event(title="Student Art Exhibit",
              description="Featuring artwork from students at Poway-area high schools.",
              location="Old Poway Park Gallery",
              start_time=datetime(2026, 5, 3, 15, 0),
              end_time=datetime(2026, 5, 3, 19, 0),
              created_by=linda.id),
        Event(title="Theatre in the Park",
              description="Community theatre performance sponsored by the Poway Woman's Club.",
              location="Old Poway Park Amphitheatre",
              start_time=datetime(2026, 6, 7, 18, 30),
              end_time=datetime(2026, 6, 7, 21, 0),
              created_by=admin.id),
        Event(title="HOBY Scholarship Awards Ceremony",
              description="Recognizing this year's Hugh O'Brian Youth Leadership scholarship recipients.",
              location="Poway Community Library",
              start_time=datetime(2026, 5, 20, 17, 0),
              end_time=datetime(2026, 5, 20, 18, 30),
              created_by=linda.id),
    ]
    db.session.add_all(events)
    db.session.flush()

    # --- RSVPs ---
    rsvps = [
        RSVP(user_id=evan.id, event_id=events[0].id),
        RSVP(user_id=maya.id, event_id=events[0].id),
        RSVP(user_id=karen.id, event_id=events[0].id),
        RSVP(user_id=linda.id, event_id=events[0].id),
        RSVP(user_id=evan.id, event_id=events[2].id),
        RSVP(user_id=maya.id, event_id=events[2].id),
        RSVP(user_id=cyrus.id, event_id=events[2].id),
        RSVP(user_id=karen.id, event_id=events[3].id),
        RSVP(user_id=janet.id, event_id=events[3].id),
        RSVP(user_id=linda.id, event_id=events[3].id),
        RSVP(user_id=evan.id, event_id=events[5].id),
        RSVP(user_id=maya.id, event_id=events[6].id),
    ]
    db.session.add_all(rsvps)

    # --- Blog Posts ---
    post1 = BlogPost(title="Welcome to the New Website",
                     body="We're excited to launch the new Poway Woman's Club website.",
                     author_id=admin.id)
    post2 = BlogPost(title="April Meeting Recap",
                     body="Thank you to everyone who came to the April general meeting.",
                     author_id=linda.id)
    post3 = BlogPost(title="Volunteer Opportunities This Spring",
                     body="We have several volunteer opportunities coming up.",
                     author_id=karen.id)
    post4 = BlogPost(title="Scholarship Applications Now Open",
                     body="The HOBY Youth Leadership scholarship applications are now open.",
                     author_id=linda.id)
    db.session.add_all([post1, post2, post3, post4])
    db.session.flush()

    # --- Comments ---
    comments = [
        Comment(body="Love the new site!", author_id=evan.id, post_id=post1.id),
        Comment(body="Looks great. Can we add a photo gallery?", author_id=maya.id, post_id=post1.id),
        Comment(body="Working on it!", author_id=admin.id, post_id=post1.id),
        Comment(body="Great meeting. Excited for the art exhibit.", author_id=karen.id, post_id=post2.id),
        Comment(body="Can we get the minutes emailed too?", author_id=janet.id, post_id=post2.id),
        Comment(body="I can help with setup on the 24th.", author_id=evan.id, post_id=post3.id),
        Comment(body="I'll be at the Friendship Tea greeting table.", author_id=maya.id, post_id=post3.id),
        Comment(body="Sharing this with the school counselors.", author_id=cyrus.id, post_id=post4.id),
    ]
    db.session.add_all(comments)

    # --- Payments ---
    payments = [
        Payment(user_id=evan.id, amount_cents=5000, description="Annual Membership Dues", status="completed", payment_method="stub"),
        Payment(user_id=maya.id, amount_cents=5000, description="Annual Membership Dues", status="completed", payment_method="stub"),
        Payment(user_id=karen.id, amount_cents=5000, description="Annual Membership Dues", status="completed", payment_method="stub"),
        Payment(user_id=linda.id, amount_cents=5000, description="Annual Membership Dues", status="completed", payment_method="stub"),
        Payment(user_id=cyrus.id, amount_cents=5000, description="Annual Membership Dues", status="pending", payment_method="stub"),
        Payment(user_id=janet.id, amount_cents=3000, description="Friendship Tea Ticket", status="completed", payment_method="stub"),
    ]
    db.session.add_all(payments)

    # --- Groups ---
    arts_group = Group(name="Arts Committee", description="Members who plan and organize art exhibits and cultural events.", created_by=linda.id)
    social_group = Group(name="Social Events", description="Plan social gatherings, teas, and community get-togethers.", created_by=admin.id)
    scholarship_group = Group(name="Scholarship Committee", description="Review and award HOBY scholarships to local students.", created_by=linda.id)

    db.session.add_all([arts_group, social_group, scholarship_group])
    db.session.flush()

    group_memberships = [
        UserGroup(user_id=linda.id, group_id=arts_group.id),
        UserGroup(user_id=evan.id, group_id=arts_group.id),
        UserGroup(user_id=maya.id, group_id=arts_group.id),
        UserGroup(user_id=admin.id, group_id=social_group.id),
        UserGroup(user_id=karen.id, group_id=social_group.id),
        UserGroup(user_id=janet.id, group_id=social_group.id),
        UserGroup(user_id=linda.id, group_id=scholarship_group.id),
        UserGroup(user_id=maya.id, group_id=scholarship_group.id),
        UserGroup(user_id=cyrus.id, group_id=scholarship_group.id),
    ]
    db.session.add_all(group_memberships)

    db.session.commit()
    print("Seeded: 7 users, 7 events, 12 RSVPs, 4 posts, 8 comments, 6 payments, 3 groups")
    print("Login: admin/admin123, evan/password, maya/password")


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5001)
