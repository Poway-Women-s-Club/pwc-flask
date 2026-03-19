import os
from flask import Flask, render_template
from flask_cors import CORS
from flask_login import LoginManager
from model.database import db
from dotenv import load_dotenv
from model.message import Message


load_dotenv()

app = Flask(__name__)

# Config
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///pwc.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Google OAuth
app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID", "")
app.config["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET", "")

# CORS — allow frontend origin
CORS(app, supports_credentials=True, origins=[
    "http://localhost:4600",
    "http://127.0.0.1:4600",
    os.environ.get("FRONTEND_URL", "http://localhost:4600"),
])

# Database
db.init_app(app)

# Login manager
login_manager = LoginManager()
login_manager.init_app(app)

from model.user import User

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Register blueprints
from api.auth import auth_bp
from api.admin import admin_bp
from api.events import events_bp
from api.blog import blog_bp
from api.payments import payments_bp

app.register_blueprint(auth_bp, url_prefix="/api/auth")
app.register_blueprint(admin_bp, url_prefix="/api/admin")
app.register_blueprint(events_bp, url_prefix="/api/events")
app.register_blueprint(blog_bp, url_prefix="/api/blog")
app.register_blueprint(payments_bp, url_prefix="/api/payments")

@app.route("/api/health")
def health():
    return {"status": "ok"}

@app.route("/")
def admin_panel():
    return render_template("admin.html")

# Create tables and seed sample data on first run
with app.app_context():
    db.create_all()
    # Lightweight schema sync for this project (no migrations).
    # If you change the model and the DB already exists (SQLite),
    # make sure new columns exist so inserts won't fail.
    try:
        from sqlalchemy import inspect as sql_inspect, text

        inspector = sql_inspect(db.engine)
        if "meeting_requests" in inspector.get_table_names():
            cols = {c["name"] for c in inspector.get_columns("meeting_requests")}
            if "preferred_end_datetime" not in cols:
                with db.engine.begin() as conn:
                    conn.execute(
                        text("ALTER TABLE meeting_requests ADD COLUMN preferred_end_datetime DATETIME")
                    )
                print("Added column: meeting_requests.preferred_end_datetime")

        # Users table schema sync (SQLite has no migrations; add missing columns).
        if "users" in inspector.get_table_names():
            user_cols = {c["name"] for c in inspector.get_columns("users")}
            with db.engine.begin() as conn:
                # Profile fields expected by model/user.py
                if "first_name" not in user_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN first_name VARCHAR(80) NOT NULL DEFAULT ''"))
                    print("Added column: users.first_name")
                if "last_name" not in user_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN last_name VARCHAR(80) NOT NULL DEFAULT ''"))
                    print("Added column: users.last_name")
                if "bio" not in user_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN bio TEXT NOT NULL DEFAULT ''"))
                    print("Added column: users.bio")
                if "languages" not in user_cols:
                    # Stored as JSON text in SQLite.
                    conn.execute(text("ALTER TABLE users ADD COLUMN languages TEXT NOT NULL DEFAULT '[]'"))
                    print("Added column: users.languages")
                if "interests" not in user_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN interests TEXT NOT NULL DEFAULT '[]'"))
                    print("Added column: users.interests")
    except Exception as e:
        # Non-fatal: app can still start, but meeting requests may fail until schema is updated.
        print("Schema sync skipped/failed:", e)

    from model.user import User
    from model.event import Event, RSVP
    from model.blog import BlogPost, Comment
    from model.payment import Payment
    from werkzeug.security import generate_password_hash
    from datetime import datetime, timedelta

    # Only seed if database is empty
    if User.query.count() == 0:
        print("Seeding database with sample data...")

        # --- Users ---
        admin = User(
            username="admin",
            email="admin@powaywomansclub.org",
            password_hash=generate_password_hash("admin"),
            role="admin",
            is_active_member=True,
        )
        evan = User(
            username="evan",
            email="evan@example.com",
            password_hash=generate_password_hash("password"),
            role="member",
            is_active_member=True,
        )
        maya = User(
            username="maya",
            email="maya@example.com",
            password_hash=generate_password_hash("password"),
            role="member",
            is_active_member=True,
        )
        cyrus = User(
            username="cyrus",
            email="cyrus@example.com",
            password_hash=generate_password_hash("password"),
            role="member",
            is_active_member=False,
        )
        linda = User(
            username="linda",
            email="linda@powaywomansclub.org",
            password_hash=generate_password_hash("password"),
            role="admin",
            is_active_member=True,
        )
        karen = User(
            username="karen",
            email="karen@example.com",
            password_hash=generate_password_hash("password"),
            role="member",
            is_active_member=True,
        )
        janet = User(
            username="janet",
            email="janet@example.com",
            password_hash=generate_password_hash("password"),
            role="member",
            is_active_member=False,
        )

        db.session.add_all([admin, evan, maya, cyrus, linda, karen, janet])
        db.session.flush()  # assign IDs

        # --- Events ---
        now = datetime.utcnow()
        events = [
            Event(
                title="General Meeting — April",
                description="Monthly general meeting. All members welcome. We'll be discussing the upcoming art exhibit and scholarship selections.",
                location="Templars Hall, Old Poway Park",
                start_time=datetime(2026, 4, 14, 17, 0),
                end_time=datetime(2026, 4, 14, 18, 30),
                created_by=admin.id,
            ),
            Event(
                title="General Meeting — May",
                description="Monthly general meeting with guest speaker on community gardening initiatives.",
                location="Templars Hall, Old Poway Park",
                start_time=datetime(2026, 5, 12, 17, 0),
                end_time=datetime(2026, 5, 12, 18, 30),
                created_by=admin.id,
            ),
            Event(
                title="Celebrate Women Art Exhibit",
                description="Annual art exhibit showcasing women artists from the Poway community. Open to the public, free admission.",
                location="Poway Center for the Performing Arts",
                start_time=datetime(2026, 4, 25, 14, 0),
                end_time=datetime(2026, 4, 25, 18, 0),
                created_by=linda.id,
            ),
            Event(
                title="Old-Fashioned Friendship Tea",
                description="Afternoon tea with finger sandwiches, scones, and good company. $30 per person, proceeds go to club scholarships.",
                location="Templars Hall, Old Poway Park",
                start_time=datetime(2026, 4, 26, 21, 0),
                end_time=datetime(2026, 4, 26, 23, 0),
                created_by=admin.id,
            ),
            Event(
                title="Student Art Exhibit",
                description="Featuring artwork from students at Poway-area high schools. Come support local young artists.",
                location="Old Poway Park Gallery",
                start_time=datetime(2026, 5, 3, 15, 0),
                end_time=datetime(2026, 5, 3, 19, 0),
                created_by=linda.id,
            ),
            Event(
                title="Theatre in the Park",
                description="Community theatre performance sponsored by the Poway Woman's Club. Family friendly.",
                location="Old Poway Park Amphitheatre",
                start_time=datetime(2026, 6, 7, 18, 30),
                end_time=datetime(2026, 6, 7, 21, 0),
                created_by=admin.id,
            ),
            Event(
                title="HOBY Scholarship Awards Ceremony",
                description="Recognizing this year's Hugh O'Brian Youth Leadership scholarship recipients from Poway, Mt. Carmel, Rancho Bernardo, and Westview High Schools.",
                location="Poway Community Library",
                start_time=datetime(2026, 5, 20, 17, 0),
                end_time=datetime(2026, 5, 20, 18, 30),
                created_by=linda.id,
            ),
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
        post1 = BlogPost(
            title="Welcome to the New Website",
            body="We're excited to launch the new Poway Woman's Club website. This site will be our hub for club news, event signups, and member communication. If you have any feedback, leave a comment below or reach out to the admin team.",
            author_id=admin.id,
        )
        post2 = BlogPost(
            title="April Meeting Recap",
            body="Thank you to everyone who came to the April general meeting. We finalized plans for the Celebrate Women Art Exhibit and selected this year's scholarship recipients. Minutes are available upon request. See you in May!",
            author_id=linda.id,
        )
        post3 = BlogPost(
            title="Volunteer Opportunities This Spring",
            body="We have several volunteer opportunities coming up: helping set up the art exhibit on April 24th, greeting guests at the Friendship Tea on April 26th, and assisting with the Student Art Exhibit in early May. Sign up at the next meeting or message us through the site.",
            author_id=karen.id,
        )
        post4 = BlogPost(
            title="Scholarship Applications Now Open",
            body="The HOBY Youth Leadership scholarship applications are now open for sophomores at Poway High, Mt. Carmel High, Rancho Bernardo High, and Westview High. Applications are due by April 30th. Spread the word to any students who might be interested.",
            author_id=linda.id,
        )

        db.session.add_all([post1, post2, post3, post4])
        db.session.flush()

        # --- Comments ---
        comments = [
            Comment(body="Love the new site! Much easier to navigate.", author_id=evan.id, post_id=post1.id),
            Comment(body="Looks great. Can we add a photo gallery section?", author_id=maya.id, post_id=post1.id),
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

        db.session.commit()
        print("Seeded: 7 users, 7 events, 12 RSVPs, 4 posts, 8 comments, 6 payments")
        print("Login: admin/admin, evan/password, maya/password, cyrus/password")

if __name__ == "__main__":
    app.run(debug=True, port=5001)